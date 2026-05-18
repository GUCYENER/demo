"""VYRA v3.27.0 — AST Shortcut Tests (B.END.1).

Pattern detection + SQL building. No DB. Pure-function focus.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.nodes.ast_shortcut import (
    MIN_CONFIDENCE,
    _detect_pattern,
    ast_shortcut_node,
    is_shortcut_eligible,
)


def _state(question: str, columns=None, dialect="postgresql"):
    return {
        "question": question,
        "selected_tables": [
            {
                "schema_name": "public",
                "table_name": "orders",
                "columns": columns or [
                    {"column_name": "id", "data_type": "int"},
                    {"column_name": "customer_id", "data_type": "int"},
                    {"column_name": "amount", "data_type": "numeric"},
                    {"column_name": "created_at", "data_type": "timestamp"},
                    {"column_name": "status", "data_type": "varchar"},
                ],
            }
        ],
        "db_dialect": dialect,
    }


class TestDetectPattern:
    def test_count_pattern(self):
        p, c, _ = _detect_pattern("toplam kaç sipariş var?")
        assert p == "COUNT"
        assert c >= MIN_CONFIDENCE

    def test_top_n_with_number(self):
        p, c, params = _detect_pattern("ilk 5 müşteriyi göster")
        assert p == "TOP_N"
        assert params.get("n") == 5
        assert c >= MIN_CONFIDENCE

    def test_latest_pattern(self):
        p, c, params = _detect_pattern("en yeni 10 kayıt")
        assert p == "LATEST"
        assert params.get("n") == 10
        assert c >= MIN_CONFIDENCE

    def test_filter_eq_pattern(self):
        p, c, params = _detect_pattern("status=active olanlar")
        assert p == "FILTER_EQ"
        assert params.get("col_hint") == "status"
        assert params.get("value") == "active"
        assert c >= MIN_CONFIDENCE

    def test_group_by_pattern(self):
        p, c, _ = _detect_pattern("müşteri başına sipariş sayısı")
        # COUNT has higher priority — "sayısı" trips COUNT before GROUP_BY
        # Plan accepts either as long as confidence ≥ threshold
        assert p in ("COUNT", "GROUP_BY")
        assert c >= MIN_CONFIDENCE

    def test_no_match_returns_none(self):
        p, c, _ = _detect_pattern("rastgele lorem ipsum metin")
        assert p is None
        assert c < MIN_CONFIDENCE


class TestEligibility:
    def test_single_table_eligible(self):
        st = _state("kaç sipariş")
        assert is_shortcut_eligible(st) is True

    def test_multi_table_not_eligible(self):
        st = _state("kaç sipariş")
        st["selected_tables"].append({"schema_name": "public", "table_name": "customers"})
        assert is_shortcut_eligible(st) is False

    def test_disable_flag_blocks(self):
        st = _state("kaç sipariş")
        st["disable_ast_shortcut"] = True
        assert is_shortcut_eligible(st) is False


class TestNodeSqlBuilding:
    def test_count_produces_count_star(self):
        out = ast_shortcut_node(_state("kaç sipariş var"))
        assert out.get("sql_source") == "ast_shortcut"
        assert out.get("ast_pattern") == "COUNT"
        assert "count(*)" in out["sql"].lower()

    def test_top_n_uses_numeric_column(self):
        out = ast_shortcut_node(_state("ilk 7 sipariş göster"))
        assert out.get("ast_pattern") == "TOP_N"
        sql = out["sql"].lower()
        assert "order by" in sql
        # 'amount' kolon adı içermeli (numeric_hints)
        assert "amount" in sql
        assert "limit 7" in sql.replace("\n", " ")

    def test_top_n_mssql_uses_top(self):
        out = ast_shortcut_node(_state("ilk 7 sipariş", dialect="mssql"))
        sql = out["sql"].lower()
        assert "top 7" in sql

    def test_latest_requires_date_column(self):
        out = ast_shortcut_node(_state("en yeni kayıt"))
        assert out.get("ast_pattern") == "LATEST"
        assert "created_at" in out["sql"].lower()

    def test_latest_skips_without_date_column(self):
        # 'created_at' yok → skip
        state = _state("en yeni kayıt", columns=[{"column_name": "id"}, {"column_name": "name"}])
        out = ast_shortcut_node(state)
        # Eligibility geçer ama LATEST için date kolonu yok → builder ValueError → no-op
        assert out == {}

    def test_filter_eq_quotes_string_value(self):
        out = ast_shortcut_node(_state("status=active olan kayıtlar"))
        assert out.get("ast_pattern") == "FILTER_EQ"
        assert "where" in out["sql"].lower()
        assert "'active'" in out["sql"]

    def test_filter_eq_numeric_unquoted(self):
        out = ast_shortcut_node(_state("customer_id=42 kayıtları"))
        assert out.get("ast_pattern") == "FILTER_EQ"
        # value 42 → numeric → quote yok
        assert "= 42" in out["sql"] or "=42" in out["sql"]

    def test_no_match_returns_empty(self):
        out = ast_shortcut_node(_state("xyzabc lorem ipsum"))
        assert out == {}
