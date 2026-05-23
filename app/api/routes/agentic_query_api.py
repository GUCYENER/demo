"""
Agentic Query API — Faz 5f + Faz 6d/g
=====================================
Faz 4-6 servisleri için backend endpoint'leri:

  GET    /api/preferences/me                       → kendi user_preferences
  PUT    /api/preferences/me                       → upsert
  GET    /api/few-shots                            → liste (company filter)
  POST   /api/few-shots                            → yeni örnek ekle
  DELETE /api/few-shots/{id}                       → sil
  POST   /api/agentic-query                        → pipeline run (sync, mode='auto'/'force')
  POST   /api/agentic-query/resume                 → clarification sonrası resume
  POST   /api/agentic-query/stream                 → SSE stream (Faz 6d)
  GET    /api/agentic-query/runs/{run_id}/summary  → run özeti (Faz 6c)
  GET    /api/agentic-query/observability/stats    → admin dashboard (Faz 6g)
  POST   /api/ml/train                             → CatBoost training trigger (admin)
  POST   /api/ml/models/{id}/activate              → model aktifleştir (admin)
  GET    /api/ml/models                            → liste

Tüm endpoint'lerin yetki kuralı:
  - me-* endpoint'ler: kullanıcı kendisi için
  - few-shots: company_id auto + tenant filter
  - agentic-query/*: tenant izolasyonu (company_id = caller's company)
  - ml/*: is_admin gerekli
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context, apply_company_scope

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
    """
    Clarification interrupt'tan sonra pipeline'ı sürdürmek için body.

    state: önceki run'ın döndüğü serileştirilebilir state (callable/cursor hariç).
           Caller (frontend) bunu yerel olarak saklar ve resume'da geri yollar.
    user_choice: ya `selected_indices` (ranked_candidates'tan indeksler) ya da
                 `selected_tables` (doğrudan {schema, table} listesi) içerir.
    """
    state: Dict[str, Any]
    selected_indices: Optional[List[int]] = None
    selected_tables: Optional[List[Dict[str, str]]] = None


class TrainIn(BaseModel):
    company_id: Optional[int] = None
    source_id: Optional[int] = None
    min_samples: int = 50
    notes: Optional[str] = None


class SyntheticQIn(BaseModel):
    """v3.28.0 G2 — synthetic Q/SQL pair generator için admin endpoint body."""
    source_id: int
    company_id: int
    target_count: int = Field(30, ge=1, le=200)
    batch_size: int = Field(5, ge=1, le=20)
    dry_run: bool = False


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

            # v3.26.0 Faz 1 — Migration 017 RLS tenant scope
            apply_company_scope(cur, company_id=company_id)

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


# ---------- Resume (Faz 3f clarification) ----------
@router.post("/api/agentic-query/resume")
def resume_agentic_query(
    body: AgenticResumeIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Clarification interrupt'tan sonra pipeline'ı sürdürür.

    Tasarım: stateless — pipeline state'i frontend tarafında saklanır ve
    resume isteğinde geri gönderilir. Tenant tutarlılığı için body.state
    içindeki company_id, çağıran kullanıcının company_id'si ile karşılaştırılır.
    """
    company_id = current_user.get("company_id")
    user_id = current_user.get("id") or current_user.get("user_id")
    if not company_id:
        raise HTTPException(400, "company_id eksik")

    state = dict(body.state or {})
    # Tenant izolasyonu — caller başka tenant'ın state'ini sürdüremez.
    if state.get("company_id") not in (None, company_id):
        raise HTTPException(403, "Bu run sizin tenant'ınıza ait değil")
    state["company_id"] = company_id
    state["user_id"] = user_id

    # Callable / cursor alanları client'tan gelmez; yeniden enjekte edilir.
    for k in list(state.keys()):
        if k.startswith("_") and k not in ("_pipeline_run_id", "_interrupt"):
            state.pop(k, None)
    state.pop("_interrupt", None)

    user_choice: Dict[str, Any] = {}
    if body.selected_indices:
        user_choice["selected_indices"] = body.selected_indices
    if body.selected_tables:
        user_choice["selected_tables"] = [
            {"schema_name": t.get("schema"), "table_name": t.get("table")}
            for t in body.selected_tables
        ]
    if not user_choice:
        raise HTTPException(400, "selected_indices veya selected_tables zorunlu")

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.pipeline.graph import resume_pipeline
            from app.services.pipeline.wiring import inject_callables

            # v3.26.0 Faz 1 — Migration 017 RLS tenant scope
            apply_company_scope(cur, company_id=company_id)

            state["_cursor"] = cur
            inject_callables(state, llm=True, execute=True, explain=True)
            final = resume_pipeline(state, user_choice)
            response = {k: v for k, v in final.items() if not k.startswith("_")}
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.exception("[agentic-query/resume] hata")
            raise HTTPException(500, f"Resume hata: {e}")
        finally:
            cur.close()

    return {
        "success": True,
        "interrupted": bool(final.get("_interrupt")),
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
        from app.services.pipeline.sse_adapter import (
            state_to_clarification_event,
            state_to_clarification_v2_event,
            format_sse,
        )
        from app.services.pipeline.streaming_execute import stream_execute, stream_to_sse
        from app.services.pipeline.observability import get_run_summary
        from app.services.pipeline.wiring import inject_callables

        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                # v3.26.0 Faz 1 — Migration 017 RLS tenant scope
                apply_company_scope(cur, company_id=company_id)

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

                # Clarification interrupt — v3.29.7 G2: v2 (zengin kartlar) varsa
                # geri uyumlu v1 + yeni v2 birlikte yayınlanır. Frontend tercih ettiği
                # event'i handle eder; her ikisini de gören modern istemci v2'yi kullanır.
                if final.get("_interrupt"):
                    yield format_sse(state_to_clarification_event(final))
                    if final.get("clarification_cards"):
                        yield format_sse(state_to_clarification_v2_event(final))
                    conn.commit()
                    return

                # v3.27.0 — Cache hit notification ("⚡ Önceki öğrenmeden")
                if final.get("_cache_hit"):
                    yield format_sse({
                        "type": "cache_hit",
                        "data": {
                            "id": final.get("_cache_hit_id"),
                            "similarity": float(final.get("_cache_similarity") or 0.0),
                            "source": final.get("_cache_source") or "user",
                            "intent": final.get("intent"),
                            "sql": final.get("sql"),
                        },
                    })

                # v3.28.2 G3 — Sample Data Preview (cache'ten okur; execute öncesi)
                # Lookup intent + tek tablo + cache hit yoksa kullanıcıya aday tablo +
                # ilk N satırı gösteririz. Hata olursa graceful: SSE event yayma.
                # v3.32.0: pick_preview_table_validated — ranker pick'i (selected_tables[0])
                # final SQL ile cross-check eder. Multi-table JOIN durumunda preview atlanır;
                # single-table SQL'de ranker yanlışsa bile SQL'deki gerçek tablo kullanılır.
                try:
                    if not final.get("_cache_hit"):
                        from app.services.pipeline.nodes.sample_data_preview import (
                            build_sample_preview,
                            pick_preview_table_validated,
                        )
                        pick = pick_preview_table_validated(final)
                        if pick and body.source_id:
                            preview = build_sample_preview(
                                cur,
                                source_id=int(body.source_id),
                                schema=pick.get("schema"),
                                table=pick.get("table"),
                                limit=5,
                            )
                            if preview:
                                yield format_sse({
                                    "type": "sample_data_preview",
                                    "data": {
                                        "source_id": int(body.source_id),
                                        **preview,
                                    },
                                })
                except Exception:
                    logger.debug("[agentic-query/stream] sample_data_preview skipped", exc_info=True)

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
            # Tenant izolasyonu — company_id NULL kayıtları da artık ait olduğu
            # tenant'a sızdırmaz; sadece tam eşleşme kabul edilir. Admin için
            # _require_admin kullanılırdı ama bu endpoint normal kullanıcıya açık.
            if company_id is None:
                raise HTTPException(400, "company_id eksik")
            cur.execute(
                "SELECT 1 FROM pipeline_events WHERE run_id=%s AND company_id=%s LIMIT 1",
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

    # Pencere intervali (make_interval — string interpolation YOK).
    # hours yukarıda max/min ile sınırlandığı için integer olduğu garanti.
    # company_id (co) None ise tüm tenant'lara açılır (sadece admin yolu).
    co_clause = "AND company_id = %s" if co is not None else ""

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            # 1) Run-level toplam
            # Resume edilen run'larda aynı run_id için BİRDEN ÇOK pipeline_end
            # event'i olabilir (önce status=interrupt, resume sonrası status=ok).
            # Aynı run hem 'interrupt' hem 'ok' bucket'a sayılmasın diye her
            # run_id için en SON pipeline_end satırını seç (DISTINCT ON).
            base_params: list = [hours]
            if co is not None:
                base_params.append(co)

            cur.execute(
                f"""
                WITH final_ends AS (
                    SELECT DISTINCT ON (run_id) run_id, status, duration_ms
                      FROM pipeline_events
                     WHERE event_type='pipeline_end'
                       AND created_at >= NOW() - make_interval(hours => %s)
                       {co_clause}
                     ORDER BY run_id, created_at DESC
                )
                SELECT
                    COUNT(*) AS total_runs,
                    COUNT(*) FILTER (WHERE status='ok') AS ok_runs,
                    COUNT(*) FILTER (WHERE status='error') AS err_runs,
                    COUNT(*) FILTER (WHERE status='interrupt') AS intr_runs,
                    AVG(duration_ms) AS avg_total_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_total_ms
                  FROM final_ends
                """,
                tuple(base_params),
            )
            r = cur.fetchone() or (0, 0, 0, 0, 0, 0)
            run_stats = {
                "total": r[0] or 0, "ok": r[1] or 0, "error": r[2] or 0, "interrupted": r[3] or 0,
                "avg_total_ms": int(r[4] or 0), "p95_total_ms": int(r[5] or 0),
            }

            # 2) Node-bazlı duration
            cur.execute(
                f"""
                SELECT node_name,
                       COUNT(*)::int AS samples,
                       AVG(duration_ms)::int AS avg_ms,
                       PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_ms)::int AS p50_ms,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::int AS p95_ms,
                       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)::int AS error_count
                  FROM pipeline_events
                 WHERE event_type='node_end'
                   AND created_at >= NOW() - make_interval(hours => %s)
                   {co_clause}
                   AND node_name IS NOT NULL
                 GROUP BY node_name
                 ORDER BY avg_ms DESC
                """,
                tuple(base_params),
            )
            nodes = [
                {"node": x[0], "samples": x[1], "avg_ms": x[2],
                 "p50_ms": x[3], "p95_ms": x[4], "error_count": x[5]}
                for x in cur.fetchall()
            ]

            # 3) SQL source dağılımı (metadata->>'sql_source')
            # DISTINCT ON ile resume duplicate'leri elenmiş.
            cur.execute(
                f"""
                WITH final_ends AS (
                    SELECT DISTINCT ON (run_id) run_id, metadata
                      FROM pipeline_events
                     WHERE event_type='pipeline_end'
                       AND created_at >= NOW() - make_interval(hours => %s)
                       {co_clause}
                     ORDER BY run_id, created_at DESC
                )
                SELECT COALESCE(metadata->>'sql_source','unknown') AS src, COUNT(*)::int AS n
                  FROM final_ends
                 GROUP BY 1 ORDER BY 2 DESC
                """,
                tuple(base_params),
            )
            sql_source = [{"source": x[0], "count": x[1]} for x in cur.fetchall()]

            # 4) Size bucket dağılımı
            cur.execute(
                f"""
                WITH final_ends AS (
                    SELECT DISTINCT ON (run_id) run_id, metadata
                      FROM pipeline_events
                     WHERE event_type='pipeline_end'
                       AND created_at >= NOW() - make_interval(hours => %s)
                       {co_clause}
                     ORDER BY run_id, created_at DESC
                )
                SELECT COALESCE(metadata->>'size_bucket','unknown') AS b, COUNT(*)::int AS n
                  FROM final_ends
                 GROUP BY 1 ORDER BY 2 DESC
                """,
                tuple(base_params),
            )
            buckets = [{"bucket": x[0], "count": x[1]} for x in cur.fetchall()]

            # 5) Son 20 run — resume duplicate'leri elenir, son created_at'a göre.
            # DISTINCT ON kendi ORDER BY'ını run_id ile başlatmak zorunda olduğu
            # için en güncel 20'yi seçmek üzere alt sorguya gerek var.
            cur.execute(
                f"""
                WITH final_ends AS (
                    SELECT DISTINCT ON (run_id)
                           run_id, status, duration_ms,
                           metadata, created_at
                      FROM pipeline_events
                     WHERE event_type='pipeline_end'
                       AND created_at >= NOW() - make_interval(hours => %s)
                       {co_clause}
                     ORDER BY run_id, created_at DESC
                )
                SELECT run_id, status, duration_ms,
                       metadata->>'sql_source', metadata->>'size_bucket',
                       (metadata->>'row_count')::int, created_at
                  FROM final_ends
                 ORDER BY created_at DESC
                 LIMIT 20
                """,
                tuple(base_params),
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


# ---------- Synthetic Q/SQL Generator (v3.28.0 G2) ----------
@router.post("/api/ml/synthetic-q/generate")
def generate_synthetic_q(
    body: SyntheticQIn,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """v3.28.0 G2 — Onaylı tablolar için LLM-tabanlı sentetik Q/SQL pair üretimi.

    Üç katmanlı dedupe + günlük LLM bütçe kontrolü uygular.
    `few_shot_examples` tablosuna INSERT eder (dry_run=False ise).
    """
    _require_admin(current_user)
    user_id = current_user.get("id") or current_user.get("user_id")
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            from app.services.ml.synthetic_db_query_pairs import generate_db_query_pairs
            res = generate_db_query_pairs(
                cur,
                source_id=body.source_id,
                company_id=body.company_id,
                target_count=body.target_count,
                batch_size=body.batch_size,
                dry_run=body.dry_run,
                created_by=user_id,
            )
            if res.get("success") and not body.dry_run:
                conn.commit()
            else:
                conn.rollback()
        finally:
            cur.close()
    return res


@router.get("/api/ml/synthetic-q/budget")
def get_synthetic_q_budget(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Mevcut günlük LLM bütçe durumunu döner (admin observability)."""
    _require_admin(current_user)
    from app.services.ml.synthetic_db_query_pairs import get_budget_state
    from app.core.config import settings
    return {
        "success": True,
        "budget_state": get_budget_state(),
        "max_daily_budget_usd": float(getattr(settings, "MAX_LLM_DAILY_BUDGET_USD", 1.0)),
    }


# ──────────────────────────────────────────────────────────────────────────
# v3.29.7 G5 — Faz 6 Observability sekmeleri
#   /observability/template-heatmap → template_kind × complexity_score grid
#   /observability/failures-top      → tekrar eden hata pattern top-10
#   /observability/glossary-usage    → en sık kullanılan glossary term'leri
# ──────────────────────────────────────────────────────────────────────────

@router.get("/api/agentic-query/observability/template-heatmap")
def get_template_heatmap(
    days: int = 30,
    company_id: Optional[int] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """ds_synthetic_query_runs üzerinden template_kind × complexity_score heatmap.

    Hücre değeri: en son `days` gün içinde başarılı üretilen (status='ok')
    sorgu sayısı. Frontend renk yoğunluğu için kullanır.
    """
    _require_admin(current_user)
    days = max(1, min(days, 365))
    co = company_id if company_id is not None else current_user.get("company_id")
    co_clause = "AND company_id = %s" if co is not None else ""
    params: list = [days]
    if co is not None:
        params.append(co)

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            # v3.29.10 fix: kolon adları ds_synthetic_query_runs şemasıyla hizalandı
            #   - created_at  →  executed_at  (021 migration)
            #   - status='ok' →  success      (BOOLEAN, 021 migration)
            # Migration uygulanmamışsa veya kolon yoksa boş dön (500 yerine).
            try:
                cur.execute(
                    f"""
                    SELECT template_kind,
                           COALESCE(complexity_score, 1) AS complexity_score,
                           COUNT(*)::int AS run_count,
                           AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)::float AS success_rate
                      FROM ds_synthetic_query_runs
                     WHERE executed_at >= NOW() - make_interval(days => %s)
                       {co_clause}
                     GROUP BY template_kind, COALESCE(complexity_score, 1)
                     ORDER BY template_kind, complexity_score
                    """,
                    tuple(params),
                )
                rows = cur.fetchall() or []
            except Exception as exc:
                logger.warning("[observability/template-heatmap] query failed: %s", exc)
                rows = []

            # RealDictCursor → dict access; fallback to tuple indexing
            def _rget(r, key, idx):
                if isinstance(r, dict):
                    return r.get(key)
                try:
                    return r[idx]
                except Exception:
                    return None
            cells = [
                {
                    "template_kind": _rget(r, "template_kind", 0),
                    "complexity_score": int(_rget(r, "complexity_score", 1) or 1),
                    "run_count": int(_rget(r, "run_count", 2) or 0),
                    "success_rate": float(_rget(r, "success_rate", 3) or 0.0),
                }
                for r in rows
            ]
            kinds = sorted({c["template_kind"] for c in cells if c["template_kind"]})
            complexities = sorted({c["complexity_score"] for c in cells})
        finally:
            cur.close()

    return {
        "success": True,
        "days": days,
        "kinds": kinds,
        "complexities": complexities,
        "cells": cells,
    }


@router.get("/api/agentic-query/observability/failures-top")
def get_failures_top(
    limit: int = 10,
    company_id: Optional[int] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """learned_query_failures'tan recurrence_count'a göre top-N hata."""
    _require_admin(current_user)
    limit = max(1, min(limit, 50))
    co = company_id if company_id is not None else current_user.get("company_id")
    co_clause = "WHERE company_id = %s" if co is not None else ""
    params: list = []
    if co is not None:
        params.append(co)
    params.append(limit)

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            # Tabloyu try/except ile sar — migration uygulanmamışsa hata vermek yerine boş dön
            try:
                cur.execute(
                    f"""
                    SELECT error_class,
                           recurrence_count,
                           failure_signature,
                           LEFT(COALESCE(failed_sql, ''), 200) AS sql_snippet,
                           LEFT(COALESCE(pattern_hint, ''), 200) AS hint,
                           updated_at
                      FROM learned_query_failures
                      {co_clause}
                     ORDER BY recurrence_count DESC, updated_at DESC
                     LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall() or []
            except Exception as exc:
                logger.warning("[observability/failures-top] table not ready: %s", exc)
                rows = []

            failures = [
                {
                    "error_class": r[0],
                    "recurrence_count": int(r[1] or 0),
                    "signature": r[2],
                    "sql_snippet": r[3],
                    "hint": r[4],
                    "last_seen": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]

            # Class bazlı toplam
            try:
                cur.execute(
                    f"""
                    SELECT error_class, COUNT(*)::int AS occurrences,
                           SUM(recurrence_count)::int AS total_recurrence
                      FROM learned_query_failures
                      {co_clause}
                     GROUP BY error_class
                     ORDER BY total_recurrence DESC
                    """,
                    tuple(params[:-1]),
                )
                cls_rows = cur.fetchall() or []
            except Exception:
                cls_rows = []
            by_class = [
                {"error_class": r[0], "occurrences": r[1], "total_recurrence": r[2]}
                for r in cls_rows
            ]
        finally:
            cur.close()

    return {"success": True, "limit": limit, "failures": failures, "by_class": by_class}


@router.get("/api/agentic-query/observability/glossary-usage")
def get_glossary_usage(
    limit: int = 20,
    company_id: Optional[int] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """business_glossary'den usage_count'a göre top-N glossary term."""
    _require_admin(current_user)
    limit = max(1, min(limit, 100))
    co = company_id if company_id is not None else current_user.get("company_id")
    co_clause = "WHERE company_id = %s" if co is not None else ""
    params: list = []
    if co is not None:
        params.append(co)
    params.append(limit)

    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            try:
                cur.execute(
                    f"""
                    SELECT term,
                           COALESCE(term_type, 'unknown') AS term_type,
                           COALESCE(expansion_tr, '') AS expansion_tr,
                           COALESCE(mapped_table, '') AS mapped_table,
                           COALESCE(usage_count, 0) AS usage_count,
                           COALESCE(admin_verified, FALSE) AS admin_verified,
                           updated_at
                      FROM business_glossary
                      {co_clause}
                     ORDER BY COALESCE(usage_count, 0) DESC, term
                     LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall() or []
            except Exception as exc:
                logger.warning("[observability/glossary-usage] table not ready: %s", exc)
                rows = []

            terms = [
                {
                    "term": r[0],
                    "term_type": r[1],
                    "expansion_tr": r[2],
                    "mapped_table": r[3],
                    "usage_count": int(r[4] or 0),
                    "admin_verified": bool(r[5]),
                    "updated_at": r[6].isoformat() if r[6] else None,
                }
                for r in rows
            ]

            # Type dağılımı
            try:
                cur.execute(
                    f"""
                    SELECT COALESCE(term_type, 'unknown') AS t,
                           COUNT(*)::int AS cnt,
                           SUM(COALESCE(usage_count, 0))::int AS total_usage,
                           SUM(CASE WHEN admin_verified THEN 1 ELSE 0 END)::int AS verified_cnt
                      FROM business_glossary
                      {co_clause}
                     GROUP BY t
                     ORDER BY total_usage DESC
                    """,
                    tuple(params[:-1]),
                )
                type_rows = cur.fetchall() or []
            except Exception:
                type_rows = []
            by_type = [
                {"term_type": r[0], "count": r[1], "total_usage": r[2], "verified": r[3]}
                for r in type_rows
            ]
        finally:
            cur.close()

    return {"success": True, "limit": limit, "terms": terms, "by_type": by_type}
