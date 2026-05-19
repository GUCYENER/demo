"""VYRA v3.29.9 — integration with v3.29.8 Signal Weight Tuner.

Covers:
  - build_centrality_index: declared=1.0, inferred unverified=0.5×conf,
    verified=1.0, rejected ignored
  - _fk_centrality_score: float index normalization
  - analyze_signal_weights: min_event_age_hours filters fk_centrality
    samples BEFORE Pearson; other signals unaffected
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.nodes.multi_signal_rank import (
    _fk_centrality_score,
    build_centrality_index,
)
from app.services.db_learning import signal_weight_analyzer as swa


# ─────────────────────────────────────────────────────────────
# build_centrality_index — confidence weighting
# ─────────────────────────────────────────────────────────────
def test_centrality_declared_weighted_1():
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("public", "orders", "public", "users", False, True, None),
    ]
    idx = build_centrality_index(cur, source_id=1)
    assert idx[("public", "orders")] == 1.0
    assert idx[("public", "users")] == 1.0


def test_centrality_inferred_unverified_half_times_conf():
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("public", "orders", "public", "users", True, False, 0.8),
    ]
    idx = build_centrality_index(cur, source_id=1)
    # 0.5 * 0.8 = 0.4 per endpoint
    assert idx[("public", "orders")] == pytest.approx(0.4)
    assert idx[("public", "users")] == pytest.approx(0.4)


def test_centrality_inferred_verified_full_weight():
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("public", "orders", "public", "users", True, True, 0.5),
    ]
    idx = build_centrality_index(cur, source_id=1)
    # verified → 1.0 regardless of confidence
    assert idx[("public", "orders")] == 1.0


def test_centrality_aggregates_multiple_edges():
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("public", "users", "public", "tenant", False, True, None),   # 1.0
        ("public", "orders", "public", "users", True, False, 0.8),    # 0.4
        ("public", "items", "public", "users", True, True, 0.6),      # 1.0
    ]
    idx = build_centrality_index(cur, source_id=1)
    # users appears in all 3 rows → 1.0 + 0.4 + 1.0 = 2.4
    assert idx[("public", "users")] == pytest.approx(2.4)


def test_centrality_rejected_filter_in_query():
    """Query has WHERE rejected_at IS NULL — verify SQL contains it."""
    cur = MagicMock()
    cur.fetchall.return_value = []
    build_centrality_index(cur, source_id=42)
    sql = cur.execute.call_args.args[0]
    assert "rejected_at IS NULL" in sql


def test_centrality_null_confidence_treats_as_zero():
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("public", "a", "public", "b", True, False, None),
    ]
    idx = build_centrality_index(cur, source_id=1)
    # conf=None → weight=0 → skipped
    assert idx == {}


# ─────────────────────────────────────────────────────────────
# _fk_centrality_score — float index normalization
# ─────────────────────────────────────────────────────────────
def test_fk_score_float_index_normalized():
    candidate = {"schema_name": "public", "table_name": "users"}
    idx = {("public", "users"): 5.0}
    score = _fk_centrality_score(candidate, idx, max_centrality=10.0)
    assert score == 0.5


def test_fk_score_above_max_clamped_to_1():
    candidate = {"schema_name": "public", "table_name": "users"}
    idx = {("public", "users"): 20.0}
    score = _fk_centrality_score(candidate, idx, max_centrality=10.0)
    assert score == 1.0


def test_fk_score_missing_table_zero():
    candidate = {"schema_name": "public", "table_name": "orphan"}
    idx = {("public", "users"): 5.0}
    assert _fk_centrality_score(candidate, idx) == 0.0


# ─────────────────────────────────────────────────────────────
# _load_fk_inference_deploy_ts
# ─────────────────────────────────────────────────────────────
def test_deploy_ts_load_iso_string():
    cur = MagicMock()
    cur.fetchone.return_value = ("2026-05-19T12:00:00+00:00",)
    ts = swa._load_fk_inference_deploy_ts(cur)
    assert ts is not None
    assert ts.year == 2026 and ts.month == 5 and ts.day == 19


def test_deploy_ts_load_missing_returns_none():
    cur = MagicMock()
    cur.fetchone.return_value = None
    assert swa._load_fk_inference_deploy_ts(cur) is None


def test_deploy_ts_load_invalid_string_returns_none():
    cur = MagicMock()
    cur.fetchone.return_value = ("not-a-date",)
    assert swa._load_fk_inference_deploy_ts(cur) is None


# ─────────────────────────────────────────────────────────────
# analyze_signal_weights — min_event_age_hours filter (fk only)
# ─────────────────────────────────────────────────────────────
def _make_sample(fk_score: float, outcome: int, weights: dict, ts,
                 other_jitter: float = 0.0):
    """Build a sample tuple in the v3.29.9 4-tuple format.

    `other_jitter` varies non-fk signals so Pearson over them isn't skipped
    for lack of variance.
    """
    base = 0.5 + other_jitter
    signals = {
        "semantic_score": base, "name_fuzzy_score": base,
        "column_match_score": base, "fk_centrality_score": fk_score,
        "recency_score": base, "usage_freq_score": base,
        "glossary_match_score": base,
    }
    return (signals, outcome, weights, ts)


def test_analyzer_min_event_age_filters_fk_centrality_only(monkeypatch):
    """Pre-deploy samples should be excluded for fk_centrality, kept for others."""
    deploy = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
    pre = deploy - timedelta(hours=10)
    post = deploy + timedelta(hours=48)
    weights = {"semantic": 0.30, "name_fuzzy": 0.18, "column_match": 0.14,
               "fk_centrality": 0.10, "recency": 0.08, "usage_freq": 0.08,
               "glossary_match": 0.12}
    # 60 pre-deploy samples + 60 post-deploy samples, varied so all signals have variance
    samples = []
    for i in range(60):
        samples.append(_make_sample(
            0.1 + (i % 5) * 0.02, 1 if i % 2 == 0 else 0, weights, pre,
            other_jitter=(i % 7) * 0.01,
        ))
    for i in range(60):
        samples.append(_make_sample(
            0.6 + (i % 5) * 0.05, 1 if i % 2 == 0 else 0, weights, post,
            other_jitter=(i % 7) * 0.01,
        ))

    cur = MagicMock()
    monkeypatch.setattr(swa, "_fetch_run_data", lambda *a, **k: samples)
    monkeypatch.setattr(swa, "_load_fk_inference_deploy_ts", lambda c: deploy)

    # With min_event_age_hours=24, fk_centrality should only see post-deploy n=60
    out = swa.analyze_signal_weights(
        cur, company_id=1, days=7, min_sample_size=50,
        min_event_age_hours=24,
    )
    by_sig = {s["signal_name"]: s for s in out}
    # fk_centrality computed from filtered n=60
    assert "fk_centrality" in by_sig
    assert by_sig["fk_centrality"]["sample_size"] == 60
    # Other signals use full n=120
    assert by_sig["semantic"]["sample_size"] == 120


def test_analyzer_min_event_age_zero_no_filter(monkeypatch):
    """min_event_age_hours=0 → no fk-specific filter, all signals use full n."""
    deploy = datetime(2026, 5, 19, tzinfo=timezone.utc)
    weights = {"semantic": 0.30, "fk_centrality": 0.10}
    samples = [_make_sample(0.5 if i % 2 == 0 else 0.7, 1 if i % 3 == 0 else 0,
                            weights, deploy) for i in range(60)]
    cur = MagicMock()
    monkeypatch.setattr(swa, "_fetch_run_data", lambda *a, **k: samples)

    out = swa.analyze_signal_weights(
        cur, company_id=1, days=7, min_sample_size=50,
        min_event_age_hours=0,
    )
    by_sig = {s["signal_name"]: s for s in out}
    if "fk_centrality" in by_sig:
        assert by_sig["fk_centrality"]["sample_size"] == 60


def test_analyzer_min_event_age_no_deploy_ts_no_filter(monkeypatch):
    """If FK_INFERENCE_DEPLOY_TS missing, filter silently disables."""
    weights = {"semantic": 0.30, "fk_centrality": 0.10}
    deploy = datetime(2026, 5, 19, tzinfo=timezone.utc)
    samples = [_make_sample(0.5 if i % 2 == 0 else 0.7, 1 if i % 3 == 0 else 0,
                            weights, deploy) for i in range(60)]
    cur = MagicMock()
    monkeypatch.setattr(swa, "_fetch_run_data", lambda *a, **k: samples)
    monkeypatch.setattr(swa, "_load_fk_inference_deploy_ts", lambda c: None)

    out = swa.analyze_signal_weights(
        cur, company_id=1, days=7, min_sample_size=50,
        min_event_age_hours=24,
    )
    by_sig = {s["signal_name"]: s for s in out}
    if "fk_centrality" in by_sig:
        assert by_sig["fk_centrality"]["sample_size"] == 60


def test_analyzer_min_event_age_drops_fk_when_below_min(monkeypatch):
    """If filtered fk_centrality samples < min_sample_size, signal is skipped."""
    deploy = datetime(2026, 5, 19, tzinfo=timezone.utc)
    pre = deploy - timedelta(hours=10)
    post = deploy + timedelta(hours=48)
    weights = {"semantic": 0.30, "fk_centrality": 0.10}
    # 60 pre + only 20 post → filtered fk_centrality has 20 (< min 50)
    samples = ([_make_sample(0.1 + (i % 5) * 0.02, 1 if i % 2 == 0 else 0, weights, pre,
                             other_jitter=(i % 7) * 0.01)
                for i in range(60)]
               + [_make_sample(0.6 + (i % 5) * 0.05, 1 if i % 2 == 0 else 0, weights, post,
                               other_jitter=(i % 7) * 0.01)
                  for i in range(20)])
    cur = MagicMock()
    monkeypatch.setattr(swa, "_fetch_run_data", lambda *a, **k: samples)
    monkeypatch.setattr(swa, "_load_fk_inference_deploy_ts", lambda c: deploy)

    out = swa.analyze_signal_weights(
        cur, company_id=1, days=7, min_sample_size=50,
        min_event_age_hours=24,
    )
    by_sig = {s["signal_name"]: s for s in out}
    assert "fk_centrality" not in by_sig   # filtered n=20 < min 50 → skipped
    assert "semantic" in by_sig             # other signals still computed
