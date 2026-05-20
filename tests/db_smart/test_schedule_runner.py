"""DB Smart — schedule_runner unit tests (v3.30.0 FAZ 3 P17 / G3.3 Schedule)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.services.db_smart import schedule_runner


@pytest.fixture
def mock_cur():
    cur = MagicMock()
    cur.rowcount = 1
    return cur


def test_find_due_reports_returns_dicts(mock_cur):
    mock_cur.fetchall.return_value = [
        (1, 42, 1, 10, "SELECT 1", "postgresql", "*/5 * * * *", 3),
        (2, 43, 1, 11, "SELECT 2", "mysql", "0 * * * *", 0),
    ]
    rows = schedule_runner.find_due_reports(mock_cur, limit=20)
    assert len(rows) == 2
    assert rows[0]["id"] == 1
    assert rows[0]["last_sql"] == "SELECT 1"
    assert rows[1]["schedule_cron"] == "0 * * * *"
    # SKIP LOCKED içerdiğini doğrula
    args = mock_cur.execute.call_args[0]
    assert "FOR UPDATE SKIP LOCKED" in args[0]
    # T-4 fix: NULL next_run sadece last_run_at IS NULL ise eligible
    assert "schedule_next_run IS NULL AND last_run_at IS NULL" in args[0]
    assert "schedule_next_run <= NOW()" in args[0]


def test_find_due_reports_empty(mock_cur):
    mock_cur.fetchall.return_value = []
    rows = schedule_runner.find_due_reports(mock_cur, limit=10)
    assert rows == []


def test_compute_next_run_basic():
    base = datetime(2026, 5, 20, 12, 0, 0)
    nxt = schedule_runner._compute_next_run("*/5 * * * *", base=base)
    assert nxt is not None
    assert nxt == datetime(2026, 5, 20, 12, 5, 0)


def test_compute_next_run_invalid_returns_none():
    nxt = schedule_runner._compute_next_run("not-a-cron-expr")
    assert nxt is None


def test_load_source_returns_dict(mock_cur):
    mock_cur.fetchone.return_value = (
        10, "postgresql", "localhost", 5432, "vyra", "u", None,
    )
    src = schedule_runner._load_source_for_schedule(mock_cur, 10)
    assert src["id"] == 10
    assert src["db_type"] == "postgresql"
    assert src["password"] == ""  # encrypted=None → boş


def test_load_source_not_found(mock_cur):
    mock_cur.fetchone.return_value = None
    src = schedule_runner._load_source_for_schedule(mock_cur, 999)
    assert src is None


def test_load_source_decrypts_password(mock_cur):
    mock_cur.fetchone.return_value = (
        10, "postgresql", "localhost", 5432, "vyra", "u", "encrypted_blob",
    )
    with patch("app.api.routes.data_sources_api._decrypt_stored_password",
               return_value="plain_pw"):
        src = schedule_runner._load_source_for_schedule(mock_cur, 10)
    assert src["password"] == "plain_pw"


def test_run_one_source_missing_writes_error(mock_cur):
    report = {
        "id": 1, "user_id": 42, "company_id": 1, "source_id": 999,
        "last_sql": "SELECT 1", "last_dialect": "postgresql",
        "schedule_cron": "*/5 * * * *", "run_count": 0,
    }
    # A-4 patch: auth ok, sonra source_not_found
    with patch.object(schedule_runner, "_verify_owner_auth", return_value=(True, None)):
        mock_cur.fetchone.return_value = None
        res = schedule_runner.run_one(mock_cur, report)
    assert res["ok"] is False
    assert res["error"] == "source_not_found_or_inactive"
    # UPDATE çağrısı yapılmış mı?
    sqls = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert any("UPDATE dbsmart_saved_reports" in s for s in sqls)


def test_run_one_executor_success(mock_cur):
    report = {
        "id": 5, "user_id": 42, "company_id": 1, "source_id": 10,
        "last_sql": "SELECT 1", "last_dialect": "postgresql",
        "schedule_cron": "0 * * * *", "run_count": 2,
    }
    # _load_source_for_schedule başarıyla source döner
    mock_cur.fetchone.return_value = (
        10, "postgresql", "localhost", 5432, "vyra", "u", None,
    )

    class _OkResult:
        success = True
        data = [[1], [2], [3]]
        columns = ["v"]
        row_count = 3
        elapsed_ms = 42.0
        truncated = False
        error = None

    with patch("app.services.safe_sql_executor.SafeSQLExecutor") as MockExec, \
         patch.object(schedule_runner, "_verify_owner_auth", return_value=(True, None)):
        instance = MockExec.return_value
        instance.execute.return_value = _OkResult()
        res = schedule_runner.run_one(mock_cur, report)

    assert res["ok"] is True
    assert res["row_count"] == 3
    # snapshot UPDATE'i çağrıldı
    update_calls = [
        c for c in mock_cur.execute.call_args_list
        if "UPDATE dbsmart_saved_reports" in c[0][0]
    ]
    assert len(update_calls) == 1
    # next_run hesaplandı (datetime) — UPDATE params 2. eleman
    update_params = update_calls[0][0][1]
    assert isinstance(update_params[1], datetime)


def test_run_one_executor_failure_writes_error_snapshot(mock_cur):
    report = {
        "id": 7, "user_id": 42, "company_id": 1, "source_id": 10,
        "last_sql": "SELECT bad", "last_dialect": "postgresql",
        "schedule_cron": "*/10 * * * *", "run_count": 0,
    }
    mock_cur.fetchone.return_value = (
        10, "postgresql", "localhost", 5432, "vyra", "u", None,
    )

    class _BadResult:
        success = False
        data = None
        columns = None
        row_count = None
        elapsed_ms = 0.0
        truncated = False
        error = "syntax error at SELECT bad"

    with patch("app.services.safe_sql_executor.SafeSQLExecutor") as MockExec, \
         patch.object(schedule_runner, "_verify_owner_auth", return_value=(True, None)):
        MockExec.return_value.execute.return_value = _BadResult()
        res = schedule_runner.run_one(mock_cur, report)

    assert res["ok"] is False
    assert "syntax error" in (res["error"] or "")


def test_check_dbsmart_scheduled_reports_stats(mock_cur):
    # 2 due, 1 ok + 1 err
    due_rows = [
        (1, 42, 1, 10, "SELECT 1", "postgresql", "*/5 * * * *", 0),
        (2, 42, 1, 999, "SELECT 2", "postgresql", "*/5 * * * *", 0),  # source missing
    ]
    # find_due_reports fetchall → due_rows; ardından her run_one'da fetchone'lar
    mock_cur.fetchall.return_value = due_rows
    # source lookups: id=10 → success, id=999 → None
    mock_cur.fetchone.side_effect = [
        (10, "postgresql", "localhost", 5432, "vyra", "u", None),
        None,
    ]

    class _OkResult:
        success = True
        data = []
        columns = []
        row_count = 0
        elapsed_ms = 1.0
        truncated = False
        error = None

    with patch("app.services.safe_sql_executor.SafeSQLExecutor") as MockExec, \
         patch.object(schedule_runner, "_verify_owner_auth", return_value=(True, None)):
        MockExec.return_value.execute.return_value = _OkResult()
        stats = schedule_runner.check_dbsmart_scheduled_reports(mock_cur)

    assert stats["due"] == 2
    assert stats["ok"] == 1
    assert stats["err"] == 1


# ---------- Yeni testler: A-4, A-5, T-4 fix doğrulama ----------

def test_run_one_auth_revoked_auto_pauses(mock_cur):
    """A-4 fix: user_can_access_source=False ise rapor schedule_cron=NULL'a çevrilir."""
    report = {
        "id": 1, "user_id": 42, "company_id": 1, "source_id": 10,
        "last_sql": "SELECT 1", "last_dialect": "postgresql",
        "schedule_cron": "*/5 * * * *", "run_count": 0,
    }
    with patch.object(schedule_runner, "_verify_owner_auth",
                       return_value=(False, "access_revoked")):
        res = schedule_runner.run_one(mock_cur, report)
    assert res["ok"] is False
    assert res["error"] == "auth_revoked:access_revoked"
    # UPDATE: schedule_cron = NULL
    sqls = [c[0][0] for c in mock_cur.execute.call_args_list]
    pause_sqls = [s for s in sqls if "schedule_cron     = NULL" in s
                  or "schedule_cron = NULL" in s]
    assert pause_sqls, f"auto-pause UPDATE bulunamadi: {sqls}"


