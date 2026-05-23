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
import math
import statistics
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


# ─────────────────────────────────────────────────────────────
# FAZ 2 P27 — Deep shape profiling + 12-pattern rule engine
# ─────────────────────────────────────────────────────────────

def _skewness(nums: List[float]) -> float:
    """Sample skewness (3rd standardised moment, Fisher-Pearson)."""
    n = len(nums)
    if n < 3:
        return 0.0
    m = sum(nums) / n
    var = sum((x - m) ** 2 for x in nums) / n
    if var <= 0:
        return 0.0
    sd = math.sqrt(var)
    return (sum((x - m) ** 3 for x in nums) / n) / (sd ** 3)


def _histogram_peaks(nums: List[float], bins: int = 10) -> int:
    """Return count of local maxima in `bins`-bin histogram."""
    if len(nums) < bins:
        return 0
    lo, hi = min(nums), max(nums)
    if hi == lo:
        return 0
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in nums:
        idx = int((v - lo) / width)
        if idx == bins:
            idx = bins - 1
        counts[idx] += 1
    peaks = 0
    for i in range(bins):
        left = counts[i - 1] if i > 0 else -1
        right = counts[i + 1] if i < bins - 1 else -1
        if counts[i] > left and counts[i] > right and counts[i] >= 2:
            peaks += 1
    return peaks


def _distribution_shape(nums: List[float]) -> str:
    """Classify distribution: uniform / skewed_left / skewed_right / bimodal / unknown."""
    if len(nums) < 3:
        return "unknown"
    if len(set(nums)) == 1:
        return "uniform"
    peaks = _histogram_peaks(nums, bins=10)
    if peaks >= 2:
        return "bimodal"
    sk = _skewness(nums)
    if sk > 0.5:
        return "skewed_right"
    if sk < -0.5:
        return "skewed_left"
    # Spread test — coefficient of variation low → uniform
    m = sum(nums) / len(nums)
    if m != 0:
        sd = statistics.pstdev(nums)
        if abs(sd / m) < 0.15:
            return "uniform"
    return "unknown"


def _pearson(xs: List[float], ys: List[float]) -> float:
    """Pearson r between two equal-length numeric lists."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    xs2, ys2 = xs[:n], ys[:n]
    mx = sum(xs2) / n
    my = sum(ys2) / n
    num = sum((xs2[i] - mx) * (ys2[i] - my) for i in range(n))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs2))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys2))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _pairwise_correlations(
    cols: Dict[str, List[float]],
    *,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Compute pearson r for top-`top_k` highest-variance numeric columns."""
    if len(cols) < 2:
        return []
    variances: List[Tuple[str, float]] = []
    for name, vals in cols.items():
        if len(vals) >= 2:
            variances.append((name, statistics.pvariance(vals)))
    variances.sort(key=lambda kv: -kv[1])
    chosen = [name for name, _ in variances[:top_k]]
    out: List[Dict[str, Any]] = []
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            r = _pearson(cols[a], cols[b])
            out.append({"x": a, "y": b, "r": round(r, 4)})
    return out


