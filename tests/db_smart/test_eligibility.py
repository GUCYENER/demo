"""eligibility.py — hybrid search + sample_preview (v3.30.0 FAZ 1 G1.2)."""
from __future__ import annotations

from typing import Any, List

import pytest

from app.services.db_smart import eligibility as el


# ─────────────────────────────────────────────────────────────
# Normalize helper
# ─────────────────────────────────────────────────────────────

def test_normalize_tr_lowercase_diacritics():
    assert el._normalize_tr("İSTANBUL ŞEHRİ") == "istanbul sehri"
    assert el._normalize_tr("Müşteri") == "musteri"
    assert el._normalize_tr("  Sipariş  ") == "siparis"
    assert el._normalize_tr("") == ""
    assert el._normalize_tr(None) == ""


# ─────────────────────────────────────────────────────────────
# Cursor mock
# ─────────────────────────────────────────────────────────────

class _SeqCursor:
    """Sırayla fetchone/fetchall yanıtları döndürür."""

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
# search_domains
# ─────────────────────────────────────────────────────────────

def test_search_domains_empty_returns_empty(fake_user_ctx):
    # user_pref → no row; main query → empty
    cur = _SeqCursor([None, []])
    out = el.search_domains(cur, source_id=1, query="", user_ctx=fake_user_ctx)
    assert out == []


def test_search_domains_ranks_by_lexical(fake_user_ctx):
    """Lexical match olan tablonun skoru daha yüksek olmalı."""
    # 1) user_pref → boş
    # 2) main lexical query → 2 row
    # 3) pgvector check — _pgvector_available beklenmeyecek (no query_embedding)
    user_pref = None
    rows = [
        # table_id, schema, object_name, object_type, row_cnt,
        # business_name_tr, description_tr, category, enrichment_score,
        # m_obj, m_bizname, m_desc, m_cat
        (10, "public", "tickets", "table", 1000,
         "Talepler", "Açık talepler", "helpdesk", 0.8,
         1, 1, 1, 0),
        (20, "public", "users", "table", 500,
         "Kullanıcılar", "Sistem kullanıcıları", "identity", 0.6,
         0, 0, 0, 0),
    ]
    cur = _SeqCursor([user_pref, rows])
    out = el.search_domains(cur, source_id=1, query="talep", user_ctx=fake_user_ctx)
    assert len(out) == 2
    # tickets (3 lexical match) > users (0)
    assert out[0]["object_name"] == "tickets"
    assert out[0]["score"] > out[1]["score"]


def test_search_domains_includes_score_breakdown(fake_user_ctx):
    cur = _SeqCursor([
        None,
        [(10, "public", "tickets", "table", 100, None, None, None, None,
          1, 0, 0, 0)],
    ])
    out = el.search_domains(cur, source_id=1, query="ticket", user_ctx=fake_user_ctx)
    assert "score_breakdown" in out[0]
    for key in ("lexical", "semantic", "cardinality", "frequent"):
        assert key in out[0]["score_breakdown"]


def test_search_domains_frequent_boost(fake_user_ctx):
    """frequent_tables içinde olan tablo daha yüksek skor almalı."""
    rows = [
        (10, "public", "tickets", "table", 100, None, None, None, None,
         0, 0, 0, 0),
        (20, "public", "users", "table", 100, None, None, None, None,
         0, 0, 0, 0),
    ]
    # user_pref: tickets sık kullanılan
    cur = _SeqCursor([
        [([10],)],   # frequent_tables = [10]
        rows,
    ])
    out = el.search_domains(cur, source_id=1, query="", user_ctx=fake_user_ctx)
    # tickets → frequent boost; üstte olmalı
    assert out[0]["object_name"] == "tickets"
    assert any("Sık kullandığınız" in r for r in out[0]["reasons"])


def test_search_domains_reasons_populated(fake_user_ctx):
    cur = _SeqCursor([
        None,
        [(10, "public", "tickets", "table", 1000000, "Talepler", None, None, None,
          1, 1, 0, 0)],
    ])
    out = el.search_domains(cur, source_id=1, query="talep", user_ctx=fake_user_ctx)
    assert out[0]["reasons"]
    # 2 lexical hit + high row count
    assert any("eşleşmesi" in r for r in out[0]["reasons"])


# ─────────────────────────────────────────────────────────────
# sample_preview
# ─────────────────────────────────────────────────────────────

def test_sample_preview_no_row(fake_user_ctx):
    cur = _SeqCursor([None])
    out = el.sample_preview(cur, table_id=10, user_ctx=fake_user_ctx)
    assert out is None


def test_sample_preview_truncates_to_max(fake_user_ctx):
    sample = {
        "columns": ["id", "name"],
        "rows": [[1, "a"], [2, "b"], [3, "c"], [4, "d"], [5, "e"], [6, "f"], [7, "g"]],
    }
    from datetime import datetime
    fetched_at = datetime(2026, 5, 19, 10, 0, 0)
    cur = _SeqCursor([(sample, fetched_at)])
    out = el.sample_preview(cur, table_id=10, user_ctx=fake_user_ctx, max_rows=5)
    assert out["columns"] == ["id", "name"]
    assert len(out["rows"]) == 5
    assert out["total_rows_in_sample"] == 7
    assert out["fetched_at"].startswith("2026-05-19")


def test_sample_preview_handles_query_exception(fake_user_ctx, monkeypatch):
    class _Boom:
        def execute(self, *a, **kw):
            raise RuntimeError("db down")
        def fetchone(self):
            return None
    out = el.sample_preview(_Boom(), table_id=10, user_ctx=fake_user_ctx)
    assert out is None


def test_sample_preview_returns_none_for_non_dict_sample(fake_user_ctx):
    from datetime import datetime
    cur = _SeqCursor([("not_a_dict", datetime(2026, 5, 19))])
    out = el.sample_preview(cur, table_id=10, user_ctx=fake_user_ctx)
    assert out is None
