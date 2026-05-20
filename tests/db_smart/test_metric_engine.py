"""metric_engine.py — applicable_when match + skor sıralama
(v3.30.0 FAZ 1 P3 G1.4)."""
from __future__ import annotations

from typing import Any, List

import pytest

from app.services.db_smart import metric_engine as me


# ─────────────────────────────────────────────────────────────
# Cursor mock — eligibility test'iyle aynı pattern
# ─────────────────────────────────────────────────────────────

class _SeqCursor:
    """Sırayla execute() yanıtlarını fetchone/fetchall'a aktarır."""

    def __init__(self, responses: List[Any]):
        self._resps = responses
        self._idx = 0
        self._last = None

    def execute(self, sql, params=None):
        if self._idx < len(self._resps):
            self._last = self._resps[self._idx]
            self._idx += 1
        else:
            self._last = None

    def fetchone(self):
        if isinstance(self._last, list) and self._last:
            return self._last[0]
        return self._last

    def fetchall(self):
        if isinstance(self._last, list):
            return self._last
        return [self._last] if self._last else []


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def helpdesk_columns():
    return [
        {"name": "id", "data_type": "integer", "semantic_type": "id"},
        {"name": "created_at", "data_type": "timestamp", "semantic_type": "date"},
        {"name": "closed_at", "data_type": "timestamp", "semantic_type": "date"},
        {"name": "status", "data_type": "varchar", "semantic_type": "status"},
        {"name": "priority", "data_type": "varchar", "semantic_type": "code"},
        {"name": "team", "data_type": "varchar", "semantic_type": "name"},
        {"name": "sla_deadline", "data_type": "timestamp", "semantic_type": "date"},
        {"name": "first_response_at", "data_type": "timestamp", "semantic_type": "date"},
    ]


@pytest.fixture
def sales_columns():
    return [
        {"name": "id", "data_type": "integer", "semantic_type": "id"},
        {"name": "customer_id", "data_type": "integer", "semantic_type": "id"},
        {"name": "product_id", "data_type": "integer", "semantic_type": "id"},
        {"name": "amount", "data_type": "numeric", "semantic_type": "amount"},
        {"name": "order_date", "data_type": "date", "semantic_type": "date"},
        {"name": "city", "data_type": "varchar", "semantic_type": "name"},
    ]


@pytest.fixture
def helpdesk_signature(helpdesk_columns):
    return {
        "table_id": 10,
        "schema_name": "public",
        "object_name": "tickets",
        "row_count": 500,
        "columns": helpdesk_columns,
    }


# ─────────────────────────────────────────────────────────────
# _check_applicable
# ─────────────────────────────────────────────────────────────

def test_applicable_no_constraints_passes(helpdesk_signature):
    ok, strength, b = me._check_applicable({}, helpdesk_signature)
    assert ok is True
    assert strength >= 0.0
    assert b == {}


def test_requires_columns_all_match(helpdesk_signature):
    aw = {"requires_columns": ["created_at", "status", "priority"]}
    ok, strength, b = me._check_applicable(aw, helpdesk_signature)
    assert ok
    assert "created_at" in b and "status" in b and "priority" in b


def test_requires_columns_missing_blocks(helpdesk_signature):
    # 'amount' yok (helpdesk'te değil)
    aw = {"requires_columns": ["created_at", "amount"]}
    ok, _, _ = me._check_applicable(aw, helpdesk_signature)
    assert not ok


def test_table_hints_match_bonus(helpdesk_signature):
    aw = {"requires_columns": ["created_at"], "table_hints": ["ticket"]}
    ok, strength, _ = me._check_applicable(aw, helpdesk_signature)
    assert ok
    # bonus 0.2 ekleniyor → base 0.6 + 0.2 = 0.8
    assert strength == pytest.approx(0.8)


def test_table_hints_mismatch_blocks(helpdesk_signature):
    aw = {"requires_columns": ["created_at"], "table_hints": ["order", "invoice"]}
    ok, _, _ = me._check_applicable(aw, helpdesk_signature)
    assert not ok  # hint var ama eşleşmiyor → False


