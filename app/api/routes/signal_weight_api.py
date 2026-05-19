"""
VYRA Signal Weight API — v3.29.8 L3
====================================
multi_signal_rank ağırlıklarının yönetimi için admin endpoint'leri.

Endpoint'ler:
    GET  /api/admin/signal-weights/current
        Şirketin yürürlükteki ağırlıkları (override + default merge) +
        en güncel öneri listesi.

    GET  /api/admin/signal-weights/suggestions
        Bekleyen ve geçmiş önerileri sayfalı döner.

    POST /api/admin/signal-weights/apply
        Bir suggestion'ı onayla ve uygula. signal_weight_overrides'a
        UPSERT, signal_weight_audit_log'a INSERT, cache invalidate.

    PUT  /api/admin/signal-weights/{signal_name}
        Manuel override — suggestion'sız doğrudan ağırlık seti.

    POST /api/admin/signal-weights/analyze
        Manuel tetikleme (scheduler beklemeden hemen üret).

    POST /api/admin/signal-weights/reset
        Şirket override'larını sil (DEFAULT_WEIGHTS'a dön).

    GET  /api/admin/signal-weights/audit
        signal_weight_audit_log son N kayıt.

Güvenlik:
    - Tüm endpoint'ler `get_current_admin` Depends — admin-only.
    - company_id token'dan alınır; payload'taki company_id ignored.
    - signal_name whitelist (7 sinyal).
    - weight aralığı [0.0, 1.0] CHECK constraint + Pydantic validator.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.routes.auth import get_current_admin
from app.core.db import get_db_context, apply_company_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/signal-weights", tags=["signal_weights"])

# multi_signal_rank.SIGNAL_NAMES ile aynı liste — backend tek kaynak
ALLOWED_SIGNALS = frozenset({
    "semantic", "name_fuzzy", "column_match",
    "fk_centrality", "recency", "usage_freq", "glossary_match",
})


# ---------- Pydantic ----------

class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_id: int = Field(..., gt=0)
    audit_note: Optional[str] = Field(None, max_length=500)


class ManualOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weight: float = Field(..., ge=0.0, le=1.0)
    audit_note: Optional[str] = Field(None, max_length=500)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(7, ge=1, le=90)
    min_sample_size: int = Field(50, ge=10, le=1000)


# ---------- Endpoints ----------

@router.get("/current")
def get_current_weights(
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Yürürlükteki ağırlıklar + en son öneriler."""
    from app.services.pipeline.nodes.multi_signal_rank import (
        DEFAULT_WEIGHTS, load_company_weights, invalidate_company_weights_cache,
    )
    co_id = current_user.get("company_id")
    if co_id is None:
        raise HTTPException(400, "company_id token'da bulunamadı")

    # Cache'i pas geçip güncel görüntü ver
    invalidate_company_weights_cache(co_id)

    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            active = load_company_weights(cur, co_id)

            # En son öneri seti (her sinyal için en yeni)
            cur.execute(
                """
                SELECT DISTINCT ON (signal_name)
                    id, signal_name, current_weight, suggested_weight,
                    confidence, correlation_pearson, sample_size,
                    window_days, computed_at, admin_verified, applied_at
                  FROM signal_weight_suggestions
                 WHERE company_id = %s
                 ORDER BY signal_name, computed_at DESC
                """,
                (co_id,),
            )
            suggestions = [dict(r) for r in (cur.fetchall() or [])]

            cur.execute(
                """
                SELECT signal_name, weight, updated_at, updated_by, audit_note
                  FROM signal_weight_overrides
                 WHERE company_id = %s
                """,
                (co_id,),
            )
            overrides = [dict(r) for r in (cur.fetchall() or [])]

    return {
        "company_id": co_id,
        "active_weights": active,
        "defaults": dict(DEFAULT_WEIGHTS),
        "overrides": overrides,
        "latest_suggestions": suggestions,
    }


