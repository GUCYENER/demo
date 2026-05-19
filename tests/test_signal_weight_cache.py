"""VYRA v3.29.8 L3 — load_company_weights cache testleri.

DB-driven weight override + TTL cache + invalidation davranışı.
"""
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.nodes.multi_signal_rank import (
    DEFAULT_WEIGHTS,
    invalidate_company_weights_cache,
    load_company_weights,
)
# NOTE: parent package `nodes.__init__` re-exports a function named
# `multi_signal_rank`, which shadows the submodule under attribute lookup.
# Use sys.modules to grab the real module for monkeypatching.
msr = sys.modules["app.services.pipeline.nodes.multi_signal_rank"]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Her testten önce cache'i temizle."""
    invalidate_company_weights_cache()
    yield
    invalidate_company_weights_cache()


def _make_cursor(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    return cur


def test_load_returns_defaults_when_no_company_id():
    assert load_company_weights(MagicMock(), None) == DEFAULT_WEIGHTS


def test_load_returns_defaults_when_no_cursor():
    assert load_company_weights(None, 1) == DEFAULT_WEIGHTS


def test_load_returns_defaults_when_no_overrides():
    cur = _make_cursor([])
    weights = load_company_weights(cur, 1)
    assert weights == DEFAULT_WEIGHTS


def test_load_applies_overrides_on_top_of_defaults():
    cur = _make_cursor([
        {"signal_name": "semantic", "weight": 0.50},
        {"signal_name": "glossary_match", "weight": 0.20},
    ])
    weights = load_company_weights(cur, 1)
    assert weights["semantic"] == 0.50
    assert weights["glossary_match"] == 0.20
    # Diğerleri default kalmalı
    assert weights["name_fuzzy"] == DEFAULT_WEIGHTS["name_fuzzy"]


def test_load_ignores_unknown_signal_names():
    """signal_name DEFAULT_WEIGHTS'ta yoksa atlanır (defense-in-depth)."""
    cur = _make_cursor([
        {"signal_name": "bogus_signal", "weight": 0.99},
        {"signal_name": "semantic", "weight": 0.40},
    ])
    weights = load_company_weights(cur, 1)
    assert "bogus_signal" not in weights
    assert weights["semantic"] == 0.40


def test_load_handles_tuple_rows():
    """RealDictCursor değilse tuple format."""
    cur = MagicMock()
    cur.fetchall.return_value = [("semantic", 0.42)]
    weights = load_company_weights(cur, 1)
    assert weights["semantic"] == 0.42


def test_load_returns_defaults_on_db_exception():
    """Tablo yok / RLS hatası → defaults dönmeli (best-effort)."""
    cur = MagicMock()
    cur.execute.side_effect = Exception("relation does not exist")
    weights = load_company_weights(cur, 1)
    assert weights == DEFAULT_WEIGHTS


def test_cache_hit_within_ttl():
    """İkinci çağrı DB'ye gitmemeli (cur.execute 1 kez)."""
    cur = _make_cursor([{"signal_name": "semantic", "weight": 0.55}])
    w1 = load_company_weights(cur, 42)
    w2 = load_company_weights(cur, 42)
    assert w1 == w2
    assert cur.execute.call_count == 1


def test_cache_invalidate_specific_company():
    cur = _make_cursor([{"signal_name": "semantic", "weight": 0.55}])
    load_company_weights(cur, 42)
    invalidate_company_weights_cache(42)
    load_company_weights(cur, 42)
    assert cur.execute.call_count == 2


def test_cache_invalidate_all():
    cur = _make_cursor([{"signal_name": "semantic", "weight": 0.55}])
    load_company_weights(cur, 1)
    load_company_weights(cur, 2)
    invalidate_company_weights_cache(None)
    load_company_weights(cur, 1)
    load_company_weights(cur, 2)
    # 4 çağrı: ilk iki cache populate, invalidate sonrası tekrar 2 fetch
    assert cur.execute.call_count == 4


def test_cache_per_company_isolation():
    """Şirket 1'in cache'i şirket 2'yi etkilemez."""
    cur_1 = _make_cursor([{"signal_name": "semantic", "weight": 0.11}])
    cur_2 = _make_cursor([{"signal_name": "semantic", "weight": 0.99}])
    w1 = load_company_weights(cur_1, 1)
    w2 = load_company_weights(cur_2, 2)
    assert w1["semantic"] == 0.11
    assert w2["semantic"] == 0.99


def test_cache_ttl_expiry(monkeypatch):
    """TTL geçince yeniden fetch."""
    cur = _make_cursor([{"signal_name": "semantic", "weight": 0.55}])
    load_company_weights(cur, 7)
    # TTL'yi 0 yap → bir sonraki call expired
    monkeypatch.setattr(msr, "_COMPANY_WEIGHTS_TTL_SEC", 0.0)
    invalidate_company_weights_cache(7)  # cleanup; TTL=0 zaten miss
    load_company_weights(cur, 7)
    assert cur.execute.call_count >= 2
