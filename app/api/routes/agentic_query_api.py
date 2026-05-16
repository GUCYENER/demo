"""
Agentic Query API — Faz 5f
==========================
Faz 4-5 servisleri için backend endpoint'leri:

  GET    /api/preferences/me                 → kendi user_preferences
  PUT    /api/preferences/me                 → upsert
  GET    /api/few-shots                      → liste (company filter)
  POST   /api/few-shots                      → yeni örnek ekle
  DELETE /api/few-shots/{id}                 → sil
  POST   /api/agentic-query                  → pipeline run (sync, mode='auto'/'force')
  POST   /api/agentic-query/resume           → clarification sonrası resume
  POST   /api/ml/train                       → CatBoost training trigger (admin)
  POST   /api/ml/models/{id}/activate        → model aktifleştir (admin)
  GET    /api/ml/models                      → liste

Tüm endpoint'lerin yetki kuralı:
  - me-* endpoint'ler: kullanıcı kendisi için
  - few-shots: company_id auto
  - ml/*: is_admin gerekli
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agentic_query"])


# ---------- Models ----------
class PreferencesIn(BaseModel):
    weight_overrides: Optional[Dict[str, float]] = None
    preferred_tables: Optional[List[str]] = None
    blacklisted_tables: Optional[List[str]] = None
    settings: Optional[Dict[str, Any]] = None


class FewShotIn(BaseModel):
    source_id: Optional[int] = None
    question: str = Field(min_length=3, max_length=2000)
    sql_query: str = Field(min_length=5, max_length=20000)
    intent: Optional[str] = Field(None, max_length=64)
    schema_signature: Optional[str] = Field(None, max_length=512)


class AgenticQueryIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    source_id: int
    mode: str = Field("auto", pattern="^(auto|force|sync)$")
    forced_tables: Optional[List[Dict[str, str]]] = None  # [{schema, table}]
    db_dialect: Optional[str] = "postgresql"
    history: Optional[List[Dict[str, Any]]] = None


class AgenticResumeIn(BaseModel):
    state_token: str  # opaque (caller saklar; bu prototipte session storage)
    selected_indices: Optional[List[int]] = None
    selected_tables: Optional[List[Dict[str, str]]] = None


class TrainIn(BaseModel):
    company_id: Optional[int] = None
    source_id: Optional[int] = None
    min_samples: int = 50
    notes: Optional[str] = None


# ---------- Helpers ----------
def _require_admin(user: Dict[str, Any]) -> None:
    if not (user.get("is_admin") or user.get("role") == "admin"):
        raise HTTPException(403, "Bu işlem için yönetici yetkisi gerekli")


# ---------- Preferences ----------
@router.get("/api/preferences/me")
def get_my_preferences(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = current_user.get("id") or current_user.get("user_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.user_preferences_service import load_preferences
            prefs = load_preferences(cur, user_id)
        finally:
            cur.close()
    return {"success": True, "preferences": prefs}


@router.put("/api/preferences/me")
def update_my_preferences(
    body: PreferencesIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = current_user.get("id") or current_user.get("user_id")
    company_id = current_user.get("company_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.user_preferences_service import upsert_preferences
            updates = {k: v for k, v in body.dict(exclude_none=True).items()}
            upsert_preferences(cur, user_id=user_id, company_id=company_id, **updates)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("[preferences] update hata: %s", e)
            raise HTTPException(500, "Tercihler güncellenemedi")
        finally:
            cur.close()
    return {"success": True}


# ---------- Few-shots ----------
@router.get("/api/few-shots")
def list_few_shots(
    source_id: Optional[int] = None,
    limit: int = 50,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    limit = min(max(limit, 1), 200)
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            params: List[Any] = [company_id]
            extra = ""
            if source_id is not None:
                extra = " AND (source_id = %s OR source_id IS NULL)"
                params.append(source_id)
            cur.execute(f"""
                SELECT id, source_id, question, sql_query, intent, schema_signature,
                       usage_count, success_rate, last_used_at, created_at
                  FROM few_shot_examples
                 WHERE company_id = %s{extra}
                 ORDER BY usage_count DESC, created_at DESC
                 LIMIT %s
            """, params + [limit])
            rows = cur.fetchall()
        finally:
            cur.close()

    return {
        "success": True,
        "items": [
            {
                "id": r[0], "source_id": r[1], "question": r[2], "sql_query": r[3],
                "intent": r[4], "schema_signature": r[5],
                "usage_count": r[6], "success_rate": r[7],
                "last_used_at": r[8].isoformat() if r[8] else None,
                "created_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows
        ],
    }


@router.post("/api/few-shots")
def create_few_shot(
    body: FewShotIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    user_id = current_user.get("id") or current_user.get("user_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.rag.few_shot_selector import upsert_example
            new_id = upsert_example(
                cur,
                company_id=company_id, source_id=body.source_id,
                question=body.question, sql_query=body.sql_query,
                intent=body.intent, schema_signature=body.schema_signature,
                embedding=None, created_by=user_id,
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("[few-shots] create hata: %s", e)
            raise HTTPException(500, "Örnek oluşturulamadı")
        finally:
            cur.close()
    if not new_id:
        raise HTTPException(500, "Örnek eklenemedi")
    return {"success": True, "id": new_id}


@router.delete("/api/few-shots/{example_id}")
def delete_few_shot(
    example_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM few_shot_examples WHERE id = %s AND company_id = %s",
                (example_id, company_id),
            )
            n = cur.rowcount
            conn.commit()
        finally:
            cur.close()
    if n == 0:
        raise HTTPException(404, "Örnek bulunamadı")
    return {"success": True, "deleted": n}


# ---------- Agentic Query ----------
@router.post("/api/agentic-query")
def run_agentic_query(
    body: AgenticQueryIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Pipeline'ı senkron çağırır. Interrupt durumunda clarification_payload döner;
    caller resume endpoint'i ile devam ettirir.

    NOT: Bu endpoint LLM/execute callable'larını wire etmeyi gerektirir. Bu
    prototipte placeholder (LLM = deep_think servisi, execute = safe_sql_executor).
    Wire yapılmadığı için errors içinde 'llm_callable_missing' görülebilir.
    """
    company_id = current_user.get("company_id")
    user_id = current_user.get("id") or current_user.get("user_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.pipeline.graph import run_pipeline

            state: Dict[str, Any] = {
                "question": body.question,
                "source_id": body.source_id,
                "company_id": company_id,
                "user_id": user_id,
                "db_dialect": body.db_dialect or "postgresql",
                "history": body.history or [],
                "_cursor": cur,
                # LLM/execute wiring yok — geliştirme aşaması, prod'da inject edilecek
            }
            if body.forced_tables:
                state["selected_tables"] = [
                    {"schema_name": t.get("schema"), "table_name": t.get("table")}
                    for t in body.forced_tables
                ]
                state["force_ast"] = True  # AST builder eligibility

            final = run_pipeline(state, mode=body.mode)

            # Cursor'ı state'ten çıkar (serialize edilemez)
            response = {k: v for k, v in final.items() if not k.startswith("_")}
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.exception("[agentic-query] hata")
            raise HTTPException(500, f"Pipeline hata: {e}")
        finally:
            cur.close()

    interrupted = bool(final.get("_interrupt"))
    return {
        "success": True,
        "interrupted": interrupted,
        "state": response,
    }


# ---------- ML / Training ----------
@router.post("/api/ml/train")
def train_model(
    body: TrainIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user)
    user_id = current_user.get("id") or current_user.get("user_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.ml.catboost_trainer import train_ranking_model
            res = train_ranking_model(
                cur,
                company_id=body.company_id,
                source_id=body.source_id,
                min_samples=body.min_samples,
                notes=body.notes,
                trained_by=user_id,
            )
            if res.get("ok"):
                conn.commit()
            else:
                conn.rollback()
        finally:
            cur.close()
    return res


@router.post("/api/ml/models/{model_id}/activate")
def activate_ml_model(
    model_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.ml.catboost_trainer import activate_model
            ok = activate_model(cur, model_id)
            if ok:
                conn.commit()
            else:
                conn.rollback()
        finally:
            cur.close()
    if not ok:
        raise HTTPException(404, "Model bulunamadı")
    return {"success": True}


@router.get("/api/ml/models")
def list_ml_models(
    model_type: Optional[str] = None,
    company_id: Optional[int] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            where = []
            params: List[Any] = []
            if model_type:
                where.append("model_type = %s"); params.append(model_type)
            if company_id is not None:
                where.append("company_id = %s"); params.append(company_id)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            cur.execute(f"""
                SELECT id, model_type, version, file_path, training_size,
                       train_metrics, validation_metrics, is_active,
                       company_id, created_at, notes
                  FROM catboost_models{where_sql}
                 ORDER BY created_at DESC
                 LIMIT 200
            """, params)
            rows = cur.fetchall()
        finally:
            cur.close()
    return {
        "success": True,
        "models": [
            {
                "id": r[0], "model_type": r[1], "version": r[2], "file_path": r[3],
                "training_size": r[4], "train_metrics": r[5],
                "validation_metrics": r[6], "is_active": r[7],
                "company_id": r[8],
                "created_at": r[9].isoformat() if r[9] else None,
                "notes": r[10],
            }
            for r in rows
        ],
    }