def test_min_rows_gate(helpdesk_columns):
    sig_tiny = {"object_name": "t", "row_count": 5, "columns": helpdesk_columns}
    aw = {"requires_columns": ["created_at"], "min_rows": 30}
    ok, _, _ = me._check_applicable(aw, sig_tiny)
    assert not ok


def test_cardinality_max_heuristic_low_card(helpdesk_signature):
    # status semantic'i düşük cardinality varsayımı → cardinality_max=10 geçer
    aw = {"requires_columns": ["status"], "cardinality_max": 10}
    ok, _, _ = me._check_applicable(aw, helpdesk_signature)
    assert ok


def test_cardinality_max_no_low_card_col_blocks():
    sig = {
        "object_name": "t",
        "row_count": 100,
        "columns": [
            {"name": "id", "data_type": "integer", "semantic_type": "id"},
            {"name": "name", "data_type": "varchar", "semantic_type": "name"},
        ],
    }
    aw = {"requires_columns": ["dimension_any"], "cardinality_max": 10}
    ok, _, _ = me._check_applicable(aw, sig)
    assert not ok  # status/flag/code yok → low-card kolon yok


# ─────────────────────────────────────────────────────────────
# Semantic tag matchers
# ─────────────────────────────────────────────────────────────

def test_matcher_measure_numeric(sales_columns):
    c = me._match_required_tag("measure_numeric", sales_columns)
    assert c is not None and c["name"] == "amount"


def test_matcher_customer_id(sales_columns):
    c = me._match_required_tag("customer_id", sales_columns)
    assert c is not None and "customer" in c["name"]


def test_matcher_closed_at(helpdesk_columns):
    c = me._match_required_tag("closed_at", helpdesk_columns)
    assert c is not None and c["name"] == "closed_at"


def test_matcher_unknown_tag_fallback_substring(helpdesk_columns):
    # 'team' tag SEMANTIC_TAG_MATCHERS'ta yok → kolon adı substring fallback
    c = me._match_required_tag("team", helpdesk_columns)
    assert c is not None and c["name"] == "team"


def test_matcher_any_returns_first_col(helpdesk_columns):
    c = me._match_required_tag("any", helpdesk_columns)
    assert c is not None  # 'any' her zaman ilk kolonu döner


def test_matcher_created_at_requires_date_semantic():
    cols = [{"name": "created_at", "data_type": "varchar", "semantic_type": "other"}]
    # date semantic'i yok → matcher reddetmeli
    c = me._match_required_tag("created_at", cols)
    assert c is None


# ─────────────────────────────────────────────────────────────
# Usage normalization
# ─────────────────────────────────────────────────────────────

def test_usage_norm_zero():
    assert me._usage_norm(0) == 0.0
    assert me._usage_norm(None) == 0.0
    assert me._usage_norm(-1) == 0.0


def test_usage_norm_caps_at_one():
    assert me._usage_norm(10000) == 1.0


def test_usage_norm_monotonic():
    assert me._usage_norm(1) < me._usage_norm(10) < me._usage_norm(100)


# ─────────────────────────────────────────────────────────────
# load_table_signature
# ─────────────────────────────────────────────────────────────

def test_load_table_signature_not_found(fake_user_ctx):
    cur = _SeqCursor([None])
    out = me.load_table_signature(cur, source_id=1, table_id=999)
    assert out is None


def test_load_table_signature_with_enrichment(fake_user_ctx):
    # 1) ds_db_objects row
    obj_row = (10, "public", "tickets", 500, [
        {"name": "id", "type": "integer"},
        {"name": "created_at", "type": "timestamp"},
    ])
    # 2) enrichment join rows
    enrich_rows = [
        ("id", "id", "Bilet No"),
        ("created_at", "date", "Olusturma Tarihi"),
    ]
    cur = _SeqCursor([obj_row, enrich_rows])
    sig = me.load_table_signature(cur, source_id=1, table_id=10)
    assert sig is not None
    assert sig["object_name"] == "tickets"
    assert sig["row_count"] == 500
    sem_by_name = {c["name"]: c["semantic_type"] for c in sig["columns"]}
    assert sem_by_name["id"] == "id"
    assert sem_by_name["created_at"] == "date"


