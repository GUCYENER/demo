"""
VYRA v3.29.7 G3 — Query Builder API unit tests
=============================================
Identifier whitelist + operator whitelist + SQL inşa testleri.
SafeSQLExecutor entegrasyonu (mock'lu) ayrı bir integration test'e bırakılır.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.query_builder_api import (
    _IDENT_RE,
    _ALLOWED_OPS,
    _safe_ident,
    _quote_ident,
    _qualified,
    _build_multi_table_sql,
    TableRef,
    JoinEdge,
    SelectColumn,
    FilterClause,
    OrderByClause,
    PreviewRequest,
)


# ───────────────────────── _safe_ident / _IDENT_RE ─────────────────────────

class TestSafeIdent:
    def test_valid_identifiers(self):
        assert _safe_ident("party") == "party"
        assert _safe_ident("Party_Relation") == "Party_Relation"
        assert _safe_ident("_private") == "_private"
        assert _safe_ident("col$1") == "col$1"

    def test_empty_returns_none(self):
        assert _safe_ident("") is None
        assert _safe_ident(None) is None

    def test_sql_injection_blocked(self):
        for bad in [
            "party; DROP TABLE users",
            "1=1",
            "party'--",
            "tbl OR 1=1",
            " party",
            "party ",
            "party.party",  # dot not allowed (use schema field)
        ]:
            assert _safe_ident(bad) is None, f"Expected None for {bad!r}"

    def test_starts_with_digit_blocked(self):
        assert _safe_ident("1party") is None

    def test_too_long_blocked(self):
        assert _safe_ident("a" * 64) is None  # max 63 (1 + 62)


# ───────────────────────── _quote_ident ─────────────────────────

class TestQuoteIdent:
    def test_postgresql_default(self):
        assert _quote_ident("party") == '"party"'

    def test_mssql_brackets(self):
        assert _quote_ident("party", "mssql") == "[party]"

    def test_mysql_backticks(self):
        assert _quote_ident("party", "mysql") == "`party`"

    def test_oracle_double_quote(self):
        assert _quote_ident("party", "oracle") == '"party"'


class TestQualified:
    def test_public_schema_omitted(self):
        assert _qualified("public", "party", "postgresql") == '"party"'

    def test_custom_schema_prefixed(self):
        assert _qualified("hr", "party", "postgresql") == '"hr"."party"'

    def test_no_schema(self):
        assert _qualified(None, "party", "postgresql") == '"party"'


# ───────────────────────── Pydantic validation ─────────────────────────

class TestTableRefValidation:
    def test_valid(self):
        t = TableRef(table="party")
        assert t.table == "party"

    def test_with_schema_alias(self):
        t = TableRef(**{"schema": "hr", "table": "party", "alias": "p"})
        assert t.schema_name == "hr"
        assert t.alias == "p"

    def test_injection_rejected(self):
        with pytest.raises(ValidationError):
            TableRef(table="party; DROP TABLE x")


class TestJoinEdgeValidation:
    def test_valid_inner(self):
        e = JoinEdge(
            from_table="problem", from_column="party_id",
            to_table="party", to_column="id", join_type="INNER",
        )
        assert e.join_type == "INNER"

    def test_invalid_join_type_rejected(self):
        with pytest.raises(ValidationError):
            JoinEdge(
                from_table="a", from_column="b",
                to_table="c", to_column="d", join_type="CROSS",
            )


class TestFilterClauseValidation:
    def test_op_whitelist(self):
        f = FilterClause(table="party", column="id", op="=", value=1)
        assert f.op == "="

    def test_op_lowercase_normalized(self):
        f = FilterClause(table="party", column="id", op="in", value=[1, 2])
        assert f.op == "IN"

    def test_invalid_op_rejected(self):
        with pytest.raises(ValidationError):
            FilterClause(table="party", column="id", op="; DROP", value=1)


class TestPreviewRequestLimits:
    def test_max_tables_8(self):
        with pytest.raises(ValidationError):
            PreviewRequest(
                source_id=1,
                tables=[TableRef(table=f"t{i}") for i in range(9)],
            )

    def test_limit_capped_1000(self):
        with pytest.raises(ValidationError):
            PreviewRequest(
                source_id=1,
                tables=[TableRef(table="x")],
                limit=1001,
            )


# ───────────────────────── _build_multi_table_sql ─────────────────────────

def _make_req(**overrides) -> PreviewRequest:
    base = dict(
        source_id=1,
        tables=[
            TableRef(table="problem", alias="p"),
            TableRef(table="party", alias="pa"),
        ],
        joins=[JoinEdge(
            from_table="problem", from_column="party_id",
            to_table="party", to_column="id", join_type="INNER",
        )],
        select=[
            SelectColumn(table="problem", column="id"),
            SelectColumn(table="party", column="name", alias="party_name"),
        ],
        filters=[],
        limit=10,
    )
    base.update(overrides)
    return PreviewRequest(**base)


class TestSqlBuild:
    def test_basic_select_join(self):
        req = _make_req()
        result = _build_multi_table_sql(req, "postgresql")
        assert result["valid"] is True
        sql = result["sql"]
        assert "SELECT" in sql
        assert '"p"."id"' in sql
        assert '"pa"."name" AS "party_name"' in sql
        assert "INNER JOIN" in sql
        assert '"party" AS "pa"' in sql
        assert 'ON "p"."party_id" = "pa"."id"' in sql
        assert "LIMIT 10" in sql
        assert result["params"] == []

    def test_filter_equal(self):
        req = _make_req(filters=[
            FilterClause(table="problem", column="status", op="=", value="open"),
        ])
        result = _build_multi_table_sql(req, "postgresql")
        assert "WHERE" in result["sql"]
        assert '"p"."status" = %s' in result["sql"]
        assert result["params"] == ["open"]

    def test_filter_in_list(self):
        req = _make_req(filters=[
            FilterClause(table="problem", column="id", op="IN", value=[1, 2, 3]),
        ])
        result = _build_multi_table_sql(req, "postgresql")
        assert '"p"."id" IN (%s, %s, %s)' in result["sql"]
        assert result["params"] == [1, 2, 3]

    def test_filter_between(self):
        req = _make_req(filters=[
            FilterClause(table="problem", column="id", op="BETWEEN", value=[1, 100]),
        ])
        result = _build_multi_table_sql(req, "postgresql")
        assert '"p"."id" BETWEEN %s AND %s' in result["sql"]
        assert result["params"] == [1, 100]

    def test_filter_is_null(self):
        req = _make_req(filters=[
            FilterClause(table="problem", column="closed_at", op="IS NULL"),
        ])
        result = _build_multi_table_sql(req, "postgresql")
        assert '"p"."closed_at" IS NULL' in result["sql"]
        assert result["params"] == []

    def test_filter_in_empty_list_warning(self):
        req = _make_req(filters=[
            FilterClause(table="problem", column="id", op="IN", value=[]),
        ])
        result = _build_multi_table_sql(req, "postgresql")
        assert any("IN" in w for w in result["warnings"])
        assert "WHERE" not in result["sql"]

    def test_filter_between_wrong_arity_warning(self):
        req = _make_req(filters=[
            FilterClause(table="problem", column="id", op="BETWEEN", value=[1]),
        ])
        result = _build_multi_table_sql(req, "postgresql")
        assert any("BETWEEN" in w for w in result["warnings"])

    def test_group_by(self):
        req = _make_req(
            select=[SelectColumn(table="party", column="id", agg="COUNT", alias="cnt")],
            group_by=[SelectColumn(table="party", column="id")],
        )
        result = _build_multi_table_sql(req, "postgresql")
        assert "COUNT" in result["sql"]
        assert "GROUP BY" in result["sql"]
        assert '"pa"."id"' in result["sql"]

    def test_order_by(self):
        req = _make_req(
            order_by=OrderByClause(table="problem", column="created_at", direction="DESC"),
        )
        result = _build_multi_table_sql(req, "postgresql")
        assert 'ORDER BY "p"."created_at" DESC' in result["sql"]

    def test_dialect_oracle_fetch_first(self):
        req = _make_req()
        result = _build_multi_table_sql(req, "oracle")
        assert "FETCH FIRST 10 ROWS ONLY" in result["sql"]
        assert "LIMIT" not in result["sql"]

    def test_dialect_mssql_top(self):
        req = _make_req()
        result = _build_multi_table_sql(req, "mssql")
        assert "SELECT TOP 10" in result["sql"]
        assert "[problem]" in result["sql"]
        assert "LIMIT" not in result["sql"]

    def test_dialect_mysql_backticks(self):
        req = _make_req()
        result = _build_multi_table_sql(req, "mysql")
        assert "`problem`" in result["sql"]
        assert "LIMIT 10" in result["sql"]

    def test_cartesian_warning_for_unjoined(self):
        req = PreviewRequest(
            source_id=1,
            tables=[
                TableRef(table="a"),
                TableRef(table="b"),
                TableRef(table="c"),
            ],
            joins=[JoinEdge(
                from_table="a", from_column="bid",
                to_table="b", to_column="id",
            )],
        )
        result = _build_multi_table_sql(req, "postgresql")
        assert any("Cartesian" in w for w in result["warnings"])
        assert any("c" in w for w in result["warnings"])

    def test_unknown_table_in_select_warning(self):
        req = _make_req(
            select=[SelectColumn(table="ghost", column="id")],
        )
        result = _build_multi_table_sql(req, "postgresql")
        assert any("Bilinmeyen tablo (SELECT)" in w for w in result["warnings"])

    def test_left_join_type_emitted(self):
        req = _make_req(joins=[JoinEdge(
            from_table="problem", from_column="party_id",
            to_table="party", to_column="id", join_type="LEFT",
        )])
        result = _build_multi_table_sql(req, "postgresql")
        assert "LEFT JOIN" in result["sql"]

    def test_qualified_schema_in_from(self):
        req = PreviewRequest(
            source_id=1,
            tables=[TableRef(**{"schema": "hr", "table": "party", "alias": "p"})],
            select=[SelectColumn(table="party", column="id")],
        )
        result = _build_multi_table_sql(req, "postgresql")
        assert '"hr"."party"' in result["sql"]

    def test_no_select_defaults_star(self):
        req = PreviewRequest(
            source_id=1,
            tables=[TableRef(table="party")],
        )
        result = _build_multi_table_sql(req, "postgresql")
        assert "SELECT *" in result["sql"]


# ───────────────────────── Allowed ops surface ─────────────────────────

class TestAllowedOps:
    def test_core_ops_present(self):
        for op in ("=", "<>", "<", ">", "IN", "NOT IN", "LIKE", "BETWEEN", "IS NULL", "IS NOT NULL"):
            assert op in _ALLOWED_OPS

    def test_dangerous_ops_absent(self):
        for op in (";", "--", "/*", "DROP", "DELETE"):
            assert op not in _ALLOWED_OPS
