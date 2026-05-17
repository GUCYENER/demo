"""
load_prefs — Faz 4e
===================
Pipeline başında çalışır; state.user_id varsa user_preferences kaydını yükler.
Sonraki node'lar (multi_signal_rank, retrieve) bu state'i okur.

Best-effort — DB hatası ya da kayıt yoksa state değişmez.
"""
from __future__ import annotations

from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


def load_prefs_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    state.user_id → state.user_preferences.

    v3.26.0 Faz 3 — Available metrics (metric_definitions) state'e enjekte edilir.
    Sonraki node (sql_generate) bunlardan eşleşenleri prompt'a ekler.
    """
    user_id = state.get("user_id")
    cur = state.get("_cursor")
    company_id = state.get("company_id")
    delta: Dict[str, Any] = {}

    if user_id and cur is not None:
        try:
            from app.services.user_preferences_service import load_preferences
            prefs = load_preferences(cur, user_id)
            if prefs:
                delta["user_preferences"] = prefs
        except Exception as e:
            logger.debug("[load_prefs] prefs skipped: %s", e)

    # v3.26.0 — metric_definitions (best-effort)
    if cur is not None and company_id is not None:
        try:
            from app.services.metric_registry import list_metrics
            metrics = list_metrics(
                cur, company_id=company_id,
                source_id=state.get("source_id"),
                include_inactive=False,
            )
            if metrics:
                delta["available_metrics"] = metrics
        except Exception as e:
            logger.debug("[load_prefs] metrics skipped: %s", e)

    return delta
