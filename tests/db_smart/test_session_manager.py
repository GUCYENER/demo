"""session_manager.py stub-level smoke (FAZ 0)."""
from __future__ import annotations

import uuid

from app.services.db_smart import session_manager as sm


def test_create_session_returns_valid_uuid(fake_user_ctx):
    uid = sm.create_session(fake_user_ctx, source_id=1)
    # geçerli bir UUID4 olmalı
    parsed = uuid.UUID(uid)
    assert str(parsed) == uid


def test_load_session_returns_none_in_stub(fake_user_ctx):
    assert sm.load_session("nonexistent-uid", fake_user_ctx) is None


def test_update_context_does_not_raise(fake_user_ctx):
    # FAZ 0'da yalnızca log atar — exception fırlatmamalı
    sm.update_context("uid", {"key": "value"}, fake_user_ctx)
    sm.mark_completed("uid", fake_user_ctx)
    sm.mark_abandoned("uid", fake_user_ctx)
