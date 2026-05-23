"""saved_reports — CRUD + share token (v3.30.0 FAZ 3 P13 G3.3)."""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

import pytest

from app.services.db_smart import saved_reports as sr


# ─────────────────────────────────────────────────────────────
# Cursor mocks
# ─────────────────────────────────────────────────────────────

class _RecCursor:
    """SQL'ları toplar; programlı tek-satırlık RETURNING/SELECT yanıtı verir."""

    def __init__(self, fetchone_value: Any = None,
                 fetchall_value: Optional[List[Any]] = None,
                 rowcount: int = 1):
        self.calls: List[tuple] = []
        self._fetchone_value = fetchone_value
        self._fetchall_value = fetchall_value if fetchall_value is not None else []
        self.rowcount = rowcount

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> Any:
        return self._fetchone_value

    def fetchall(self) -> Any:
        return self._fetchall_value


class _RaiseCursor:
    """execute() exception fırlatır; defansif path doğrulamak için."""
    def execute(self, sql: str, params: Any = None) -> None:
        raise RuntimeError("db down")

    def fetchone(self) -> Any:
        return None

    def fetchall(self) -> Any:
        return []

    rowcount = 0


USER_CTX = {"id": 7, "company_id": 42}


# ─────────────────────────────────────────────────────────────
# _require_user_ctx & _normalize_tags
# ─────────────────────────────────────────────────────────────

def test_require_user_ctx_returns_ids():
    assert sr._require_user_ctx({"id": 1, "company_id": 2}) == (1, 2)


def test_require_user_ctx_missing_raises():
    with pytest.raises(ValueError):
        sr._require_user_ctx({"id": 1})
    with pytest.raises(ValueError):
        sr._require_user_ctx({})


def test_normalize_tags_dedupe_and_strip():
    out = sr._normalize_tags(["  satış  ", "satış", "rapor", ""])
    assert out == ["satış", "rapor"]


def test_normalize_tags_caps_at_max():
    many = [f"t{i}" for i in range(40)]
    out = sr._normalize_tags(many)
    assert len(out) == sr._MAX_TAGS == 20


def test_normalize_tags_truncates_long_tag():
    long_tag = "x" * 200
    out = sr._normalize_tags([long_tag])
    assert len(out[0]) == 60


def test_normalize_tags_none_or_empty():
    assert sr._normalize_tags(None) is None
    assert sr._normalize_tags([]) is None
    assert sr._normalize_tags(["", "   "]) is None


# ─────────────────────────────────────────────────────────────
# save()
# ─────────────────────────────────────────────────────────────

def test_save_inserts_and_returns_id():
    cur = _RecCursor(fetchone_value=(123, _dt.datetime(2026, 5, 20)))
    out = sr.save(
        cur, USER_CTX,
        name="Aylık Satış",
        wizard_state={"step": 7},
        last_sql="SELECT 1",
        last_dialect="postgresql",
        source_id=3,
        description="Aylık satış raporu",
        tags=["satış", "aylık"],
    )
    assert out is not None
    assert out["id"] == 123
    sql, params = cur.calls[0]
    assert "INSERT INTO dbsmart_saved_reports" in sql
    # user_id, company_id, source_id, name, description, state, sql, dialect, tags
    assert params[0] == 7
    assert params[1] == 42
    assert params[3] == "Aylık Satış"
    assert params[7] == "postgresql"
    assert params[8] == ["satış", "aylık"]


def test_save_requires_name():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        sr.save(cur, USER_CTX, name="   ", wizard_state={})


def test_save_requires_user_ctx():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        sr.save(cur, {}, name="x", wizard_state={})


def test_save_truncates_long_name():
    cur = _RecCursor(fetchone_value=(1, None))
    long_name = "y" * 500
    sr.save(cur, USER_CTX, name=long_name, wizard_state={})
    _, params = cur.calls[0]
    assert len(params[3]) == sr._MAX_NAME_LEN


def test_save_returns_none_on_exception():
    out = sr.save(_RaiseCursor(), USER_CTX, name="x", wizard_state={})
    assert out is None


def test_save_returns_none_when_returning_empty():
    cur = _RecCursor(fetchone_value=None)
    out = sr.save(cur, USER_CTX, name="x", wizard_state={})
    assert out is None


def test_save_accepts_dict_row():
    cur = _RecCursor(fetchone_value={"id": 9, "created_at": "2026-05-20"})
    out = sr.save(cur, USER_CTX, name="x", wizard_state={})
    assert out["id"] == 9


# ─────────────────────────────────────────────────────────────
# update()
# ─────────────────────────────────────────────────────────────

