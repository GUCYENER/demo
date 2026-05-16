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
    """state.user_id → state.user_preferences."""
    user_id = state.get("user_id")
    cur = state.get("_cursor")
    if not user_id or cur is None:
        return {}

    try:
        from app.services.user_preferences_service import load_preferences
        prefs = load_preferences(cur, user_id)
    except Exception as e:
        logger.debug("[load_prefs] skipped: %s", e)
        return {}

    if not prefs:
        return {}
    return {"user_preferences": prefs}
