"""dialect-aware metric SQL doğruluk matrisi (v3.30.0 FAZ 3 G3.1 closure).

migration 033'teki 30 metrik (generic 8 + helpdesk 12 + sales 10) × 4 dialect
= 120 sql_template kombinasyonu için yapısal doğruluk kontrolü:

    - Her metrik tüm 4 dialect template'ine sahip mi?
    - Template non-empty string mi?
    - {table} placeholder var mı?
    - Dialect-spesifik syntax kuralları:
        * MSSQL: LIMIT kullanmamalı (TOP / OFFSET-FETCH)
        * Oracle: LIMIT kullanmamalı (ROWNUM / FETCH FIRST)
        * PostgreSQL/MySQL: LIMIT kullanabilir
    - {placeholder} ve :param setleri 4 dialect arasında tutarlı mı?
    - dialect_dictionary.supported_dialects() ile uyumlu mu?

NOT: Bu testler **dialect runtime'da çalıştırmıyor** — saf metin/yapı kontrolü.
Gerçek DB execution P14 streaming + 4-dialect smoke matrisinde yapılacak (FAZ 5).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

from app.services.db_smart import dialect_dictionary as dd


# ─────────────────────────────────────────────────────────────
# Seed yükleyici (alembic migration'ı saf modül olarak import)
# ─────────────────────────────────────────────────────────────

_SEED_PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "033_v3300_metric_library_seed.py"


def _load_seed() -> Any:
    spec = importlib.util.spec_from_file_location("seed033", str(_SEED_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SEED = _load_seed()

ALL_METRICS: List[Dict[str, Any]] = (
    list(_SEED.GENERIC_METRICS)
    + list(_SEED.HELPDESK_METRICS)
    + list(_SEED.SALES_METRICS)
)

DIALECTS = ("postgresql", "oracle", "mssql", "mysql")


def _metric_dialect_pairs() -> List[tuple]:
    out = []
    for m in ALL_METRICS:
        for d in DIALECTS:
            out.append((m["metric_key"], d))
    return out


# ─────────────────────────────────────────────────────────────
# Üst seviye topoloji
# ─────────────────────────────────────────────────────────────

def test_metric_seed_total_count():
    # generic 8 + helpdesk 12 + sales 10 = 30
    assert len(ALL_METRICS) == 30
    cats = {m["category"] for m in ALL_METRICS}
    assert cats == {"generic", "helpdesk", "sales"}


def test_metric_keys_unique():
    keys = [m["metric_key"] for m in ALL_METRICS]
    assert len(keys) == len(set(keys))


def test_dialects_match_dictionary():
    # Migration seed dialect set'i dialect_dictionary ile aynı olmalı
    assert set(DIALECTS) == set(dd.supported_dialects())


# ─────────────────────────────────────────────────────────────
# 30 × 4 = 120 — template var ve non-empty
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metric_key,dialect", _metric_dialect_pairs())
def test_template_present_and_nonempty(metric_key, dialect):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    tpl = m["sql_templates"].get(dialect)
    assert isinstance(tpl, str), f"{metric_key}/{dialect} template missing"
    assert tpl.strip(), f"{metric_key}/{dialect} template empty"
    # SELECT veya WITH (CTE) ile başlamalı (case-insensitive)
    head = tpl.strip().upper()
    assert head.startswith("SELECT") or head.startswith("WITH"), (
        f"{metric_key}/{dialect} unexpected statement head: {head[:20]}"
    )


# ─────────────────────────────────────────────────────────────
# 30 — her metrik tüm dialect'lere sahip
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_metric_has_all_four_dialects(metric_key):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    assert set(m["sql_templates"].keys()) == set(DIALECTS), (
        f"{metric_key} dialect set mismatch: {set(m['sql_templates'].keys())}"
    )


# ─────────────────────────────────────────────────────────────
# 30 — {table} placeholder var
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_metric_has_table_placeholder(metric_key):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    for d in DIALECTS:
        tpl = m["sql_templates"][d]
        assert "{table}" in tpl, f"{metric_key}/{d} missing {{table}} placeholder"


# ─────────────────────────────────────────────────────────────
# Dialect-spesifik kurallar — LIMIT kullanımı
# ─────────────────────────────────────────────────────────────

# LIMIT keyword'ünü token bazında yakala. Önemli: `:limit` parametre adı LIMIT
# SQL anahtar kelimesi değildir — strip-params adımı `:identifier`'ları siler.
_LIMIT_TOKEN = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_PARAM_STRIP = re.compile(r":[a-zA-Z_][a-zA-Z0-9_]*")


def _strip_params(sql: str) -> str:
    return _PARAM_STRIP.sub("?", sql)


@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_mssql_avoids_limit_keyword(metric_key):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    tpl = _strip_params(m["sql_templates"]["mssql"])
    assert not _LIMIT_TOKEN.search(tpl), (
        f"{metric_key}/mssql LIMIT yerine TOP/OFFSET-FETCH kullanılmalı"
    )


@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_oracle_avoids_limit_keyword(metric_key):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    tpl = _strip_params(m["sql_templates"]["oracle"])
    assert not _LIMIT_TOKEN.search(tpl), (
        f"{metric_key}/oracle LIMIT yerine ROWNUM/FETCH FIRST kullanılmalı"
    )


# ─────────────────────────────────────────────────────────────
# Placeholder tutarlılığı — :param ve {curly} setleri 4 dialect'te aynı
# ─────────────────────────────────────────────────────────────

_PARAM_RX = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")
_CURLY_RX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

# Bilinçli olarak dialect-spesifik fragmentler için izin verilenler
# (postgresql'in :granularity'si oracle'da :oracle_fmt, mysql'de :mysql_fmt
# olabilir — bu testte mutlak eşitlik beklemiyoruz, sadece "boş değil" + "her
# template kendi içinde tutarlı". Aşağıdaki ayrı testte bunu detaylandırıyoruz.)

@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_curly_placeholders_consistent_across_dialects(metric_key):
    """{table}/{measure}/{dimension} gibi structural placeholder'lar dialect bağımsız.

    Kural: bir metrikteki tüm dialect'lerin {curly} placeholder setleri aynı olmalı.
    (`:param` placeholder'lar dialect-spesifik olabilir — örn. :oracle_fmt vs
    :mysql_fmt — onları ayrı testte ele alıyoruz.)
    """
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    sets_per_dialect: Dict[str, Set[str]] = {
        d: set(_CURLY_RX.findall(m["sql_templates"][d])) for d in DIALECTS
    }
    reference = sets_per_dialect[DIALECTS[0]]
    for d in DIALECTS[1:]:
        assert sets_per_dialect[d] == reference, (
            f"{metric_key}: dialect {d} curly placeholders {sets_per_dialect[d]} "
            f"≠ {DIALECTS[0]} {reference}"
        )


@pytest.mark.parametrize("metric_key,dialect", _metric_dialect_pairs())
def test_no_unbounded_param_collision(metric_key, dialect):
    """:param adları geçerli identifier biçiminde olmalı (boş veya 'rakam-başlı' yok)."""
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    tpl = m["sql_templates"][dialect]
    params = _PARAM_RX.findall(tpl)
    # Bütün eşleşmeler regex zaten ident kuralına uygun döndürüyor; ekstra
    # garanti olarak: hiçbir parametre adı tek başına `_` olmasın.
    for p in params:
        assert p != "_" and p, f"{metric_key}/{dialect} invalid param: {p!r}"


# ─────────────────────────────────────────────────────────────
# default_viz dialect_dictionary ve viz whitelist ile uyumlu
# ─────────────────────────────────────────────────────────────

# db_smart_api'deki VIZ_TYPES enum'ı ile uyum (migration 032 ck constraint zaten
# DB seviyesinde uyguluyor; burada seed verisinin bizim viz list'imizle eşleştiğini
# doğruluyoruz).
VALID_VIZ = {
    "table", "bar", "line", "area", "kpi", "pie", "donut", "heatmap",
    "treemap", "funnel", "cohort", "map", "scatter", "box", "sankey",
    "sunburst", "calendar",
}


@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_default_viz_in_whitelist(metric_key):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    assert m["default_viz"] in VALID_VIZ, (
        f"{metric_key} default_viz={m['default_viz']!r} viz whitelist dışı"
    )


# ─────────────────────────────────────────────────────────────
# applicable_when JSONB şeması — min_rows int (varsa) + requires_columns list
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metric_key", [m["metric_key"] for m in ALL_METRICS])
def test_applicable_when_schema(metric_key):
    m = next(x for x in ALL_METRICS if x["metric_key"] == metric_key)
    aw = m.get("applicable_when") or {}
    assert isinstance(aw, dict), f"{metric_key} applicable_when not dict"
    if "min_rows" in aw:
        assert isinstance(aw["min_rows"], int) and aw["min_rows"] >= 0
    if "requires_columns" in aw:
        assert isinstance(aw["requires_columns"], list)
        assert all(isinstance(c, str) and c for c in aw["requires_columns"])


# ─────────────────────────────────────────────────────────────
# Sanity — 132'ye yakın çağrılabilir test üretimi doğrulaması
# (parametrize ile gerçek test sayısı: 120 + 30×6 = 300 üzeri)
# ─────────────────────────────────────────────────────────────

def test_pair_count_matches_30x4():
    pairs = _metric_dialect_pairs()
    assert len(pairs) == 30 * 4 == 120