def test_update_patch_name_only():
    cur = _RecCursor(rowcount=1)
    ok = sr.update(cur, 5, USER_CTX, name="Yeni Ad")
    assert ok is True
    sql, params = cur.calls[0]
    assert "UPDATE dbsmart_saved_reports" in sql
    assert "name = %s" in sql
    # name, updated_at NOW, id
    assert params[0] == "Yeni Ad"
    assert params[-1] == 5


def test_update_no_fields_returns_false():
    cur = _RecCursor()
    assert sr.update(cur, 5, USER_CTX) is False
    assert cur.calls == []  # SQL gönderilmedi


def test_update_blank_name_raises():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        sr.update(cur, 5, USER_CTX, name="   ")


def test_update_returns_false_when_rowcount_zero():
    cur = _RecCursor(rowcount=0)
    ok = sr.update(cur, 5, USER_CTX, name="x")
    assert ok is False


def test_update_returns_false_on_exception():
    assert sr.update(_RaiseCursor(), 5, USER_CTX, name="x") is False


def test_update_wizard_state_jsonb_cast():
    cur = _RecCursor(rowcount=1)
    sr.update(cur, 5, USER_CTX, wizard_state={"a": 1})
    sql, _ = cur.calls[0]
    assert "wizard_state = %s::jsonb" in sql


def test_update_tags_normalized():
    cur = _RecCursor(rowcount=1)
    sr.update(cur, 5, USER_CTX, tags=["a", "a", "b"])
    _, params = cur.calls[0]
    assert params[0] == ["a", "b"]


# ─────────────────────────────────────────────────────────────
# list_for_user()
# ─────────────────────────────────────────────────────────────

def test_list_for_user_returns_dicts():
    rows = [
        (1, "R1", "d1", None, "postgresql", ["t1"], 3,
         _dt.datetime(2026, 5, 20), False,
         _dt.datetime(2026, 5, 1), _dt.datetime(2026, 5, 20)),
        (2, "R2", None, 4, "mysql", None, 0, None, True,
         _dt.datetime(2026, 5, 2), _dt.datetime(2026, 5, 19)),
    ]
    cur = _RecCursor(fetchall_value=rows)
    out = sr.list_for_user(cur, USER_CTX, limit=10, offset=0)
    assert len(out) == 2
    assert out[0]["id"] == 1
    assert out[0]["tags"] == ["t1"]
    assert out[1]["tags"] == []


def test_list_for_user_clamps_limit():
    cur = _RecCursor(fetchall_value=[])
    sr.list_for_user(cur, USER_CTX, limit=10_000, offset=-3)
    _, params = cur.calls[0]
    assert params[0] == sr._MAX_LIMIT
    assert params[1] == 0


def test_list_for_user_requires_user_ctx():
    with pytest.raises(ValueError):
        sr.list_for_user(_RecCursor(), {})


def test_list_for_user_returns_empty_on_exception():
    assert sr.list_for_user(_RaiseCursor(), USER_CTX) == []


# ─────────────────────────────────────────────────────────────
# get_by_id()
# ─────────────────────────────────────────────────────────────

def test_get_by_id_returns_full_record():
    row = (1, "R1", "d", 3, {"step": 7}, "SELECT 1", "postgresql",
           ["a"], 2, _dt.datetime(2026, 5, 1), {"ok": True}, False,
           None, _dt.datetime(2026, 4, 1), _dt.datetime(2026, 5, 1))
    cur = _RecCursor(fetchone_value=row)
    out = sr.get_by_id(cur, 1, USER_CTX)
    assert out["id"] == 1
    assert out["wizard_state"] == {"step": 7}
    assert out["last_sql"] == "SELECT 1"


def test_get_by_id_returns_none_when_not_found():
    cur = _RecCursor(fetchone_value=None)
    assert sr.get_by_id(cur, 999, USER_CTX) is None


def test_get_by_id_returns_none_on_exception():
    assert sr.get_by_id(_RaiseCursor(), 1, USER_CTX) is None


# ─────────────────────────────────────────────────────────────
# Share token flow
# ─────────────────────────────────────────────────────────────

def test_generate_token_length_43():
    t = sr._generate_token()
    assert isinstance(t, str)
    assert 40 <= len(t) <= 64


def test_generate_token_unique():
    a, b = sr._generate_token(), sr._generate_token()
    assert a != b


