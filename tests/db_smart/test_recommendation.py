"""recommendation.py — chart/insight rule engine (v3.30.0 FAZ 2 P9 G2.3)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services.db_smart import recommendation as rec


# ─────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────

def test_profile_infers_numeric_type():
    rows = [(1, 10), (2, 20), (3, 30)]
    p = rec._profile(rows, ["id", "amount"])
    assert p["columns"][0]["type"] == "numeric"
    assert p["columns"][1]["type"] == "numeric"
    assert p["row_count"] == 3


def test_profile_infers_temporal_type():
    rows = [(date(2026, 1, 1),), (date(2026, 1, 2),)]
    p = rec._profile(rows, ["d"])
    assert p["columns"][0]["type"] == "temporal"


def test_profile_infers_categorical():
    rows = [("open",), ("closed",), ("wip",)]
    p = rec._profile(rows, ["status"])
    assert p["columns"][0]["type"] == "categorical"


def test_profile_cardinality():
    rows = [("a",), ("b",), ("a",), ("c",)]
    p = rec._profile(rows, ["k"])
    assert p["columns"][0]["cardinality"] == 3


def test_profile_null_ratio():
    rows = [(1,), (None,), (None,), (None,)]
    p = rec._profile(rows, ["x"])
    assert p["columns"][0]["null_ratio"] == 0.75


def test_profile_accepts_dict_rows():
    rows = [{"id": 1, "amount": 10}, {"id": 2, "amount": 20}]
    p = rec._profile(rows, ["id", "amount"])
    assert p["columns"][1]["type"] == "numeric"


def test_profile_decimal_is_numeric():
    rows = [(Decimal("10.50"),), (Decimal("20.75"),)]
    p = rec._profile(rows, ["amount"])
    assert p["columns"][0]["type"] == "numeric"


# ─────────────────────────────────────────────────────────────
# recommend_charts
# ─────────────────────────────────────────────────────────────

def test_recommend_kpi_for_single_row():
    rows = [(42,)]
    out = rec.recommend_charts(rows, ["total"])
    vizs = [i["viz"] for i in out["items"]]
    assert "kpi_card" in vizs
    assert out["items"][0]["viz"] == "kpi_card"


def test_recommend_line_for_time_series():
    rows = [(date(2026, 1, i + 1), i * 10) for i in range(10)]
    out = rec.recommend_charts(rows, ["d", "amount"])
    vizs = [i["viz"] for i in out["items"]]
    assert "line" in vizs


def test_recommend_multi_line_for_time_grouped():
    rows = []
    for i in range(10):
        rows.append((date(2026, 1, i + 1), "A", i * 10))
        rows.append((date(2026, 1, i + 1), "B", i * 5))
    out = rec.recommend_charts(rows, ["d", "team", "amount"])
    vizs = [i["viz"] for i in out["items"]]
    assert "multi_line" in vizs


def test_recommend_donut_for_few_categories():
    rows = [("open", 10), ("closed", 20), ("wip", 5)]
    out = rec.recommend_charts(rows, ["status", "cnt"])
    vizs = [i["viz"] for i in out["items"]]
    assert "donut" in vizs


def test_recommend_bar_for_medium_cardinality():
    rows = [(f"cat-{i}", i * 2) for i in range(15)]
    out = rec.recommend_charts(rows, ["category", "cnt"])
    vizs = [i["viz"] for i in out["items"]]
    assert "bar" in vizs


def test_recommend_treemap_for_high_cardinality():
    rows = [(f"cat-{i}", i) for i in range(50)]
    out = rec.recommend_charts(rows, ["category", "cnt"])
    vizs = [i["viz"] for i in out["items"]]
    assert "treemap" in vizs


def test_recommend_scatter_for_two_numerics():
    rows = [(i, i * 2 + 5) for i in range(20)]
    out = rec.recommend_charts(rows, ["x", "y"])
    vizs = [i["viz"] for i in out["items"]]
    assert "scatter" in vizs


def test_recommend_table_fallback_for_empty_pattern():
    """Tek kategorik kolon (sayısal yok) → table fallback."""
    rows = [("a",), ("b",), ("c",)]
    out = rec.recommend_charts(rows, ["x"])
    vizs = [i["viz"] for i in out["items"]]
    assert "table" in vizs


def test_recommend_empty_rows():
    out = rec.recommend_charts([], ["x", "y"])
    assert out["items"] == []
    assert out["profile"]["row_count"] == 0


def test_recommend_empty_columns():
    out = rec.recommend_charts([(1, 2)], [])
    assert out["items"] == []


def test_recommend_results_sorted_by_confidence():
    rows = [(42,)]
    out = rec.recommend_charts(rows, ["total"])
    confidences = [i["confidence"] for i in out["items"]]
    assert confidences == sorted(confidences, reverse=True)


def test_recommend_only_returns_valid_viz_types():
    rows = [(date(2026, 1, i + 1), i * 10) for i in range(10)]
    out = rec.recommend_charts(rows, ["d", "amount"])
    for item in out["items"]:
        assert item["viz"] in rec.VALID_VIZ_TYPES


def test_recommend_max_results_limit():
    rows = [(date(2026, 1, i + 1), "team", i * 10) for i in range(10)]
    out = rec.recommend_charts(rows, ["d", "team", "amount"], max_results=2)
    assert len(out["items"]) <= 2


# ─────────────────────────────────────────────────────────────
# detect_insights
# ─────────────────────────────────────────────────────────────

def test_insights_empty_rows():
    insights = rec.detect_insights([], ["x"])
    assert any(i["kind"] == "empty_result" for i in insights)


def test_insights_no_columns():
    insights = rec.detect_insights([(1,)], [])
    assert any(i["kind"] == "no_columns" for i in insights)


def test_insights_detects_high_outlier():
    rows = [(10,), (12,), (11,), (9,), (13,), (200,)]
    insights = rec.detect_insights(rows, ["amount"])
    kinds = [i["kind"] for i in insights]
    assert "outlier_high" in kinds


def test_insights_no_outlier_when_uniform():
    rows = [(10,), (11,), (12,), (10,), (11,), (12,)]
    insights = rec.detect_insights(rows, ["amount"])
    kinds = [i["kind"] for i in insights]
    assert "outlier_high" not in kinds


def test_insights_detects_upward_trend():
    rows = [(1,), (2,), (3,), (4,), (5,), (6,)]
    insights = rec.detect_insights(rows, ["v"])
    kinds = [i["kind"] for i in insights]
    assert "trend_up" in kinds


def test_insights_detects_downward_trend():
    rows = [(10,), (8,), (6,), (4,), (2,), (1,)]
    insights = rec.detect_insights(rows, ["v"])
    kinds = [i["kind"] for i in insights]
    assert "trend_down" in kinds


def test_insights_ignores_categorical():
    rows = [("a",), ("b",), ("c",), ("d",), ("e",), ("f",)]
    insights = rec.detect_insights(rows, ["k"])
    # categorical → no outlier/trend
    assert all(i["kind"] not in ("outlier_high", "trend_up", "trend_down") for i in insights)


def test_insights_safe_floats_skips_nones_and_bools():
    rows = [(1,), (None,), (True,), (2,), (3,)]
    # True is bool → skipped; remaining [1, 2, 3] insufficient for trend (needs >=5)
    insights = rec.detect_insights(rows, ["v"])
    assert isinstance(insights, list)


def test_insights_outlier_severity_levels():
    rows = [(10,), (10,), (10,), (10,), (10,), (150,)]  # 15x avg → high
    insights = rec.detect_insights(rows, ["amount"])
    outliers = [i for i in insights if i["kind"] == "outlier_high"]
    assert outliers
    assert outliers[0]["severity"] == "high"