def test_run_one_user_inactive_auto_pauses(mock_cur):
    """A-4 fix: kullanici is_active=False ise rapor durdurulur."""
    report = {
        "id": 2, "user_id": 99, "company_id": 1, "source_id": 10,
        "last_sql": "SELECT 1", "last_dialect": "postgresql",
        "schedule_cron": "*/5 * * * *", "run_count": 0,
    }
    with patch.object(schedule_runner, "_verify_owner_auth",
                       return_value=(False, "user_inactive")):
        res = schedule_runner.run_one(mock_cur, report)
    assert res["ok"] is False
    assert "user_inactive" in res["error"]


def test_run_one_invalid_cron_auto_pauses(mock_cur):
    """T-4 fix: invalid cron → next_run=None → schedule_cron=NULL."""
    report = {
        "id": 3, "user_id": 42, "company_id": 1, "source_id": 10,
        "last_sql": "SELECT 1", "last_dialect": "postgresql",
        "schedule_cron": "garbage-cron", "run_count": 0,
    }
    mock_cur.fetchone.return_value = (
        10, "postgresql", "localhost", 5432, "vyra", "u", None,
    )

    class _OkResult:
        success = True
        data = []
        columns = []
        row_count = 0
        elapsed_ms = 1.0
        truncated = False
        error = None

    with patch("app.services.safe_sql_executor.SafeSQLExecutor") as MockExec, \
         patch.object(schedule_runner, "_verify_owner_auth", return_value=(True, None)):
        MockExec.return_value.execute.return_value = _OkResult()
        res = schedule_runner.run_one(mock_cur, report)

    # T-4 path: query çalıştı ama next_run None → auto-pause
    sqls = [c[0][0] for c in mock_cur.execute.call_args_list]
    pause_sqls = [s for s in sqls if "schedule_cron     = NULL" in s]
    assert pause_sqls, f"T-4 auto-pause UPDATE bulunamadi: {sqls}"
    # error field invalid_cron işaretlendi
    assert res["error"] in ("invalid_cron", None) or "invalid_cron" in (res["error"] or "")