def test_create_share_token_default_ttl():
    cur = _RecCursor(fetchone_value=("tok123", _dt.datetime(2026, 5, 21)))
    out = sr.create_share_token(cur, 5, USER_CTX)
    assert out["share_token"]  # gerçek token override edilmedi → cursor döndürdüğü
    assert out["ttl_hours"] == 24
    sql, params = cur.calls[0]
    assert "is_shared = TRUE" in sql
    assert params[1] == "24"  # ttl str
    assert params[2] == 5  # report_id


def test_create_share_token_custom_ttl():
    cur = _RecCursor(fetchone_value=("tok", _dt.datetime(2026, 5, 25)))
    out = sr.create_share_token(cur, 5, USER_CTX, ttl_hours=72)
    assert out["ttl_hours"] == 72
    _, params = cur.calls[0]
    assert params[1] == "72"


def test_create_share_token_invalid_ttl():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        sr.create_share_token(cur, 5, USER_CTX, ttl_hours=0)
    with pytest.raises(ValueError):
        sr.create_share_token(cur, 5, USER_CTX, ttl_hours=10_000)
    with pytest.raises(ValueError):
        sr.create_share_token(cur, 5, USER_CTX, ttl_hours=-1)


def test_create_share_token_returns_none_when_no_row():
    cur = _RecCursor(fetchone_value=None)
    assert sr.create_share_token(cur, 5, USER_CTX) is None


def test_create_share_token_returns_none_on_exception():
    assert sr.create_share_token(_RaiseCursor(), 5, USER_CTX) is None


def test_revoke_share_sets_false():
    cur = _RecCursor(rowcount=1)
    ok = sr.revoke_share(cur, 5, USER_CTX)
    assert ok is True
    sql, params = cur.calls[0]
    assert "is_shared = FALSE" in sql
    # Token alanını DOKUNULMAMASI doğrulanıyor (audit için saklı)
    assert "share_token" not in sql.split("WHERE")[0]
    assert params[0] == 5


def test_revoke_share_zero_rowcount_returns_false():
    cur = _RecCursor(rowcount=0)
    assert sr.revoke_share(cur, 5, USER_CTX) is False


def test_revoke_share_returns_false_on_exception():
    assert sr.revoke_share(_RaiseCursor(), 5, USER_CTX) is False


def test_get_by_share_token_valid():
    row = (9, 7, 42, "Public R", "d", 3, {"step": 1}, "SELECT 1", "postgresql",
           ["a"], None, _dt.datetime(2026, 6, 1))
    cur = _RecCursor(fetchone_value=row)
    out = sr.get_by_share_token(cur, "validtoken")
    assert out["id"] == 9
    assert out["user_id"] == 7
    # Explicit guard SQL kontrolü — RLS bypass'a güvenmediği doğrulanıyor
    sql, params = cur.calls[0]
    assert "is_shared = TRUE" in sql
    assert "share_expires_at > NOW()" in sql
    assert params[0] == "validtoken"


def test_get_by_share_token_empty_token_short_circuits():
    cur = _RecCursor(fetchone_value=("x",))
    assert sr.get_by_share_token(cur, "") is None
    assert sr.get_by_share_token(cur, None) is None  # type: ignore[arg-type]
    assert cur.calls == []


def test_get_by_share_token_not_found_returns_none():
    cur = _RecCursor(fetchone_value=None)
    assert sr.get_by_share_token(cur, "unknown") is None


def test_get_by_share_token_returns_none_on_exception():
    assert sr.get_by_share_token(_RaiseCursor(), "tok") is None


# ─────────────────────────────────────────────────────────────
# mark_run()
# ─────────────────────────────────────────────────────────────

def test_mark_run_without_snapshot():
    cur = _RecCursor(rowcount=1)
    ok = sr.mark_run(cur, 5, USER_CTX)
    assert ok is True
    sql, params = cur.calls[0]
    assert "run_count = run_count + 1" in sql
    assert "last_run_snapshot" not in sql
    assert params[0] == 5


def test_mark_run_with_snapshot():
    cur = _RecCursor(rowcount=1)
    ok = sr.mark_run(cur, 5, USER_CTX, snapshot={"rows": [{"a": 1}]})
    assert ok is True
    sql, params = cur.calls[0]
    assert "last_run_snapshot = %s::jsonb" in sql
    assert "rows" in params[0]  # json.dumps output
    assert params[1] == 5


def test_mark_run_zero_rowcount():
    cur = _RecCursor(rowcount=0)
    assert sr.mark_run(cur, 5, USER_CTX) is False


def test_mark_run_returns_false_on_exception():
    assert sr.mark_run(_RaiseCursor(), 5, USER_CTX) is False


def test_mark_run_requires_user_ctx():
    with pytest.raises(ValueError):
        sr.mark_run(_RecCursor(), 5, {})
