"""VYRA v3.27.0 — Reasoning Trace Writer (C.G9).

Pipeline state snapshot'ını ``pipeline_traces`` tablosuna kaydeder.
Her run sonunda (run_pipeline / resume_pipeline bitişinde) çağrılır.

Best-effort: hata olursa pipeline akışını bozmaz. Ana cursor'la aynı
TX'te değil — kendi cursor'unu açar ve commit'i caller yapar.

Kayıt alanları:
  * run_id, dialog_id, message_id, source_id, company_id, user_id
  * question, intent + intent_confidence
  * cache_hit, cache_hit_id, ast_shortcut_used
  * candidates_json (ranked tables + scores), selected_tables_json
  * few_shot_ids
  * sql_generated, validation_errors, self_heal_iterations
  * execute_success, row_count, elapsed_ms
  * feedback_value, feedback_id
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# State → row mapping
# ─────────────────────────────────────────────────────────────

def _to_jsonb(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return "[]"


def _build_row(state: Dict[str, Any]) -> Dict[str, Any]:
    """pipeline state → pipeline_traces row dict.

    Tutarlı tip dönüşümü + None-safe alanlar.
    """
    # Validation errors — node çıktısında list[str] veya list[dict] olabilir
    val_errs = state.get("validation_errors") or []
    if val_errs and isinstance(val_errs[0], str):
        val_errs = [{"message": e} for e in val_errs]

    # Candidates — ranked table scores
    candidates = state.get("ranked_tables") or state.get("table_candidates") or []

    # Few-shot ids — populator INSERT id'leri eklemiş olabilir
    fs_ids = state.get("few_shot_used_ids") or state.get("few_shot_ids") or []
    fs_ids = [int(x) for x in fs_ids if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit())]

    return {
        "run_id": state.get("run_id") or state.get("trace_id") or "",
        "dialog_id": state.get("dialog_id"),
        "message_id": state.get("message_id") or state.get("assistant_message_id"),
        "source_id": state.get("source_id"),
        "company_id": state.get("company_id"),
        "user_id": state.get("user_id"),
        "question": (state.get("question") or "")[:8000],
        "intent": state.get("intent"),
        "intent_confidence": state.get("intent_confidence"),
        "cache_hit": bool(state.get("_cache_hit") or state.get("cache_hit")),
        "cache_hit_id": state.get("cache_hit_id"),
        "ast_shortcut_used": (state.get("sql_source") == "ast_shortcut"),
        "candidates_json": _to_jsonb(candidates),
        "selected_tables_json": _to_jsonb(state.get("selected_tables") or []),
        "few_shot_ids": fs_ids or None,
        "sql_generated": (state.get("sql") or "")[:8000] or None,
        "validation_errors": _to_jsonb(val_errs),
        "self_heal_iterations": int(state.get("retry_count") or state.get("self_heal_iterations") or 0),
        "execute_success": state.get("execute_success") if state.get("execute_success") is not None else state.get("success"),
        "row_count": state.get("row_count"),
        "elapsed_ms": state.get("elapsed_ms") or state.get("pipeline_elapsed_ms"),
        "feedback_value": state.get("feedback_value"),
        "feedback_id": state.get("feedback_id"),
    }


# ─────────────────────────────────────────────────────────────
# DB write
# ─────────────────────────────────────────────────────────────

_INSERT_SQL = """
INSERT INTO pipeline_traces (
    run_id, dialog_id, message_id, source_id, company_id, user_id,
    question, intent, intent_confidence,
    cache_hit, cache_hit_id, ast_shortcut_used,
    candidates_json, selected_tables_json, few_shot_ids,
    sql_generated, validation_errors,
    self_heal_iterations, execute_success, row_count, elapsed_ms,
    feedback_value, feedback_id
) VALUES (
    %(run_id)s, %(dialog_id)s, %(message_id)s, %(source_id)s, %(company_id)s, %(user_id)s,
    %(question)s, %(intent)s, %(intent_confidence)s,
    %(cache_hit)s, %(cache_hit_id)s, %(ast_shortcut_used)s,
    %(candidates_json)s::jsonb, %(selected_tables_json)s::jsonb, %(few_shot_ids)s,
    %(sql_generated)s, %(validation_errors)s::jsonb,
    %(self_heal_iterations)s, %(execute_success)s, %(row_count)s, %(elapsed_ms)s,
    %(feedback_value)s, %(feedback_id)s
)
RETURNING id
"""


def write_trace(cur, state: Dict[str, Any]) -> Optional[int]:
    """pipeline_traces'a tek satır yaz.

    Args:
        cur: psycopg2 cursor (RLS scope caller'da set)
        state: pipeline state dict

    Returns:
        Yeni satır id'si veya None (skip / hata)
    """
    if not state.get("question"):
        return None
    if not state.get("source_id"):
        return None
    try:
        params = _build_row(state)
        if not params["run_id"]:
            # run_id boşsa skip — frontend correlation çalışmaz
            return None
        cur.execute(_INSERT_SQL, params)
        row = cur.fetchone()
        if row is None:
            return None
        # RealDictRow vs tuple
        return row.get("id") if hasattr(row, "get") else row[0]
    except Exception as e:
        logger.debug("[trace_writer] insert failed: %s", e)
        return None


def fetch_trace(cur, *, run_id: Optional[str] = None, trace_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Admin debug — run_id veya id ile trace çek."""
    if not (run_id or trace_id):
        return None
    try:
        if trace_id:
            cur.execute("SELECT * FROM pipeline_traces WHERE id = %s LIMIT 1", (trace_id,))
        else:
            cur.execute(
                "SELECT * FROM pipeline_traces WHERE run_id = %s ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row) if not isinstance(row, dict) else row
    except Exception as e:
        logger.debug("[trace_writer.fetch] err: %s", e)
        return None


__all__ = ["write_trace", "fetch_trace", "_build_row"]