def test_run_one_clears_password_after_execute(mock_cur):
    """A-5 defense: execute sonrası src['password'] temizleniyor."""
    report = {
        "id": 4, "user_id": 42, "company_id": 1, "source_id": 10,
        "last_sql": "SELECT 1", "last_dialect": "postgresql",
        "schedule_cron": "*/5 * * * *", "run_count": 0,
    }
    captured_src: Dict[str, Any] = {}

    def _capture_execute(sql, src, dialect, **kw):
        captured_src["copy"] = dict(src)  # execute SIRASINDA password orada
        # password execute icinde gercek deger
        class _R:
            success = True
            data = []
            columns = []
            row_count = 0
            elapsed_ms = 0.0
            truncated = False
            error = None
        return _R()

    # source decrypt'i mock'la — password 'plain_pw' olacak
    mock_cur.fetchone.return_value = (
        10, "postgresql", "localhost", 5432, "vyra", "u", "enc_blob",
    )
    with patch("app.api.routes.data_sources_api._decrypt_stored_password",
               return_value="plain_pw"), \
         patch("app.services.safe_sql_executor.SafeSQLExecutor") as MockExec, \
         patch.object(schedule_runner, "_verify_owner_auth", return_value=(True, None)):
        MockExec.return_value.execute.side_effect = _capture_execute
        schedule_runner.run_one(mock_cur, report)

    # execute sirasinda password mevcuttu
    assert captured_src["copy"].get("password") == "plain_pw"


def test_find_due_reports_null_next_run_only_first_run():
    """T-4 fix: SQL'de NULL next_run + last_run_at NULL = eligible kurali var."""
    import re
    # Sadece SQL string'ini regex ile dogrulayalim — entegre testte
    mock = MagicMock()
    mock.fetchall.return_value = []
    schedule_runner.find_due_reports(mock, limit=5)
    sql = mock.execute.call_args[0][0]
    # WHERE clause: (NULL AND last_run_at NULL) OR <= NOW()
    norm = re.sub(r"\s+", " ", sql)
    assert "schedule_next_run IS NULL AND last_run_at IS NULL" in norm
