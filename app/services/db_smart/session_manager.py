"""dbsmart_sessions CRUD + Redis L1 cache (v3.30.0 FAZ 0 iskelet).

Sorumluluklar (gerçek implementasyon FAZ 1 G1.1'de):
    - create_session(user_ctx, source_id) → session_uid (UUID)
    - load_session(session_uid, user_ctx) → context dict
    - update_context(session_uid, partial_state, user_ctx)
    - mark_completed / mark_abandoned
    - Redis L1 cache: anahtar "dbsmart:sess:{uid}", TTL 30dk
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def create_session(
    user_ctx: Dict[str, Any],
    source_id: Optional[int] = None,
) -> str:
    """Yeni wizard oturumu aç ve session_uid döndür.

    FAZ 0 stub: yalnızca UUID üretir; gerçek INSERT FAZ 1'de.
    """
    session_uid = str(uuid.uuid4())
    logger.info(
        "[db_smart.session] create stub user=%s source=%s uid=%s",
        user_ctx.get("id"), source_id, session_uid,
    )
    return session_uid


def load_session(session_uid: str, user_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mevcut oturum context'ini Redis L1'den, miss ise DB'den getir.

    FAZ 0 stub: None döner.
    """
    logger.debug("[db_smart.session] load stub uid=%s", session_uid)
    return None


def update_context(
    session_uid: str,
    partial: Dict[str, Any],
    user_ctx: Dict[str, Any],
) -> None:
    """jsonb_set ile context'i atomik güncelle + last_activity_at."""
    logger.debug("[db_smart.session] update stub uid=%s keys=%s",
                 session_uid, list(partial.keys()))


def mark_completed(session_uid: str, user_ctx: Dict[str, Any]) -> None:
    """status='completed' + completed_at=NOW()."""
    logger.info("[db_smart.session] complete stub uid=%s", session_uid)


def mark_abandoned(session_uid: str, user_ctx: Dict[str, Any]) -> None:
    """status='abandoned' (kullanıcı çıkış / TTL doldu)."""
    logger.info("[db_smart.session] abandoned stub uid=%s", session_uid)
