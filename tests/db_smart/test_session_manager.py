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


class _FakeCache:
    """Minimal RedisCache surface — get_raw/set_raw/delete."""
    def __init__(self):
        self.store = {}
        self.get_calls = 0
        self.set_calls = 0
        self.del_calls = 0

    def get_raw(self, key):
        self.get_calls += 1
        return self.store.get(key)

    def set_raw(self, key, value, ttl=None):
        self.set_calls += 1
        self.store[key] = value

    def delete(self, key):
        self.del_calls += 1
        return self.store.pop(key, None) is not None


@pytest.fixture(autouse=True)
def _disable_session_cache(monkeypatch):
    """Default: cache None → mevcut DB-only test'ler etkilenmez."""
    monkeypatch.setattr(sm, "_SESSION_CACHE", None, raising=False)
    monkeypatch.setattr(sm, "_SESSION_CACHE_INIT_FAILED", True, raising=False)
    monkeypatch.setattr(sm, "_get_session_cache", lambda: None)


@pytest.fixture
def fake_cache(monkeypatch):
    """Cache enabled: in-memory FakeCache enjekte et."""
    fc = _FakeCache()
    monkeypatch.setattr(sm, "_get_session_cache", lambda: fc)
    return fc


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
        7, 42,  # user_id, company_id (P6: cache guard alanları)
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
    # Public payload user_id/company_id sızdırmamalı (cache guard internal).
    assert "user_id" not in out
    assert "company_id" not in out


def test_load_session_normalizes_string_context(user_ctx, session_uid_sample):
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    row = (session_uid_sample, 0, "active", None,
           '{"k": "v"}', None, None, now, now, None, 7, 42)
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


# ─────────────────────────────────────────────────────────────
# P6 — L1 cache (Redis-backed, graceful)
# ─────────────────────────────────────────────────────────────

def test_cache_not_populated_before_commit(user_ctx, fake_cache):
    """ARES YÜKSEK: create_session içinde cache yazılmamalı (caller commit
    etmeden cache phantom oturum tutar). Cache ancak commit sonrası
    cache_warm_created() ile warm-up edilir."""
    cur = _RecCursor(responses=[("fake",)])
    uid = sm.create_session(cur, user_ctx, source_id=3, initial_context={"x": 1})
    assert isinstance(uid, str)
    # Önce INSERT yapıldı, AMA cache henüz yazılmadı.
    assert fake_cache.set_calls == 0
    assert fake_cache.store == {}


def test_cache_populated_after_commit(user_ctx, fake_cache):
    """ARES YÜKSEK: caller conn.commit() başarılı olduktan sonra
    cache_warm_created() explicit çağrıldığında cache doğru payload ile dolar."""
    cur = _RecCursor(responses=[("fake",)])
    uid = sm.create_session(cur, user_ctx, source_id=3, initial_context={"x": 1})
    # Commit phase'i simüle et:
    assert fake_cache.set_calls == 0
    sm.cache_warm_created(uid, user_ctx, source_id=3, initial_context={"x": 1})
    assert fake_cache.set_calls == 1
    raw = list(fake_cache.store.values())[0]
    payload = json.loads(raw.decode("utf-8"))
    assert payload["user_id"] == 7
    assert payload["company_id"] == 42
    assert payload["context"] == {"x": 1}
    assert payload["session_uid"] == uid
    assert payload["status"] == "active"
    assert payload["current_step"] == 0


def test_cache_warm_created_noop_without_user_or_company(fake_cache):
    """cache_warm_created defensive: user_id/company_id eksikse sessiz no-op."""
    sm.cache_warm_created("uid-x", {"id": None, "company_id": 1})
    sm.cache_warm_created("uid-y", {"id": 1, "company_id": None})
    sm.cache_warm_created("uid-z", {})
    assert fake_cache.set_calls == 0


def test_load_session_cache_hit_skips_db(user_ctx, session_uid_sample, fake_cache):
    payload = {
        "session_uid": session_uid_sample,
        "user_id": 7, "company_id": 42,
        "current_step": 1, "status": "active",
        "source_id": None, "context": {"k": "v"},
        "dialect": None, "generated_sql": None,
        "created_at": None, "last_activity_at": None, "completed_at": None,
    }
    fake_cache.store[session_uid_sample] = json.dumps(payload).encode("utf-8")
    cur = _RecCursor()
    out = sm.load_session(cur, session_uid_sample, user_ctx)
    assert out is not None
    assert out["context"] == {"k": "v"}
    # DB hit'i olmadı
    assert cur.executed == []
    # Public payload internal alanları sızdırmadı
    assert "user_id" not in out
    assert "company_id" not in out


def test_load_session_cache_cross_tenant_rejected(user_ctx, session_uid_sample, fake_cache):
    """ARES: başka tenant'ın cache payload'ı → fallback DB (RLS), not served."""
    foreign = {
        "session_uid": session_uid_sample,
        "user_id": 999, "company_id": 888,
        "current_step": 0, "status": "active",
        "source_id": None, "context": {"secret": "leak"},
        "dialect": None, "generated_sql": None,
        "created_at": None, "last_activity_at": None, "completed_at": None,
    }
    fake_cache.store[session_uid_sample] = json.dumps(foreign).encode("utf-8")
    # DB'de bu kullanıcı için kayıt yok → None dönmeli
    cur = _RecCursor(responses=[None])
    out = sm.load_session(cur, session_uid_sample, user_ctx)
    assert out is None
    # DB'ye düştü
    assert len(cur.executed) == 1


