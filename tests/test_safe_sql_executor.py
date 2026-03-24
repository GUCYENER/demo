"""
VYRA - Safe SQL Executor & SQL Dialect Tests
=============================================
SQL güvenlik doğrulama, dialect adaptasyonu ve hassas alan maskeleme testleri.

Test Sayısı: ~15 test
"""

import pytest
from app.services.safe_sql_executor import (
    validate_sql,
    check_table_whitelist,
    mask_sensitive_columns,
    SQLSecurityError,
)
from app.services.sql_dialect import (
    SQLDialect,
    apply_row_limit,
    adapt_functions,
    quote_identifier,
    quote_table,
    build_template_sql,
)


# =============================================================================
# TEST: SQL Validation (Güvenlik)
# =============================================================================

class TestSQLValidation:
    """SQL güvenlik doğrulama testleri."""

    def test_select_is_valid(self):
        """SELECT sorgusu geçerli olmalı."""
        is_valid, error = validate_sql("SELECT * FROM users")
        assert is_valid is True
        assert error is None

    def test_select_with_where_is_valid(self):
        """WHERE koşullu SELECT geçerli olmalı."""
        is_valid, error = validate_sql("SELECT id, name FROM users WHERE id = 1")
        assert is_valid is True

    def test_with_cte_is_valid(self):
        """WITH ... SELECT (CTE) geçerli olmalı."""
        sql = "WITH active_users AS (SELECT * FROM users WHERE active = TRUE) SELECT * FROM active_users"
        is_valid, error = validate_sql(sql)
        assert is_valid is True

    def test_delete_is_blocked(self):
        """DELETE yasak olmalı."""
        is_valid, error = validate_sql("DELETE FROM users WHERE id = 1")
        assert is_valid is False
        assert "SELECT" in error or "Yasak" in error

    def test_drop_table_is_blocked(self):
        """DROP TABLE yasak olmalı."""
        is_valid, error = validate_sql("DROP TABLE users")
        assert is_valid is False

    def test_insert_is_blocked(self):
        """INSERT yasak olmalı."""
        is_valid, error = validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert is_valid is False

    def test_update_is_blocked(self):
        """UPDATE yasak olmalı."""
        is_valid, error = validate_sql("UPDATE users SET name = 'test'")
        assert is_valid is False

    def test_truncate_is_blocked(self):
        """TRUNCATE yasak olmalı."""
        is_valid, error = validate_sql("TRUNCATE TABLE users")
        assert is_valid is False

    def test_sql_injection_semicolon(self):
        """'; DROP TABLE' injection engellenmeli."""
        is_valid, error = validate_sql("SELECT * FROM users; DROP TABLE users")
        assert is_valid is False

    def test_sql_injection_union(self):
        """UNION ALL SELECT injection engellenmeli."""
        is_valid, error = validate_sql(
            "SELECT * FROM users UNION ALL SELECT * FROM admin_passwords"
        )
        assert is_valid is False

    def test_empty_sql_is_invalid(self):
        """Boş SQL geçersiz olmalı."""
        is_valid, error = validate_sql("")
        assert is_valid is False

    def test_none_sql_is_invalid(self):
        """None SQL geçersiz olmalı."""
        is_valid, error = validate_sql(None)
        assert is_valid is False

    def test_into_outfile_injection_blocked(self):
        """SELECT INTO OUTFILE injection engellenmeli."""
        is_valid, error = validate_sql("SELECT * FROM users INTO OUTFILE '/tmp/data.csv'")
        assert is_valid is False

    def test_into_dumpfile_injection_blocked(self):
        """SELECT INTO DUMPFILE injection engellenmeli."""
        is_valid, error = validate_sql("SELECT * FROM users INTO DUMPFILE '/tmp/data.bin'")
        assert is_valid is False

    def test_insert_into_still_blocked(self):
        """INSERT INTO hala engellenmeli (SELECT ile başlamıyor kontrolü)."""
        is_valid, error = validate_sql("INSERT INTO users (name) VALUES ('hack')")
        assert is_valid is False


# =============================================================================
# TEST: Table Whitelist
# =============================================================================

class TestTableWhitelist:
    """Tablo erişim kontrolü testleri."""

    def test_allowed_table_passes(self):
        """Whitelist'teki tablo geçmeli."""
        is_valid, error = check_table_whitelist(
            "SELECT * FROM users",
            allowed_tables=["users", "orders"]
        )
        assert is_valid is True

    def test_denied_table_fails(self):
        """Whitelist dışı tablo engellenmeli."""
        is_valid, error = check_table_whitelist(
            "SELECT * FROM admin_secrets",
            allowed_tables=["users", "orders"]
        )
        assert is_valid is False
        assert "admin_secrets" in error

    def test_empty_whitelist_allows_all(self):
        """Boş whitelist tüm tablolara izin vermeli."""
        is_valid, error = check_table_whitelist(
            "SELECT * FROM any_table_name",
            allowed_tables=[]
        )
        assert is_valid is True

    def test_schema_qualified_table(self):
        """schema.table formatı sadece tablo kısmı kontrol edilmeli."""
        is_valid, error = check_table_whitelist(
            'SELECT * FROM "public"."users"',
            allowed_tables=["users"]
        )
        assert is_valid is True


# =============================================================================
# TEST: Hassas Alan Maskeleme
# =============================================================================

