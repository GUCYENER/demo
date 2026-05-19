"""VYRA v3.28.0 — Synthetic DB Q/SQL Pair Generator Tests (G2).

Test stratejisi:
- LLM çağrısı `llm_func` injection ile mock'lanır
- EmbeddingManager `embedding_manager` injection ile mock'lanır
- DB cursor için tablo-bazlı script'li `_MockCursor` kullanılır
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ml import synthetic_db_query_pairs as sqp
from app.services.ml.synthetic_db_query_pairs import (
    _canonical_sql,
    _cosine,
    _jaccard,
    _parse_embedding_field,
    _parse_llm_pairs,
    _schema_signature,
    _sql_hash,
    generate_db_query_pairs,
    get_budget_state,
    reset_budget_state,
)


# ============================================================
# Pure-function tests
# ============================================================

class TestCanonicalSql:
    def test_whitespace_normalize(self):
        assert _canonical_sql("SELECT  *  FROM   t") == "select * from t"

    def test_trailing_semicolon(self):
        assert _canonical_sql("SELECT 1;") == "select 1"
        assert _canonical_sql("SELECT 1 ; ") == "select 1"

    def test_empty(self):
        assert _canonical_sql("") == ""
        assert _canonical_sql("   ") == ""

    def test_hash_stable_under_whitespace(self):
        assert _sql_hash("SELECT * FROM t") == _sql_hash("select *   from t;")


class TestSchemaSignature:
    def test_alphabetical(self):
        sig = _schema_signature([("public", "users"), ("public", "accounts")])
        assert sig == "public.accounts,public.users"

    def test_dedupe(self):
        sig = _schema_signature([("public", "t"), ("public", "t")])
        assert sig == "public.t"

    def test_empty_schema(self):
        sig = _schema_signature([("", "t")])
        assert sig == "t"


class TestJaccard:
    def test_identical(self):
        assert _jaccard("a,b", "a,b") == 1.0

    def test_partial(self):
        # {a,b} ∩ {b,c} = {b}, union = {a,b,c} -> 1/3
        assert abs(_jaccard("a,b", "b,c") - 1/3) < 1e-9

    def test_disjoint(self):
        assert _jaccard("a", "b") == 0.0

    def test_both_empty(self):
        assert _jaccard("", "") == 1.0


class TestCosine:
    def test_orthogonal(self):
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_parallel(self):
        assert abs(_cosine([1.0, 0.0], [2.0, 0.0]) - 1.0) < 1e-9

    def test_empty(self):
        assert _cosine([], [1.0]) == 0.0

    def test_zero_vector(self):
        assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestParseEmbedding:
    def test_list_passthrough(self):
        assert _parse_embedding_field([0.1, 0.2]) == [0.1, 0.2]

    def test_pgvector_text(self):
        assert _parse_embedding_field("[0.1, 0.2, 0.3]") == [0.1, 0.2, 0.3]

    def test_none(self):
        assert _parse_embedding_field(None) is None

    def test_invalid(self):
        assert _parse_embedding_field("not-vector") is None


class TestParseLLMPairs:
    def test_clean_json(self):
        raw = '[{"question": "Kaç ürün var?", "sql": "SELECT COUNT(*) FROM products", "intent": "aggregate"}]'
        pairs = _parse_llm_pairs(raw)
        assert len(pairs) == 1
        assert pairs[0]["question"] == "Kaç ürün var?"
        assert pairs[0]["intent"] == "aggregate"

    def test_markdown_fence(self):
        raw = '```json\n[{"question": "test soru", "sql": "SELECT 1", "intent": "lookup"}]\n```'
        pairs = _parse_llm_pairs(raw)
        assert len(pairs) == 1

    def test_extra_text(self):
        raw = 'Here you go:\n[{"question": "test soru", "sql": "SELECT 1"}]\nThanks'
        pairs = _parse_llm_pairs(raw)
        assert len(pairs) == 1
        assert pairs[0]["intent"] == "lookup"  # default

    def test_invalid_intent_fallback(self):
        raw = '[{"question": "test soru", "sql": "SELECT 1", "intent": "weird_intent"}]'
        pairs = _parse_llm_pairs(raw)
        assert pairs[0]["intent"] == "lookup"

    def test_filter_short_items(self):
        raw = '[{"question": "ab", "sql": "X"}, {"question": "valid soru", "sql": "SELECT 1"}]'
        pairs = _parse_llm_pairs(raw)
        assert len(pairs) == 1
        assert pairs[0]["question"] == "valid soru"

    def test_empty_raw(self):
        assert _parse_llm_pairs("") == []
        assert _parse_llm_pairs("no json here") == []

    def test_sql_query_alias(self):
        # LLM bazen "sql_query" alanı kullanabilir
        raw = '[{"question": "kaç sipariş?", "sql_query": "SELECT count(*) FROM orders"}]'
        pairs = _parse_llm_pairs(raw)
        assert len(pairs) == 1
        assert pairs[0]["sql"] == "SELECT count(*) FROM orders"


# ============================================================
# Budget tests
# ============================================================

class TestBudget:
    def setup_method(self, _):
        reset_budget_state()

    def test_initial_state(self):
        st = get_budget_state()
        assert st["calls"] == 0
        assert st["estimated_cost_usd"] == 0.0

    def test_budget_exceeded(self):
        ok, msg = sqp._check_budget(max_daily_usd=0.0001, n_calls_planned=1)
        assert ok is False
        assert "daily_budget_exceeded" in msg

    def test_budget_ok(self):
        ok, msg = sqp._check_budget(max_daily_usd=10.0, n_calls_planned=1)
        assert ok is True

    def test_record_increments(self):
        sqp._record_call()
        sqp._record_call()
        assert get_budget_state()["calls"] == 2


# ============================================================
# Mock cursor & end-to-end generate_db_query_pairs
# ============================================================

class _DictRow(dict):
    def get(self, k, default=None):
        return super().get(k, default)


class _MockCursor:
    """
    SQL prefix'e göre fetchall/fetchone döner.
    `script` = list of (sql_prefix, fetchall_rows) — sıralı match.
    """

    def __init__(self, script: List[Sequence[Any]]):
        self._script = list(script)
        self._last_rows: List[Dict[str, Any]] = []
        self._last_one: Optional[Dict[str, Any]] = None
        self.inserted_rows: List[tuple] = []

    def execute(self, sql, params=None):
        sql_norm = " ".join(sql.strip().split()).lower()
        # INSERT yakala
        if sql_norm.startswith("insert into few_shot_examples"):
            self.inserted_rows.append(params)
            self._last_rows = []
            self._last_one = None
            return
        # Sıradaki script item ile match et (prefix)
        for i, (prefix, rows) in enumerate(self._script):
            if sql_norm.startswith(prefix.lower()):
                self._last_rows = [_DictRow(r) for r in rows]
                self._last_one = self._last_rows[0] if self._last_rows else None
                # Bu adımı tüket
                self._script.pop(i)
                return
        # Match yok → boş
        self._last_rows = []
        self._last_one = None

    def fetchall(self):
        return self._last_rows

    def fetchone(self):
        return self._last_one


class _FakeEmbedding:
    def get_embedding(self, text):
        # Sabit-uzunluk basit hash → deterministic vektör
        h = abs(hash(text))
        return [(h >> (i * 4)) & 0xF for i in range(8)]


def _fake_llm_func(messages, temperature):
    return json.dumps([
        {"question": "Kaç müşteri var?", "sql": "SELECT COUNT(*) FROM customers", "intent": "aggregate"},
        {"question": "İlk müşteri kim?", "sql": "SELECT * FROM customers ORDER BY id LIMIT 1", "intent": "lookup"},
    ])


def _build_script_basic() -> List[Sequence[Any]]:
    """Standart end-to-end senaryo: 1 onaylı tablo, no existing few-shots."""
    return [
        # 1. Approved tables
        (
            "select te.id as te_id, te.schema_name, te.table_name,",
            [{
                "te_id": 1,
                "schema_name": "public",
                "table_name": "customers",
                "admin_label_tr": "Müşteriler",
                "business_name_tr": "Müşteri",
                "description_tr": "Müşteri tablosu",
            }],
        ),
        # 2. db_type
        ("select db_type from data_sources", [{"db_type": "postgresql"}]),
        # 3. ds_db_objects
        (
            "select schema_name, object_name, columns_json",
            [{
                "schema_name": "public",
                "object_name": "customers",
                "columns_json": json.dumps([
                    {"name": "id", "data_type": "int", "is_pk": True},
                    {"name": "name", "data_type": "varchar"},
                ]),
            }],
        ),
        # 4. ds_db_samples
        ("select o.object_name, s.sample_data", []),
        # 5. ds_db_relationships
        ("select from_schema, from_table, from_column,", []),
        # 6. existing few_shot_examples
        ("select id, question, sql_query, intent, schema_signature, embedding", []),
    ]


class TestGenerateE2E:
    def setup_method(self, _):
        reset_budget_state()

    def test_basic_generation_inserts(self):
        cur = _MockCursor(_build_script_basic())
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            target_count=10,
            batch_size=5,
            dry_run=False,
            created_by=99,
            llm_func=_fake_llm_func,
            embedding_manager=_FakeEmbedding(),
            max_daily_budget_usd=10.0,
        )
        assert res["success"] is True
        assert res["generated"] == 2
        assert res["inserted"] == 2
        assert res["tables_processed"] == 1
        assert res["llm_calls_used"] == 1
        assert len(cur.inserted_rows) == 2
        # company_id ve source_id doğru bind edilmiş mi
        first = cur.inserted_rows[0]
        assert first[0] == 42  # company_id
        assert first[1] == 1  # source_id

    def test_dry_run_no_insert(self):
        cur = _MockCursor(_build_script_basic())
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            dry_run=True,
            llm_func=_fake_llm_func,
            embedding_manager=_FakeEmbedding(),
            max_daily_budget_usd=10.0,
        )
        assert res["success"] is True
        assert res["dry_run"] is True
        assert res["inserted"] == 0
        assert len(cur.inserted_rows) == 0
        assert "pairs" in res
        assert len(res["pairs"]) == 2

    def test_no_approved_tables(self):
        cur = _MockCursor([
            ("select te.id as te_id, te.schema_name, te.table_name,", []),
        ])
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            llm_func=_fake_llm_func,
        )
        assert res["success"] is False
        assert res["error"] == "no_approved_tables"
        assert res["generated"] == 0

    def test_l1_dedupe_sql_hash(self):
        """Mevcut few_shot_examples'da aynı SQL hash varsa skip."""
        script = _build_script_basic()
        # existing few-shots adımını güncelle: aynı SQL'i koy
        same_sql_hash_row = {
            "id": 1,
            "question": "Önceki soru",
            "sql_query": "SELECT COUNT(*) FROM customers",
            "intent": "aggregate",
            "schema_signature": "public.customers",
            "embedding": None,
        }
        for i, (p, _r) in enumerate(script):
            if p.startswith("select id, question, sql_query"):
                script[i] = (p, [same_sql_hash_row])
                break
        cur = _MockCursor(script)
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            llm_func=_fake_llm_func,
            embedding_manager=_FakeEmbedding(),
            max_daily_budget_usd=10.0,
        )
        # 2 pair üretildi; biri L1'de dropped
        assert res["skipped_l1_sql_hash"] == 1
        assert res["generated"] == 1
        assert res["inserted"] == 1

    def test_budget_blocks_calls(self):
        """Çok düşük bütçe LLM'den önce kesmeli."""
        cur = _MockCursor(_build_script_basic())
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            llm_func=_fake_llm_func,
            embedding_manager=_FakeEmbedding(),
            max_daily_budget_usd=0.00001,
        )
        # Bütçe sıfıra yakın → tablo döngüsü erken kesilir
        assert res["llm_calls_used"] == 0
        assert res["generated"] == 0
        assert "budget" in (res.get("error") or "")

    def test_llm_error_continues(self):
        """LLM hatası tablo bazında counter artırmalı, exception fırlatmamalı."""
        def _bad_llm(messages, temperature):
            raise RuntimeError("LLM gateway down")

        cur = _MockCursor(_build_script_basic())
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            llm_func=_bad_llm,
            embedding_manager=_FakeEmbedding(),
            max_daily_budget_usd=10.0,
        )
        assert res["success"] is True
        assert res["llm_errors"] == 1
        assert res["generated"] == 0
        assert res["inserted"] == 0

    def test_unknown_dialect_falls_back(self):
        script = _build_script_basic()
        for i, (p, _r) in enumerate(script):
            if p.startswith("select db_type"):
                script[i] = (p, [{"db_type": "cassandra"}])
                break
        cur = _MockCursor(script)
        res = generate_db_query_pairs(
            cur,
            source_id=1,
            company_id=42,
            llm_func=_fake_llm_func,
            embedding_manager=_FakeEmbedding(),
            max_daily_budget_usd=10.0,
        )
        assert res["dialect"] == "postgresql"


# ============================================================
# Run as script
# ============================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
