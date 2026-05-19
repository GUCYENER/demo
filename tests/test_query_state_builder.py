"""
v3.28.3 G4 — Unit tests for query_state_builder
"""
from __future__ import annotations

import pytest

from app.services.pipeline.nodes.query_state_builder import (
    _is_safe_identifier,
    _normalize_op,
    _clamp_limit,
    build_sql_from_state,
)


class TestSafeIdentifier:

    def test_valid(self):
        for n in ("users", "user_id", "_x", "MyTable", "t1"):
            assert _is_safe_identifier(n)

    def test_invalid(self):
        for n in ("", "1abc", "user;DROP", "a-b", "a.b", None, 123, []):
            assert not _is_safe_identifier(n)

    def test_too_long(self):
        assert not _is_safe_identifier("a" * 64)
        assert _is_safe_identifier("a" * 63)


class TestNormalizeOp:

    def test_basic(self):
        assert _normalize_op("=") == "="
        assert _normalize_op("!=") == "!="
        assert _normalize_op("like") == "LIKE"
        assert _normalize_op(" ilike ") == "ILIKE"
        assert _normalize_op("is null") == "IS NULL"

    def test_reject(self):
        assert _normalize_op("DELETE") is None
        assert _normalize_op(";--") is None
        assert _normalize_op(None) is None
        assert _normalize_op("BETWEEN") is None  # whitelist'te yok


class TestClampLimit:

    def test_default(self):
        assert _clamp_limit(None, []) == 100

    def test_in_range(self):
        assert _clamp_limit(50, []) == 50

    def test_too_low(self):
        warnings = []
        assert _clamp_limit(0, warnings) == 1
        assert warnings

    def test_too_high(self):
        warnings = []
        assert _clamp_limit(99999, warnings) == 10000
        assert warnings

    def test_garbage(self):
        warnings = []
        assert _clamp_limit("abc", warnings) == 100
        assert warnings


class TestBuildSQL:

    def test_simple_select_all(self):
        # NOTE: ast_query_builder._format_table 'public' şemasını çıkartır (PG default)
        state = {"schema": "app", "table": "users", "dialect": "postgresql"}
        r = build_sql_from_state(state)
        assert r["valid"] is True
        assert 'FROM "app"."users"' in r["sql"]
        assert "SELECT *" in r["sql"]
        assert "LIMIT 100" in r["sql"]
        assert r["params"] == []

    def test_selected_columns(self):
        state = {
            "table": "orders",
            "dialect": "postgresql",
            "selected_columns": ["id", "total"],
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert '"id", "total"' in r["sql"]

    def test_invalid_column_dropped(self):
        state = {
            "table": "orders",
            "selected_columns": ["id", "DROP TABLE", "total"],
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        # 'DROP TABLE' (boşluklu) → drop edilir, geriye id+total kalır
        assert '"DROP TABLE"' not in r["sql"]
        assert any("DROP TABLE" in w or "geçersiz" in w for w in r["warnings"])

    def test_filters_eq(self):
        state = {
            "table": "orders",
            "filters": [{"column": "status", "op": "=", "value": "PAID"}],
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert '"status" = %s' in r["sql"]
        assert r["params"] == ["PAID"]

    def test_filters_in(self):
        state = {
            "table": "orders",
            "filters": [{"column": "id", "op": "IN", "value": [1, 2, 3]}],
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert '"id" IN (%s, %s, %s)' in r["sql"]
        assert r["params"] == [1, 2, 3]

    def test_filters_is_null(self):
        state = {
            "table": "orders",
            "filters": [{"column": "deleted_at", "op": "IS NULL"}],
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert '"deleted_at" IS NULL' in r["sql"]
        assert r["params"] == []

    def test_invalid_op_rejected(self):
        state = {
            "table": "orders",
            "filters": [{"column": "x", "op": "DELETE", "value": 1}],
        }
        r = build_sql_from_state(state)
        # Filter atılır ama SQL üretilir (boş WHERE)
        assert r["valid"]
        assert "WHERE" not in r["sql"]

    def test_order_by(self):
        state = {
            "table": "orders",
            "order_by": {"column": "created_at", "direction": "DESC"},
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert '"created_at" DESC' in r["sql"]

    def test_dialect_mssql_no_order_pseudo(self):
        state = {"table": "Orders", "dialect": "mssql"}
        r = build_sql_from_state(state)
        assert r["valid"]
        assert "ORDER BY (SELECT NULL)" in r["sql"]
        assert "OFFSET 0 ROWS FETCH NEXT 100" in r["sql"]

    def test_dialect_mysql_backticks(self):
        state = {"schema": "app", "table": "users", "dialect": "mysql"}
        r = build_sql_from_state(state)
        assert r["valid"]
        assert "`app`.`users`" in r["sql"]

    def test_dialect_oracle_fetch_first(self):
        state = {"table": "EMPLOYEES", "dialect": "oracle", "limit": 25}
        r = build_sql_from_state(state)
        assert r["valid"]
        assert "FETCH FIRST 25 ROWS ONLY" in r["sql"]

    def test_invalid_table_rejected(self):
        state = {"table": "users;DROP"}
        r = build_sql_from_state(state)
        assert r["valid"] is False
        assert r["sql"] is None
        assert r["warnings"]

    def test_invalid_schema_rejected(self):
        state = {"schema": "x;y", "table": "t"}
        r = build_sql_from_state(state)
        assert r["valid"] is False

    def test_limit_clamped(self):
        state = {"table": "t", "limit": 999999}
        r = build_sql_from_state(state)
        assert "LIMIT 10000" in r["sql"]

    def test_non_dict_state(self):
        r = build_sql_from_state("not a dict")  # type: ignore
        assert r["valid"] is False

    def test_too_many_filters(self):
        state = {
            "table": "t",
            "filters": [{"column": "c", "op": "=", "value": i} for i in range(50)],
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert len(r["params"]) == 20  # _MAX_FILTERS

    def test_complete_state(self):
        state = {
            "schema": "public",
            "table": "orders",
            "dialect": "postgresql",
            "selected_columns": ["id", "total", "status"],
            "filters": [
                {"column": "status", "op": "=", "value": "PAID"},
                {"column": "total", "op": ">", "value": 100},
            ],
            "order_by": {"column": "created_at", "direction": "DESC"},
            "limit": 25,
        }
        r = build_sql_from_state(state)
        assert r["valid"]
        assert r["params"] == ["PAID", 100]
        assert '"id", "total", "status"' in r["sql"]
        assert "LIMIT 25" in r["sql"]
        assert "ORDER BY" in r["sql"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
