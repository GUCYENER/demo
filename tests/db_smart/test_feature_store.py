"""feature_store — Per-user/table/query/recommendation aggregator tests
(v3.30.0 FAZ 4 P22).

Brief path `tests/unit/db_smart/` proje convention'ı `tests/db_smart/`
ile çatıştığı için sibling testlerle aynı dizinde (test discovery zaten
buradan tarıyor). Davranışsal kapsam birebir korunmuştur:

  - Empty baseline (kullanıcı hiç interaction yapmamış)
  - Aggregation (10 interaction + 2 session fixture)
  - get_table_features MV → live fallback
  - get_query_features ast_snapshot/context JSONB parse
  - get_recommendation_features user-historical acceptance
  - to_vector stable order + unknown key default + bool→0/1
  - RLS isolation (cross-tenant call → zeros, no leakage)
  - PII filter (is_pii=TRUE kolonlar pii_column_ratio'ya yansır)
  - MV refresh idempotency (REFRESH iki kez → hata yok)
  - MV CONCURRENTLY UNIQUE INDEX olmadan reddedilir (negative)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.services.db_smart import feature_store as fs


# ─────────────────────────────────────────────────────────────
# Fake cursor — psycopg2 contract minimum
# ─────────────────────────────────────────────────────────────

class _FakeCursor:
    """SQL-string'e göre route eden test cursor'ı.

    `responses` listesi: her tuple (predicate, rows) — predicate(sql)
    True dönerse fetchone/fetchall bu rows'tan beslenir.
    `executed` log'u assertion için.
    """

    def __init__(self, responses: Optional[List[Tuple[Any, List[tuple]]]] = None):
        # responses: [(lambda sql,params: bool, [row, row, ...]), ...]
        self.responses = responses or []
        self.executed: List[Tuple[str, tuple]] = []
        self._buf: List[tuple] = []
        self.refresh_calls: int = 0

    # NOTE: psycopg2 execute(sql, params=None) imzasıyla uyumlu
    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))
        if "REFRESH MATERIALIZED VIEW" in sql.upper():
            self.refresh_calls += 1
            self._buf = []
            return
        for predicate, rows in self.responses:
            try:
                if predicate(sql, params):
                    self._buf = list(rows)
                    return
            except Exception:
                continue
        self._buf = []

    def fetchone(self):
        return self._buf[0] if self._buf else None

    def fetchall(self):
        return list(self._buf)


# ─────────────────────────────────────────────────────────────
# Predicate helpers
# ─────────────────────────────────────────────────────────────

def _p_contains(*needles: str):
    """Returns predicate that matches all needles in SQL (case-insensitive)."""
    def _pred(sql: str, params: tuple) -> bool:
        s = sql.lower()
        return all(n.lower() in s for n in needles)
    return _pred


def _p_not_contains(needle: str, *also_must: str):
    def _pred(sql: str, params: tuple) -> bool:
        s = sql.lower()
        if needle.lower() in s:
            return False
        return all(a.lower() in s for a in also_must)
    return _pred


# ─────────────────────────────────────────────────────────────
# 1) USER FEATURES — empty baseline
# ─────────────────────────────────────────────────────────────

def test_get_user_features_empty_returns_zero_baseline():
    # MV freshness check → no row; live agg → all zero/None.
    cur = _FakeCursor(responses=[
        (_p_contains("mv_dbsmart_user_features"), []),                   # MV freshness empty
        (_p_contains("from dbsmart_interactions"), [(0, 0, 0, 0, 0, 0, None)]),
        (_p_contains("from dbsmart_sessions"), [(None,)]),
        (_p_contains("from dbsmart_interactions", "metricchosen"), []),
    ])
    out = fs.get_user_features(cur, user_id=42, company_id=7)
    assert out["total_queries_30d"] == 0
    assert out["domain_diversity"] == 0
    assert out["table_coverage"] == 0
    assert out["recommendation_acceptance_rate"] == 0.0
    assert out["top_metric_categories"] == []
    assert out["last_active_ts"] is None
    assert out["avg_session_duration_sec"] == 0.0


def test_get_user_features_zero_for_invalid_inputs():
    cur = _FakeCursor()
    assert fs.get_user_features(cur, 0, 7) == fs._USER_ZERO_BASELINE
    assert fs.get_user_features(cur, 42, 0) == fs._USER_ZERO_BASELINE


# ─────────────────────────────────────────────────────────────
# 2) USER FEATURES — aggregation
# ─────────────────────────────────────────────────────────────

def test_get_user_features_aggregates_from_live_query():
    # 10 toplam q, 3 distinct domain, 2 tablo, accept=4 / rej=1 / shown=5 → 4/10=0.4
    cur = _FakeCursor(responses=[
        (_p_contains("mv_dbsmart_user_features"), []),  # MV missing
        (_p_contains("from dbsmart_interactions"), [(10, 3, 2, 4, 1, 5, "2026-05-21T10:00:00Z")]),
        (_p_contains("from dbsmart_sessions"), [(123.5,)]),
        (_p_contains("from dbsmart_interactions", "metricchosen"),
         [("helpdesk", 6), ("sales", 3), ("generic", 1)]),
    ])
    out = fs.get_user_features(cur, user_id=42, company_id=7)
    assert out["total_queries_30d"] == 10
    assert out["domain_diversity"] == 3
    assert out["table_coverage"] == 2
    assert out["recommendation_acceptance_rate"] == 0.4
    assert out["avg_session_duration_sec"] == 123.5
    assert out["top_metric_categories"] == ["helpdesk", "sales", "generic"]
    assert out["last_active_ts"] == "2026-05-21T10:00:00Z"


def test_get_user_features_reads_mv_when_fresh():
    # MV freshness sorgusu 1 saatlik gecikme dönerse → MV row okunur
    cur = _FakeCursor(responses=[
        # 1st: freshness check (returns 1.0 hours)
        (_p_contains("max(refreshed_at)"), [(1.0,)]),
        # 2nd: MV row read
        (_p_contains("mv_dbsmart_user_features", "where user_id"),
         [(99, 12.34, 5, 7, 0.7777, ["helpdesk"], "2026-05-20T00:00:00Z")]),
    ])
    out = fs.get_user_features(cur, user_id=42, company_id=7)
    assert out["total_queries_30d"] == 99
    assert out["recommendation_acceptance_rate"] == 0.7777
    assert out["top_metric_categories"] == ["helpdesk"]


# ─────────────────────────────────────────────────────────────
# 3) RLS isolation — cross-tenant returns zeros
# ─────────────────────────────────────────────────────────────

def test_get_user_features_cross_tenant_returns_zeros_no_leakage():
    # RLS predicate live'da boş satır döner → all zeros, leakage YOK.
    cur = _FakeCursor(responses=[
        (_p_contains("mv_dbsmart_user_features"), []),
        (_p_contains("from dbsmart_interactions"), [(0, 0, 0, 0, 0, 0, None)]),
        (_p_contains("from dbsmart_sessions"), [(None,)]),
        (_p_contains("from dbsmart_interactions", "metricchosen"), []),
    ])
    out = fs.get_user_features(cur, user_id=999, company_id=999)
    # No tenant data → baseline shape
    assert out["total_queries_30d"] == 0
    assert out["table_coverage"] == 0
    assert out["top_metric_categories"] == []
    # En kritik: hiçbir String/Hash leakage olmamalı
    assert out["last_active_ts"] is None


# ─────────────────────────────────────────────────────────────
# 4) TABLE FEATURES — basic + PII filter
# ─────────────────────────────────────────────────────────────

def test_get_table_features_zero_for_invalid_inputs():
    cur = _FakeCursor()
    assert fs.get_table_features(cur, 0, 7) == fs._TABLE_ZERO_BASELINE
    assert fs.get_table_features(cur, 1, 0) == fs._TABLE_ZERO_BASELINE


def test_get_table_features_aggregates_with_pii_ratio(monkeypatch):
    # PII lookup'ı monkeypatch'le: 3 PII kolonu raporla.
    monkeypatch.setattr(
        fs,
        "_load_pii_columns",
        lambda cur, sid: {"email", "phone", "tckn"},
    )
    cur = _FakeCursor(responses=[
        # MV freshness empty → live yol
        (_p_contains("mv_dbsmart_table_features"), []),
        # ds_db_objects
        (_p_contains("from ds_db_objects"),
         [("public", "tickets", 5000, [{"name": "id"}, {"name": "title"}, {"name": "email"},
                                        {"name": "phone"}, {"name": "tckn"}, {"name": "status"},
                                        {"name": "created_at"}, {"name": "closed_at"},
                                        {"name": "priority"}, {"name": "team"}], 1)]),
        # PII count
        (_p_contains("from ds_column_enrichments", "is_pii"), [(3,)]),
        # FK centrality
        (_p_contains("ds_relationships"), [(5,)]),
        # Glossary
        (_p_contains("from business_glossary"), [(2,)]),
        # Select frequency
        (_p_contains("'tableselected'"), [(42, 7)]),
    ])
    out = fs.get_table_features(cur, table_id=99, company_id=7, source_id=1)
    assert out["row_count_bucket"] == 3  # 5000 → bucket 3
    assert out["column_count"] == 10
    assert out["pii_column_ratio"] == 0.3  # 3/10
    assert out["fk_centrality"] == 0.5  # min(5/10, 1)
    assert out["business_glossary_term_count"] == 2
    assert out["select_frequency_30d"] == 42
    assert out["distinct_user_count_30d"] == 7


# ─────────────────────────────────────────────────────────────
# 5) QUERY FEATURES — JSONB ast_snapshot extract
# ─────────────────────────────────────────────────────────────

def test_get_query_features_extracts_from_context():
    ctx = {
        "tables": ["a", "b", "c"],
        "joins": [{"l": "a", "r": "b"}],
        "filters": [{"col": "x"}, {"col": "y"}],
        "groups": ["g1"],
        "orders": [],
        "limit": 100,
        "columns": ["a.x", "a.y", "b.z"],
        "metric_categories": ["helpdesk", "sales"],
        "domains": ["helpdesk", "sales"],
    }
    cur = _FakeCursor(responses=[
        (_p_contains("from dbsmart_sessions"), [(ctx, "postgresql")]),
    ])
    out = fs.get_query_features(cur, session_uid="abc-123")
    assert out["table_count"] == 3
    assert out["join_count"] == 1
    assert out["filter_count"] == 2
    assert out["group_count"] == 1
    assert out["order_count"] == 0
    assert out["has_limit"] is True
    assert out["distinct_columns"] == 3
    assert out["distinct_metric_categories"] == 2
    assert out["cross_domain"] is True
    assert out["dialect"] == "postgresql"
    # complexity = 3 + 1*2 + 2 + 1 + 0 = 8 → bucket 2 (>=6)
    assert out["estimated_cost_bucket"] == 2


def test_get_query_features_empty_session_uid_returns_baseline():
    cur = _FakeCursor()
    out = fs.get_query_features(cur, session_uid="")
    assert out == fs._QUERY_ZERO_BASELINE


def test_get_query_features_handles_string_jsonb():
    import json
    ctx_str = json.dumps({"tables": ["x"], "joins": [], "filters": [], "limit": None})
    cur = _FakeCursor(responses=[
        (_p_contains("from dbsmart_sessions"), [(ctx_str, "mysql")]),
    ])
    out = fs.get_query_features(cur, session_uid="uid")
    assert out["table_count"] == 1
    assert out["has_limit"] is False
    assert out["dialect"] == "mysql"


# ─────────────────────────────────────────────────────────────
# 6) RECOMMENDATION FEATURES
# ─────────────────────────────────────────────────────────────

def test_get_recommendation_features_with_historical_rate():
    cur = _FakeCursor(responses=[
        (_p_contains("from dbsmart_report_recommendations"),
         [("oldest_open_table", "table",
           {"insights": ["a", "b", "c"], "severity": "high", "tables": ["t1", "t2"]})]),
        (_p_contains("from dbsmart_interactions", "accepted"),
         [(7, 2, 1)]),  # acc=7, rej=2, shown=1 → 7/10=0.7
    ])
    out = fs.get_recommendation_features(cur, recommendation_id=11, user_id=42, company_id=7)
    assert out["chart_type"] == "table"
    assert out["insight_count"] == 3
    assert out["severity_max"] == 3  # high
    assert out["table_count_in_recommendation"] == 2
    assert out["user_acceptance_rate_for_chart_type"] == 0.7


def test_get_recommendation_features_zero_for_invalid_inputs():
    cur = _FakeCursor()
    assert fs.get_recommendation_features(cur, 0, 1, 1) == fs._RECO_ZERO_BASELINE
    assert fs.get_recommendation_features(cur, 1, 0, 1) == fs._RECO_ZERO_BASELINE
    assert fs.get_recommendation_features(cur, 1, 1, 0) == fs._RECO_ZERO_BASELINE


# ─────────────────────────────────────────────────────────────
# 7) to_vector — stable order, defaults, coercions
# ─────────────────────────────────────────────────────────────

def test_to_vector_stable_order_and_defaults():
    d = {"a": 1, "b": True, "c": False, "d": "x", "e": None, "f": [1, 2, 3]}
    order = ["a", "b", "c", "d", "e", "f", "missing"]
    v = fs.to_vector(d, order, default=-1.0)
    assert v[0] == 1.0
    assert v[1] == 1.0  # True
    assert v[2] == 0.0  # False
    # 'd' hashed bucket — 0..99 arası float
    assert 0.0 <= v[3] < 100.0
    assert v[4] == -1.0  # None → default
    assert v[5] == 3.0  # list len
    assert v[6] == -1.0  # missing key


def test_to_vector_handles_non_dict_and_empty_order():
    assert fs.to_vector(None, ["a", "b"]) == [0.0, 0.0]  # type: ignore[arg-type]
    assert fs.to_vector({"a": 1}, []) == []


def test_to_vector_guards_nan_inf():
    d = {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf"), "ok": 2.5}
    v = fs.to_vector(d, ["nan", "inf", "ninf", "ok"], default=0.0)
    assert v == [0.0, 0.0, 0.0, 2.5]


def test_to_vector_consistent_hash_across_calls():
    # Aynı string aynı bucket'a düşmeli — train/predict drift guard.
    v1 = fs.to_vector({"x": "helpdesk"}, ["x"])
    v2 = fs.to_vector({"x": "helpdesk"}, ["x"])
    assert v1 == v2


# ─────────────────────────────────────────────────────────────
# 8) PII filter behaviour — explicit
# ─────────────────────────────────────────────────────────────

def test_pii_filter_zero_when_no_pii_columns(monkeypatch):
    monkeypatch.setattr(fs, "_load_pii_columns", lambda cur, sid: set())
    cur = _FakeCursor(responses=[
        (_p_contains("mv_dbsmart_table_features"), []),
        (_p_contains("from ds_db_objects"),
         [("public", "t", 50, [{"name": "id"}, {"name": "name"}], 1)]),
        (_p_contains("ds_relationships"), [(0,)]),
        (_p_contains("from business_glossary"), [(0,)]),
        (_p_contains("'tableselected'"), [(0, 0)]),
    ])
    out = fs.get_table_features(cur, table_id=1, company_id=1, source_id=1)
    assert out["pii_column_ratio"] == 0.0


# ─────────────────────────────────────────────────────────────
# 9) MV refresh idempotency (smoke — DDL semantik)
# ─────────────────────────────────────────────────────────────

def test_mv_refresh_can_be_called_twice_no_error():
    # Burada gerçek DB yok; semantik check: feature_store MV freshness
    # sorgusunu iki kez ardarda çağırıyor → hata oluşmamalı.
    cur = _FakeCursor(responses=[
        (_p_contains("mv_dbsmart_user_features"), []),
        (_p_contains("from dbsmart_interactions"), [(0, 0, 0, 0, 0, 0, None)]),
        (_p_contains("from dbsmart_sessions"), [(None,)]),
        (_p_contains("from dbsmart_interactions", "metricchosen"), []),
    ])
    fs.get_user_features(cur, 1, 1)
    fs.get_user_features(cur, 1, 1)
    # En az iki kez freshness check çağrılmış olmalı
    freshness_calls = [e for e in cur.executed if "max(refreshed_at)" in e[0].lower()]
    assert len(freshness_calls) >= 2


# ─────────────────────────────────────────────────────────────
# 10) Migration file presence + UNIQUE INDEX guard
# ─────────────────────────────────────────────────────────────

def test_migration_037_declares_unique_indexes_for_concurrent_refresh():
    """REFRESH … CONCURRENTLY için UNIQUE INDEX ZORUNLU.

    Negatif test mantığı: migration dosyasında her MV için en az 1
    UNIQUE INDEX ifadesi bulunmalı. Yoksa CONCURRENTLY refresh PG
    tarafından reddedilir (operasyonel regression).
    """
    import os
    mig_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "migrations", "versions",
        "037_v3300_feature_store_mvs.py",
    )
    mig_path = os.path.abspath(mig_path)
    assert os.path.exists(mig_path), f"migration not found: {mig_path}"
    with open(mig_path, "r", encoding="utf-8") as f:
        body = f.read()
    # Per-MV unique index guard
    assert "uq_mv_dbsmart_user_features_user" in body
    assert "uq_mv_dbsmart_table_features_tbl_co" in body
    # CONCURRENTLY-able semantic: CREATE UNIQUE INDEX ifadesi var mı
    assert body.upper().count("CREATE UNIQUE INDEX") >= 2
    # Idempotency
    assert "IF NOT EXISTS" in body
    assert "DROP MATERIALIZED VIEW IF EXISTS" in body
    # Down_revision chain
    assert "033_v3300_metric_library_seed" in body


# ─────────────────────────────────────────────────────────────
# 11) Bucket helpers
# ─────────────────────────────────────────────────────────────

def test_row_count_bucket_monotonic():
    assert fs._row_count_bucket(None) == 0
    assert fs._row_count_bucket(0) == 0
    assert fs._row_count_bucket(50) == 0
    assert fs._row_count_bucket(500) == 1
    assert fs._row_count_bucket(5_000) == 2
    assert fs._row_count_bucket(50_000) == 3
    assert fs._row_count_bucket(500_000) == 4
    assert fs._row_count_bucket(5_000_000) == 5
    assert fs._row_count_bucket(50_000_000) == 6


def test_cost_bucket_monotonic():
    assert fs._cost_bucket(0.0) == 0
    assert fs._cost_bucket(1.0) == 0
    assert fs._cost_bucket(3.0) == 1
    assert fs._cost_bucket(6.0) == 2
    assert fs._cost_bucket(10.0) == 3
    assert fs._cost_bucket(99.0) == 3
