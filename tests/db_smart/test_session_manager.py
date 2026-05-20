"""session_manager.py — dbsmart_sessions CRUD (v3.30.0 FAZ 1 P5 G1.7)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, List, Optional

import pytest

from app.services.db_smart import session_manager as sm


# ─────────────────────────────────────────────────────────────
# Cursor mock — Eligibility/Metric test'iyle aynı pattern.
# ─────────────────────────────────────────────────────────────

class _RecCursor:
    """SQL kayıt + sıralı fetch yanıtları + rowcount stub."""

    def __init__(self, responses: Optional[List[Any]] = None, rowcount: int = 1):
        self._resps = responses or []
        self._idx = 0
        self._last: Any = None
        self.executed: List[tuple] = []  # (sql, params)
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._idx < len(self._resps):
            self._last = self._resps[self._idx]
            self._idx += 1
        else:
            self._last = None

    def fetchone(self):
        if isinstance(self._last, list) and self._last:
            return self._last[0]
        return self._last

    def fetchall(self):
        if isinstance(self._last, list):
            return self._last
        return [self._last] if self._last else []


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def user_ctx():
    return {"id": 7, "company_id": 42, "is_admin": False, "role": "user"}


@pytest.fixture
def session_uid_sample():
    return "11111111-2222-3333-4444-555555555555"


def _last_sql(cur: _RecCursor) -> str:
    return cur.executed[-1][0]


def _last_params(cur: _RecCursor) -> tuple:
    return cur.executed[-1][1]


# ─────────────────────────────────────────────────────────────
# create_session
# ─────────────────────────────────────────────────────────────

def test_create_session_inserts_and_returns_uid(user_ctx):
    cur = _RecCursor(responses=[("fake-uuid",)])
    uid = sm.create_session(cur, user_ctx, source_id=3)
    assert isinstance(uid, str)
    # UUID4 format
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", uid)
    sql = _last_sql(cur)
    assert "INSERT INTO dbsmart_sessions" in sql
    assert "RETURNING session_uid" in sql
    params = _last_params(cur)
    assert params[1] == 7
    assert params[2] == 42
    assert params[3] == 3
    assert params[4] == "{}"


def test_create_session_with_initial_context(user_ctx):
    cur = _RecCursor(responses=[("fake",)])
    ctx = {"foo": "bar", "n": 1}
    sm.create_session(cur, user_ctx, source_id=None, initial_context=ctx)
    params = _last_params(cur)
    assert json.loads(params[4]) == ctx


def test_create_session_requires_user_and_company():
    cur = _RecCursor()
    with pytest.raises(ValueError, match="user_id ve company_id zorunlu"):
        sm.create_session(cur, {"id": None, "company_id": None}, None)
    with pytest.raises(ValueError):
        sm.create_session(cur, {"id": 1}, None)  # company_id missing


def test_create_session_raises_when_returning_empty(user_ctx):
    cur = _RecCursor(responses=[None])  # RLS rejection scenario
    with pytest.raises(RuntimeError, match="INSERT RETURNING"):
        sm.create_session(cur, user_ctx)


# ─────────────────────────────────────────────────────────────
# load_session
# ─────────────────────────────────────────────────────────────

def test_load_session_returns_dict(user_ctx, session_uid_sample):
    now = datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    row = (
        session_uid_sample, 2, "active", 5,
        {"selected_table": "tickets"},
        "postgresql", "SELECT 1",
        now, now, None,
    )
    cur = _RecCursor(responses=[row])
    out = sm.load_session(cur, session_uid_sample, user_ctx)
    assert out is not None
    assert out["session_uid"] == session_uid_sample
    assert out["current_step"] == 2
    assert out["status"] == "active"
    assert out["source_id"] == 5
    assert out["context"] == {"selected_table": "tickets"}
    assert out["dialect"] == "postgresql"
    assert out["created_at"] == now.isoformat()
    assert out["completed_at"] is None


def test_load_session_normalizes_string_context(user_ctx, session_uid_sample):
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    row = (session_uid_sample, 0, "active", None,
           '{"k": "v"}', None, None, now, now, None)
    cur = _RecCursor(responses=[row])
    out = sm.load_session(cur, session_uid_sample, user_ctx)
    assert out["context"] == {"k": "v"}


def test_load_session_returns_none_on_miss(user_ctx, session_uid_sample):
    cur = _RecCursor(responses=[None])
    assert sm.load_session(cur, session_uid_sample, user_ctx) is None


def test_load_session_swallows_db_error(user_ctx):
    class _BoomCursor:
        def execute(self, *a, **k): raise RuntimeError("invalid uuid")
        def fetchone(self): return None
    assert sm.load_session(_BoomCursor(), "not-a-uuid", user_ctx) is None


def test_load_session_uses_session_uid_bind(user_ctx, session_uid_sample):
    cur = _RecCursor(responses=[None])
    sm.load_session(cur, session_uid_sample, user_ctx)
    sql = _last_sql(cur)
    assert "WHERE session_uid = %s::uuid" in sql
    # No string concat — uid only via bind
    assert session_uid_sample not in sql
    assert _last_params(cur) == (session_uid_sample,)


# ─────────────────────────────────────────────────────────────
# update_context
# ─────────────────────────────────────────────────────────────

def test_update_context_returns_true_on_match(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=1)
    ok = sm.update_context(cur, session_uid_sample, {"key": "val"})
    assert ok is True
    sql = _last_sql(cur)
    assert "UPDATE dbsmart_sessions" in sql
    assert "context = context || %s::jsonb" in sql
    assert "last_activity_at = NOW()" in sql


def test_update_context_returns_false_on_no_match(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=0)
    assert sm.update_context(cur, session_uid_sample, {"k": "v"}) is False


def test_update_context_with_current_step(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=1)
    sm.update_context(cur, session_uid_sample, {"step_payload": 1}, current_step=3)
    sql = _last_sql(cur)
    assert "current_step = %s" in sql
    params = _last_params(cur)
    assert 3 in params
    assert session_uid_sample in params


def test_update_context_no_op_when_empty(user_ctx, session_uid_sample):
    cur = _RecCursor()
    assert sm.update_context(cur, session_uid_sample, {}) is False
    assert cur.executed == []  # zero execute calls


def test_update_context_step_only_runs_update(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=1)
    ok = sm.update_context(cur, session_uid_sample, {}, current_step=2)
    assert ok is True
    sql = _last_sql(cur)
    assert "current_step = %s" in sql
    assert "context = context || " not in sql


# ─────────────────────────────────────────────────────────────
# mark_completed / mark_abandoned
# ─────────────────────────────────────────────────────────────

def test_mark_completed_only_active_sessions(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=1)
    ok = sm.mark_completed(cur, session_uid_sample, generated_sql="SELECT 1", dialect="postgresql")
    assert ok is True
    sql = _last_sql(cur)
    assert "status = 'completed'" in sql
    assert "completed_at = NOW()" in sql
    assert "status = 'active'" in sql  # guard
    params = _last_params(cur)
    assert "SELECT 1" in params
    assert "postgresql" in params


def test_mark_completed_no_sql_dialect(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=1)
    ok = sm.mark_completed(cur, session_uid_sample)
    assert ok is True
    sql = _last_sql(cur)
    # Optional columns shouldn't appear when not provided
    assert "generated_sql = %s" not in sql
    assert "dialect = %s" not in sql


def test_mark_completed_returns_false_when_already_completed(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=0)
    assert sm.mark_completed(cur, session_uid_sample) is False


def test_mark_abandoned_status_guard(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=1)
    ok = sm.mark_abandoned(cur, session_uid_sample)
    assert ok is True
    sql = _last_sql(cur)
    assert "status = 'abandoned'" in sql
    assert "status = 'active'" in sql


def test_mark_abandoned_returns_false_on_no_match(user_ctx, session_uid_sample):
    cur = _RecCursor(rowcount=0)
    assert sm.mark_abandoned(cur, session_uid_sample) is False
