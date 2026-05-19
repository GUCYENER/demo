"""VYRA v3.29.9 — fk_inference_dialects per-dialect adapter tests."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning.fk_inference_dialects import (
    MSSQLDialect,
    MySQLDialect,
    OracleDialect,
    PostgresDialect,
    get_dialect,
    is_safe_identifier,
)


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────
def test_get_dialect_postgres_default():
    assert isinstance(get_dialect(None), PostgresDialect)
    assert isinstance(get_dialect(""), PostgresDialect)


def test_get_dialect_aliases():
    assert isinstance(get_dialect("oracle"), OracleDialect)
    assert isinstance(get_dialect("sqlserver"), MSSQLDialect)
    assert isinstance(get_dialect("mariadb"), MySQLDialect)
    assert isinstance(get_dialect("PG"), PostgresDialect)


def test_get_dialect_unknown_raises():
    with pytest.raises(ValueError):
        get_dialect("redis")


# ─────────────────────────────────────────────────────────────
# Identifier case-folding
# ─────────────────────────────────────────────────────────────
def test_postgres_normalize_lower():
    d = PostgresDialect()
    assert d.normalize_ident("PartyId") == "partyid"
    assert d.normalize_ident("  USER_ID ") == "user_id"


def test_oracle_normalize_upper():
    d = OracleDialect()
    assert d.normalize_ident("party_id") == "PARTY_ID"
    assert d.normalize_ident("UserId") == "USERID"


def test_mssql_normalize_lower_default():
    d = MSSQLDialect()
    assert d.normalize_ident("PartyID") == "partyid"


def test_mysql_normalize_lower_default():
    d = MySQLDialect()
    assert d.normalize_ident("ProblemId") == "problemid"


# ─────────────────────────────────────────────────────────────
# Quote escaping
# ─────────────────────────────────────────────────────────────
def test_postgres_quote_double_quote():
    d = PostgresDialect()
    assert d.quote_ident("user") == '"user"'
    assert d.quote_ident('a"b') == '"a""b"'


def test_mssql_quote_bracket():
    d = MSSQLDialect()
    assert d.quote_ident("user") == "[user]"
    assert d.quote_ident("a]b") == "[a]]b]"


def test_mysql_quote_backtick():
    d = MySQLDialect()
    assert d.quote_ident("user") == "`user`"
    assert d.quote_ident("a`b") == "`a``b`"


# ─────────────────────────────────────────────────────────────
# Type normalization
# ─────────────────────────────────────────────────────────────
def test_postgres_type_int_family():
    d = PostgresDialect()
    assert d.normalize_type("integer") == "int"
    assert d.normalize_type("BIGINT") == "int"
    assert d.normalize_type("smallint") == "int"


def test_postgres_type_uuid():
    d = PostgresDialect()
    assert d.normalize_type("uuid") == "uuid"


def test_postgres_type_str():
    d = PostgresDialect()
    assert d.normalize_type("varchar(50)") == "str"
    assert d.normalize_type("text") == "str"


def test_oracle_type_number_variants():
    d = OracleDialect()
    assert d.normalize_type("NUMBER(10,0)") == "int"
    assert d.normalize_type("NUMBER") == "int"
    assert d.normalize_type("INTEGER") == "int"


def test_oracle_type_raw_as_uuid():
    d = OracleDialect()
    assert d.normalize_type("RAW(16)") == "uuid"


def test_mssql_type_uniqueidentifier_as_uuid():
    d = MSSQLDialect()
    assert d.normalize_type("uniqueidentifier") == "uuid"


def test_mysql_type_binary16_as_uuid():
    d = MySQLDialect()
    assert d.normalize_type("binary(16)") == "uuid"


def test_type_other_fallback():
    d = PostgresDialect()
    assert d.normalize_type("jsonb") == "other"
    assert d.normalize_type("inet") == "other"


# ─────────────────────────────────────────────────────────────
# Sample validation SQL generation
# ─────────────────────────────────────────────────────────────
def test_pg_sample_sql_uses_double_quotes():
    d = PostgresDialect()
    sql, params = d.build_sample_validate_sql(
        "public", "problem", "user_id",
        "public", "users", "id", 100,
    )
    assert '"public"."problem"' in sql
    assert '"public"."users"' in sql
    assert "%s" in sql  # placeholder
    assert params == (100,)


def test_oracle_sample_sql_uses_rownum():
    d = OracleDialect()
    sql, params = d.build_sample_validate_sql(
        "HR", "PROBLEM", "USER_ID",
        "HR", "USERS", "ID", 50,
    )
    assert "ROWNUM" in sql
    assert ":1" in sql
    assert params == (50,)


def test_mssql_sample_sql_uses_top():
    d = MSSQLDialect()
    sql, params = d.build_sample_validate_sql(
        "dbo", "Problem", "UserId",
        "dbo", "Users", "Id", 75,
    )
    assert "TOP" in sql
    assert "[dbo].[Problem]" in sql
    assert "?" in sql  # T-SQL placeholder
    assert params == (75,)


def test_mysql_sample_sql_uses_limit():
    d = MySQLDialect()
    sql, params = d.build_sample_validate_sql(
        "app", "problem", "user_id",
        "app", "users", "id", 100,
    )
    assert "LIMIT %s" in sql
    assert "`app`.`problem`" in sql
    assert params == (100,)


# ─────────────────────────────────────────────────────────────
# is_safe_identifier
# ─────────────────────────────────────────────────────────────
def test_safe_ident_valid():
    assert is_safe_identifier("user")
    assert is_safe_identifier("user_id")
    assert is_safe_identifier("_private")
    assert is_safe_identifier("Camel123")


def test_safe_ident_rejects_injection():
    assert not is_safe_identifier("user; DROP TABLE")
    assert not is_safe_identifier("user--")
    assert not is_safe_identifier("user'")
    assert not is_safe_identifier("user.col")
    assert not is_safe_identifier("user col")
    assert not is_safe_identifier("")
    assert not is_safe_identifier(None)
    assert not is_safe_identifier("1user")  # starts with digit