def test_load_table_signature_no_enrichment_uses_infer(fake_user_ctx):
    obj_row = (10, "public", "items", 100, [
        {"name": "qty", "type": "integer"},
        {"name": "active", "type": "boolean"},
    ])
    # enrichment JOIN fail (exception silinir) ya da boş — boş döndürelim
    cur = _SeqCursor([obj_row, []])
    sig = me.load_table_signature(cur, source_id=1, table_id=10)
    assert sig is not None
    sem_by_name = {c["name"]: c["semantic_type"] for c in sig["columns"]}
    # _infer_semantic_from_type → int → amount, bool → flag
    assert sem_by_name["qty"] == "amount"
    assert sem_by_name["active"] == "flag"


def test_infer_semantic_from_type():
    assert me._infer_semantic_from_type("timestamp") == "date"
    assert me._infer_semantic_from_type("DATE") == "date"
    assert me._infer_semantic_from_type("integer") == "amount"
    assert me._infer_semantic_from_type("numeric(18,2)") == "amount"
    assert me._infer_semantic_from_type("boolean") == "flag"
    assert me._infer_semantic_from_type("varchar(255)") == "other"
    assert me._infer_semantic_from_type(None) == "other"


# ─────────────────────────────────────────────────────────────
# list_eligible — end-to-end (fake cursor)
# ─────────────────────────────────────────────────────────────

def _metric_row(metric_key, name_tr, category, sub, desc, viz, aw, tmpl, usage=0, success=None):
    return (metric_key, name_tr, category, sub, desc, viz, aw, tmpl, usage, success)


def test_list_eligible_filters_by_score(fake_user_ctx, helpdesk_signature):
    # 3 metrik: 1'i helpdesk (eşleşir), 1'i sales (table_hints fail), 1'i generic (eşleşir)
    metrics = [
        _metric_row(
            "helpdesk.oldest_open", "En Eski Açık", "helpdesk", "ranking", "...", "table",
            {"requires_columns": ["created_at", "status"], "table_hints": ["ticket"]},
            {"postgresql": "SELECT 1"},
            usage=50,
        ),
        _metric_row(
            "sales.top_customer_revenue", "Top Müşteri", "sales", "ranking", "...", "bar",
            {"requires_columns": ["customer_id", "amount"], "table_hints": ["order", "invoice"]},
            {"postgresql": "SELECT 2"},
            usage=10,
        ),
        _metric_row(
            "generic.time_series_count", "Trend", "generic", "trend", "...", "line",
            {"requires_columns": ["date_column"], "min_rows": 30},
            {"postgresql": "SELECT 3"},
            usage=0,
        ),
    ]
    # 1) metric list, 2) user_pref lookup (boş)
    cur = _SeqCursor([metrics, None])
    # min_score=0.0 — table_hints fail eden 'sales' filtrelenir; diğer ikisi geçer
    out = me.list_eligible(cur, helpdesk_signature, fake_user_ctx, min_score=0.0)
    keys = [m["metric_key"] for m in out]
    assert "helpdesk.oldest_open" in keys
    assert "generic.time_series_count" in keys
    assert "sales.top_customer_revenue" not in keys  # table_hints fail


def test_list_eligible_sorted_desc(fake_user_ctx, helpdesk_signature):
    metrics = [
        _metric_row(
            "low_usage", "Low", "helpdesk", None, "", "table",
            {"requires_columns": ["created_at", "status"], "table_hints": ["ticket"]},
            {"postgresql": "X"},
            usage=0,
        ),
        _metric_row(
            "high_usage", "High", "helpdesk", None, "", "table",
            {"requires_columns": ["created_at", "status"], "table_hints": ["ticket"]},
            {"postgresql": "X"},
            usage=100,
        ),
    ]
    cur = _SeqCursor([metrics, None])
    out = me.list_eligible(cur, helpdesk_signature, fake_user_ctx, min_score=0.0)
    assert len(out) == 2
    assert out[0]["metric_key"] == "high_usage"  # daha yüksek usage_norm
    assert out[1]["metric_key"] == "low_usage"


