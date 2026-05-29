"""v3.38.0 — Tablo bazlı yetkilendirme gate testleri (TYCHE).

`app/services/data_source_access.py`:
  - AccessScope.allows (saf birim — DB yok)
  - user_accessible_tables çözümleme (mock cursor ile)

NOT: Gerçek DB yok — `get_db_context` fake conn/cursor ile patch'lenir.
Doküman gereği kritik senaryo: scope_mode='restricted' + 0 tablo => HİÇBİR tablo.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.services import data_source_access as dsa
from app.services.data_source_access import AccessScope, user_accessible_tables


# ───────────────────────── AccessScope.allows (saf) ─────────────────────────

def test_scope_all_tables_allows_everything():
    scope = AccessScope(all_tables=True)
    assert scope.allows("public", "orders") is True
    assert scope.allows(None, None) is True  # all → her şey


def test_scope_restricted_matches_only_listed():
    scope = AccessScope(all_tables=False, tables=frozenset({("public", "orders")}))
    assert scope.allows("public", "orders") is True
    assert scope.allows("public", "customers") is False


def test_scope_restricted_is_case_insensitive():
    # Oracle UPPER vs PG lower — allowlist lowercase tutulur, allows normalize eder
    scope = AccessScope(all_tables=False, tables=frozenset({("hr", "employees")}))
    assert scope.allows("HR", "EMPLOYEES") is True
    assert scope.allows("Hr", "Employees") is True


def test_scope_restricted_empty_denies_all():
    # KRİTİK (doküman): restricted + hiç tablo => hiçbir şey okunamaz
    scope = AccessScope(all_tables=False, tables=frozenset())
    assert scope.allows("public", "orders") is False
    assert scope.allows(None, None) is False


def test_scope_allows_table_name_schema_agnostic():
    # get_allowed_tables şemasız çıplak ad döner → şema-agnostik eşleşme
    scope = AccessScope(all_tables=False, tables=frozenset({("public", "orders")}))
    assert scope.allows_table_name("orders") is True
    assert scope.allows_table_name("ORDERS") is True  # case-insensitive
    assert scope.allows_table_name("customers") is False
    assert scope.allows_table_name("") is False
    assert scope.allows_table_name(None) is False


def test_scope_all_tables_allows_any_table_name():
    scope = AccessScope(all_tables=True)
    assert scope.allows_table_name("anything") is True


def test_scope_empty_restricted_allows_no_table_name():
    scope = AccessScope(all_tables=False, tables=frozenset())
    assert scope.allows_table_name("orders") is False


def test_scope_default_schema_blank_match():
    scope = AccessScope(all_tables=False, tables=frozenset({("", "orders")}))
    assert scope.allows(None, "orders") is True   # None schema → "" normalize
    assert scope.allows("", "orders") is True


# ───────────────────────── user_accessible_tables (mock) ─────────────────────

@contextmanager
def _fake_ctx(results):
    """get_db_context yerine: execute sırasıyla `results` listesinden fetchall döner."""
    queue = list(results)
    state = {"last": []}

    cur = MagicMock()

    def _execute(sql, params=None):
        state["last"] = queue.pop(0) if queue else []

    cur.execute.side_effect = _execute
    cur.fetchall.side_effect = lambda: state["last"]
    conn = MagicMock()
    conn.cursor.return_value = cur
    yield conn


def _patch_ctx(monkeypatch, results):
    monkeypatch.setattr(dsa, "get_db_context", lambda: _fake_ctx(results))


def test_admin_gets_all_without_db(monkeypatch):
    # Admin → DB'ye hiç gitmeden all_tables
    called = {"n": 0}
    monkeypatch.setattr(dsa, "get_db_context", lambda: called.__setitem__("n", called["n"] + 1))
    scope = user_accessible_tables(1, 10, is_admin=True)
    assert scope.all_tables is True
    assert called["n"] == 0


def test_no_grants_means_no_access(monkeypatch):
    _patch_ctx(monkeypatch, [[]])  # grants boş
    scope = user_accessible_tables(5, 10, is_admin=False)
    assert scope.all_tables is False
    assert scope.tables == frozenset()


def test_grant_scope_all_returns_all(monkeypatch):
    # tek grant scope_mode='all' → tüm tablolar (tablo sorgusu hiç gerekmez)
    grants = [("user", 5, "all")]
    _patch_ctx(monkeypatch, [grants])
    scope = user_accessible_tables(5, 10, is_admin=False)
    assert scope.all_tables is True


def test_restricted_grant_returns_union(monkeypatch):
    grants = [("user", 5, "restricted")]
    tables = [
        ("user", 5, "public", "orders"),
        ("user", 5, "PUBLIC", "CUSTOMERS"),  # case farkı → normalize
        ("org", 99, "public", "secret"),     # bu subject grant'larda yok → dahil edilmez
    ]
    _patch_ctx(monkeypatch, [grants, tables])
    scope = user_accessible_tables(5, 10, is_admin=False)
    assert scope.all_tables is False
    assert scope.tables == frozenset({("public", "orders"), ("public", "customers")})
    assert ("public", "secret") not in scope.tables


def test_restricted_grant_with_no_tables_denies(monkeypatch):
    # KRİTİK (doküman): restricted ama allowlist boş → hiçbir tablo
    grants = [("user", 5, "restricted")]
    _patch_ctx(monkeypatch, [grants, []])
    scope = user_accessible_tables(5, 10, is_admin=False)
    assert scope.all_tables is False
    assert scope.tables == frozenset()
    assert scope.allows("public", "orders") is False


def test_union_across_user_and_org_grants(monkeypatch):
    # Kullanıcı hem direkt hem org üyeliğiyle restricted → birleşim
    grants = [("user", 5, "restricted"), ("org", 7, "restricted")]
    tables = [
        ("user", 5, "public", "orders"),
        ("org", 7, "public", "invoices"),
    ]
    _patch_ctx(monkeypatch, [grants, tables])
    scope = user_accessible_tables(5, 10, is_admin=False)
    assert scope.tables == frozenset({("public", "orders"), ("public", "invoices")})


def test_any_all_grant_wins_over_restricted(monkeypatch):
    # Bir grant 'all' ise (org üyeliği) diğer restricted'a bakılmaz → tümü
    grants = [("user", 5, "restricted"), ("org", 7, "all")]
    _patch_ctx(monkeypatch, [grants])  # tablo sorgusu çağrılmamalı
    scope = user_accessible_tables(5, 10, is_admin=False)
    assert scope.all_tables is True


def test_invalid_permission_raises(monkeypatch):
    with pytest.raises(ValueError):
        user_accessible_tables(5, 10, is_admin=False, permission="can_delete")
