"""Session cache cross-tenant isolation tests (FIX9 / TYCHE+ARES).

`session_manager.load_session` keeps an L1 (Redis) cache keyed by `session_uid`
only — there is NO {company_id}/{user_id} segment in the key. The cross-tenant
guard is therefore enforced by the *payload check* inside `load_session`:

    cached.user_id  == user_ctx.id    AND
    cached.company_id == user_ctx.company_id

If those don't match, the code MUST fall back to a DB read (RLS-bound). These
tests stub the cache (`_cache_get` / `_cache_set`) and assert that contract.

POSEIDON: no DB, no Redis — purely in-process monkeypatching. Idempotent.
ARES: the negative tests reproduce the cross-tenant leak that the
v3.30.0 P15+ fix closed.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

try:
    from app.services.db_smart import session_manager as sm
except Exception:  # pragma: no cover
    sm = None  # type: ignore[assignment]


pytestmark: List[Any] = []  # unit-only


def _skip_if_no_module() -> None:
    if sm is None:
        pytest.skip("session_manager module unavailable")


# ─────────────────────────────────────────────────────────────────────────────
# Cursor stub — minimal subset used by load_session.
# ─────────────────────────────────────────────────────────────────────────────


class _RecCursor:
    """Records SQL + serves a single fixed row."""

    def __init__(self, row: Optional[Tuple[Any, ...]] = None):
        self.executed: List[Tuple[str, Any]] = []
        self._row = row

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> Optional[Tuple[Any, ...]]:
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# In-memory cache backend — replaces the Redis-backed L1.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_cache(monkeypatch) -> Dict[str, Dict[str, Any]]:
    """Patch session_manager's L1 helpers with an in-memory dict.

    Returns the underlying store so tests can pre-seed / inspect.
    """
    _skip_if_no_module()
    store: Dict[str, Dict[str, Any]] = {}

    def _get(uid: str):
        return store.get(uid)

    def _set(uid: str, payload: Dict[str, Any]):
        # Mimic JSON round-trip the real impl does.
        store[uid] = json.loads(json.dumps(payload, default=str))

    def _del(uid: str):
        store.pop(uid, None)

    monkeypatch.setattr(sm, "_cache_get", _get)
    monkeypatch.setattr(sm, "_cache_set", _set)
    monkeypatch.setattr(sm, "_cache_delete", _del)
    return store


@pytest.fixture
def uid_a() -> str:
    return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def uid_b() -> str:
    return "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def ctx_a() -> Dict[str, Any]:
    return {"id": 11, "company_id": 100, "role": "user", "is_admin": False}


@pytest.fixture
def ctx_b() -> Dict[str, Any]:
    return {"id": 22, "company_id": 200, "role": "user", "is_admin": False}


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE happy: same-tenant cache hit returns scrubbed payload.
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_hit_same_tenant_returns_payload(fake_cache, ctx_a, uid_a):
    fake_cache[uid_a] = {
        "session_uid": uid_a,
        "current_step": 2,
        "status": "active",
        "source_id": 5,
        "context": {"step": "metric"},
        "dialect": "postgresql",
        "generated_sql": None,
        "created_at": None,
        "last_activity_at": None,
        "completed_at": None,
        # Guard fields:
        "user_id": ctx_a["id"],
        "company_id": ctx_a["company_id"],
    }
    cur = _RecCursor(row=None)  # If cache hits properly, DB is never touched.

    out = sm.load_session(cur, uid_a, ctx_a)

    assert out is not None
    assert out["session_uid"] == uid_a
    # ARES contract: guard fields must NOT leak to callers.
    assert "user_id" not in out
    assert "company_id" not in out
    # Cache hit ⇒ no SQL executed.
    assert cur.executed == [], "DB should not be touched on a clean cache hit"


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: cross-tenant cached payload must NOT be served.
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_cross_tenant_company_id_mismatch_falls_back_to_db(
    fake_cache, ctx_a, ctx_b, uid_a
):
    """Cached payload belongs to tenant A; requesting user belongs to tenant B.

    Expected: load_session ignores the cache and queries the DB. Since our
    fake cursor returns None for that DB read, the call returns None — proving
    the cache shortcut did NOT leak A's data into B's session.
    """
    fake_cache[uid_a] = {
        "session_uid": uid_a,
        "current_step": 9,
        "status": "active",
        "source_id": None,
        "context": {"leak": "secret"},
        "dialect": "postgresql",
        "generated_sql": "SELECT secret",
        "created_at": None,
        "last_activity_at": None,
        "completed_at": None,
        "user_id": ctx_a["id"],
        "company_id": ctx_a["company_id"],
    }
    cur = _RecCursor(row=None)  # DB has nothing for tenant B → expect None.

    out = sm.load_session(cur, uid_a, ctx_b)

    assert out is None, "ARES: cross-tenant cache leak — payload served to wrong tenant"
    # And we must have actually attempted the DB fallback.
    assert any("dbsmart_sessions" in sql for sql, _ in cur.executed), (
        "fallback DB read missing — guard did not trigger DB path"
    )


def test_cache_user_id_mismatch_falls_back_to_db(fake_cache, ctx_a, uid_a):
    """Same company_id but different user_id ⇒ still must NOT serve from cache."""
    fake_cache[uid_a] = {
        "session_uid": uid_a,
        "current_step": 1,
        "status": "active",
        "source_id": None,
        "context": {},
        "dialect": None,
        "generated_sql": None,
        "created_at": None,
        "last_activity_at": None,
        "completed_at": None,
        "user_id": 99_999,  # different user, same company
        "company_id": ctx_a["company_id"],
    }
    cur = _RecCursor(row=None)

    out = sm.load_session(cur, uid_a, ctx_a)

    assert out is None
    assert any("dbsmart_sessions" in sql for sql, _ in cur.executed)


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: missing guard fields in cached payload ⇒ fail-closed (DB read).
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_missing_guard_fields_does_not_serve(fake_cache, ctx_a, uid_a):
    """Legacy payloads without user_id/company_id must NOT bypass the guard."""
    fake_cache[uid_a] = {
        "session_uid": uid_a,
        "current_step": 0,
        "status": "active",
        "source_id": None,
        "context": {},
        "dialect": None,
        "generated_sql": None,
        "created_at": None,
        "last_activity_at": None,
        "completed_at": None,
        # NO user_id / company_id keys.
    }
    cur = _RecCursor(row=None)

    out = sm.load_session(cur, uid_a, ctx_a)

    assert out is None
    assert any("dbsmart_sessions" in sql for sql, _ in cur.executed)


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE edge: empty user_ctx ⇒ fail-closed, never serves cache.
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_user_ctx_does_not_serve_cache(fake_cache, ctx_a, uid_a):
    fake_cache[uid_a] = {
        "session_uid": uid_a,
        "current_step": 0,
        "status": "active",
        "source_id": None,
        "context": {},
        "dialect": None,
        "generated_sql": None,
        "created_at": None,
        "last_activity_at": None,
        "completed_at": None,
        "user_id": ctx_a["id"],
        "company_id": ctx_a["company_id"],
    }
    cur = _RecCursor(row=None)

    out = sm.load_session(cur, uid_a, {})

    assert out is None, "empty user_ctx must not pass the guard"


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE edge: cache miss + DB row present → returns payload AND repopulates cache.
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_miss_then_db_hit_repopulates(fake_cache, ctx_a, uid_a):
    """Cache miss → DB read → payload returned and cache_set called with guard fields."""
    # SELECT returns 12 columns: see load_session implementation.
    row = (
        uid_a,            # session_uid
        3,                # current_step
        "active",         # status
        None,             # source_id
        {"x": 1},         # context (jsonb → dict)
        "postgresql",     # dialect
        None,             # generated_sql
        None,             # created_at
        None,             # last_activity_at
        None,             # completed_at
        ctx_a["id"],      # user_id (guard)
        ctx_a["company_id"],  # company_id (guard)
    )
    cur = _RecCursor(row=row)

    out = sm.load_session(cur, uid_a, ctx_a)

    assert out is not None
    assert out["session_uid"] == uid_a
    assert out["context"] == {"x": 1}
    # Repopulation: store must now hold the payload WITH guard fields.
    assert uid_a in fake_cache
    assert fake_cache[uid_a].get("user_id") == ctx_a["id"]
    assert fake_cache[uid_a].get("company_id") == ctx_a["company_id"]


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE edge: cache miss + DB row absent → returns None, no cache write.
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_miss_db_miss_returns_none(fake_cache, ctx_a, uid_a):
    cur = _RecCursor(row=None)
    out = sm.load_session(cur, uid_a, ctx_a)
    assert out is None
    assert uid_a not in fake_cache  # no spurious cache write on miss
