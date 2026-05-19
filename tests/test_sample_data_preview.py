"""
v3.28.2 G3 — Unit tests for sample_data_preview helper

Covers:
- extract_first_table_from_sql() — FROM clause regex
- pick_top_table_for_preview() — selected_tables / ranked_candidates fallback
- build_sample_preview() — cursor mock ile cache hit + miss
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from app.services.pipeline.nodes.sample_data_preview import (
    build_sample_preview,
    extract_first_table_from_sql,
    pick_top_table_for_preview,
)


class _MockCursor:
    """psycopg2 RealDictCursor benzeri — fetchone() ile sıralı sahte yanıt."""

    def __init__(self, responses: List[Optional[Dict[str, Any]]]):
        self._responses = list(responses)
        self.executed: List[tuple] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if not self._responses:
            return None
        return self._responses.pop(0)


# ----------------------------------------------------------------------
# extract_first_table_from_sql
# ----------------------------------------------------------------------

class TestExtractFirstTable:

    def test_simple_from(self):
        r = extract_first_table_from_sql("SELECT * FROM users")
        assert r == {"schema": None, "table": "users"}

    def test_schema_qualified(self):
        r = extract_first_table_from_sql("SELECT id FROM public.users WHERE id=1")
        assert r == {"schema": "public", "table": "users"}

    def test_double_quoted(self):
        r = extract_first_table_from_sql('SELECT * FROM "public"."users"')
        assert r == {"schema": "public", "table": "users"}

    def test_bracket_quoted_mssql(self):
        r = extract_first_table_from_sql("SELECT * FROM [dbo].[Orders]")
        assert r == {"schema": "dbo", "table": "Orders"}

    def test_backtick_mysql(self):
        r = extract_first_table_from_sql("SELECT * FROM `app`.`users`")
        assert r == {"schema": "app", "table": "users"}

    def test_case_insensitive(self):
        r = extract_first_table_from_sql("select id from MySchema.MyTable")
        assert r == {"schema": "MySchema", "table": "MyTable"}

    def test_join_picks_main_from(self):
        # Birden fazla FROM varsa son tabloyu döndürür (CTE'lerde main SELECT genelde sonda)
        r = extract_first_table_from_sql(
            "WITH x AS (SELECT * FROM aux_table) SELECT * FROM main_table JOIN x ON x.id=main_table.id"
        )
        assert r is not None
        assert r["table"] in ("main_table", "aux_table")  # last match heuristic

    def test_empty_or_invalid(self):
        assert extract_first_table_from_sql("") is None
        assert extract_first_table_from_sql(None) is None
        assert extract_first_table_from_sql("DELETE WHERE x=1") is None

    def test_not_a_string(self):
        assert extract_first_table_from_sql(123) is None
        assert extract_first_table_from_sql([]) is None


# ----------------------------------------------------------------------
# pick_top_table_for_preview
# ----------------------------------------------------------------------

class TestPickTopTable:

    def test_selected_tables_priority(self):
        state = {
            "selected_tables": [{"schema_name": "public", "table_name": "orders"}],
            "ranked_candidates": [{"schema_name": "other", "table_name": "users"}],
        }
        assert pick_top_table_for_preview(state) == {"schema": "public", "table": "orders"}

    def test_ranked_candidates_fallback(self):
        state = {
            "ranked_candidates": [{"schema_name": "app", "table_name": "products"}],
        }
        assert pick_top_table_for_preview(state) == {"schema": "app", "table": "products"}

    def test_alternative_key_names(self):
        # 'table' / 'schema' anahtarları da desteklenir
        state = {"selected_tables": [{"schema": "x", "table": "y"}]}
        assert pick_top_table_for_preview(state) == {"schema": "x", "table": "y"}

    def test_object_name_key(self):
        state = {"ranked_candidates": [{"schema_name": None, "object_name": "raw_tbl"}]}
        assert pick_top_table_for_preview(state) == {"schema": None, "table": "raw_tbl"}

    def test_empty_state(self):
        assert pick_top_table_for_preview({}) is None
        assert pick_top_table_for_preview(None) is None  # type: ignore

    def test_missing_table_name(self):
        # Tablo adı yoksa None
        state = {"selected_tables": [{"schema_name": "x"}]}
        assert pick_top_table_for_preview(state) is None


# ----------------------------------------------------------------------
# build_sample_preview
# ----------------------------------------------------------------------

class TestBuildSamplePreview:

    def test_cache_hit_with_schema(self):
        sample = [
            {"id": 1, "name": "Ali"},
            {"id": 2, "name": "Veli"},
        ]
        cur = _MockCursor([
            {
                "sample_data": sample,
                "row_count": 2,
                "fetched_at": datetime(2026, 5, 18, 12, 0, 0),
                "columns_json": [
                    {"name": "id", "type": "integer"},
                    {"name": "name", "type": "varchar"},
                ],
                "schema_name": "public",
                "object_name": "users",
            },
            # ds_table_enrichments lookup → business_name_tr
            {"business_name_tr": "Kullanıcılar"},
        ])

        result = build_sample_preview(cur, source_id=5, schema="public", table="users", limit=5)

        assert result is not None
        assert result["schema"] == "public"
        assert result["table"] == "users"
        assert result["business_name_tr"] == "Kullanıcılar"
        assert result["row_count"] == 2
        assert result["cached"] is True
        assert len(result["rows"]) == 2
        assert result["rows"][0]["name"] == "Ali"
        assert result["columns"] == [
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "varchar"},
        ]
        # fetched_at ISO format string olmalı
        assert isinstance(result["fetched_at"], str)
        assert "2026-05-18" in result["fetched_at"]

    def test_cache_hit_null_schema(self):
        cur = _MockCursor([
            {
                "sample_data": [{"x": 1}],
                "row_count": 1,
                "fetched_at": None,
                "columns_json": [{"name": "x", "type": "int"}],
                "schema_name": None,
                "object_name": "tbl",
            },
            None,  # enrichment yok
        ])
        result = build_sample_preview(cur, source_id=1, schema=None, table="tbl")
        assert result is not None
        assert result["schema"] is None
        assert result["business_name_tr"] is None
        assert result["fetched_at"] is None

    def test_cache_miss(self):
        cur = _MockCursor([None])
        result = build_sample_preview(cur, source_id=1, schema="public", table="missing")
        assert result is None

    def test_empty_table_name(self):
        cur = _MockCursor([])
        assert build_sample_preview(cur, source_id=1, schema=None, table="") is None
        assert build_sample_preview(cur, source_id=1, schema=None, table=None) is None  # type: ignore

    def test_limit_clamping(self):
        sample = [{"i": i} for i in range(20)]
        cur = _MockCursor([
            {
                "sample_data": sample,
                "row_count": 20,
                "fetched_at": None,
                "columns_json": [{"name": "i", "type": "int"}],
                "schema_name": "public",
                "object_name": "big",
            },
            None,
        ])
        # limit=3 → sadece 3 satır
        r = build_sample_preview(cur, source_id=1, schema="public", table="big", limit=3)
        assert r is not None
        assert len(r["rows"]) == 3

    def test_limit_clamped_to_max(self):
        # limit=999 → 50 cap
        sample = [{"i": i} for i in range(100)]
        cur = _MockCursor([
            {
                "sample_data": sample,
                "row_count": 100,
                "fetched_at": None,
                "columns_json": [{"name": "i", "type": "int"}],
                "schema_name": "public",
                "object_name": "big",
            },
            None,
        ])
        r = build_sample_preview(cur, source_id=1, schema="public", table="big", limit=999)
        assert r is not None
        assert len(r["rows"]) == 50

    def test_columns_fallback_from_rows(self):
        # columns_json boşsa, sample data'nın ilk satırından kolon çıkar
        cur = _MockCursor([
            {
                "sample_data": [{"a": 1, "b": 2}],
                "row_count": 1,
                "fetched_at": None,
                "columns_json": None,
                "schema_name": "public",
                "object_name": "t",
            },
            None,
        ])
        r = build_sample_preview(cur, source_id=1, schema="public", table="t")
        assert r is not None
        col_names = sorted([c["name"] for c in r["columns"]])
        assert col_names == ["a", "b"]

    def test_invalid_sample_data_falls_back(self):
        # sample_data list değilse boş array kabul edilir
        cur = _MockCursor([
            {
                "sample_data": "not a list",
                "row_count": 0,
                "fetched_at": None,
                "columns_json": [{"name": "x", "type": "int"}],
                "schema_name": None,
                "object_name": "t",
            },
            None,
        ])
        r = build_sample_preview(cur, source_id=1, schema=None, table="t")
        assert r is not None
        assert r["rows"] == []

    def test_enrichment_lookup_error_graceful(self):
        # Enrichment query exception atarsa label None ile devam
        class _ErrorAfterCursor:
            def __init__(self):
                self.calls = 0

            def execute(self, sql, params=None):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("enrichment table missing")

            def fetchone(self):
                if self.calls == 1:
                    return {
                        "sample_data": [{"x": 1}],
                        "row_count": 1,
                        "fetched_at": None,
                        "columns_json": [{"name": "x", "type": "int"}],
                        "schema_name": "s",
                        "object_name": "t",
                    }
                return None

        cur = _ErrorAfterCursor()
        r = build_sample_preview(cur, source_id=1, schema="s", table="t")
        assert r is not None
        assert r["business_name_tr"] is None  # graceful fallback


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
