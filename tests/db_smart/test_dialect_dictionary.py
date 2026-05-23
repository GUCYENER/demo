"""dialect_dictionary — 4 RDBMS feature/syntax map (v3.30.0 FAZ 3 P12 G3.1)."""
from __future__ import annotations

import pytest

from app.services.db_smart import dialect_dictionary as dd


# ─────────────────────────────────────────────────────────────
# supported_dialects + normalization
# ─────────────────────────────────────────────────────────────

def test_supported_dialects_immutable_tuple():
    s = dd.supported_dialects()
    assert isinstance(s, tuple)
    assert set(s) == {"postgresql", "oracle", "mssql", "mysql"}


def test_supports_rejects_unknown_dialect():
    with pytest.raises(ValueError):
        dd.supports("snowflake", "supports_ilike")


def test_normalize_case_insensitive():
    # uppercase / spaces tolerated
    assert dd.supports("PostgreSQL", "supports_ilike") is True
    assert dd.supports("  Oracle ", "supports_listagg") is True


# ─────────────────────────────────────────────────────────────
# Features — bool flags
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("d,f,exp", [
    ("postgresql", "supports_ilike", True),
    ("postgresql", "supports_lateral", True),
    ("postgresql", "supports_grouping_sets", True),
    ("postgresql", "supports_jsonb_agg", True),
    ("postgresql", "supports_listagg", False),
    ("oracle", "supports_ilike", False),
    ("oracle", "supports_listagg", True),
    ("oracle", "supports_connect_by", True),
    ("oracle", "supports_array_agg", False),
    ("mssql", "supports_top", True),
    ("mssql", "supports_string_agg", True),
    ("mssql", "supports_array_agg", False),
    ("mysql", "supports_grouping_sets", False),  # MySQL 8 — bilinçli False
    ("mysql", "supports_recursive_cte", True),
    ("mysql", "supports_ilike", False),
])
def test_supports_feature_flags(d, f, exp):
    assert dd.supports(d, f) is exp


def test_supports_unknown_feature_returns_false():
    # Bilinmeyen feature → False (KeyError yok)
    assert dd.supports("postgresql", "supports_quantum_entanglement") is False


def test_features_returns_full_map():
    fs = dd.features("postgresql")
    for k in dd.FEATURE_KEYS:
        assert k in fs


def test_features_is_immutable():
    # MappingProxyType — setitem TypeError fırlatmalı
    fs = dd.features("postgresql")
    with pytest.raises(TypeError):
        fs["supports_ilike"] = False  # type: ignore[index]


# ─────────────────────────────────────────────────────────────
# Syntax fragments
# ─────────────────────────────────────────────────────────────

def test_syntax_ident_quote():
    assert dd.syntax("postgresql", "ident_quote_open") == '"'
    assert dd.syntax("mssql", "ident_quote_open") == "["
    assert dd.syntax("mysql", "ident_quote_open") == "`"
    assert dd.syntax("oracle", "ident_quote_open") == '"'


def test_syntax_unknown_key_returns_default():
    assert dd.syntax("postgresql", "no_such_key", default="x") == "x"
    assert dd.syntax("postgresql", "no_such_key") is None


def test_quote_identifier_basic():
    assert dd.quote_identifier("postgresql", "users") == '"users"'
    assert dd.quote_identifier("mysql", "users") == "`users`"
    assert dd.quote_identifier("mssql", "users") == "[users]"


def test_quote_identifier_escapes_quote_chars():
    # PostgreSQL: " → ""
    assert dd.quote_identifier("postgresql", 'we"ird') == '"we""ird"'
    # MSSQL: ] → ]]
    assert dd.quote_identifier("mssql", "we]ird") == "[we]]ird]"
    # MySQL: ` → ``
    assert dd.quote_identifier("mysql", "we`ird") == "`we``ird`"


def test_quote_identifier_empty_input():
    assert dd.quote_identifier("postgresql", "") == ""


# ─────────────────────────────────────────────────────────────
# build_limit_offset_clause
# ─────────────────────────────────────────────────────────────

def test_limit_clause_postgresql_simple():
    assert dd.build_limit_offset_clause("postgresql", 100) == "LIMIT 100"


def test_limit_offset_clause_postgresql():
    assert dd.build_limit_offset_clause("postgresql", 100, 50) == "LIMIT 100 OFFSET 50"


def test_limit_clause_oracle_uses_fetch_first():
    out = dd.build_limit_offset_clause("oracle", 100)
    assert "FETCH FIRST 100 ROWS ONLY" == out