def _detect_hierarchy(
    rows: List[Any],
    columns: List[str],
    profile_cols: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Detect parent→child column pairs (B nests under A; A has ≤20 distinct; B ≥5x A)."""
    out: List[Dict[str, str]] = []
    cats = [c for c in profile_cols if c["type"] == "categorical"]
    if len(cats) < 2:
        return out
    by_col: Dict[str, List[Any]] = {c: [] for c in columns}
    for row in rows[:_MAX_ROWS_SAMPLE]:
        tup = _row_to_tuple(row, columns)
        for i, c in enumerate(columns):
            if i < len(tup):
                by_col[c].append(tup[i])
    for a in cats:
        a_card = a["cardinality"]
        if a_card == 0 or a_card > 20:
            continue
        for b in cats:
            if a["name"] == b["name"]:
                continue
            b_card = b["cardinality"]
            if b_card < a_card * 5:
                continue
            # Each B value must nest under exactly one A value
            mapping: Dict[Any, Any] = {}
            nests = True
            for av, bv in zip(by_col[a["name"]], by_col[b["name"]]):
                if av is None or bv is None:
                    continue
                if bv in mapping and mapping[bv] != av:
                    nests = False
                    break
                mapping[bv] = av
            if nests and mapping:
                out.append({"parent": a["name"], "child": b["name"]})
    return out


def _seasonality_zscore(
    timestamps: List[Any],
    values: List[float],
    *,
    threshold: float = 2.5,
) -> List[Dict[str, Any]]:
    """Weekday-partitioned z-score outliers (avoid weekday-of-week false positives)."""
    buckets: Dict[int, List[Tuple[int, float]]] = {}
    for idx, (ts, v) in enumerate(zip(timestamps, values)):
        if ts is None or v is None:
            continue
        if isinstance(ts, datetime):
            wd = ts.weekday()
        elif isinstance(ts, date):
            wd = ts.weekday()
        else:
            continue
        buckets.setdefault(wd, []).append((idx, float(v)))
    anomalies: List[Dict[str, Any]] = []
    for wd, items in buckets.items():
        if len(items) < 3:
            continue
        vs = [v for _, v in items]
        m = sum(vs) / len(vs)
        sd = statistics.pstdev(vs)
        if sd == 0:
            continue
        for idx, v in items:
            z = (v - m) / sd
            if abs(z) >= threshold:
                anomalies.append({
                    "index": idx,
                    "weekday": wd,
                    "value": v,
                    "z": round(z, 3),
                })
    return anomalies


def _slope(values: List[float]) -> float:
    """Simple OLS slope of values vs index 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    num = sum((xs[i] - mx) * (values[i] - my) for i in range(n))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def _slope_sign_change(values: List[float], window: int = 3) -> bool:
    """True if last `window` slope sign differs from prior `window` slope sign."""
    if len(values) < window * 2:
        return False
    prior = _slope(values[-2 * window:-window])
    recent = _slope(values[-window:])
    if prior == 0 or recent == 0:
        return False
    return (prior > 0) != (recent > 0)


def analyze_shape(data: List[Dict[str, Any]], numeric_cols: List[str]) -> Dict[str, Any]:
    """Deep statistical profile: distribution shape, correlations, hierarchy, seasonality, slope reversals."""
    sample = (data or [])[:_MAX_ROWS_SAMPLE]
    columns = list(numeric_cols) if numeric_cols else []
    by_num: Dict[str, List[float]] = {}
    for col in columns:
        vals: List[float] = []
        for row in sample:
            if not isinstance(row, dict):
                continue
            v = row.get(col)
            if v is None or isinstance(v, bool):
                continue
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        by_num[col] = vals

    shapes: Dict[str, str] = {col: _distribution_shape(vals) for col, vals in by_num.items()}
    correlations = _pairwise_correlations(by_num, top_k=10)

    # Hierarchy needs all columns + their categorical profile
    all_cols = list(sample[0].keys()) if sample and isinstance(sample[0], dict) else columns
    prof_cols = []
    for c in all_cols:
        vals_any = [row.get(c) for row in sample if isinstance(row, dict)]
        prof_cols.append({
            "name": c,
            "type": _infer_col_type(vals_any),
            "cardinality": _cardinality(vals_any),
        })
    hierarchy = _detect_hierarchy(sample, all_cols, prof_cols)

    # Seasonality + slope reversal (if a temporal column is present)
    temporal_cols = [c["name"] for c in prof_cols if c["type"] == "temporal"]
    seasonality: Dict[str, List[Dict[str, Any]]] = {}
    slope_changes: Dict[str, bool] = {}
    if temporal_cols and columns:
        ts_col = temporal_cols[0]
        ts_vals = [row.get(ts_col) for row in sample if isinstance(row, dict)]
        for ncol in columns:
            nvals = [row.get(ncol) for row in sample if isinstance(row, dict)]
            try:
                nvals_f = [float(v) if v is not None and not isinstance(v, bool) else None for v in nvals]
            except (TypeError, ValueError):
                nvals_f = []
            seasonality[ncol] = _seasonality_zscore(ts_vals, nvals_f)
            clean = [v for v in nvals_f if v is not None]
            slope_changes[ncol] = _slope_sign_change(clean)

    return {
        "row_count": len(data or []),
        "sample_count": len(sample),
        "shapes": shapes,
        "correlations": correlations,
        "hierarchy": hierarchy,
        "seasonality_anomalies": seasonality,
        "slope_reversals": slope_changes,
    }


def score_recommendations(
    recommendations: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Composite-score & stable-sort recos by relevance × shape_fit × user_history_weight."""
    if not recommendations:
        return []
    shape_fit = context.get("shape_fit", {}) if isinstance(context, dict) else {}
    history = context.get("user_history_weight", {}) if isinstance(context, dict) else {}
    out: List[Dict[str, Any]] = []
    for idx, rec_item in enumerate(recommendations):
        viz = rec_item.get("viz", "")
        relevance = float(rec_item.get("confidence", 0.5))
        s_fit = float(shape_fit.get(viz, 1.0))
        u_hist = float(history.get(viz, 1.0))
        score = round(relevance * s_fit * u_hist, 6)
        enriched = dict(rec_item)
        enriched["score"] = score
        enriched["_orig_idx"] = idx
        out.append(enriched)
    # Stable sort: desc by score, asc by original index for ties
    out.sort(key=lambda r: (-r["score"], r["_orig_idx"]))
    for r in out:
        r.pop("_orig_idx", None)
    return out


def _rule_engine_12pattern(
    shape_info: Dict[str, Any],
    data_meta: Dict[str, Any],
) -> List[str]:
    """12-branch pattern → viz mapping (Prompt H §2). Returns list of viz keys."""
    out: List[str] = []
    n_cat = int(data_meta.get("categorical_count", 0))
    n_num = int(data_meta.get("numeric_count", 0))
    n_temp = int(data_meta.get("temporal_count", 0))
    row_count = int(data_meta.get("row_count", 0))
    max_card = int(data_meta.get("max_cardinality", 0))
    has_hierarchy = bool(shape_info.get("hierarchy"))
    has_flow = bool(data_meta.get("has_flow", False))
    has_funnel_steps = bool(data_meta.get("has_funnel_steps", False))
    has_date_grid = bool(data_meta.get("has_date_grid", False))
    shapes = shape_info.get("shapes", {}) if isinstance(shape_info, dict) else {}
    correlations = shape_info.get("correlations", []) if isinstance(shape_info, dict) else []

    # 1) heatmap — 2 categorical + 1 numeric, moderate cardinality
    if n_cat >= 2 and n_num >= 1 and max_card <= 50:
        out.append("heatmap")
    # 2) sankey — flow metadata (source/target/value)
    if has_flow and n_num >= 1:
        out.append("sankey")
    # 3) funnel — ordered steps + 1 numeric (counts)
    if has_funnel_steps and n_num >= 1:
        out.append("funnel")
    # 4) sunburst — hierarchy + 1 numeric
    if has_hierarchy and n_num >= 1:
        out.append("sunburst")
    # 5) calendar — temporal + numeric + day-grid metadata
    if has_date_grid and n_temp >= 1 and n_num >= 1:
        out.append("calendar")
    # 6) box — single numeric with skewed/bimodal shape
    if n_num >= 1 and any(s in ("skewed_left", "skewed_right", "bimodal") for s in shapes.values()):
        out.append("box")
    # 7) stacked_bar — 2 categorical + 1 numeric, smaller cardinality
    if n_cat >= 2 and n_num >= 1 and max_card <= 20 and "heatmap" not in out:
        out.append("stacked_bar")
    # 8) multi_line — temporal + numeric + a low-card categorical grouping
    if n_temp >= 1 and n_num >= 1 and n_cat >= 1 and max_card <= 8:
        out.append("multi_line")
    # 9) area — temporal + single numeric, cumulative-friendly
    if n_temp >= 1 and n_num >= 1 and n_cat == 0:
        out.append("area")
    # 10) scatter — ≥2 numeric with at least one strong-|r| pair
    if n_num >= 2 and any(abs(c.get("r", 0)) >= 0.5 for c in correlations):
        out.append("scatter")
    # 11) treemap — hierarchy OR high cardinality categorical
    if has_hierarchy or (n_cat >= 1 and max_card > 30):
        if "treemap" not in out:
            out.append("treemap")
    # 12) donut — single low-card categorical + numeric
    if n_cat == 1 and n_num >= 1 and max_card <= 6 and row_count >= 1:
        out.append("donut")

    # Keep only valid viz keys, preserve order, drop duplicates
    seen: set = set()
    uniq: List[str] = []
    for v in out:
        if v in VALID_VIZ_TYPES and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq
