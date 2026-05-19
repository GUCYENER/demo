"""VYRA v3.27.0 — DB Learning Loop API.

Endpoints (prefix: /api/data-sources/{source_id}):

  POST /generate-synthetic-queries   — FK-driven sentetik üretim tetikle (background)
  GET  /synthetic-status             — son üretim durumu (kuyrukta + son özet)
  GET  /learned-queries              — admin listing (filtrelenebilir)
  POST /learned-queries/{lid}/deactivate  — tek satır pasifleştir
  POST /learned-queries/invalidate-by-table — tabloya bağlı tümünü pasifleştir

Auth: get_current_user (companies/tenant scope set)
RLS: apply_company_scope ile her endpoint kendi connection'unda set eder
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import apply_company_scope, get_db_context, get_db_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-sources", tags=["db_learning"])


# ─────────────────────────────────────────────────────────────
# In-memory job tracker (tek-makine; v3.27.0 Faz A için yeterli)
# Faz B veya v3.28'de Redis'e taşınacak.
# ─────────────────────────────────────────────────────────────

_jobs: Dict[int, Dict[str, Any]] = {}   # source_id → state
_jobs_lock = threading.Lock()


def _set_job(source_id: int, **kwargs) -> None:
    with _jobs_lock:
        st = _jobs.get(source_id) or {}
        st.update(kwargs)
        _jobs[source_id] = st


def _get_job(source_id: int) -> Dict[str, Any]:
    with _jobs_lock:
        return dict(_jobs.get(source_id) or {})


def _is_running(source_id: int) -> bool:
    return _get_job(source_id).get("status") == "running"


# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    dialect: Optional[str] = Field(default=None, description="Override dialect (default: data_source.db_type)")
    max_fks: Optional[int] = Field(default=None, ge=1, le=10000)
    skip_existing: bool = Field(default=True, description="Daha önce başarılı (FK, template) atla")
    template_kinds: Optional[List[str]] = Field(default=None, description="['LOOKUP_JOIN'] | ['AGGREGATE_COUNT'] (default: ikisi de)")


class InvalidateByTableRequest(BaseModel):
    table_name: str = Field(..., min_length=1)
    schema_name: Optional[str] = None


class FewShotPruneRequest(BaseModel):
    top_n: int = Field(default=1000, ge=10, le=100000)
    stale_days: int = Field(default=90, ge=1, le=3650)


# v3.29.0 Faz 6 G1 — Relationship cardinality override schema
class RelationshipOverrideRequest(BaseModel):
    cardinality_from: Optional[str] = Field(default=None, pattern=r"^[1N]$")
    cardinality_to: Optional[str] = Field(default=None, pattern=r"^[1N]$")
    is_junction: Optional[bool] = None
    path_weight: Optional[int] = Field(default=None, ge=1, le=10000)
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# v3.29.4 Faz 6 G5 — Failure approve/hint
class FailureApproveRequest(BaseModel):
    pattern_hint: Optional[str] = Field(default=None, max_length=2048,
                                        description="Admin notu — LLM'e retry hint olarak verilir")


# v3.29.1 Faz 6 G2 — Code value admin upsert
class CodeValueUpsertRequest(BaseModel):
    table_name: str = Field(..., min_length=1, max_length=256)
    column_name: str = Field(..., min_length=1, max_length=256)
    code_value: str = Field(..., min_length=1, max_length=256)
    label_tr: Optional[str] = Field(default=None, max_length=256)
    label_en: Optional[str] = Field(default=None, max_length=256)
    description_tr: Optional[str] = None
    ordinal: Optional[int] = Field(default=None, ge=0, le=10000)
    is_active: Optional[bool] = None


# v3.29.9 — FK Inference admin requests
class InferFKsRequest(BaseModel):
    sample_validate: bool = Field(
        default=False,
        description="Hedef DB'ye bağlanıp coverage probe çalıştır (yavaş ama hassas)",
    )
    sample_rows: int = Field(default=200, ge=10, le=10000)
    min_confidence: float = Field(default=0.60, ge=0.0, le=1.0)
    dialect: Optional[str] = Field(default=None, description="Override; default: data_source.db_type")


class FKBulkVerifyRequest(BaseModel):
    relationship_ids: List[int] = Field(..., min_length=1, max_length=10000)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _resolve_dialect(cur, source_id: int, override: Optional[str]) -> str:
    if override:
        return override.lower().strip()
    try:
        cur.execute("SELECT db_type FROM data_sources WHERE id = %s", (source_id,))
        row = cur.fetchone()
        if row:
            db_type = row.get("db_type") if hasattr(row, "get") else row[0]
            if db_type:
                d = str(db_type).lower().strip()
                if d in ("postgresql", "postgres", "pg"):
                    return "postgresql"
                if d in ("oracle", "ora"):
                    return "oracle"
                if d in ("mssql", "sqlserver", "ms sql"):
                    return "mssql"
                if d in ("mysql", "mariadb"):
                    return "mysql"
    except Exception:
        pass
    return "postgresql"


def _ensure_source_visible(cur, source_id: int) -> Dict[str, Any]:
    """RLS scoped lookup — tenant'ın gerçekten kendi source'u mu?"""
    cur.execute("SELECT id, name, db_type, company_id FROM data_sources WHERE id = %s", (source_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı")
    return dict(row) if hasattr(row, "keys") else {
        "id": row[0], "name": row[1], "db_type": row[2], "company_id": row[3],
    }


# ─────────────────────────────────────────────────────────────
# POST /generate-synthetic-queries
# ─────────────────────────────────────────────────────────────

@router.post("/{source_id}/generate-synthetic-queries")
def trigger_synthetic_generation(
    source_id: int,
    body: GenerateRequest = GenerateRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """FK ilişkilerinden örnek sorgular üret-çalıştır-öğret (background)."""
    company_id = current_user.get("company_id")
    user_id = current_user.get("id")

    # Önce source visibility ve dialect tespiti
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            src = _ensure_source_visible(cur, source_id)
            dialect = _resolve_dialect(cur, source_id, body.dialect)
        finally:
            cur.close()

    if _is_running(source_id):
        return {
            "success": False,
            "message": "Bu kaynak için zaten çalışan bir sentetik üretim işi var.",
            "job": _get_job(source_id),
        }

    _set_job(source_id, status="running", source_name=src.get("name"),
             dialect=dialect, by_user=user_id, summary=None, error=None)

    def _bg():
        bg_conn = None
        try:
            bg_conn = get_db_conn()
            cur_bg = bg_conn.cursor()
            try:
                apply_company_scope(cur_bg, company_id=company_id)
                # source_id RLS — ds_db_relationships set context (014 RLS pattern)
                try:
                    cur_bg.execute(
                        "SELECT set_config('app.current_source_id', %s, true)",
                        (str(int(source_id)),),
                    )
                except Exception:
                    pass

                from app.services.db_learning.fk_synthetic_generator import (
                    generate_for_source,
                )
                summary = generate_for_source(
                    cur_bg,
                    source_id=source_id,
                    dialect=dialect,
                    company_id=company_id,
                    max_fks=body.max_fks,
                    skip_existing=body.skip_existing,
                    template_kinds=body.template_kinds,
                )
                bg_conn.commit()
                _set_job(source_id, status="done", summary=summary.to_dict(), error=None)
            finally:
                cur_bg.close()
        except Exception as e:
            logger.exception("[db_learning.generate.bg] hata")
            try:
                if bg_conn:
                    bg_conn.rollback()
            except Exception:
                pass
            _set_job(source_id, status="error", error=str(e)[:500])
        finally:
            if bg_conn:
                try:
                    bg_conn.close()
                except Exception:
                    pass

    threading.Thread(target=_bg, daemon=True).start()
    return {
        "success": True,
        "message": "Sentetik üretim başlatıldı (arka plan).",
        "source_id": source_id,
        "dialect": dialect,
    }


@router.get("/{source_id}/synthetic-status")
def get_synthetic_status(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Son sentetik üretim işinin durumu (running/done/error + summary)."""
    state = _get_job(source_id)
    return {"success": True, "source_id": source_id, "job": state or {"status": "idle"}}