def test_limit_offset_clause_oracle_uses_fetch_next():
    out = dd.build_limit_offset_clause("oracle", 100, 50)
    assert "OFFSET 50 ROWS" in out and "FETCH NEXT 100 ROWS ONLY" in out


def test_limit_clause_mssql():
    # MSSQL standart pattern OFFSET 0 ROWS FETCH NEXT N ROWS ONLY
    out = dd.build_limit_offset_clause("mssql", 100)
    assert "FETCH NEXT 100 ROWS ONLY" in out


def test_limit_clause_mysql():
    assert dd.build_limit_offset_clause("mysql", 100) == "LIMIT 100"
    assert dd.build_limit_offset_clause("mysql", 100, 25) == "LIMIT 100 OFFSET 25"


def test_limit_negative_returns_empty():
    assert dd.build_limit_offset_clause("postgresql", -5) == ""


def test_limit_offset_negative_clamped_to_zero():
    # negative offset → 0; offset=0 → limit_clause (no offset)
    out = dd.build_limit_offset_clause("postgresql", 10, -3)
    assert out == "LIMIT 10"


def test_limit_invalid_type_returns_empty():
    assert dd.build_limit_offset_clause("postgresql", "bad") == ""  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────
# Function mapping
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("d,name,exp_fragment", [
    ("postgresql", "string_agg", "STRING_AGG"),
    ("oracle", "string_agg", "LISTAGG"),
    ("mssql", "string_agg", "STRING_AGG"),
    ("mysql", "string_agg", "GROUP_CONCAT"),
    ("postgresql", "median", "PERCENTILE_CONT"),
    ("oracle", "median", "MEDIAN"),
    ("postgresql", "now", "NOW()"),
    ("oracle", "now", "SYSTIMESTAMP"),
    ("mssql", "now", "SYSDATETIME()"),
    ("mysql", "now", "NOW()"),
])
def test_func_returns_dialect_template(d, name, exp_fragment):
    out = dd.func(d, name)
    assert out is not None
    assert exp_fragment in out


def test_func_unsupported_returns_none():
    assert dd.func("mysql", "median") is None
    assert dd.func("mssql", "regex_match") is None
    assert dd.func("oracle", "array_agg") is None


def test_render_function_fills_placeholders():
    out = dd.render_function("postgresql", "string_agg", "name", sep="', '")
    assert out == "STRING_AGG(name, ', ')"


def test_render_function_oracle_listagg():
    out = dd.render_function("oracle", "string_agg", "name", sep="', '")
    assert "LISTAGG(name, ', ')" in out
    assert "WITHIN GROUP" in out


def test_render_function_mysql_group_concat():
    out = dd.render_function("mysql", "string_agg", "name", sep="', '")
    assert "GROUP_CONCAT(name SEPARATOR ', ')" == out


def test_render_function_unsupported_returns_none():
    assert dd.render_function("mysql", "median", "amount") is None


def test_render_function_concat_two_args():
    out = dd.render_function("mssql", "concat", "a", "b")
    assert out == "CONCAT(a, b)"


# ─────────────────────────────────────────────────────────────
# Hint catalog
# ─────────────────────────────────────────────────────────────

def test_hint_catalog_postgres():
    h = dd.hint_catalog("postgresql")
    assert "work_mem_mb" in h


def test_hint_catalog_oracle():
    h = dd.hint_catalog("oracle")
    assert "parallel" in h
    assert "result_cache" in h


def test_hint_catalog_mssql():
    h = dd.hint_catalog("mssql")
    assert "maxdop" in h
    assert "recompile" in h


def test_hint_catalog_mysql():
    h = dd.hint_catalog("mysql")
    assert "max_execution_time_ms" in h


# ─────────────────────────────────────────────────────────────
# Cross-dialect consistency
# ─────────────────────────────────────────────────────────────

def test_all_dialects_have_full_feature_keys():
    for d in dd.supported_dialects():
        f = dd.features(d)
        assert set(f.keys()) == set(dd.FEATURE_KEYS)


def test_all_dialects_have_quote_pair():
    for d in dd.supported_dialects():
        o = dd.syntax(d, "ident_quote_open")
        c = dd.syntax(d, "ident_quote_close")
        assert o and c


def test_all_dialects_have_limit_clause_template():
    for d in dd.supported_dialects():
        out = dd.build_limit_offset_clause(d, 10)
        assert out  # non-empty