def test_admin_does_not_bypass_company_scoping(session_uid_sample, fake_cache):
    """ARES KRİTİK: is_admin=True cache cross-tenant erişimini side-effect
    olarak açmamalı. Admin user_ctx company_id != cache payload company_id ise
    cache HIT yerine MISS davranışı → DB'ye (RLS-bound) düşmeli.

    apply_vyra_user_context admin'in OWN company_id'sini set eder; cache path
    bunu bypass ederse downstream sorgular admin'in kendi tenant'ı dışındaki
    veriyi sızdırır. Cross-tenant erişim ancak ayrı explicit admin API ile
    yapılabilir."""
    admin = {"id": 1, "company_id": 1, "is_admin": True, "role": "admin"}
    foreign_payload = {
        "session_uid": session_uid_sample,
        "user_id": 7, "company_id": 42,  # admin'in (1) DIŞINDA bir tenant
        "current_step": 1, "status": "active",
        "source_id": None, "context": {"secret": "other-tenant"},
        "dialect": None, "generated_sql": None,
        "created_at": None, "last_activity_at": None, "completed_at": None,
    }
    fake_cache.store[session_uid_sample] = json.dumps(foreign_payload).encode("utf-8")
    # DB'de admin'in kendi tenant'ında bu uid yok → None dönmeli (RLS).
    cur = _RecCursor(responses=[None])
    out = sm.load_session(cur, session_uid_sample, admin)
    # Cache HIT direkt servis edilmedi; DB'ye düştü; DB None döndü → None.
    assert out is None
    assert len(cur.executed) == 1  # DB fallback gerçekleşti


def test_admin_cache_hit_only_when_same_tenant(session_uid_sample, fake_cache):
    """Admin'in OWN tenant'ında cache hit normal şekilde servis edilebilir
    (same-tenant payload eşleşmesi). is_admin flag'i guard'ı atlatmamalı."""
    admin = {"id": 1, "company_id": 1, "is_admin": True, "role": "admin"}
    own_tenant_payload = {
        "session_uid": session_uid_sample,
        "user_id": 1, "company_id": 1,  # admin'in OWN tenant'ı
        "current_step": 1, "status": "active",
        "source_id": None, "context": {"k": "v"},
        "dialect": None, "generated_sql": None,
        "created_at": None, "last_activity_at": None, "completed_at": None,
    }
    fake_cache.store[session_uid_sample] = json.dumps(own_tenant_payload).encode("utf-8")
    cur = _RecCursor()
    out = sm.load_session(cur, session_uid_sample, admin)
    assert out is not None
    assert out["context"] == {"k": "v"}
    assert cur.executed == []  # cache HIT, DB'ye düşmedi


def test_load_session_db_read_warms_cache(user_ctx, session_uid_sample, fake_cache):
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    row = (session_uid_sample, 0, "active", None, {}, None, None,
           now, now, None, 7, 42)
    cur = _RecCursor(responses=[row])
    out = sm.load_session(cur, session_uid_sample, user_ctx)
    assert out is not None
    assert fake_cache.set_calls == 1
    cached = json.loads(fake_cache.store[session_uid_sample].decode("utf-8"))
    assert cached["user_id"] == 7
    assert cached["company_id"] == 42


def test_update_context_invalidates_cache(user_ctx, session_uid_sample, fake_cache):
    fake_cache.store[session_uid_sample] = b'{"stale":true}'
    cur = _RecCursor(rowcount=1)
    ok = sm.update_context(cur, session_uid_sample, {"k": "v"})
    assert ok is True
    assert fake_cache.del_calls == 1
    assert session_uid_sample not in fake_cache.store


def test_update_context_no_match_does_not_invalidate(session_uid_sample, fake_cache):
    fake_cache.store[session_uid_sample] = b'{"x":1}'
    cur = _RecCursor(rowcount=0)
    ok = sm.update_context(cur, session_uid_sample, {"k": "v"})
    assert ok is False
    assert fake_cache.del_calls == 0
    assert session_uid_sample in fake_cache.store


def test_mark_completed_invalidates_cache(session_uid_sample, fake_cache):
    fake_cache.store[session_uid_sample] = b'{"x":1}'
    cur = _RecCursor(rowcount=1)
    assert sm.mark_completed(cur, session_uid_sample) is True
    assert fake_cache.del_calls == 1


def test_mark_abandoned_invalidates_cache(session_uid_sample, fake_cache):
    fake_cache.store[session_uid_sample] = b'{"x":1}'
    cur = _RecCursor(rowcount=1)
    assert sm.mark_abandoned(cur, session_uid_sample) is True
    assert fake_cache.del_calls == 1


def test_cache_get_returns_none_when_cache_disabled(session_uid_sample):
    """_disable_session_cache aktif → cache None → DB'ye düşer."""
    cur = _RecCursor(responses=[None])
    out = sm.load_session(cur, session_uid_sample, {"id": 7, "company_id": 42})
    assert out is None
    # Cache disable olunca DB execute edildi
    assert len(cur.executed) == 1
