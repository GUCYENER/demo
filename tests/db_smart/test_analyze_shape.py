"""analyze_shape + score_recommendations + 12-pattern rule engine (v3.30.0 FAZ 2 P27)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.services.db_smart import recommendation as rec


# ─────────────────────────────────────────────────────────────
# Distribution shape detection
# ─────────────────────────────────────────────────────────────

def test_shape_uniform_constant_values():
    assert rec._distribution_shape([5.0] * 20) == "uniform"


def test_shape_uniform_low_variance():
    # Values close to mean → low coefficient of variation
    nums = [100.0 + (i % 3) * 0.5 for i in range(30)]
    assert rec._distribution_shape(nums) == "uniform"


def test_shape_skewed_right():
    # Right tail — most low values, few high
    nums = [1.0] * 20 + [10.0, 12.0, 15.0, 20.0, 50.0]
    assert rec._distribution_shape(nums) == "skewed_right"


def test_shape_skewed_left():
    # Left tail — most high values, few low
    nums = [50.0, 30.0, 20.0, 10.0, 5.0] + [100.0] * 20
    assert rec._distribution_shape(nums) == "skewed_left"


def test_shape_bimodal_two_peaks():
    # Two clusters → 2 histogram peaks
    nums = [1.0, 1.1, 1.2, 0.9, 1.05] * 4 + [10.0, 10.1, 10.2, 9.9, 10.05] * 4
    shape = rec._distribution_shape(nums)
    assert shape == "bimodal"


def test_shape_edge_case_n1():
    assert rec._distribution_shape([42.0]) == "unknown"


def test_shape_edge_case_n2():
    assert rec._distribution_shape([1.0, 2.0]) == "unknown"


def test_shape_all_same_explicit():
    assert rec._distribution_shape([7.0, 7.0, 7.0, 7.0, 7.0]) == "uniform"


# ─────────────────────────────────────────────────────────────
# Pearson correlation
# ─────────────────────────────────────────────────────────────

def test_pearson_strong_positive():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert rec._pearson(xs, ys) == pytest.approx(1.0, abs=1e-9)


def test_pearson_strong_negative():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 8.0, 6.0, 4.0, 2.0]
    assert rec._pearson(xs, ys) == pytest.approx(-1.0, abs=1e-9)


def test_pearson_no_correlation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    ys = [3.0, 1.0, 4.0, 1.0, 5.0, 2.0]
    r = rec._pearson(xs, ys)
    assert abs(r) < 0.5


def test_correlations_capped_at_top_k():
    cols = {f"c{i}": [float(j + i) for j in range(20)] for i in range(15)}
    pairs = rec._pairwise_correlations(cols, top_k=10)
    # 10 columns → C(10,2) = 45 pairs max
    assert len(pairs) == 45


# ─────────────────────────────────────────────────────────────
# Hierarchy detection
# ─────────────────────────────────────────────────────────────

def test_hierarchy_parent_child_detected():
    # category (3 distinct) → subcategory (15 distinct, each nests under exactly one cat)
    rows = []
    for cat_idx in range(3):
        for sub_idx in range(5):
            rows.append({"cat": f"C{cat_idx}", "sub": f"S{cat_idx}-{sub_idx}", "val": 1})
    profile_cols = [
        {"name": "cat", "type": "categorical", "cardinality": 3},
        {"name": "sub", "type": "categorical", "cardinality": 15},
        {"name": "val", "type": "numeric", "cardinality": 1},
    ]
    result = rec._detect_hierarchy(rows, ["cat", "sub", "val"], profile_cols)
    assert any(h["parent"] == "cat" and h["child"] == "sub" for h in result)


def test_hierarchy_non_nesting_returns_empty():
    # Free-form many-to-many — no nesting
    rows = [
        {"a": "x", "b": "1"}, {"a": "y", "b": "1"},
        {"a": "x", "b": "2"}, {"a": "y", "b": "2"},
        {"a": "x", "b": "3"}, {"a": "y", "b": "3"},
    ] * 3
    profile_cols = [
        {"name": "a", "type": "categorical", "cardinality": 2},
        {"name": "b", "type": "categorical", "cardinality": 3},
    ]
    result = rec._detect_hierarchy(rows, ["a", "b"], profile_cols)
    # b doesn't have 5x cardinality of a anyway
    assert result == [] or all(h["parent"] != "a" or h["child"] != "b" for h in result)


# ─────────────────────────────────────────────────────────────
# Seasonality-aware z-score
# ─────────────────────────────────────────────────────────────

def test_seasonality_no_anomaly_when_flat():
    base = date(2026, 1, 5)  # Monday
    ts = [base + timedelta(days=i) for i in range(28)]  # 4 weeks
    values = [100.0 + (i % 7) * 5 for i in range(28)]  # systematic weekday pattern
    anomalies = rec._seasonality_zscore(ts, values, threshold=2.5)
    assert anomalies == []


def test_seasonality_detects_saturday_spike():
    # 4 Saturdays — three normal, one huge spike
    base = date(2026, 1, 3)  # Saturday
    ts = [base + timedelta(weeks=w) for w in range(4)]
    values = [10.0, 11.0, 9.0, 500.0]
    anomalies = rec._seasonality_zscore(ts, values, threshold=1.5)
    assert any(a["value"] == 500.0 for a in anomalies)


def test_seasonality_ignores_when_too_few():
    ts = [date(2026, 1, 5), date(2026, 1, 12)]
    values = [10.0, 1000.0]
    # Only 2 Mondays → bucket too small
    anomalies = rec._seasonality_zscore(ts, values)
    assert anomalies == []


# ─────────────────────────────────────────────────────────────
# Slope sign change
# ─────────────────────────────────────────────────────────────

def test_slope_reversal_up_then_down():
    # First half climbing, second half falling
    vals = [1.0, 2.0, 3.0, 6.0, 4.0, 2.0]
    assert rec._slope_sign_change(vals, window=3) is True


def test_slope_no_reversal_monotonic_up():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert rec._slope_sign_change(vals, window=3) is False


def test_slope_too_short_returns_false():
    assert rec._slope_sign_change([1.0, 2.0], window=3) is False


# ─────────────────────────────────────────────────────────────
# analyze_shape integration
# ─────────────────────────────────────────────────────────────

def test_analyze_shape_returns_full_structure():
    data = [{"x": float(i), "y": float(i * 2)} for i in range(15)]
    out = rec.analyze_shape(data, ["x", "y"])
    assert "shapes" in out and "correlations" in out
    assert "hierarchy" in out and "seasonality_anomalies" in out
    assert "slope_reversals" in out
    assert out["row_count"] == 15


def test_analyze_shape_empty_data():
    out = rec.analyze_shape([], ["a"])
    assert out["row_count"] == 0
    assert out["shapes"] == {"a": "unknown"}


def test_analyze_shape_correlation_present():
    data = [{"a": float(i), "b": float(i * 3 + 1)} for i in range(20)]
    out = rec.analyze_shape(data, ["a", "b"])
    pair = next((c for c in out["correlations"] if {c["x"], c["y"]} == {"a", "b"}), None)
    assert pair is not None
    assert pair["r"] == pytest.approx(1.0, abs=1e-6)


# ─────────────────────────────────────────────────────────────
# score_recommendations stable ordering
# ─────────────────────────────────────────────────────────────

def test_score_recommendations_stable_when_tied():
    recos = [
        {"viz": "bar", "confidence": 0.5},
        {"viz": "line", "confidence": 0.5},
        {"viz": "pie", "confidence": 0.5},
    ]
    out = rec.score_recommendations(recos, {})
    # Equal scores → preserve original order
    assert [r["viz"] for r in out] == ["bar", "line", "pie"]


def test_score_recommendations_ranks_by_composite():
    recos = [
        {"viz": "bar", "confidence": 0.6},
        {"viz": "line", "confidence": 0.9},
    ]
    out = rec.score_recommendations(recos, {"shape_fit": {"bar": 2.0, "line": 0.5}})
    # bar: 0.6 * 2.0 = 1.2; line: 0.9 * 0.5 = 0.45 → bar first
    assert out[0]["viz"] == "bar"
    assert out[0]["score"] > out[1]["score"]


def test_score_recommendations_empty():
    assert rec.score_recommendations([], {}) == []


# ─────────────────────────────────────────────────────────────
# 12-pattern rule engine
# ─────────────────────────────────────────────────────────────

def test_pattern_heatmap_two_cat_one_num():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 2, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 100, "max_cardinality": 25},
    )
    assert "heatmap" in out


def test_pattern_sankey_when_flow_metadata():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 2, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 100, "max_cardinality": 5, "has_flow": True},
    )
    assert "sankey" in out


def test_pattern_funnel_when_steps():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 1, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 5, "max_cardinality": 5, "has_funnel_steps": True},
    )
    assert "funnel" in out


def test_pattern_sunburst_with_hierarchy():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [],
                    "hierarchy": [{"parent": "cat", "child": "sub"}]},
        data_meta={"categorical_count": 2, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 100, "max_cardinality": 30},
    )
    assert "sunburst" in out


def test_pattern_calendar_with_date_grid():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 0, "numeric_count": 1, "temporal_count": 1,
                   "row_count": 365, "max_cardinality": 0, "has_date_grid": True},
    )
    assert "calendar" in out


def test_pattern_box_for_skewed_shape():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {"amt": "skewed_right"}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 0, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 100, "max_cardinality": 0},
    )
    assert "box" in out


def test_pattern_multi_line_for_temporal_grouped():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 1, "numeric_count": 1, "temporal_count": 1,
                   "row_count": 100, "max_cardinality": 5},
    )
    assert "multi_line" in out


def test_pattern_area_for_pure_time_series():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 0, "numeric_count": 1, "temporal_count": 1,
                   "row_count": 50, "max_cardinality": 0},
    )
    assert "area" in out


def test_pattern_scatter_for_strong_correlation():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [{"x": "a", "y": "b", "r": 0.85}],
                    "hierarchy": []},
        data_meta={"categorical_count": 0, "numeric_count": 2, "temporal_count": 0,
                   "row_count": 50, "max_cardinality": 0},
    )
    assert "scatter" in out


def test_pattern_treemap_for_high_cardinality():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 1, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 200, "max_cardinality": 80},
    )
    assert "treemap" in out


def test_pattern_donut_for_low_card_single_cat():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {}, "correlations": [], "hierarchy": []},
        data_meta={"categorical_count": 1, "numeric_count": 1, "temporal_count": 0,
                   "row_count": 5, "max_cardinality": 5},
    )
    assert "donut" in out


def test_pattern_returns_only_valid_viz_keys():
    out = rec._rule_engine_12pattern(
        shape_info={"shapes": {"x": "bimodal"}, "correlations": [{"x": "a", "y": "b", "r": 0.9}],
                    "hierarchy": [{"parent": "p", "child": "c"}]},
        data_meta={"categorical_count": 2, "numeric_count": 2, "temporal_count": 1,
                   "row_count": 100, "max_cardinality": 15,
                   "has_flow": True, "has_funnel_steps": True, "has_date_grid": True},
    )
    for v in out:
        assert v in rec.VALID_VIZ_TYPES
    # No duplicates
    assert len(out) == len(set(out))
