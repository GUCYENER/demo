"""
validate — Faz 3e
=================
SQL'i çalıştırmadan önce statik + EXPLAIN pre-flight kontrol.

Statik kontrol: app/services/safe_sql_executor.py:validate_sql (whitelist, DDL ban,
       JOIN/WHERE sanity, vs.) — zaten mevcut.

EXPLAIN pre-flight: caller'ın SQL'i target source'a karşı EXPLAIN/EXPLAIN PLAN ile
       çalıştırır — sözdizimi ve şema kontrolu için. Faz 3'te opsiyonel (callable injekte).

Self-heal routing: route_after_validate → 'sql_generate' (retry) | 'execute'.
"""
from __future__ import annotations

from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SQL'i statik valide eder, EXPLAIN callable varsa onu da çalıştırır."""
    sql = (state.get("sql") or "").strip()
    if not sql:
        return {"validation_passed": False, "validation_errors": ["empty_sql"]}

    errors = []

    # Statik valide (mevcut servis)
    try:
        from app.services.safe_sql_executor import validate_sql
        ok, err = validate_sql(sql)
        if not ok:
            errors.append(f"static: {err}")
    except Exception as e:
        logger.warning("[validate] static validator yuklenemedi: %s", e)

    # EXPLAIN pre-flight (opsiyonel — caller injekte eder)
    explain_callable = state.get("_explain_callable")
    explain_plan = None
    if explain_callable and not errors:
        try:
            explain_plan = explain_callable(sql)
        except Exception as e:
            errors.append(f"explain: {e}")

    passed = len(errors) == 0
    out = {"validation_passed": passed, "validation_errors": errors}
    if explain_plan is not None:
        out["explain_plan"] = explain_plan
    return out


def route_after_validate(state: Dict[str, Any]) -> str:
    """
    LangGraph conditional edge:
      - passed → 'execute'
      - failed + retry_count < MAX_RETRIES → 'sql_generate' (self-heal)
      - failed + retry_count >= MAX_RETRIES → 'execute' (fail) or 'END'
    """
    if state.get("validation_passed"):
        return "execute"
    retry_count = state.get("retry_count", 0)
    if retry_count < MAX_RETRIES:
        return "sql_generate"
    return "execute"  # son denemede yine de execute'a düşüyoruz (logla & döndür)
