"""DB Smart — template_marketplace unit tests (v3.30.0 FAZ 3 P18 G3.3)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.db_smart import template_marketplace as tm


@pytest.fixture
def mock_cur():
    cur = MagicMock()
    cur.rowcount = 1
    return cur


@pytest.fixture
def user42():
    return {"id": 42, "username": "u", "company_id": 1, "is_admin": False}


def _row(metric_key="oldest_open", name_tr="Oldest Open", cat="helpdesk",
         is_official=True, owner=None, usage=10, success=0.8):
    """browse SELECT kolon sırasına uyumlu test row."""
    return (1, metric_key, name_tr, "Oldest", cat, "ticket",
            "desc tr", "table", {"col": "x"}, {"postgresql": "SELECT 1"},
            is_official, owner, usage, success, None)


def test_browse_default_all(mock_cur, user42):
    mock_cur.fetchall.return_value = [_row()]
    items = tm.browse(mock_cur, user42)
    assert len(items) == 1
    assert items[0]["metric_key"] == "oldest_open"
    assert items[0]["is_mine"] is False  # owner=None
    sql = mock_cur.execute.call_args[0][0]
    assert "ORDER BY usage_count DESC" in sql.replace("\n", " ").replace("  ", " ").replace("  ", " ")


def test_browse_with_q_escapes_like(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    tm.browse(mock_cur, user42, q="50%_off\\test")
    sql, params = mock_cur.execute.call_args[0]
    assert "ILIKE %s ESCAPE %s" in sql
    # 50%_off → 50\%\_off ; backslash da escape edilir → 50\\\%\\_off ? hayır:
    # mantık: \\ → \\\\, % → \%, _ → \_ ; sırasıyla
    # girdi: 50%_off\test → \\ first: 50%_off\\test → %: 50\%_off\\test → _: 50\%\_off\\test
    pattern = [p for p in params if isinstance(p, str) and p.startswith("%50")]
    assert pattern, f"escaped pattern bulunamadı: params={params}"
    assert "\\%" in pattern[0] and "\\_" in pattern[0]


def test_browse_category_filter(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    tm.browse(mock_cur, user42, category="sales")
    sql, params = mock_cur.execute.call_args[0]
    assert "category = %s" in sql
    assert "sales" in params


def test_browse_owner_mine(mock_cur, user42):
    mock_cur.fetchall.return_value = [_row(owner=42)]
    items = tm.browse(mock_cur, user42, owner="mine")
    sql, params = mock_cur.execute.call_args[0]
    assert "owner_user_id = %s" in sql
    assert 42 in params
    assert items[0]["is_mine"] is True


def test_browse_owner_community_excludes_self(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    tm.browse(mock_cur, user42, owner="community")
    sql, params = mock_cur.execute.call_args[0]
    assert "is_official IS FALSE" in sql
    assert "owner_user_id IS NULL OR owner_user_id <> %s" in sql
    assert 42 in params


def test_browse_order_options(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    for ordering, hint in [("popular", "usage_count DESC"),
                           ("recent", "created_at DESC"),
                           ("name", "name_tr ASC")]:
        mock_cur.execute.reset_mock()
        tm.browse(mock_cur, user42, order=ordering)
        sql = mock_cur.execute.call_args[0][0]
        assert hint in sql, f"order={ordering} bekleniyordu {hint}"


def test_browse_limit_clamps(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    tm.browse(mock_cur, user42, limit=99999)  # > max → clamp 50
    params = mock_cur.execute.call_args[0][1]
    assert params[-1] == 50  # default
    mock_cur.execute.reset_mock()
    tm.browse(mock_cur, user42, limit=-5)  # invalid → default 50
    params = mock_cur.execute.call_args[0][1]
    assert params[-1] == 50


def test_browse_is_official_true(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    tm.browse(mock_cur, user42, is_official=True)
    sql = mock_cur.execute.call_args[0][0]
    assert "is_official IS TRUE" in sql


def test_browse_is_official_false(mock_cur, user42):
    mock_cur.fetchall.return_value = []
    tm.browse(mock_cur, user42, is_official=False)
    sql = mock_cur.execute.call_args[0][0]
    assert "is_official IS FALSE" in sql


def test_browse_pii_owner_user_id_stripped(mock_cur, user42):
    mock_cur.fetchall.return_value = [_row(owner=99)]  # başkasının
    items = tm.browse(mock_cur, user42)
    assert "owner_user_id" not in items[0]
    assert items[0]["is_mine"] is False


def test_get_categories(mock_cur):
    mock_cur.fetchall.return_value = [("helpdesk", 12), ("sales", 10), ("generic", 8)]
    cats = tm.get_categories(mock_cur)
    assert cats == [
        {"category": "helpdesk", "count": 12},
        {"category": "sales", "count": 10},
        {"category": "generic", "count": 8},
    ]


def test_get_by_key_found(mock_cur, user42):
    mock_cur.fetchone.return_value = (
        1, "oldest_open", "Oldest", "Oldest EN", "helpdesk", "ticket",
        "desc tr", "rationale tr", "table", {}, {}, {}, {},
        True, 42, 5, 0.7, None,
    )
    rec = tm.get_by_key(mock_cur, "oldest_open", user42)
    assert rec is not None
    assert rec["metric_key"] == "oldest_open"
    assert rec["is_mine"] is True
    assert "owner_user_id" not in rec


def test_get_by_key_not_found(mock_cur, user42):
    mock_cur.fetchone.return_value = None
    rec = tm.get_by_key(mock_cur, "doesnt_exist", user42)
    assert rec is None