@router.get("/suggestions")
def list_suggestions(
    limit: int = 100,
    only_pending: bool = False,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Bekleyen veya geçmiş tüm önerileri sayfalı döner."""
    co_id = current_user.get("company_id")
    if co_id is None:
        raise HTTPException(400, "company_id bulunamadı")
    limit = max(1, min(500, int(limit)))
    where_pending = "AND applied_at IS NULL AND admin_verified = FALSE" if only_pending else ""

    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            cur.execute(
                f"""
                SELECT id, signal_name, current_weight, suggested_weight,
                       confidence, correlation_pearson, sample_size,
                       window_days, computed_at, admin_verified,
                       applied_at, applied_by
                  FROM signal_weight_suggestions
                 WHERE company_id = %s
                       {where_pending}
                 ORDER BY computed_at DESC
                 LIMIT %s
                """,
                (co_id, limit),
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
    return {"suggestions": rows, "count": len(rows)}


@router.post("/apply")
def apply_suggestion(
    body: ApplyRequest,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Bir suggestion'ı onayla ve override'a uygula."""
    from app.services.pipeline.nodes.multi_signal_rank import invalidate_company_weights_cache
    co_id = current_user.get("company_id")
    user_id = current_user.get("id")
    if co_id is None:
        raise HTTPException(400, "company_id bulunamadı")

    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            cur.execute(
                """
                SELECT id, signal_name, current_weight, suggested_weight,
                       confidence, applied_at
                  FROM signal_weight_suggestions
                 WHERE id = %s AND company_id = %s
                 FOR UPDATE
                """,
                (body.suggestion_id, co_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Öneri bulunamadı")
            sug = dict(row)
            if sug.get("applied_at") is not None:
                raise HTTPException(409, "Bu öneri daha önce uygulanmış")
            if sug["signal_name"] not in ALLOWED_SIGNALS:
                raise HTTPException(400, "Geçersiz signal_name")

            # Mevcut weight (override veya default)
            cur.execute(
                "SELECT weight FROM signal_weight_overrides WHERE company_id = %s AND signal_name = %s",
                (co_id, sug["signal_name"]),
            )
            existing = cur.fetchone()
            old_weight = (
                float(existing["weight"]) if existing else float(sug["current_weight"])
            )
            new_weight = float(sug["suggested_weight"])

            # UPSERT override
            cur.execute(
                """
                INSERT INTO signal_weight_overrides
                    (company_id, signal_name, weight, updated_at, updated_by,
                     source_suggestion_id, audit_note)
                VALUES (%s, %s, %s, NOW(), %s, %s, %s)
                ON CONFLICT (company_id, signal_name) DO UPDATE
                    SET weight = EXCLUDED.weight,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by,
                        source_suggestion_id = EXCLUDED.source_suggestion_id,
                        audit_note = EXCLUDED.audit_note
                """,
                (co_id, sug["signal_name"], new_weight, user_id,
                 body.suggestion_id, body.audit_note),
            )

            # Audit log
            cur.execute(
                """
                INSERT INTO signal_weight_audit_log
                    (company_id, signal_name, old_weight, new_weight,
                     changed_by, action, source_suggestion_id, audit_note)
                VALUES (%s, %s, %s, %s, %s, 'apply', %s, %s)
                """,
                (co_id, sug["signal_name"], old_weight, new_weight,
                 user_id, body.suggestion_id, body.audit_note),
            )

            # Suggestion'ı applied olarak işaretle
            cur.execute(
                """
                UPDATE signal_weight_suggestions
                   SET admin_verified = TRUE, applied_at = NOW(), applied_by = %s
                 WHERE id = %s
                """,
                (user_id, body.suggestion_id),
            )

    invalidate_company_weights_cache(co_id)
    return {
        "ok": True,
        "signal_name": sug["signal_name"],
        "old_weight": old_weight,
        "new_weight": new_weight,
    }


@router.put("/{signal_name}")
def manual_override(
    signal_name: str,
    body: ManualOverrideRequest,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Suggestion'sız doğrudan manuel weight set."""
    from app.services.pipeline.nodes.multi_signal_rank import invalidate_company_weights_cache
    if signal_name not in ALLOWED_SIGNALS:
        raise HTTPException(400, f"Geçersiz signal_name. İzin verilen: {sorted(ALLOWED_SIGNALS)}")
    co_id = current_user.get("company_id")
    user_id = current_user.get("id")
    if co_id is None:
        raise HTTPException(400, "company_id bulunamadı")

    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            cur.execute(
                "SELECT weight FROM signal_weight_overrides WHERE company_id = %s AND signal_name = %s",
                (co_id, signal_name),
            )
            existing = cur.fetchone()
            old_weight = float(existing["weight"]) if existing else None

            cur.execute(
                """
                INSERT INTO signal_weight_overrides
                    (company_id, signal_name, weight, updated_at, updated_by, audit_note)
                VALUES (%s, %s, %s, NOW(), %s, %s)
                ON CONFLICT (company_id, signal_name) DO UPDATE
                    SET weight = EXCLUDED.weight,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by,
                        audit_note = EXCLUDED.audit_note,
                        source_suggestion_id = NULL
                """,
                (co_id, signal_name, body.weight, user_id, body.audit_note),
            )
            cur.execute(
                """
                INSERT INTO signal_weight_audit_log
                    (company_id, signal_name, old_weight, new_weight,
                     changed_by, action, audit_note)
                VALUES (%s, %s, %s, %s, %s, 'manual', %s)
                """,
                (co_id, signal_name, old_weight, body.weight, user_id, body.audit_note),
            )

    invalidate_company_weights_cache(co_id)
    return {"ok": True, "signal_name": signal_name, "weight": body.weight}


@router.post("/analyze")
def analyze_now(
    body: AnalyzeRequest = AnalyzeRequest(),
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Scheduler beklemeden manuel öneri tetikleme."""
    from app.services.db_learning.signal_weight_analyzer import run_full_analysis
    co_id = current_user.get("company_id")
    if co_id is None:
        raise HTTPException(400, "company_id bulunamadı")
    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            res = run_full_analysis(
                cur, company_id=co_id, days=body.days,
                min_sample_size=body.min_sample_size,
            )
    return res


@router.post("/reset")
def reset_overrides(
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Şirketin tüm override'larını sil (DEFAULT_WEIGHTS'a dön)."""
    from app.services.pipeline.nodes.multi_signal_rank import invalidate_company_weights_cache
    co_id = current_user.get("company_id")
    user_id = current_user.get("id")
    if co_id is None:
        raise HTTPException(400, "company_id bulunamadı")

    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            cur.execute(
                "SELECT signal_name, weight FROM signal_weight_overrides WHERE company_id = %s",
                (co_id,),
            )
            removed = [dict(r) for r in (cur.fetchall() or [])]
            for r in removed:
                cur.execute(
                    """
                    INSERT INTO signal_weight_audit_log
                        (company_id, signal_name, old_weight, new_weight,
                         changed_by, action, audit_note)
                    VALUES (%s, %s, %s, NULL, %s, 'reset', 'reset-all')
                    """,
                    (co_id, r["signal_name"], r["weight"], user_id),
                )
            cur.execute("DELETE FROM signal_weight_overrides WHERE company_id = %s", (co_id,))

    invalidate_company_weights_cache(co_id)
    return {"ok": True, "removed_count": len(removed)}


@router.get("/audit")
def audit_log(
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(get_current_admin),
) -> Dict[str, Any]:
    co_id = current_user.get("company_id")
    if co_id is None:
        raise HTTPException(400, "company_id bulunamadı")
    limit = max(1, min(500, int(limit)))
    with get_db_context() as conn:
        with conn.cursor() as cur:
            apply_company_scope(cur, co_id)
            cur.execute(
                """
                SELECT id, signal_name, old_weight, new_weight, changed_at,
                       changed_by, action, source_suggestion_id, audit_note
                  FROM signal_weight_audit_log
                 WHERE company_id = %s
                 ORDER BY changed_at DESC
                 LIMIT %s
                """,
                (co_id, limit),
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
    return {"audit_log": rows, "count": len(rows)}
