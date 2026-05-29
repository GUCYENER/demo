"""v3.38.0 — Smart Discovery tablo kapsamı helper testleri (TYCHE).

`app/services/db_smart/table_scope.py`:
  - is_admin_ctx (is_admin VEYA role=='admin')
  - resolve_scope (admin → all; user_id yok → fail-closed boş; aksi → gate'e devreder)
"""
from unittest.mock import patch

from app.services.data_source_access import AccessScope
from app.services.db_smart import table_scope


def test_is_admin_ctx_variants():
    assert table_scope.is_admin_ctx({"is_admin": True}) is True
    assert table_scope.is_admin_ctx({"role": "admin"}) is True
    assert table_scope.is_admin_ctx({"is_admin": False, "role": "user"}) is False
    assert table_scope.is_admin_ctx(None) is False
    assert table_scope.is_admin_ctx({}) is False


def test_resolve_scope_admin_returns_all_without_gate():
    # admin → user_accessible_tables hiç çağrılmamalı
    with patch.object(table_scope, "user_accessible_tables") as gate:
        scope = table_scope.resolve_scope(10, {"id": 1, "is_admin": True})
        assert scope.all_tables is True
        gate.assert_not_called()


def test_resolve_scope_no_user_id_fail_closed():
    # kimlik yok → fail-closed (boş kapsam, hiçbir tablo)
    with patch.object(table_scope, "user_accessible_tables") as gate:
        scope = table_scope.resolve_scope(10, {"id": 0})
        assert scope.all_tables is False
        assert scope.tables == frozenset()
        gate.assert_not_called()


def test_resolve_scope_delegates_to_gate():
    expected = AccessScope(all_tables=False, tables=frozenset({("public", "orders")}))
    with patch.object(table_scope, "user_accessible_tables", return_value=expected) as gate:
        scope = table_scope.resolve_scope(10, {"id": 5}, permission="can_execute")
        assert scope is expected
        gate.assert_called_once_with(5, 10, is_admin=False, permission="can_execute")
