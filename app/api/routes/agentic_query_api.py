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
from fastapi.responses import StreamingResponse
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
            from app.services.pipeline.wiring import inject_callables

            state: Dict[str, Any] = {
                "question": body.question,
                "source_id": body.source_id,
                "company_id": company_id,
                "user_id": user_id,
                "db_dialect": body.db_dialect or "postgresql",
                "history": body.history or [],
                "_cursor": cur,
            }
            if body.forced_tables:
                state["selected_tables"] = [
                    {"schema_name": t.get("schema"), "table_name": t.get("table")}
                    for t in body.forced_tables
                ]
                state["force_ast"] = True  # AST builder eligibility

            # Prod wiring — LLM + execute + explain
            inject_callables(state, llm=True, execute=True, explain=True)

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


# ---------- Streaming (Faz 6d) ----------
@router.post("/api/agentic-query/stream")
def stream_agentic_query(
    body: AgenticQueryIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    SSE endpoint — pipeline state olaylarını ve sonuç satırlarını batch'ler
    halinde stream eder.

    SSE event type'ları:
      - clarification : ambiguity'de modeli bilgilendirir, kullanıcı resume yapmalı
      - size_prediction : execute öncesi tahmini bucket
      - columns / rows / end : streaming_execute akışı
      - error : hata
      - run_summary : kapanışta node-bazlı duration özeti

    Caller frontend: EventSource veya fetch+ReadableStream ile tüketir.
    """
    company_id = current_user.get("company_id")
    user_id = current_user.get("id") or current_user.get("user_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")

    def _event_stream():
        import json
        from app.services.pipeline.graph import run_pipeline
        from app.services.pipeline.sse_adapter import state_to_clarification_event, format_sse
        from app.services.pipeline.streaming_execute import stream_execute, stream_to_sse
        from app.services.pipeline.observability import get_run_summary
        from app.services.pipeline.wiring import inject_callables

        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                state: Dict[str, Any] = {
                    "question": body.question,
                    "source_id": body.source_id,
                    "company_id": company_id,
                    "user_id": user_id,
                    "db_dialect": body.db_dialect or "postgresql",
                    "history": body.history or [],
                    "_cursor": cur,
                }
                if body.forced_tables:
                    state["selected_tables"] = [
                        {"schema_name": t.get("schema"), "table_name": t.get("table")}
                        for t in body.forced_tables
                    ]
                    state["force_ast"] = True

                # Prod wiring
                inject_callables(state, llm=True, execute=True, explain=True)

                final = run_pipeline(state, mode=body.mode)

                run_id = final.get("_pipeline_run_id")

                # Clarification interrupt
                if final.get("_interrupt"):
                    yield format_sse(state_to_clarification_event(final))
                    conn.commit()
                    return

                # Size prediction
                pred = final.get("result_size_prediction") or {}
                if pred:
                    yield format_sse({"type": "size_prediction", "data": pred})

                # Execute results — stream
                exec_cb = final.get("_execute_callable")
                sql = final.get("sql") or ""
                if exec_cb and sql:
                    for evt in stream_execute(exec_cb, sql, batch_size=200):
                        yield stream_to_sse(evt)
                else:
                    # Buffered yedek: pipeline zaten execute etti, rows içeride
                    cols = final.get("columns") or []
                    rows = final.get("rows") or []
                    if cols:
                        yield stream_to_sse({"type": "columns", "columns": cols})
                    bs = 200
                    for i in range(0, len(rows), bs):
                        yield stream_to_sse({
                            "type": "rows",
                            "rows": rows[i:i + bs],
                            "batch_index": i // bs,
                        })
                    yield stream_to_sse({
                        "type": "end",
                        "row_count": final.get("row_count", len(rows)),
                        "elapsed_ms": final.get("elapsed_ms", 0),
                        "truncated": final.get("truncated", False),
                    })

                # Observability özeti
                if run_id:
                    summary = get_run_summary(cur, run_id)
                    yield format_sse({"type": "run_summary", "data": summary})

                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.exception("[agentic-query/stream] hata")
                yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx buffering kapalı
            "Connection": "keep-alive",
        },
    )


# ---------- Observability ----------
@router.get("/api/agentic-query/runs/{run_id}/summary")
def get_pipeline_run_summary(
    run_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Bir pipeline çalışmasının node-bazlı süre özeti."""
    company_id = current_user.get("company_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.pipeline.observability import get_run_summary
            # company_id ile filtre (yetki)
            cur.execute(
                "SELECT 1 FROM pipeline_events WHERE run_id=%s AND "
                "(company_id IS NULL OR company_id=%s) LIMIT 1",
                (run_id, company_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(404, "Run bulunamadı")
            summary = get_run_summary(cur, run_id)
        finally:
            cur.close()
    return {"success": True, "summary": summary}


@router.get("/api/agentic-query/observability/stats")
def get_observability_stats(
    hours: int = 24,
    company_id: Optional[int] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Pipeline observability özet metrikleri:
      - Toplam run sayısı, başarılı/hatalı/interrupt oranları
      - Node-bazlı p50/p95/avg duration_ms
      - En sık hatalı node
      - sql_source dağılımı (ast vs llm)
      - bucket dağılımı (small/medium/large/huge)
    """
    _require_admin(current_user)
    hours = max(1, min(hours, 24 * 30))
    co = company_id if company_id is not None else current_user.get("company_id")

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            # 1) Run-level toplam
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT run_id) FILTER (WHERE event_type='pipeline_end') AS total_runs,
                    COUNT(DISTINCT run_id) FILTER (WHERE event_type='pipeline_end' AND status='ok') AS ok_runs,
                    COUNT(DISTINCT run_id) FILTER (WHERE event_type='pipeline_end' AND status='error') AS err_runs,
                    COUNT(DISTINCT run_id) FILTER (WHERE event_type='pipeline_end' AND status='interrupt') AS intr_runs,
                    AVG(duration_ms) FILTER (WHERE event_type='pipeline_end') AS avg_total_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
                        FILTER (WHERE event_type='pipeline_end') AS p95_total_ms
                  FROM pipeline_events
                 WHERE created_at >= NOW() - INTERVAL '%s hours'
                   AND (%s::int IS NULL OR company_id = %s)
                """,
                (hours, co, co),
            )
            r = cur.fetchone() or (0, 0, 0, 0, 0, 0)
            run_stats = {
                "total": r[0] or 0, "ok": r[1] or 0, "error": r[2] or 0, "interrupted": r[3] or 0,
                "avg_total_ms": int(r[4] or 0), "p95_total_ms": int(r[5] or 0),
            }

            # 2) Node-bazlı duration
            cur.execute(
                """
                SELECT node_name,
                       COUNT(*)::int AS samples,
                       AVG(duration_ms)::int AS avg_ms,
                       PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms)::int AS p50_ms,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::int AS p95_ms,
                       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)::int AS error_count
                  FROM pipeline_events
                 WHERE event_type='node_end'
                   AND created_at >= NOW() - INTERVAL '%s hours'
                   AND (%s::int IS NULL OR company_id = %s)
                   AND node_name IS NOT NULL
                 GROUP BY node_name
                 ORDER BY avg_ms DESC
                """,
                (hours, co, co),
            )
            nodes = [
                {"node": x[0], "samples": x[1], "avg_ms": x[2],
                 "p50_ms": x[3], "p95_ms": x[4], "error_count": x[5]}
                for x in cur.fetchall()
            ]

            # 3) SQL source dağılımı (metadata->>'sql_source')
            cur.execute(
                """
                SELECT COALESCE(metadata->>'sql_source','unknown') AS src, COUNT(*)::int AS n
                  FROM pipeline_events
                 WHERE event_type='pipeline_end'
                   AND created_at >= NOW() - INTERVAL '%s hours'
                   AND (%s::int IS NULL OR company_id = %s)
                 GROUP BY 1 ORDER BY 2 DESC
                """,
                (hours, co, co),
            )
            sql_source = [{"source": x[0], "count": x[1]} for x in cur.fetchall()]

            # 4) Size bucket dağılımı
            cur.execute(
                """
                SELECT COALESCE(metadata->>'size_bucket','unknown') AS b, COUNT(*)::int AS n
                  FROM pipeline_events
                 WHERE event_type='pipeline_end'
                   AND created_at >= NOW() - INTERVAL '%s hours'
                   AND (%s::int IS NULL OR company_id = %s)
                 GROUP BY 1 ORDER BY 2 DESC
                """,
                (hours, co, co),
            )
            buckets = [{"bucket": x[0], "count": x[1]} for x in cur.fetchall()]

            # 5) Son 20 run
            cur.execute(
                """
                SELECT run_id, status, duration_ms,
                       metadata->>'sql_source', metadata->>'size_bucket',
                       (metadata->>'row_count')::int, created_at
                  FROM pipeline_events
                 WHERE event_type='pipeline_end'
                   AND created_at >= NOW() - INTERVAL '%s hours'
                   AND (%s::int IS NULL OR company_id = %s)
                 ORDER BY created_at DESC LIMIT 20
                """,
                (hours, co, co),
            )
            recent = [
                {"run_id": str(x[0]), "status": x[1], "duration_ms": x[2],
                 "sql_source": x[3], "size_bucket": x[4],
                 "row_count": x[5], "created_at": x[6].isoformat() if x[6] else None}
                for x in cur.fetchall()
            ]
        finally:
            cur.close()

    return {
        "success": True,
        "window_hours": hours,
        "company_id": co,
        "runs": run_stats,
        "nodes": nodes,
        "sql_source": sql_source,
        "size_buckets": buckets,
        "recent_runs": recent,
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
