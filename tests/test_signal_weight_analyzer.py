"""VYRA v3.29.8 L2 — signal_weight_analyzer testleri.

Pearson korelasyon, Bayesian shrinkage, drift cap, renormalize doğrulamaları.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning.signal_weight_analyzer import (
    SIGNAL_NAMES,
    _confidence,
    _pearson,
    _renormalize,
    analyze_signal_weights,
)


# ---------- Helpers / Sample fabrika ----------

def _make_sample(signals_dict, outcome, weights=None):
    """signal_breakdown metadata gibi: (top1.signals, outcome, weights)."""
    if weights is None:
        weights = {
            "semantic": 0.30, "name_fuzzy": 0.18, "column_match": 0.14,
            "fk_centrality": 0.10, "recency": 0.08, "usage_freq": 0.08,
            "glossary_match": 0.12,
        }
    return (signals_dict, outcome, weights)


def _build_cursor_with_samples(samples):
    """analyze_signal_weights _fetch_run_data'nın döndüreceği veriyi simüle eden mock cursor."""
    cur = MagicMock()
    # _fetch_run_data tek bir cur.execute + cur.fetchall yapar.
    # rows: (sb_meta_dict, status, end_meta_dict)
    rows = []
    for signals, outcome, weights in samples:
        sb_meta = {"top": [{"signals": signals}], "weights": weights}
        status = "ok" if outcome == 1 else "error"
        end_meta = {"row_count": 5 if outcome == 1 else 0, "retry_count": 0}
        rows.append((sb_meta, status, end_meta))
    cur.fetchall.return_value = rows
    return cur


# ---------- Pearson ----------

def test_pearson_perfect_positive():
    assert _pearson([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    assert _pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_pearson_zero_variance():
    assert _pearson([1.0, 1.0, 1.0], [0.0, 1.0, 0.0]) == 0.0


def test_pearson_short_input():
    assert _pearson([0.5], [1.0]) == 0.0


# ---------- Confidence ----------

def test_confidence_zero_when_no_samples():
    assert _confidence(0.9, 0) == 0.0


def test_confidence_shrinks_for_small_n():
    c_small = _confidence(1.0, 10)
    c_large = _confidence(1.0, 1000)
    assert c_small < c_large
    assert 0 < c_small < 1
    assert c_large < 1.0


# ---------- Renormalize ----------

def test_renormalize_sum_one():
    w = _renormalize({"a": 0.4, "b": 0.4, "c": 0.2})
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)


def test_renormalize_zero_total_returns_input():
    w = _renormalize({"a": 0.0, "b": 0.0})
    assert w == {"a": 0.0, "b": 0.0}


# ---------- analyze_signal_weights — büyük resim ----------

def test_analyze_returns_empty_when_n_below_min():
    """min_sample_size=50 default, sample 10 verirsek boş dönmeli."""
    samples = [
        _make_sample({"semantic_score": 0.8}, 1) for _ in range(10)
    ]
    cur = _build_cursor_with_samples(samples)
    out = analyze_signal_weights(cur, company_id=1, days=7, min_sample_size=50)
    assert out == []


def test_analyze_produces_one_row_per_active_signal():
    """50+ sample, 7 sinyalde varyans var → her sinyal için 1 satır."""
    import random
    random.seed(42)
    samples = []
    for i in range(60):
        # Tüm sinyaller [0,1] aralığında rastgele
        sig = {
            "semantic_score": random.uniform(0.2, 0.9),
            "name_fuzzy_score": random.uniform(0.1, 0.8),
            "column_match_score": random.uniform(0.0, 0.7),
            "fk_centrality_score": random.uniform(0.0, 0.6),
            "recency_score": random.uniform(0.0, 0.5),
            "usage_freq_score": random.uniform(0.0, 0.5),
            "glossary_match_score": random.uniform(0.0, 0.4),
        }
        outcome = 1 if sig["semantic_score"] > 0.55 else 0
        samples.append(_make_sample(sig, outcome))
    cur = _build_cursor_with_samples(samples)
    out = analyze_signal_weights(cur, company_id=1, days=7, min_sample_size=50)
    assert len(out) >= 1
    # En azından semantic için anlamlı pozitif korelasyon
    sem_row = next((r for r in out if r["signal_name"] == "semantic"), None)
    assert sem_row is not None
    assert sem_row["correlation_pearson"] > 0
    assert sem_row["sample_size"] == 60
    assert sem_row["window_days"] == 7
    # Tüm alanlar mevcut
    for r in out:
        assert "current_weight" in r
        assert "suggested_weight" in r
        assert "confidence" in r
        assert 0 <= r["confidence"] <= 1


def test_analyze_drift_cap_max_2x():
    """Pearson çok güçlü olsa bile suggested current'in 2 katını aşmamalı."""
    samples = []
    for i in range(80):
        # semantic mükemmel positive correlation
        score = i / 80.0
        sig = {
            "semantic_score": score,
            "name_fuzzy_score": 0.5,
            "column_match_score": 0.5,
            "fk_centrality_score": 0.5,
            "recency_score": 0.5,
            "usage_freq_score": 0.5,
            "glossary_match_score": 0.5,
        }
        samples.append(_make_sample(sig, 1 if score > 0.5 else 0))
    cur = _build_cursor_with_samples(samples)
    out = analyze_signal_weights(cur, company_id=1, days=7, min_sample_size=50, lambda_=0.3)
    sem_row = next(r for r in out if r["signal_name"] == "semantic")
    # current 0.30, drift cap 2.0× = 0.60. Ama renormalize sonrası farklı olabilir.
    # Korelasyon ~1.0, lambda=0.3 → proposed ~0.30*1.3=0.39, clip içinde.
    assert sem_row["suggested_weight"] <= 0.6 + 1e-6


def test_analyze_skips_constant_signal():
    """Bir sinyal sabit (variance=0) ise korelasyon hesaplanamaz, öneri üretilmez."""
    samples = []
    for i in range(60):
        sig = {
            "semantic_score": i / 60.0,
            "name_fuzzy_score": 0.5,         # SABİT
            "column_match_score": (i + 7) % 5 / 5.0,
            "fk_centrality_score": (i * 3) % 4 / 4.0,
            "recency_score": (i + 1) % 6 / 6.0,
            "usage_freq_score": (i + 2) % 7 / 7.0,
            "glossary_match_score": (i + 3) % 8 / 8.0,
        }
        samples.append(_make_sample(sig, i % 2))
    cur = _build_cursor_with_samples(samples)
    out = analyze_signal_weights(cur, company_id=1, days=7, min_sample_size=50)
    # name_fuzzy sabitti → bu sinyal için öneri olmamalı
    fz = [r for r in out if r["signal_name"] == "name_fuzzy"]
    assert fz == []
    # Diğerleri var
    other = [r for r in out if r["signal_name"] != "name_fuzzy"]
    assert len(other) >= 1