def test_list_eligible_min_score_filter(fake_user_ctx, helpdesk_signature):
    metrics = [
        _metric_row(
            "weak", "Weak", "generic", None, "", "table",
            {"requires_columns": ["any"]},  # strength=0.6 base, usage=0, user_pref=0 → score=0.3
            {"postgresql": "X"},
            usage=0,
        ),
    ]
    cur = _SeqCursor([metrics, None])
    # min_score=0.5 → weak'i filtreler (0.3 < 0.5)
    out = me.list_eligible(cur, helpdesk_signature, fake_user_ctx, min_score=0.5)
    assert out == []


def test_list_eligible_user_pref_boost(fake_user_ctx, helpdesk_signature):
    metrics = [
        _metric_row(
            "fav_metric", "Favori", "helpdesk", None, "", "table",
            {"requires_columns": ["created_at"], "table_hints": ["ticket"]},
            {"postgresql": "X"},
            usage=0,
        ),
    ]
    # user_pref lookup → metric_key 'fav_metric' içeren list
    cur = _SeqCursor([metrics, (["fav_metric"],)])
    out = me.list_eligible(cur, helpdesk_signature, fake_user_ctx, min_score=0.5)
    assert out and out[0]["metric_key"] == "fav_metric"
    # user_pref boost: 0.2 → strength*0.5 + 0 + 1.0*0.2 = 0.4+0.2 = 0.6 minimum
    assert out[0]["score"] >= 0.6


def test_list_eligible_returns_empty_on_no_match(fake_user_ctx):
    # Tablo helpdesk, metrikler sales → tek bir tane bile geçmeyecek
    sig = {
        "object_name": "tickets",
        "row_count": 100,
        "columns": [
            {"name": "id", "data_type": "integer", "semantic_type": "id"},
            {"name": "created_at", "data_type": "timestamp", "semantic_type": "date"},
            {"name": "status", "data_type": "varchar", "semantic_type": "status"},
        ],
    }
    metrics = [
        _metric_row(
            "sales.top", "Top", "sales", None, "", "bar",
            {"requires_columns": ["customer_id", "amount"], "table_hints": ["order"]},
            {"postgresql": "X"},
        ),
    ]
    cur = _SeqCursor([metrics, None])
    out = me.list_eligible(cur, sig, fake_user_ctx, min_score=0.0)
    assert out == []


# ─────────────────────────────────────────────────────────────
# get_template / record_usage
# ─────────────────────────────────────────────────────────────

def test_get_template_found():
    row = ("k.t", "table", {"requires_columns": []}, {"postgresql": "SELECT 1", "mysql": "SELECT 1"})
    cur = _SeqCursor([row])
    tpl = me.get_template(cur, "k.t", "postgresql")
    assert tpl is not None
    assert tpl["sql_template"] == "SELECT 1"
    assert tpl["dialect"] == "postgresql"


def test_get_template_missing_dialect():
    row = ("k.t", "table", {}, {"oracle": "SELECT 1"})
    cur = _SeqCursor([row])
    tpl = me.get_template(cur, "k.t", "mssql")
    assert tpl is None  # mssql template yok


def test_get_template_not_found():
    cur = _SeqCursor([None])
    tpl = me.get_template(cur, "nonexistent", "postgresql")
    assert tpl is None


class _RecCursor:
    """record_usage UPDATE'i hata atmazsa kabul edilir; çağrı sayısı sayar."""
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
    def execute(self, sql, params=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated")


def test_record_usage_silent_on_failure(fake_user_ctx):
    cur = _RecCursor(fail=True)
    # Hata yutulmalı (telemetri kritik path'i bloklamasın)
    me.record_usage(cur, "k.t", success=True, user_ctx=fake_user_ctx)
    assert cur.calls == 1


def test_record_usage_calls_update(fake_user_ctx):
    cur = _RecCursor()
    me.record_usage(cur, "k.t", success=False, user_ctx=fake_user_ctx)
    assert cur.calls == 1
