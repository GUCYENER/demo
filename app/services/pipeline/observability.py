"""
observability — Faz 6c
======================
Pipeline node yürütümlerini yapılandırılmış event olarak kaydeder.

Tasarım kararları:
  - Best-effort: DB hata fırlatırsa pipeline akışı bozulmaz (sessizce geç).
  - run_id state'e bir kez enjekte edilir; tüm event'ler aynı run_id altında.
  - emit() hem DB'ye yazar (cursor varsa) hem logger.info() çağırır.
  - Node sarmalayıcı `instrument_node(name, fn)` decorator/HOF olarak kullanılır:
       state['_pipeline_run_id'] yoksa otomatik üretir
       start/end event'lerini yazar, duration_ms ölçer
       Exception fırlarsa 'error' event + re-raise

Public API:
    ensure_run_id(state) -> str
    emit_event(state, event_type, node_name=None, status=None,
               duration_ms=None, metadata=None) -> None
    instrument_node(name, fn) -> wrapper(fn)
    instrument_pipeline(state, mode) -> ctx manager benzeri (start/end)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Hata fırlatmasın diye ayar
_SILENT_DB_ERRORS = True


def ensure_run_id(state: Dict[str, Any]) -> str:
    """state'te run_id yoksa üretir ve döner."""
    rid = state.get("_pipeline_run_id")
    if not rid:
        rid = str(uuid.uuid4())
        state["_pipeline_run_id"] = rid
    return rid


def emit_event(
    state: Dict[str, Any],
    event_type: str,
    *,
    node_name: Optional[str] = None,
    status: Optional[str] = None,
    duration_ms: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    pipeline_events tablosuna append + log.

    Tablo yoksa veya cursor yoksa: sadece log.

    Tasarım notu: persist çağrısı SAVEPOINT içinde çalışır. INSERT başarısız
    olursa (örn. tablo yok, deadlock, sıkı tip uyumsuzluğu) yalnızca o
    savepoint'e rollback yapılır — pipeline'ın asıl transaction'ı kirlenmez.
    Aksi takdirde tek bir başarısız emit, transaction'ı abort'a düşürüp
    sonraki tüm cur.execute çağrılarını "current transaction is aborted"
    hatasıyla bozar.
    """
    run_id = ensure_run_id(state)
    meta = metadata or {}

    logger.info(
        "[pipeline.event] run=%s type=%s node=%s status=%s ms=%s meta=%s",
        run_id, event_type, node_name, status, duration_ms, meta,
    )

    cur = state.get("_cursor")
    if cur is None:
        return

    # SAVEPOINT adı çakışmayacak: run_id'nin son 8 karakteri.
    sp_name = f"_evt_{run_id[-8:].replace('-', '_')}"
    try:
        cur.execute(f"SAVEPOINT {sp_name}")
        try:
            cur.execute(
                """
                INSERT INTO pipeline_events
                    (run_id, company_id, source_id, user_id,
                     event_type, node_name, duration_ms, status, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    run_id,
                    state.get("company_id"),
                    state.get("source_id"),
                    state.get("user_id"),
                    event_type,
                    node_name,
                    duration_ms,
                    status,
                    json.dumps(meta, default=str, ensure_ascii=False),
                ),
            )
            cur.execute(f"RELEASE SAVEPOINT {sp_name}")
        except Exception as inner:
            try:
                cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                cur.execute(f"RELEASE SAVEPOINT {sp_name}")
            except Exception:
                pass
            if _SILENT_DB_ERRORS:
                logger.debug("[pipeline.event] persist skipped: %s", inner)
            else:
                raise
    except Exception as outer:
        # SAVEPOINT açılamadı (örn. cursor zaten kapalı / transaction yok).
        if _SILENT_DB_ERRORS:
            logger.debug("[pipeline.event] savepoint failed: %s", outer)
        else:
            raise


