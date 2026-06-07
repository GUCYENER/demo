"""v3.78.x — case-insensitive text-equality rewriter (_apply_ci_text_equality) testleri.
gstack-adversarial bu katmanın 0 testi olduğunu işaretledi; B1 (LOB/CLOB) fix'i dahil."""
from app.services.db_smart.llm_generate_report import (
    _apply_ci_text_equality,
    _collect_text_columns,
)

# table_columns: {tablo: [(kolon_adı, veri_tipi), ...]}
COLS = {
    "t": [
        ("Name", "varchar(50)"),
        ("Bio", "text"),            # PG text → UPPER güvenli
        ("Age", "integer"),
        ("Notes", "clob"),          # Oracle LOB → UPPER ORA-00932 (B1)
        ("Memo", "ntext"),          # MSSQL LOB → CI-wrap dışı (B1)
        ("Created", "timestamp"),
    ]
}


class TestCollectTextColumns:
    def test_varchar_is_text(self):
        assert "name" in _collect_text_columns(COLS)

    def test_pg_text_is_text(self):
        assert "bio" in _collect_text_columns(COLS)

    def test_numeric_date_excluded(self):
        tc = _collect_text_columns(COLS)
        assert "age" not in tc and "created" not in tc

    def test_b1_clob_excluded(self):
        # B1: CLOB CI-wrap'tan elenmeli (UPPER(CLOB) → ORA-00932)
        assert "notes" not in _collect_text_columns(COLS)

    def test_b1_ntext_excluded(self):
        assert "memo" not in _collect_text_columns(COLS)

    def test_ambiguous_excluded(self):
        # Aynı ad bir tabloda text başka tabloda int → dokunma
        cols = {"a": [("code", "varchar")], "b": [("code", "integer")]}
        assert "code" not in _collect_text_columns(cols)


class TestApplyCiTextEquality:
    def test_basic_text_wrap(self):
        out = _apply_ci_text_equality('SELECT * FROM t WHERE "Name" = \'john\'', COLS)
        assert 'UPPER("Name") = UPPER(\'john\')' in out

    def test_numeric_not_wrapped(self):
        sql = 'SELECT * FROM t WHERE "Age" = \'5\''
        assert _apply_ci_text_equality(sql, COLS) == sql

    def test_b1_clob_not_wrapped(self):
        # B1 REGRESYON: CLOB kolonu UPPER'a SARILMAMALI (geçersiz Oracle SQL üretmesin)
        sql = 'SELECT * FROM t WHERE "Notes" = \'x\''
        assert _apply_ci_text_equality(sql, COLS) == sql
        assert "UPPER" not in _apply_ci_text_equality(sql, COLS)

    def test_operators_not_matched(self):
        # >=, <=, <>, != yalnız `=` değil → sarma yok
        for op in (">=", "<=", "<>", "!="):
            sql = 'SELECT * FROM t WHERE "Name" %s \'x\'' % op
            assert "UPPER" not in _apply_ci_text_equality(sql, COLS)

    def test_escaped_quote_literal(self):
        out = _apply_ci_text_equality("SELECT * FROM t WHERE \"Name\" = 'O''Brien'", COLS)
        assert "UPPER(\"Name\") = UPPER('O''Brien')" in out

    def test_idempotent_no_double_wrap(self):
        # İki kez uygulamak çifte-sarmamalı
        once = _apply_ci_text_equality('SELECT * FROM t WHERE "Name" = \'x\'', COLS)
        twice = _apply_ci_text_equality(once, COLS)
        assert once == twice
        assert twice.count("UPPER(\"Name\")") == 1

    def test_qualified_identifier(self):
        out = _apply_ci_text_equality('... WHERE "t"."Name" = \'x\'', COLS)
        assert 'UPPER("t"."Name") = UPPER(\'x\')' in out

    def test_join_ident_eq_ident_not_wrapped(self):
        # RHS literal değil (kolon) → JOIN koşulu doğal kapsam-dışı
        sql = 'SELECT * FROM a JOIN b ON "a"."id" = "b"."id"'
        assert _apply_ci_text_equality(sql, COLS) == sql

    def test_alias_collision_skipped(self):
        # niteliksiz ad SELECT-list alias'ı (sayısal ifade gizliyor olabilir) → atla
        sql = 'SELECT MAX("Age") AS "Name" FROM t HAVING "Name" = \'5\''
        assert _apply_ci_text_equality(sql, COLS) == sql

    def test_multiple_equalities(self):
        out = _apply_ci_text_equality(
            'SELECT * FROM t WHERE "Name" = \'a\' AND "Bio" = \'b\'', COLS)
        assert 'UPPER("Name") = UPPER(\'a\')' in out
        assert 'UPPER("Bio") = UPPER(\'b\')' in out

    def test_none_and_empty(self):
        assert _apply_ci_text_equality(None, COLS) is None
        assert _apply_ci_text_equality('SELECT 1', {}) == 'SELECT 1'
        assert _apply_ci_text_equality('SELECT 1', None) == 'SELECT 1'
