"""Sonuç-tabanlı chart & insight önerileri (v3.30.0 FAZ 2 P9 G2.3).

Sorumluluklar:
    - recommend_charts(rows, columns) — data shape'inden chart önerileri (kuralcı)
    - detect_insights(rows, columns) — outlier / trend / empty kuralcı insight'lar
    - score_recommendations(...) — confidence skor + sıralama (LLM yok, deterministik)

Tasarım notları:
    - Hiçbir fonksiyon DB'ye gitmez; saf hesap. Caller execute sonrası rows verir.
    - Chart tipleri migration_032 VALID_VIZ_TYPES ile uyumlu (line/bar/area/pie/
      donut/heatmap/treemap/scatter/box/funnel/sankey/sunburst/calendar/table/
      kpi_card/stacked_bar/multi_line).
    - Veri tipini "type" alanı yerine örnek değerlerden çıkarıyoruz (psycopg2
      RealDictRow / list[dict] / list[tuple] desteği).
    - max_rows_sample = 500 — büyük sonuçta sadece ilk 500 satır analiz edilir
      (insight latency bütçesi <50ms).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Migration 032 viz enum ile uyumlu kalmalı.
VALID_VIZ_TYPES = {
    "table", "kpi_card", "bar", "stacked_bar", "line", "multi_line", "area",
    "pie", "donut", "heatmap", "treemap", "scatter", "box", "funnel",
    "sankey", "sunburst", "calendar",
}

# Saf hesap latency guard'ı
_MAX_ROWS_SAMPLE = 500
_NUMERIC_TYPES = (int, float, Decimal)
_TEMPORAL_TYPES = (date, datetime)


# ─────────────────────────────────────────────────────────────
# Helpers — data shape detection
# ─────────────────────────────────────────────────────────────

def _row_to_tuple(row: Any, columns: List[str]) -> Tuple:
    """Row dict|tuple|list → tuple ordered by columns."""
    if isinstance(row, dict):
        return tuple(row.get(c) for c in columns)
    if isinstance(row, (list, tuple)):
        return tuple(row)
    return (row,)


def _infer_col_type(values: List[Any]) -> str:
    """Sample değerlerden kolon tipi çıkar: 'numeric'|'temporal'|'categorical'|'unknown'."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "unknown"
    n = len(non_null)
    n_num = sum(1 for v in non_null if isinstance(v, _NUMERIC_TYPES) and not isinstance(v, bool))
    n_time = sum(1 for v in non_null if isinstance(v, _TEMPORAL_TYPES))
    if n_time / n >= 0.8:
        return "temporal"
    if n_num / n >= 0.8:
        return "numeric"
    return "categorical"


def _cardinality(values: List[Any]) -> int:
    """Distinct olmayan-null sayım."""
    return len({v for v in values if v is not None})


def _profile(rows: List[Any], columns: List[str]) -> Dict[str, Any]:
    """Kolon-bazlı tip + cardinality + null ratio profili."""
    if not columns:
        return {"row_count": 0, "columns": []}
    sample = rows[:_MAX_ROWS_SAMPLE]
    n = len(sample)
    by_col: List[List[Any]] = [[] for _ in columns]
    for row in sample:
        tup = _row_to_tuple(row, columns)
        for i, v in enumerate(tup[:len(columns)]):
            by_col[i].append(v)
    profiles = []
    for i, col in enumerate(columns):
        vals = by_col[i]
        non_null = [v for v in vals if v is not None]
        profiles.append({
            "name": col,
            "type": _infer_col_type(vals),
            "cardinality": _cardinality(vals),
            "null_ratio": 1.0 - (len(non_null) / n) if n else 1.0,
        })
    return {"row_count": len(rows), "sample_count": n, "columns": profiles}


# ─────────────────────────────────────────────────────────────
# Chart recommendation rules
# ─────────────────────────────────────────────────────────────