class TestSensitiveColumnMasking:
    """Hassas sütun maskeleme testleri."""

    def test_tc_no_masked(self):
        """tc_no sütunu maskelenmeli."""
        rows = [{"id": 1, "name": "Ali", "tc_no": "12345678901"}]
        masked = mask_sensitive_columns(rows, ["id", "name", "tc_no"])

        assert masked[0]["tc_no"] == "***"
        assert masked[0]["name"] == "Ali"

    def test_iban_masked(self):
        """IBAN sütunu maskelenmeli."""
        rows = [{"id": 1, "iban": "TR123456789012345678901234"}]
        masked = mask_sensitive_columns(rows, ["id", "iban"])

        assert masked[0]["iban"] == "***"

    def test_password_masked(self):
        """password sütunu maskelenmeli."""
        rows = [{"id": 1, "password": "hashed_value"}]
        masked = mask_sensitive_columns(rows, ["id", "password"])

        assert masked[0]["password"] == "***"

    def test_normal_columns_not_masked(self):
        """Normal sütunlar maskelenmemeli."""
        rows = [{"id": 1, "name": "Ali", "email": "ali@test.com"}]
        masked = mask_sensitive_columns(rows, ["id", "name", "email"])

        assert masked[0]["name"] == "Ali"
        assert masked[0]["email"] == "ali@test.com"

    def test_empty_rows_returns_empty(self):
        """Boş satırlar boş dönmeli."""
        result = mask_sensitive_columns([], ["id"])
        assert result == []


# =============================================================================
# TEST: SQL Dialect Adapter
# =============================================================================

class TestSQLDialect:
    """SQL dialect dönüşüm testleri."""

    def test_postgresql_limit(self):
        """PostgreSQL LIMIT doğru eklenmeli."""
        sql = apply_row_limit("SELECT * FROM users", 10, SQLDialect.POSTGRESQL)
        assert "LIMIT 10" in sql

    def test_mssql_top(self):
        """MSSQL TOP doğru eklenmeli."""
        sql = apply_row_limit("SELECT * FROM users", 10, SQLDialect.MSSQL)
        assert "TOP 10" in sql

    def test_oracle_fetch_first(self):
        """Oracle FETCH FIRST doğru eklenmeli."""
        sql = apply_row_limit("SELECT * FROM users", 10, SQLDialect.ORACLE)
        assert "FETCH FIRST 10 ROWS ONLY" in sql

    def test_existing_limit_not_duplicated(self):
        """Zaten LIMIT varsa tekrar eklenmemeli."""
        sql = apply_row_limit("SELECT * FROM users LIMIT 5", 10, SQLDialect.POSTGRESQL)
        assert sql.count("LIMIT") == 1

    def test_function_adaptation_mssql(self):
        """NOW() → GETDATE() dönüşümü (MSSQL)."""
        sql = adapt_functions("SELECT NOW() as current_time", SQLDialect.MSSQL)
        assert "GETDATE()" in sql
        assert "NOW()" not in sql

    def test_function_adaptation_oracle(self):
        """NOW() → SYSDATE dönüşümü (Oracle)."""
        sql = adapt_functions("SELECT NOW() as current_time", SQLDialect.ORACLE)
        assert "SYSDATE" in sql

    def test_quote_identifier_postgresql(self):
        """PostgreSQL identifier quoting."""
        assert quote_identifier("users", SQLDialect.POSTGRESQL) == '"users"'

    def test_quote_identifier_mssql(self):
        """MSSQL identifier quoting."""
        assert quote_identifier("users", SQLDialect.MSSQL) == "[users]"

    def test_quote_identifier_mysql(self):
        """MySQL identifier quoting."""
        assert quote_identifier("users", SQLDialect.MYSQL) == "`users`"


# =============================================================================
# TEST: Template SQL Builder
# =============================================================================

class TestTemplateSQLBuilder:
    """Template SQL üretim testleri."""

    def test_row_count_template(self):
        """row_count template doğru SQL üretmeli."""
        sql = build_template_sql(
            template_name="row_count",
            table="users",
            dialect=SQLDialect.POSTGRESQL,
            schema="public",
        )

        assert sql is not None
        assert "COUNT(*)" in sql
        assert '"public"."users"' in sql
        assert "LIMIT" in sql

    def test_latest_records_template(self):
        """latest_records template ORDER BY ve LIMIT içermeli."""
        sql = build_template_sql(
            template_name="latest_records",
            table="orders",
            dialect=SQLDialect.POSTGRESQL,
            date_col="order_date",
            row_limit=10,
        )

        assert sql is not None
        assert "ORDER BY" in sql
        assert "DESC" in sql
        assert "LIMIT 10" in sql

    def test_sum_column_template(self):
        """sum_column template SUM() içermeli."""
        sql = build_template_sql(
            template_name="sum_column",
            table="orders",
            dialect=SQLDialect.POSTGRESQL,
            col="amount",
        )

        assert sql is not None
        assert "SUM(" in sql

    def test_unknown_template_returns_none(self):
        """Bilinmeyen template None dönmeli."""
        sql = build_template_sql(
            template_name="nonexistent_template",
            table="users",
            dialect=SQLDialect.POSTGRESQL,
        )
        assert sql is None

    def test_mssql_template_uses_top(self):
        """MSSQL template TOP kullanmalı."""
        sql = build_template_sql(
            template_name="latest_records",
            table="orders",
            dialect=SQLDialect.MSSQL,
            date_col="order_date",
            row_limit=10,
        )

        assert sql is not None
        assert "TOP 10" in sql