# v3.28.9 Paket C: Hata detayları endpoint'i — ds_synthetic_query_runs'taki
# son başarısız denemeleri çek; UI bunu modal'da listeler.
@router.get("/{source_id}/synthetic-failures")
def list_synthetic_failures(
    source_id: int,
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Son başarısız sentetik denemeleri listele (FK + template + hata mesajı)."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            cur.execute(
                """
                SELECT id, relationship_id,
                       from_schema, from_table, from_column,
                       to_schema, to_table, to_column,
                       template_kind, dialect,
                       rendered_sql, error_message, elapsed_ms, executed_at
                FROM ds_synthetic_query_runs
                WHERE source_id = %s
                  AND success = FALSE
                ORDER BY executed_at DESC NULLS LAST, id DESC
                LIMIT %s
                """,
                (source_id, limit),
            )
            rows = cur.fetchall() or []
            items = []
            for r in rows:
                def _g(k, idx):
                    if hasattr(r, "get"):
                        return r.get(k)
                    return r[idx] if idx < len(r) else None
                items.append({
                    "id": _g("id", 0),
                    "relationship_id": _g("relationship_id", 1),
                    "from_table": f"{_g('from_schema', 2) or ''}.{_g('from_table', 3) or ''}".strip("."),
                    "from_column": _g("from_column", 4),
                    "to_table": f"{_g('to_schema', 5) or ''}.{_g('to_table', 6) or ''}".strip("."),
                    "to_column": _g("to_column", 7),
                    "template_kind": _g("template_kind", 8),
                    "dialect": _g("dialect", 9),
                    "rendered_sql": (_g("rendered_sql", 10) or "")[:600],
                    "error_message": _g("error_message", 11),
                    "elapsed_ms": _g("elapsed_ms", 12),
                    "executed_at": str(_g("executed_at", 13)) if _g("executed_at", 13) else None,
                })
            return {
                "success": True,
                "items": items,
                "count": len(items),
            }
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# v3.29.0 Faz 6 G1 — Cardinality & Junction Analyzer
# ─────────────────────────────────────────────────────────────

