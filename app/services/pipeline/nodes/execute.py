"""
execute — Faz 3e
================
Doğrulanmış SQL'i hedef veri kaynağında çalıştırır.

Gerçek yürütme caller tarafından enjekte edilen `_execute_callable` üzerinden yapılır
(test edilebilirlik + RLS sözleşmesi). Bu sayede pipeline doğrudan
SafeSQLExecutor'a sıkı sıkıya bağlanmaz.

Beklenen callable imzası:
    callable(sql: str) -> {
        "rows": [...], "columns": [...], "row_count": int,
        "elapsed_ms": int, "truncated": bool
    }
"""
from __future__ import annotations

from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


def execute_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """SQL'i çalıştırır, sonuç payload'unu state'e yazar."""
    sql = (state.get("sql") or "").strip()
    if not sql:
        return {"rows": [], "columns": [], "row_count": 0, "elapsed_ms": 0,
                "errors": (state.get("errors") or []) + ["empty_sql"]}

    if not state.get("validation_passed"):
        # Validate başarısızsa ve buraya geldiyse — execute etme, errors döndür
        return {
            "rows": [], "columns": [], "row_count": 0, "elapsed_ms": 0,
            "errors": (state.get("errors") or []) + state.get("validation_errors", []),
        }

    exec_callable = state.get("_execute_callable")
    if exec_callable is None:
        logger.error("[execute] _execute_callable yok — caller injekte etmemiş")
        return {
            "rows": [], "columns": [], "row_count": 0, "elapsed_ms": 0,
            "errors": (state.get("errors") or []) + ["execute_callable_missing"],
        }

    try:
        result = exec_callable(sql)
        return {
            "rows": result.get("rows", []),
            "columns": result.get("columns", []),
            "row_count": int(result.get("row_count", len(result.get("rows", [])))),
            "elapsed_ms": int(result.get("elapsed_ms", 0)),
            "truncated": bool(result.get("truncated", False)),
        }
    except Exception as e:
        logger.error("[execute] yurutme hata: %s", e)
        return {
            "rows": [], "columns": [], "row_count": 0, "elapsed_ms": 0,
            "errors": (state.get("errors") or []) + [f"execute_error: {e}"],
        }