def _rule_kpi_single_value(profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tek satır + tek/iki sayısal sütun → KPI card."""
    if profile["row_count"] != 1:
        return None
    num_cols = [c for c in profile["columns"] if c["type"] == "numeric"]
    if not num_cols:
        return None
    return {
        "viz": "kpi_card",
        "confidence": 0.95,
        "rationale": "Tek satır tek/birkaç sayısal değer — KPI kartı en sade gösterim.",
        "columns": [c["name"] for c in num_cols][:4],
    }


def _rule_time_series(profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    temporal = [c for c in profile["columns"] if c["type"] == "temporal"]
    numeric = [c for c in profile["columns"] if c["type"] == "numeric"]
    categorical = [c for c in profile["columns"] if c["type"] == "categorical"]
    if not temporal or not numeric:
        return None
    # Çoklu kategori → multi_line, tek → line
    viz = "multi_line" if categorical and categorical[0]["cardinality"] <= 8 else "line"
    return {
        "viz": viz,
        "confidence": 0.9,
        "rationale": f"Zaman ({temporal[0]['name']}) + sayısal ({numeric[0]['name']}) — trend görselleştirme.",
        "x": temporal[0]["name"],
        "y": numeric[0]["name"],
        "group_by": categorical[0]["name"] if viz == "multi_line" else None,
    }


def _rule_category_distribution(profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    categorical = [c for c in profile["columns"] if c["type"] == "categorical"]
    numeric = [c for c in profile["columns"] if c["type"] == "numeric"]
    if not categorical or not numeric:
        return None
    cat = categorical[0]
    # Az kategori → pie/donut, çok kategori → bar
    if cat["cardinality"] <= 6:
        return {
            "viz": "donut",
            "confidence": 0.85,
            "rationale": f"{cat['cardinality']} kategori — donut dağılım için uygun.",
            "x": cat["name"],
            "y": numeric[0]["name"],
        }
    if cat["cardinality"] <= 30:
        return {
            "viz": "bar",
            "confidence": 0.85,
            "rationale": f"{cat['cardinality']} kategori — bar chart karşılaştırma için uygun.",
            "x": cat["name"],
            "y": numeric[0]["name"],
        }
    return {
        "viz": "treemap",
        "confidence": 0.7,
        "rationale": f"{cat['cardinality']} yüksek kardinalite — treemap hiyerarşik gösterim için.",
        "x": cat["name"],
        "y": numeric[0]["name"],
    }


def _rule_scatter(profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    numeric = [c for c in profile["columns"] if c["type"] == "numeric"]
    if len(numeric) >= 2 and profile["row_count"] >= 10:
        return {
            "viz": "scatter",
            "confidence": 0.75,
            "rationale": "İki sayısal eksen — korelasyon için scatter.",
            "x": numeric[0]["name"],
            "y": numeric[1]["name"],
        }
    return None


def _rule_fallback_table(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "viz": "table",
        "confidence": 0.5,
        "rationale": "Veri profili net bir chart tipine işaret etmiyor — tablo en güvenli.",
    }


def recommend_charts(
    rows: List[Any],
    columns: List[str],
    *,
    max_results: int = 5,
) -> Dict[str, Any]:
    """Sonuç verisinden 1-5 chart önerisi (skorlu, sıralı) döner.

    Returns:
        {
          "profile": {row_count, sample_count, columns: [...]},
          "items": [{viz, confidence, rationale, x?, y?, group_by?}, ...]
        }
    """
    if not isinstance(rows, list):
        rows = list(rows) if rows else []
    if not isinstance(columns, list) or not columns:
        return {"profile": {"row_count": 0, "columns": []}, "items": []}

    profile = _profile(rows, columns)
    if profile["row_count"] == 0:
        return {"profile": profile, "items": []}

    candidates: List[Dict[str, Any]] = []
    for rule in (
        _rule_kpi_single_value,
        _rule_time_series,
        _rule_category_distribution,
        _rule_scatter,
    ):
        out = rule(profile)
        if out:
            candidates.append(out)
    candidates.append(_rule_fallback_table(profile))

    # Tekil viz tipini bir kez al (en yüksek confidence'la)
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for c in sorted(candidates, key=lambda x: -x["confidence"]):
        if c["viz"] in seen:
            continue
        if c["viz"] not in VALID_VIZ_TYPES:
            continue
        seen.add(c["viz"])
        uniq.append(c)
    return {"profile": profile, "items": uniq[:max_results]}


# ─────────────────────────────────────────────────────────────
# Insight detection (rule engine)
# ─────────────────────────────────────────────────────────────

def _safe_floats(values: List[Any]) -> List[float]:
    out: List[float] = []
    for v in values:
        if v is None or isinstance(v, bool):
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _detect_outliers(name: str, values: List[Any]) -> Optional[Dict[str, Any]]:
    nums = _safe_floats(values)
    if len(nums) < 5:
        return None
    # Max'ı dışlayan ortalama — outlier kendi varlığı ortalamayı bozmasın.
    sorted_desc = sorted(nums, reverse=True)
    mx = sorted_desc[0]
    rest = sorted_desc[1:]
    avg_rest = sum(rest) / len(rest) if rest else 0
    if avg_rest <= 0:
        return None
    ratio = mx / avg_rest
    if ratio >= 5.0:
        return {
            "kind": "outlier_high",
            "column": name,
            "rationale": f"'{name}' kolonunda max ({mx:.1f}) diğerlerinin ortalamasının ({avg_rest:.1f}) {ratio:.1f}× üstünde.",
            "severity": "high" if ratio >= 10 else "medium",
        }
    return None


def _detect_trend(name: str, values: List[Any]) -> Optional[Dict[str, Any]]:
    nums = _safe_floats(values)
    if len(nums) < 5:
        return None
    asc = sum(1 for i in range(1, len(nums)) if nums[i] > nums[i - 1])
    desc = sum(1 for i in range(1, len(nums)) if nums[i] < nums[i - 1])
    total = len(nums) - 1
    if total == 0:
        return None
    if asc / total >= 0.8:
        return {
            "kind": "trend_up",
            "column": name,
            "rationale": f"'{name}' kolonu %{int(100 * asc / total)} oranında monoton artan.",
            "severity": "info",
        }
    if desc / total >= 0.8:
        return {
            "kind": "trend_down",
            "column": name,
            "rationale": f"'{name}' kolonu %{int(100 * desc / total)} oranında monoton azalan.",
            "severity": "info",
        }
    return None


def detect_insights(
    rows: List[Any],
    columns: List[str],
) -> List[Dict[str, Any]]:
    """Outlier + trend + empty kuralcı insight'lar döner."""
    if not isinstance(rows, list):
        rows = list(rows) if rows else []
    if not isinstance(columns, list) or not columns:
        return [{"kind": "no_columns", "rationale": "Kolon listesi boş.", "severity": "warn"}]
    if not rows:
        return [{"kind": "empty_result", "rationale": "Sorgu hiç satır döndürmedi.", "severity": "warn"}]

    sample = rows[:_MAX_ROWS_SAMPLE]
    insights: List[Dict[str, Any]] = []
    by_col: Dict[str, List[Any]] = {c: [] for c in columns}
    for row in sample:
        tup = _row_to_tuple(row, columns)
        for i, c in enumerate(columns):
            if i < len(tup):
                by_col[c].append(tup[i])

    for name, vals in by_col.items():
        col_type = _infer_col_type(vals)
        if col_type != "numeric":
            continue
        ol = _detect_outliers(name, vals)
        if ol:
            insights.append(ol)
        tr = _detect_trend(name, vals)
        if tr:
            insights.append(tr)
    return insights
