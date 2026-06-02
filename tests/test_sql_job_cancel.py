"""v3.53.0 — sql_query_jobs cross-worker cancel (multi-worker 404 fix).

_job_db_conn fake'lenir (gerçek DB yok). In-memory + DB yollarının her ikisi de test edilir.
"""
import threading

import pytest

from app.services import safe_sql_executor as S


class _FakeCur:
    def __init__(self, store):
        self.store = store
        self._last = None

    def execute(self, sql, params=None):
        s = sql.lower()
        if "insert into sql_query_jobs" in s:
            jid, owner, dialog = params
            self.store[jid] = {"owner_user_id": owner, "status": "running"}
        elif "delete from sql_query_jobs where started_at" in s:
            pass  # stale-cleanup (parametresiz) — fake'te no-op (eski satır yok)
        elif "delete from sql_query_jobs" in s:
            self.store.pop(params[0], None)
        elif "update sql_query_jobs set status='cancel_requested'" in s:
            jid = params[0]
            if jid in self.store:
                self.store[jid]["status"] = "cancel_requested"
        elif "select owner_user_id from sql_query_jobs" in s:
            r = self.store.get(params[0])
            self._last = {"owner_user_id": r["owner_user_id"]} if r else None
        elif "select status from sql_query_jobs" in s:
            r = self.store.get(params[0])
            self._last = {"status": r["status"]} if r else None

    def fetchone(self):
        return self._last


class _FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return _FakeCur(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    store = {}
    monkeypatch.setattr(S, "_job_db_conn", lambda: _FakeConn(store))
    with S._JOB_REGISTRY_LOCK:
        S._SQL_JOB_REGISTRY.clear()
    return store


def test_cancel_same_worker_sets_event_and_db(fake_db):
    ev = threading.Event()
    S.register_sql_job("j1", ev, owner_user_id=42)
    assert fake_db["j1"]["status"] == "running"
    ok, _ = S.cancel_sql_job("j1", requesting_user_id=42)
    assert ok
    assert ev.is_set()
    assert fake_db["j1"]["status"] == "cancel_requested"


def test_cancel_cross_worker_db_only(fake_db):
    # İş başka worker'da: DB'de 'running' ama bu worker'ın in-memory registry'sinde YOK
    fake_db["j2"] = {"owner_user_id": 42, "status": "running"}
    ok, msg = S.cancel_sql_job("j2", requesting_user_id=42)
    assert ok  # 404 DEĞİL — cross-worker sinyal yazıldı
    assert fake_db["j2"]["status"] == "cancel_requested"


def test_cancel_owner_mismatch_cross_worker(fake_db):
    fake_db["j3"] = {"owner_user_id": 99, "status": "running"}
    ok, msg = S.cancel_sql_job("j3", requesting_user_id=42)
    assert not ok
    assert "yetki" in msg.lower()
    assert fake_db["j3"]["status"] == "running"  # değişmedi


def test_cancel_not_found_anywhere(fake_db):
    ok, msg = S.cancel_sql_job("nope", requesting_user_id=42)
    assert not ok
    assert "bulunam" in msg.lower()


def test_is_cancel_requested_polls_db(fake_db):
    fake_db["j4"] = {"owner_user_id": 42, "status": "running"}
    assert S.is_cancel_requested("j4") is False
    fake_db["j4"]["status"] = "cancel_requested"
    assert S.is_cancel_requested("j4") is True
    assert S.is_cancel_requested("ghost") is False


def test_unregister_clears_db(fake_db):
    S.register_sql_job("j5", threading.Event(), owner_user_id=42)
    assert "j5" in fake_db
    S.unregister_sql_job("j5")
    assert "j5" not in fake_db