@router.post("/{source_id}/analyze-cardinality")
def analyze_cardinality_endpoint(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """ds_db_relationships üzerinde cardinality + junction analizi çalıştır."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            from app.services.db_learning.cardinality_analyzer import (
                analyze_relationships,
            )
            stats = analyze_relationships(cur, source_id)
            conn.commit()
            return {"success": True, "source_id": source_id, "stats": stats}
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[analyze-cardinality] failed source_id=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.get("/{source_id}/relationships")
def list_relationships_endpoint(
    source_id: int,
    only_junctions: bool = Query(False),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """FK ilişkilerini cardinality metadatasıyla listele."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            where = "source_id = %s"
            args: List[Any] = [source_id]
            if only_junctions:
                where += " AND is_junction = TRUE"
            cur.execute(
                f"""
                SELECT id, from_schema, from_table, from_column,
                       to_schema, to_table, to_column,
                       cardinality_from, cardinality_to, is_junction,
                       path_weight, inverse_relationship_id,
                       confidence_score, last_analyzed_at, constraint_name
                FROM ds_db_relationships
                WHERE {where}
                ORDER BY confidence_score DESC NULLS LAST, id
                LIMIT %s OFFSET %s
                """,
                tuple(args + [limit, offset]),
            )
            rows = cur.fetchall() or []
            items = []
            for r in rows:
                def _g(k, idx):
                    if hasattr(r, "get"):
                        return r.get(k)
                    return r[idx] if idx < len(r) else None
                items.append({
                    "id": _g("id", 0),
                    "from": f"{_g('from_schema', 1) or ''}.{_g('from_table', 2) or ''}".strip("."),
                    "from_column": _g("from_column", 3),
                    "to": f"{_g('to_schema', 4) or ''}.{_g('to_table', 5) or ''}".strip("."),
                    "to_column": _g("to_column", 6),
                    "cardinality_from": _g("cardinality_from", 7),
                    "cardinality_to": _g("cardinality_to", 8),
                    "is_junction": bool(_g("is_junction", 9)),
                    "path_weight": _g("path_weight", 10),
                    "inverse_relationship_id": _g("inverse_relationship_id", 11),
                    "confidence_score": _g("confidence_score", 12),
                    "last_analyzed_at": str(_g("last_analyzed_at", 13)) if _g("last_analyzed_at", 13) else None,
                    "constraint_name": _g("constraint_name", 14),
                })
            return {"success": True, "items": items, "count": len(items), "limit": limit, "offset": offset}
        finally:
            cur.close()


@router.put("/{source_id}/relationships/{rel_id}")
def override_relationship_endpoint(
    source_id: int,
    rel_id: int,
    payload: RelationshipOverrideRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin manuel cardinality/junction override."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            # ilişkinin gerçekten bu source'a ait olduğunu doğrula
            cur.execute(
                "SELECT id FROM ds_db_relationships WHERE id = %s AND source_id = %s",
                (rel_id, source_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="İlişki bulunamadı")
            from app.services.db_learning.cardinality_analyzer import (
                override_relationship,
            )
            updated = override_relationship(
                cur,
                relationship_id=rel_id,
                cardinality_from=payload.cardinality_from,
                cardinality_to=payload.cardinality_to,
                is_junction=payload.is_junction,
                path_weight=payload.path_weight,
                confidence_score=payload.confidence_score,
            )
            if not updated:
                raise HTTPException(status_code=400, detail="Hiçbir alan verilmedi")
            conn.commit()
            return {"success": True, "relationship_id": rel_id}
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[override-relationship] failed rel_id=%s", rel_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# v3.29.9 — FK Inference endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/{source_id}/infer-fks")
def infer_fks_endpoint(
    source_id: int,
    payload: InferFKsRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Naming + type + (opsiyonel) sample-validate ile FK ilişkileri çıkar.

    sample_validate=True: hedef DB'ye bağlanır ve coverage probe çalıştırır
    (yavaş, statement_timeout uygulanır). Default False — naming+type only.
    """
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        target_conn = None
        target_cur = None
        try:
            apply_company_scope(cur, company_id=company_id)
            src = _ensure_source_visible(cur, source_id)
            dialect_name = _resolve_dialect(cur, source_id, payload.dialect)

            if payload.sample_validate:
                # Hedef DB bağlantısı için tüm bilgileri al
                cur.execute(
                    "SELECT id, db_type, host, port, db_name, db_user, "
                    "db_password_encrypted FROM data_sources WHERE id = %s",
                    (source_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı")
                source_full = dict(row) if hasattr(row, "keys") else {
                    "id": row[0], "db_type": row[1], "host": row[2],
                    "port": row[3], "db_name": row[4], "db_user": row[5],
                    "db_password_encrypted": row[6],
                }
                try:
                    from app.services.ds_learning_service import (
                        _decrypt_password, _get_db_connector,
                    )
                    pwd = _decrypt_password(source_full.get("db_password_encrypted", ""))
                    target_conn, _ = _get_db_connector(source_full, pwd)
                    target_cur = target_conn.cursor()
                    # Apply statement_timeout per dialect for safety
                    try:
                        if dialect_name == "postgresql":
                            target_cur.execute("SET LOCAL statement_timeout='3s'")
                        elif dialect_name == "mssql":
                            target_cur.execute("SET LOCK_TIMEOUT 3000")
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(
                        "[infer-fks] target DB connect failed source=%s: %s",
                        source_id, str(e)[:200],
                    )
                    # Fall through with sample_validate disabled
                    target_cur = None

            from app.services.db_learning.fk_inference_service import (
                infer_fks_for_source,
            )
            res = infer_fks_for_source(
                cur, source_id,
                sample_validate=(payload.sample_validate and target_cur is not None),
                sample_rows=payload.sample_rows,
                min_confidence=payload.min_confidence,
                dialect=dialect_name,
                target_cur=target_cur,
            )
            conn.commit()
            return {"success": True, **res}
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[infer-fks] failed source=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            try:
                if target_cur is not None:
                    target_cur.close()
            except Exception:
                pass
            try:
                if target_conn is not None:
                    target_conn.close()
            except Exception:
                pass
            cur.close()


@router.get("/{source_id}/inferred-relationships")
def list_inferred_relationships(
    source_id: int,
    status: str = Query("pending", pattern=r"^(pending|verified|rejected|all)$"),
    method: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Çıkarsanan FK'ları listele (status: pending|verified|rejected|all)."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            where = "source_id = %s AND is_inferred = TRUE"
            args: List[Any] = [source_id]
            if status == "pending":
                where += " AND admin_verified = FALSE AND rejected_at IS NULL"
            elif status == "verified":
                where += " AND admin_verified = TRUE"
            elif status == "rejected":
                where += " AND rejected_at IS NOT NULL"
            # status == "all" → no extra filter
            if method:
                where += " AND inference_method = %s"
                args.append(method)
            cur.execute(
                f"""
                SELECT id, from_schema, from_table, from_column,
                       to_schema, to_table, to_column,
                       inference_method, confidence_score, evidence_json,
                       admin_verified, verified_at, rejected_at
                  FROM ds_db_relationships
                 WHERE {where}
                 ORDER BY confidence_score DESC NULLS LAST, id
                 LIMIT %s OFFSET %s
                """,
                tuple(args + [limit, offset]),
            )
            rows = cur.fetchall() or []
            items = []
            for r in rows:
                def _g(k, idx):
                    if hasattr(r, "get"):
                        return r.get(k)
                    return r[idx] if idx < len(r) else None
                items.append({
                    "id": _g("id", 0),
                    "from": f"{_g('from_schema', 1) or ''}.{_g('from_table', 2) or ''}.{_g('from_column', 3) or ''}",
                    "to": f"{_g('to_schema', 4) or ''}.{_g('to_table', 5) or ''}.{_g('to_column', 6) or ''}",
                    "method": _g("inference_method", 7),
                    "confidence": _g("confidence_score", 8),
                    "evidence": _g("evidence_json", 9),
                    "admin_verified": bool(_g("admin_verified", 10)),
                    "verified_at": str(_g("verified_at", 11)) if _g("verified_at", 11) else None,
                    "rejected_at": str(_g("rejected_at", 12)) if _g("rejected_at", 12) else None,
                })
            return {"success": True, "items": items, "count": len(items), "status": status}
        finally:
            cur.close()


def _verify_or_reject(
    cur, source_id: int, rel_id: int, user_id: int | None, *, verify: bool,
) -> None:
    """Common path for verify/reject — ownership check + UPDATE."""
    cur.execute(
        "SELECT id, is_inferred FROM ds_db_relationships "
        "WHERE id = %s AND source_id = %s",
        (rel_id, source_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="İlişki bulunamadı")
    is_inferred = (row.get("is_inferred") if hasattr(row, "get") else row[1])
    if not is_inferred:
        raise HTTPException(
            status_code=400, detail="Sadece çıkarsanan ilişkiler verify/reject edilebilir",
        )
    if verify:
        cur.execute(
            """
            UPDATE ds_db_relationships
               SET admin_verified = TRUE,
                   verified_by = %s,
                   verified_at = NOW(),
                   rejected_at = NULL
             WHERE id = %s AND source_id = %s
            """,
            (user_id, rel_id, source_id),
        )
    else:
        cur.execute(
            """
            UPDATE ds_db_relationships
               SET admin_verified = FALSE,
                   verified_by = %s,
                   verified_at = NULL,
                   rejected_at = NOW()
             WHERE id = %s AND source_id = %s
            """,
            (user_id, rel_id, source_id),
        )


@router.post("/{source_id}/relationships/{rel_id}/verify")
def verify_inferred_relationship(
    source_id: int, rel_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin: çıkarsanan FK'yı onayla (admin_verified=TRUE)."""
    company_id = current_user.get("company_id")
    user_id = current_user.get("id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            _verify_or_reject(cur, source_id, rel_id, user_id, verify=True)
            conn.commit()
            return {"success": True, "relationship_id": rel_id, "admin_verified": True}
        except HTTPException:
            try: conn.rollback()
            except Exception: pass
            raise
        except Exception as exc:
            try: conn.rollback()
            except Exception: pass
            logger.exception("[verify-relationship] failed rel_id=%s", rel_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.post("/{source_id}/relationships/{rel_id}/reject")
def reject_inferred_relationship(
    source_id: int, rel_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin: çıkarsanan FK'yı reddet (rejected_at set)."""
    company_id = current_user.get("company_id")
    user_id = current_user.get("id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            _verify_or_reject(cur, source_id, rel_id, user_id, verify=False)
            conn.commit()
            return {"success": True, "relationship_id": rel_id, "rejected": True}
        except HTTPException:
            try: conn.rollback()
            except Exception: pass
            raise
        except Exception as exc:
            try: conn.rollback()
            except Exception: pass
            logger.exception("[reject-relationship] failed rel_id=%s", rel_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.post("/{source_id}/relationships/bulk-verify")
def bulk_verify_inferred(
    source_id: int,
    payload: FKBulkVerifyRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin: birden fazla FK'yı tek seferde onayla."""
    company_id = current_user.get("company_id")
    user_id = current_user.get("id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            cur.execute(
                """
                UPDATE ds_db_relationships
                   SET admin_verified = TRUE,
                       verified_by = %s,
                       verified_at = NOW(),
                       rejected_at = NULL
                 WHERE source_id = %s
                   AND is_inferred = TRUE
                   AND id = ANY(%s::int[])
                """,
                (user_id, source_id, payload.relationship_ids),
            )
            try:
                updated = cur.rowcount or 0
            except Exception:
                updated = 0
            conn.commit()
            return {"success": True, "verified_count": int(updated)}
        except Exception as exc:
            try: conn.rollback()
            except Exception: pass
            logger.exception("[bulk-verify] failed source=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.get("/{source_id}/fk-inference-stats")
def fk_inference_stats(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Observability: declared vs inferred FK sayıları, method dağılımı."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE is_inferred = FALSE)                               AS declared,
                    COUNT(*) FILTER (WHERE is_inferred = TRUE AND admin_verified = FALSE
                                          AND rejected_at IS NULL)                            AS pending,
                    COUNT(*) FILTER (WHERE is_inferred = TRUE AND admin_verified = TRUE)      AS verified,
                    COUNT(*) FILTER (WHERE is_inferred = TRUE AND rejected_at IS NOT NULL)    AS rejected,
                    COUNT(*) FILTER (WHERE inference_method = 'naming')                       AS m_naming,
                    COUNT(*) FILTER (WHERE inference_method = 'naming+type')                  AS m_naming_type,
                    COUNT(*) FILTER (WHERE inference_method = 'naming+type+sample')           AS m_naming_type_sample
                  FROM ds_db_relationships
                 WHERE source_id = %s
                """,
                (source_id,),
            )
            row = cur.fetchone()
            if not row:
                stats = {"declared": 0, "pending": 0, "verified": 0, "rejected": 0,
                         "by_method": {}}
            else:
                def _g(k, idx):
                    if hasattr(row, "get"):
                        return int(row.get(k) or 0)
                    return int(row[idx] or 0)
                stats = {
                    "declared": _g("declared", 0),
                    "pending": _g("pending", 1),
                    "verified": _g("verified", 2),
                    "rejected": _g("rejected", 3),
                    "by_method": {
                        "naming": _g("m_naming", 4),
                        "naming+type": _g("m_naming_type", 5),
                        "naming+type+sample": _g("m_naming_type_sample", 6),
                    },
                }
            return {"success": True, "source_id": source_id, "stats": stats}
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# v3.29.1 Faz 6 G2 — Code Value Dictionary endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/{source_id}/extract-code-values")
def extract_code_values_endpoint(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """ds_db_samples'tan code value sözlüğünü çıkar (LLM çağrısı yok, sadece sample scan)."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            from app.services.db_learning.code_value_extractor import extract_from_samples
            stats = extract_from_samples(cur, source_id, company_id=company_id)
            conn.commit()
            return {"success": True, "source_id": source_id, "stats": stats}
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[extract-code-values] failed source_id=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.get("/{source_id}/code-values")
def list_code_values_endpoint(
    source_id: int,
    table_name: Optional[str] = Query(None),
    column_name: Optional[str] = Query(None),
    only_active: bool = Query(True),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Code value sözlüğünü filtreli olarak listele."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            where = ["source_id = %s"]
            args: List[Any] = [source_id]
            if table_name:
                where.append("table_name = %s")
                args.append(table_name)
            if column_name:
                where.append("column_name = %s")
                args.append(column_name)
            if only_active:
                where.append("is_active = TRUE")
            cur.execute(
                f"""
                SELECT id, table_name, column_name, code_value,
                       label_tr, label_en, description_tr,
                       ordinal, is_active, inferred_by, confidence,
                       usage_count, last_used_at
                FROM ds_code_values
                WHERE {' AND '.join(where)}
                ORDER BY table_name, column_name, ordinal NULLS LAST, code_value
                LIMIT %s OFFSET %s
                """,
                tuple(args + [limit, offset]),
            )
            rows = cur.fetchall() or []
            items: List[Dict[str, Any]] = []
            for r in rows:
                def _g(k, idx):
                    if hasattr(r, "get"):
                        return r.get(k)
                    return r[idx] if idx < len(r) else None
                items.append({
                    "id": _g("id", 0),
                    "table_name": _g("table_name", 1),
                    "column_name": _g("column_name", 2),
                    "code_value": _g("code_value", 3),
                    "label_tr": _g("label_tr", 4),
                    "label_en": _g("label_en", 5),
                    "description_tr": _g("description_tr", 6),
                    "ordinal": _g("ordinal", 7),
                    "is_active": bool(_g("is_active", 8)),
                    "inferred_by": _g("inferred_by", 9),
                    "confidence": _g("confidence", 10),
                    "usage_count": _g("usage_count", 11),
                    "last_used_at": str(_g("last_used_at", 12)) if _g("last_used_at", 12) else None,
                })
            return {"success": True, "items": items, "count": len(items), "limit": limit, "offset": offset}
        finally:
            cur.close()


@router.post("/{source_id}/code-values")
def upsert_code_value_endpoint(
    source_id: int,
    payload: CodeValueUpsertRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin manuel code value ekle/güncelle (inferred_by='admin', confidence=1.0)."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            from app.services.db_learning.code_value_extractor import upsert_admin
            result = upsert_admin(
                cur,
                source_id=source_id,
                company_id=company_id,
                table_name=payload.table_name,
                column_name=payload.column_name,
                code_value=payload.code_value,
                label_tr=payload.label_tr,
                label_en=payload.label_en,
                description_tr=payload.description_tr,
                ordinal=payload.ordinal,
                is_active=payload.is_active,
            )
            if result.get("status") != "ok":
                raise HTTPException(status_code=400, detail=result.get("error", "upsert failed"))
            conn.commit()
            return {"success": True, "id": result.get("id")}
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[upsert-code-value] failed")
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.delete("/{source_id}/code-values/{cv_id}")
def delete_code_value_endpoint(
    source_id: int,
    cv_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Soft delete — is_active=FALSE yapar."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            cur.execute(
                "UPDATE ds_code_values SET is_active = FALSE, updated_at = NOW() "
                "WHERE id = %s AND source_id = %s",
                (cv_id, source_id),
            )
            if not (cur.rowcount or 0):
                raise HTTPException(status_code=404, detail="Code value bulunamadı")
            conn.commit()
            return {"success": True}
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[delete-code-value] failed")
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# GET /learned-queries
# ─────────────────────────────────────────────────────────────

@router.get("/{source_id}/learned-queries")
def list_learned_queries_endpoint(
    source_id: int,
    only_active: bool = Query(True),
    source_filter: Optional[str] = Query(None, pattern=r"^(user|synthetic|manual)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin sayfası için öğrenilmiş sorguları listele."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            from app.services.db_learning.learned_queries_service import (
                list_learned_queries,
            )
            items = list_learned_queries(
                cur,
                source_id=source_id,
                limit=limit,
                offset=offset,
                only_active=only_active,
                source_filter=source_filter,
            )
            return {
                "success": True,
                "items": items,
                "limit": limit,
                "offset": offset,
                "count": len(items),
            }
        finally:
            cur.close()


@router.post("/{source_id}/learned-queries/{lid}/deactivate")
def deactivate_learned_query(
    source_id: int,
    lid: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Tek bir öğrenilmiş sorguyu pasifleştir."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            from app.services.db_learning.learned_queries_service import deactivate
            ok = deactivate(cur, lid)
            conn.commit()
            return {"success": ok, "id": lid}
        finally:
            cur.close()


@router.post("/{source_id}/learned-queries/invalidate-by-table")
def invalidate_by_table_endpoint(
    source_id: int,
    body: InvalidateByTableRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Tabloya bağlı tüm öğrenilmiş sorguları pasifleştir (schema drift adımı)."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            from app.services.db_learning.learned_queries_service import (
                invalidate_by_table,
            )
            n = invalidate_by_table(
                cur,
                source_id=source_id,
                table_name=body.table_name,
                schema_name=body.schema_name,
            )
            conn.commit()
            return {"success": True, "invalidated": n,
                    "table": body.table_name, "schema": body.schema_name}
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# POST /few-shot/prune (tenant-scoped admin job)
# ─────────────────────────────────────────────────────────────

@router.post("/few-shot/prune")
def prune_few_shot_endpoint(
    body: FewShotPruneRequest = FewShotPruneRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """LRU cleanup for few_shot_examples — current tenant only.

    Korunan: her (source_id, intent) bucket için top_n usage.
    Silinen: bucket'tan taşan + (usage_count=0 AND created_at < NOW()-stale_days).
    """
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            from app.services.db_learning.few_shot_pruner import prune
            summary = prune(
                cur,
                company_id=company_id,
                top_n=body.top_n,
                stale_days=body.stale_days,
            )
            conn.commit()
            return {"success": True, "summary": summary.to_dict()}
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# v3.27.0 C.G7 — Result fingerprint cache (Redis)
# ─────────────────────────────────────────────────────────────

@router.get("/result-cache/stats")
def result_cache_stats_endpoint(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Result cache istatistikleri (admin)."""
    if not (current_user.get("is_admin") or current_user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    from app.services.db_learning.result_cache import stats as _stats
    return {"success": True, "stats": _stats()}


@router.post("/result-cache/flush")
def result_cache_flush_endpoint(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Tüm SQL result cache'i temizle (admin only)."""
    if not (current_user.get("is_admin") or current_user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    from app.services.db_learning.result_cache import flush_all
    return flush_all()


# ─────────────────────────────────────────────────────────────
# v3.27.0 C.G5 — Synonym suggestion review queue
# ─────────────────────────────────────────────────────────────

class SynonymReviewBody(BaseModel):
    decision: str = Field(..., description="'approved' | 'rejected'")


@router.get("/synonyms/pending")
def list_synonym_pending_endpoint(
    source_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Pending sinonim önerileri (admin onay kuyruğu)."""
    if not (current_user.get("is_admin") or current_user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            from app.services.db_learning.synonym_learner import list_pending
            rows = list_pending(cur, source_id=source_id, limit=limit)
            return {"success": True, "items": rows}
        finally:
            cur.close()


@router.post("/synonyms/{sugg_id}/review")
def review_synonym_endpoint(
    sugg_id: int,
    body: SynonymReviewBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Sinonim önerisini onayla/reddet (admin)."""
    if not (current_user.get("is_admin") or current_user.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'rejected'")
    company_id = current_user.get("company_id")
    reviewer_id = current_user.get("id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            from app.services.db_learning.synonym_learner import review
            ok = review(cur, sugg_id, decision=body.decision, reviewer_user_id=reviewer_id)
            conn.commit()
            if not ok:
                raise HTTPException(status_code=404, detail="Pending kayıt bulunamadı")
            return {"success": True, "id": sugg_id, "decision": body.decision}
        finally:
            cur.close()


@router.get("/traces/{run_id}")
def get_trace_by_run_id(
    run_id: str,
    company_id_override: Optional[int] = Query(None, alias="company_id"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Belirli run_id için pipeline trace satırını döndür.

    Tenant izolasyonu (defense-in-depth):
      * RLS scope HER ZAMAN set edilir (admin dahil).
      * Admin değilse: kendi company_id'sine kilitlenir (override yok sayılır).
      * Admin ise: opsiyonel `?company_id=N` query param ile başka tenant'ı
        debug edebilir; verilmezse kendi company_id'si kullanılır.
      * fetch_trace WHERE'ına da explicit `company_id` predikatı eklenir
        (RLS PERMISSIVE policy'nin null-scope bypass'ına karşı).
    """
    user_company_id = current_user.get("company_id")
    is_admin = bool(current_user.get("is_admin") or current_user.get("role") == "admin")
    # Admin override sadece admin'e açık
    effective_company = company_id_override if is_admin else user_company_id
    # v3.27.1 defense-in-depth: tenant scope BELİRSİZSE erişimi reddet.
    # Aksi halde RLS PERMISSIVE policy null-scope altında cross-tenant satır dönebilir
    # ve fetch_trace WHERE'a predikat eklemez.
    if effective_company is None:
        raise HTTPException(status_code=403, detail="Tenant kapsamı belirlenemedi")

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            # RLS scope her zaman set — admin de olsa null-bypass'a izin verme
            apply_company_scope(cur, company_id=effective_company)
            from app.services.db_learning.trace_writer import fetch_trace
            trace = fetch_trace(cur, run_id=run_id, company_id=effective_company)
            if not trace:
                raise HTTPException(status_code=404, detail="Trace bulunamadı")
            return {"success": True, "trace": trace}
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# v3.29.4 Faz 6 G5 — Error pattern learning admin endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/{source_id}/failure-queue")
def list_failure_queue_endpoint(
    source_id: int,
    min_recurrence: int = Query(3, ge=1, le=100),
    limit: int = Query(50, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Tekrar eşiğini geçen, admin onayı bekleyen hata kayıtları."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            # source_id filtresi için custom query (review_queue tüm tenant'ı verir).
            cur.execute(
                """
                SELECT id, source_id, question, error_class, error_message,
                       recurrence_count, corrected_sql, admin_approved,
                       last_seen_at, created_at, pattern_hint, failed_sql
                FROM learned_query_failures
                WHERE source_id = %s
                  AND recurrence_count >= %s
                  AND admin_approved = FALSE
                ORDER BY recurrence_count DESC, last_seen_at DESC
                LIMIT %s
                """,
                (source_id, min_recurrence, limit),
            )
            rows = cur.fetchall() or []
            items: List[Dict[str, Any]] = []
            for r in rows:
                items.append({
                    "id": int(r[0]),
                    "source_id": int(r[1] or 0),
                    "question": r[2] or "",
                    "error_class": r[3] or "unknown",
                    "error_message": r[4],
                    "recurrence_count": int(r[5] or 1),
                    "corrected_sql": r[6],
                    "admin_approved": bool(r[7]),
                    "last_seen_at": r[8].isoformat() if r[8] else None,
                    "created_at": r[9].isoformat() if r[9] else None,
                    "pattern_hint": r[10],
                    "failed_sql": r[11],
                })
            return {"success": True, "items": items, "count": len(items)}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[failure-queue] list failed source_id=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.post("/{source_id}/failures/{failure_id}/approve")
def approve_failure_endpoint(
    source_id: int,
    failure_id: int,
    payload: FailureApproveRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin onayı — corrected_sql artık few-shot'a girebilir + pattern_hint set."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            # Önce kayıt bu source'a ait mi doğrula (RLS + source filter)
            cur.execute(
                "SELECT id FROM learned_query_failures WHERE id = %s AND source_id = %s",
                (failure_id, source_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Failure kaydı bulunamadı")
            from app.services.db_learning.error_pattern_learner import admin_approve
            admin_approve(cur, failure_id, pattern_hint=payload.pattern_hint)
            conn.commit()
            return {"success": True, "id": failure_id}
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[failure-approve] failed id=%s", failure_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


@router.delete("/{source_id}/failures/{failure_id}")
def dismiss_failure_endpoint(
    source_id: int,
    failure_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin tarafından "incelendi, aksiyon gerekmiyor" — kaydı kuyruktan düşürür.

    Hard delete YERINE admin_approved=TRUE + corrected_sql=NULL set eder; böylece
    suggest_fix bu satırı hint olarak ÜRETMEZ (corrected/hint yok) ama tarihçe
    kalır (recurrence istatistiği bozulmaz).
    """
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            cur.execute(
                """
                UPDATE learned_query_failures
                SET admin_approved = TRUE,
                    corrected_sql = NULL,
                    pattern_hint = NULL
                WHERE id = %s AND source_id = %s
                """,
                (failure_id, source_id),
            )
            if not (cur.rowcount or 0):
                raise HTTPException(status_code=404, detail="Failure kaydı bulunamadı")
            conn.commit()
            return {"success": True, "id": failure_id, "dismissed": True}
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("[failure-dismiss] failed id=%s", failure_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
        finally:
            cur.close()


# ─────────────────────────────────────────────────────────────
# v3.29.6 Faz 7 — Incremental Schema Integration
# ─────────────────────────────────────────────────────────────
# Yeni tablo(lar) eklendiğinde sıfırdan re-discovery yapmadan keşfeder ve
# en kritik şekilde de yeni tablonun MEVCUT (önceden keşfedilmiş)
# tablolarla olan FK ilişkilerini bulup downstream pipeline'ı yeniden
# tetikler (cardinality, synthetic, code_values, failure re-eligibility).
# ─────────────────────────────────────────────────────────────

class IntegrateNewTablesRequest(BaseModel):
    dry_run: bool = Field(False, description="Sadece yeni tablo listesini döndür, INSERT yapma")
    auto_synthetic: bool = Field(True, description="Yeni FK'lar için sentetik sorgu üret")
    auto_codevalues: bool = Field(True, description="Yeni kodlu kolonlar için ds_code_values güncelle")
    auto_reflag_failures: bool = Field(True, description="missing_table/amb_column failures'ı re-flag et")
    max_new_tables: int = Field(100, ge=1, le=500, description="Tek seferde max yeni tablo")


@router.get("/{source_id}/new-tables")
def list_new_tables_endpoint(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Remote DB'de olup ds_db_objects'ta olmayan tabloları listele (preview)."""
    from app.services.pipeline.wiring import _load_source_dict
    from app.services.db_learning.incremental_schema_integrator import detect_new_tables

    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            source = _load_source_dict(cur, source_id, company_id=company_id)
            if not source:
                raise HTTPException(status_code=404, detail="Data source bulunamadı")
        finally:
            cur.close()

        try:
            new_list = detect_new_tables(source, conn)
            return {
                "success": True,
                "source_id": source_id,
                "new_tables": [
                    {"schema": s, "table": t, "type": typ}
                    for (s, t, typ) in new_list
                ],
                "count": len(new_list),
            }
        except Exception as exc:
            logger.exception("[integrate.preview] failed source_id=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])


@router.post("/{source_id}/integrate-new-tables")
def integrate_new_tables_endpoint(
    source_id: int,
    payload: IntegrateNewTablesRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Yeni eklenen tabloları keşfedip downstream learning pipeline'a entegre et.

    Akış:
      1. Remote DB'den fresh tablo listesi → diff (ds_db_objects vs fresh)
      2. Yeni tablolar ds_db_objects'a INSERT (enrichment kaybı YOK)
      3. _refresh_relationships_for_tables — yeni tablonun MEVCUT tablolarla
         olan FK'ları otomatik bulunur (KRİTİK adım — bidirectional lookup)
      4. cardinality_analyzer.analyze_relationships (TÜM source — junction global)
      5. (opsiyonel) fk_synthetic_generator.generate_for_source skip_existing=True
      6. (opsiyonel) code_value_extractor.extract_from_samples
      7. (opsiyonel) learned_query_failures re-eligibility flag
      8. pipeline_events'e audit kaydı

    `dry_run=True` ise yalnızca diff sonucu döner, hiçbir INSERT/UPDATE yapılmaz.

    Job tracker: Aynı source için generate-synthetic ile aynı kuyruğu paylaşır;
    bu endpoint senkron çalışır (tipik akışta < 30 sn). Eş zamanlı çalıştırma
    blok edilir.
    """
    from app.services.pipeline.wiring import _load_source_dict
    from app.services.db_learning.incremental_schema_integrator import (
        integrate_new_tables,
    )

    if _is_running(source_id):
        raise HTTPException(
            status_code=409,
            detail="Bu source için zaten bir öğrenme/keşif görevi çalışıyor",
        )

    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            apply_company_scope(cur, company_id=company_id)
            _ensure_source_visible(cur, source_id)
            source = _load_source_dict(cur, source_id, company_id=company_id)
            if not source:
                raise HTTPException(status_code=404, detail="Data source bulunamadı")
        finally:
            cur.close()

        _set_job(source_id, status="running", kind="incremental_integration")
        try:
            result = integrate_new_tables(
                source,
                conn,
                dry_run=payload.dry_run,
                auto_synthetic=payload.auto_synthetic,
                auto_codevalues=payload.auto_codevalues,
                auto_reflag_failures=payload.auto_reflag_failures,
                max_new_tables=payload.max_new_tables,
            )
            _set_job(source_id, status="done", summary=result)
            return {"success": True, "result": result}
        except HTTPException:
            _set_job(source_id, status="error")
            raise
        except Exception as exc:
            _set_job(source_id, status="error", error=str(exc)[:300])
            logger.exception("[integrate-new-tables] failed source_id=%s", source_id)
            raise HTTPException(status_code=500, detail=str(exc)[:300])
