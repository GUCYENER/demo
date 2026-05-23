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
    """Sırayla fetchone/fetchall yanıtları döndürür.

    `calls`: her execute çağrısı için (sql, params) tuple'larını saklar —
    test'ler escape clause / NULL-fallback predicate vb. doğrulayabilir.
    """

    def __init__(self, responses: List[Any]):
        self._resps = responses
        self._idx = 0
        self._last = None
        self.calls: List[Any] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
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


# ─────────────────────────────────────────────────────────────
# _escape_like — ARES ORTA finding-2 unit kapsamı
# ─────────────────────────────────────────────────────────────

def test_escape_like_handles_all_meta_chars():
    """\\, %, _ → backslash ile escape edilmeli (sıra korunmalı)."""
    # Backslash önce escape edilmeli ki sonraki %/_ escape'leri çift escape etmesin.
    assert el._escape_like("a%b") == "a\\%b"
    assert el._escape_like("a_b") == "a\\_b"
    assert el._escape_like("a\\b") == "a\\\\b"
    assert el._escape_like("100%_test") == "100\\%\\_test"
    assert el._escape_like("") == ""
    assert el._escape_like(None) == ""


# ─────────────────────────────────────────────────────────────
# Finding 1 — glossary company_id IS NULL leak guard'ı
# (search_domains semantic ranking yolu)
# ─────────────────────────────────────────────────────────────

class _GlossaryCursor:
    """Semantic ranking yolunu da deterministik döndüren mock.

    Sıra:
      1) user_preferences SELECT          → fetchone
      2) main lexical SELECT              → fetchall (rows)
      3) _pgvector_available SELECT       → fetchone (1,) → True
      4) _glossary_has_embedding_column   → fetchone (1,) → True
      5) glossary semantic SELECT         → fetchall (sim_rows)
    """

    def __init__(self, lexical_rows, sim_rows):
        self._lexical_rows = lexical_rows
        self._sim_rows = sim_rows
        self.calls: List[Any] = []
        self._step = 0
        self._last = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._step += 1
        s = sql.strip().lower()
        if "dbsmart_user_preferences" in s:
            self._last = None
        elif "from ds_db_objects" in s or "ds_db_objects" in s:
            self._last = self._lexical_rows
        elif "pg_extension" in s:
            self._last = (1,)
        elif "information_schema.columns" in s:
            self._last = (1,)
        elif "business_glossary" in s:
            self._last = self._sim_rows
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


def _make_lexical_row(table_id=10, name="tickets"):
    # (table_id, schema, object_name, object_type, row_cnt,
    #  business_name_tr, description_tr, category, enrichment_score,
    #  m_obj, m_bizname, m_desc, m_cat)
    return (table_id, "public", name, "table", 100, None, None, None, None,
            0, 0, 0, 0)


def test_glossary_null_company_blocked_for_non_admin():
    """Non-admin + company_id=None: glossary lookup yalnızca
    `bg.company_id IS NULL` sistem fallback satırlarına kısıtlanmalı —
    eski `(%s IS NULL OR bg.company_id = %s)` cross-tenant leak'i kapanmalı."""
    user_ctx = {"id": 99, "company_id": None, "is_admin": False}
    cur = _GlossaryCursor(
        lexical_rows=[_make_lexical_row()],
        sim_rows=[("tickets", 0.9)],
    )
    el.search_domains(
        cur, source_id=1, query="ticket",
        user_ctx=user_ctx, query_embedding=[0.0] * 4,
    )
    # Glossary semantic query bulunmalı
    gloss_calls = [c for c in cur.calls if "<=>" in c[0]]
    assert gloss_calls, "semantic glossary query çağrılmadı"
    sql, params = gloss_calls[0]
    # Eski leaky predicate ortadan kalkmalı
    assert "(%s IS NULL OR bg.company_id = %s)" not in sql
    # Non-admin + company None → company_id IS NULL clause'u mevcut olmalı
    assert "bg.company_id IS NULL" in sql
    # Cross-tenant okuma yapılmadığı: params'da company_id bağlanmamalı
    # (yalnızca embedding parametresi olmalı)
    assert params is not None
    assert len(params) == 1


def test_glossary_seed_only_for_null_company():
    """Sistem (NULL company_id) fallback'i yalnızca admin_verified=TRUE
    satırlarına izin vermeli — seed sinyali olarak admin_verified kullanılıyor."""
    user_ctx = {"id": 7, "company_id": 1, "is_admin": False}
    cur = _GlossaryCursor(
        lexical_rows=[_make_lexical_row()],
        sim_rows=[("tickets", 0.7)],
    )
    el.search_domains(
        cur, source_id=1, query="t",
        user_ctx=user_ctx, query_embedding=[0.0] * 4,
    )
    gloss_calls = [c for c in cur.calls if "<=>" in c[0]]
    assert gloss_calls
    sql, params = gloss_calls[0]
    # admin_verified TRUE filter → seed-only fallback
    assert "admin_verified = TRUE" in sql
    # Kendi tenant satırları VEYA sistem NULL fallback
    assert "bg.company_id = %s" in sql
    assert "bg.company_id IS NULL" in sql
    # Params: embedding + company_id (=1)
    assert params is not None
    assert len(params) == 2
    assert params[1] == 1


def test_like_escape_percent_literal():
    """term='%' kullanıcısı tüm satırları taratmamalı — '%' literal olarak
    escape edilmiş bir LIKE pattern'e bind edilmeli ve SQL ESCAPE clause'u taşımalı."""
    cur = _SeqCursor([
        None,                             # user_pref
        [_make_lexical_row(name="x")],    # main lexical
    ])
    el.search_domains(cur, source_id=1, query="%", user_ctx={"id": 1, "company_id": 1})
    # En az 2 execute: user_pref + main lexical
    assert len(cur.calls) >= 2
    main_sql, main_params = cur.calls[1]
    # SQL ESCAPE clause kullanılmalı
    assert "ESCAPE '\\'" in main_sql
    # LIKE pattern'inde '%' escape edilmiş olmalı → '\%' (literal)
    # Pattern: '%' + escape('%') + '%' = '%\%%'
    assert main_params is not None
    like_patterns = [p for p in main_params if isinstance(p, str) and "\\%" in p]
    assert like_patterns, f"escape edilmiş '%' pattern bulunamadı: {main_params}"
    # Tam doğrula: pattern '%\%%' olmalı (norm_q='%', escape → '\%')
    assert like_patterns[0] == "%\\%%"


def test_like_escape_underscore_literal():
    """term='_' tek karakter wildcard'ı olarak değil, literal '_' olarak
    eşleştirilmeli; pattern içinde '\\_' bulunmalı ve ESCAPE clause olmalı."""
    cur = _SeqCursor([
        None,
        [_make_lexical_row(name="x")],
    ])
    el.search_domains(cur, source_id=1, query="_", user_ctx={"id": 1, "company_id": 1})
    main_sql, main_params = cur.calls[1]
    assert "ESCAPE '\\'" in main_sql
    like_patterns = [p for p in main_params if isinstance(p, str) and "\\_" in p]
    assert like_patterns, f"escape edilmiş '_' pattern bulunamadı: {main_params}"
    assert like_patterns[0] == "%\\_%"
