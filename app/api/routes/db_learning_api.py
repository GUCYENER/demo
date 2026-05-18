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


# ─────────────────────────────────────────────────────────────
# GET /learned-queries
# ─────────────────────────────────────────────────────────────

@router.get("/{source_id}/learned-queries")
def list_learned_queries_endpoint(
    source_id: int,
    only_active: bool = Query(True),
    source_filter: Optional[str] = Query(None, regex=r"^(user|synthetic|manual)$"),
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
# v3.27.0 C.G9 — Reasoning trace fetch (admin debug)
# ─────────────────────────────────────────────────────────────

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
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Belirli run_id için pipeline trace satırını döndür.

    Tenant izolasyonu: company_id RLS scope ile filtrelenir; admin değilse
    sadece kendi tenant'ı.
    """
    company_id = current_user.get("company_id")
    is_admin = bool(current_user.get("is_admin") or current_user.get("role") == "admin")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            if not is_admin:
                apply_company_scope(cur, company_id=company_id)
            from app.services.db_learning.trace_writer import fetch_trace
            trace = fetch_trace(cur, run_id=run_id)
            if not trace:
                raise HTTPException(status_code=404, detail="Trace bulunamadı")
            return {"success": True, "trace": trace}
        finally:
            cur.close()