def instrument_node(name: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]):
    """
    Node fonksiyonunu sarmalar — node_start/node_end event'leri + duration.

    Status hesaplaması: sadece bu node'un EKLEDİĞİ yeni hatalar bakılır.
    Önceki node'dan birikmiş hataları "bu node hatalı" diye etiketlemek
    dashboard'da yanlış suçlamaya yol açıyordu.

    Kullanım:
        instrumented = instrument_node('multi_signal_rank', multi_signal_rank_node)
        state.update(instrumented(state))
    """
    def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
        emit_event(state, "node_start", node_name=name)
        started = time.perf_counter()
        try:
            prior_errors = list(state.get("errors") or [])
            delta = fn(state) or {}
            elapsed_ms = int((time.perf_counter() - started) * 1000)

            # Bu node tarafından eklenen YENİ hata var mı?
            delta_errs = delta.get("errors") if isinstance(delta, dict) else None
            new_errors: list = []
            if isinstance(delta_errs, list):
                # delta.errors birden çok stratejide kullanılır:
                #  - tüm hata listesi (state'i ezer)
                #  - sadece yeni hatalar (append intent)
                # En güvenli yaklaşım: prior'da olmayanları yeni kabul et.
                new_errors = [e for e in delta_errs if e not in prior_errors]
            status = "error" if new_errors else "ok"
            emit_event(
                state, "node_end", node_name=name, status=status,
                duration_ms=elapsed_ms,
                metadata={"errors": new_errors[:3]} if new_errors else None,
            )
            # v3.26.0 Faz 5 — Langfuse span
            try:
                from .langfuse_adapter import is_enabled as _lf_on, log_span as _lf_span
                if _lf_on():
                    _lf_span(
                        state.get("_pipeline_run_id") or "",
                        name=name, duration_ms=elapsed_ms, status=status,
                        metadata={"errors": new_errors[:3]} if new_errors else None,
                    )
            except Exception:
                pass
            return delta
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            emit_event(
                state, "node_end", node_name=name, status="error",
                duration_ms=elapsed_ms, metadata={"exception": str(e)[:300]},
            )
            try:
                from .langfuse_adapter import is_enabled as _lf_on, log_span as _lf_span
                if _lf_on():
                    _lf_span(
                        state.get("_pipeline_run_id") or "",
                        name=name, duration_ms=elapsed_ms, status="error",
                        metadata={"exception": str(e)[:300]},
                    )
            except Exception:
                pass
            raise

    wrapper.__name__ = f"instrumented_{name}"
    return wrapper


def pipeline_start(state: Dict[str, Any], mode: str = "auto") -> None:
    """run başlangıcında çağrılır."""
    run_id = ensure_run_id(state)
    emit_event(
        state, "pipeline_start",
        metadata={
            "mode": mode,
            "question_preview": (state.get("question") or "")[:160],
            "db_dialect": state.get("db_dialect"),
        },
    )
    # v3.26.0 Faz 5 — Langfuse trace (opsiyonel, no-op when disabled)
    try:
        from .langfuse_adapter import is_enabled, start_trace
        if is_enabled():
            start_trace(
                run_id,
                user_id=state.get("user_id"),
                company_id=state.get("company_id"),
                metadata={
                    "mode": mode,
                    "db_dialect": state.get("db_dialect"),
                    "question_preview": (state.get("question") or "")[:160],
                    "source_id": state.get("source_id"),
                },
            )
    except Exception as e:
        logger.debug("[langfuse] start_trace skipped: %s", e)


def pipeline_end(state: Dict[str, Any], duration_ms: int) -> None:
    """run sonunda çağrılır."""
    sql_source = state.get("sql_source") or ("ast" if state.get("force_ast") else "llm")
    errors = state.get("errors") or []
    interrupted = bool(state.get("_interrupt"))
    status = ("interrupt" if interrupted else ("error" if errors else "ok"))
    metadata = {
        "sql_source": sql_source,
        "row_count": state.get("row_count"),
        "retry_count": state.get("retry_count", 0),
        "error_count": len(errors),
        "size_bucket": (state.get("result_size_prediction") or {}).get("bucket"),
    }
    emit_event(
        state, "pipeline_end",
        status=status, duration_ms=duration_ms, metadata=metadata,
    )
    # v3.26.0 Faz 5 — Langfuse trace kapanışı
    try:
        from .langfuse_adapter import is_enabled, end_trace
        if is_enabled():
            run_id = state.get("_pipeline_run_id")
            if run_id:
                end_trace(
                    run_id,
                    output={"row_count": state.get("row_count"),
                            "sql": (state.get("sql") or "")[:500]},
                    status=status,
                    metadata={**metadata, "duration_ms": duration_ms},
                )
    except Exception as e:
        logger.debug("[langfuse] end_trace skipped: %s", e)


def get_run_summary(cursor, run_id: str) -> Dict[str, Any]:
    """Bir run'ın node-bazlı süre özetini döner (dashboard için)."""
    try:
        cursor.execute(
            """
            SELECT node_name,
                   MAX(duration_ms) AS duration_ms,
                   MAX(status) AS status
              FROM pipeline_events
             WHERE run_id = %s AND event_type = 'node_end'
             GROUP BY node_name
             ORDER BY MIN(created_at)
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        return {
            "run_id": run_id,
            "nodes": [
                {"node": r[0], "duration_ms": r[1], "status": r[2]} for r in rows
            ],
            "total_ms": sum((r[1] or 0) for r in rows),
        }
    except Exception:
        return {"run_id": run_id, "nodes": [], "total_ms": 0}
