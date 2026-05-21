"""Derin insight detection — seasonal z-score, slope reversal, missing category
(v3.30.0 FAZ 2 P28 G2.x).

Sorumluluklar:
    - detect_z_score_seasonality(series, time_col, value_col, threshold=2.5)
        Haftanın gününe göre (weekday) bucket'lanan mevsimsellik-farkında
        z-score anomalisi.
    - detect_slope_reversal(series, time_col, value_col, window=3)
        Hareketli eğim (moving slope) işaret değişimini trend kırılması
        olarak işaretler.
    - detect_missing_category(data, expected, category_col)
        Beklenen kategori listesinde olup veride bulunmayanları tespit eder.
    - confidence_guard(insights, threshold=0.6)
        confidence < threshold olan insight'ları filtreler (false-positive
        suppression).

Tasarım notları:
    - Saf hesap; DB'ye gitmez. statistics stdlib dışında bağımlılık yok.
    - Bu modül recommendation.detect_insights() ile çakışmaz; deep=True
      modunda insights_v2 olarak ek döner. Eski insight kontratı (kind/
      severity/rationale) korunur.
    - Insight şeması (standart):
        {
          "type": "anomaly_seasonal" | "trend_reversal" | "missing_category",
          "severity": "high" | "medium" | "low",
          "value": float,
          "baseline": float | None,
          "detector": "z_score_seasonal" | "slope_reversal" | "missing_category",
          "confidence": float,
          "metadata": {...}
        }
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────

_WEEKDAY_NAMES = (
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
)

# Bir bucket'ta z-score hesaplamak için gereken minimum nokta sayısı.
# stdev en az 2 örnek ister; 3 ile sapma anlamlı olmaya başlar.
_MIN_BUCKET_SIZE = 3

# Slope reversal için minimum seri uzunluğu (en az 2 pencere arası karşılaştırma).
_MIN_SERIES_FOR_SLOPE = 4


# ─────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────

def _to_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # NaN guard (statistics fonksiyonları NaN'i sessiz bozar).
    if f != f:  # noqa: PLR0124
        return None
    return f


def _to_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        # ISO 8601 (YYYY-MM-DD veya YYYY-MM-DDTHH:MM:SS)
        try:
            return datetime.fromisoformat(v).date()
        except ValueError:
            return None
    return None


def _severity_from_z(z: float) -> str:
    az = abs(z)
    if az >= 4.0:
        return "high"
    if az >= 3.0:
        return "medium"
    return "low"


def _confidence_from_z(z: float, threshold: float) -> float:
    """|z| - threshold farkını 0..1'e haritalar. |z|=threshold → 0.5."""
    az = abs(z)
    if az <= threshold:
        # threshold'a tam eşit/altı düşük güven (filter chain yakalar)
        return max(0.0, min(0.5, az / (2 * threshold) if threshold > 0 else 0.0))
    extra = az - threshold
    # extra=threshold → 0.9; üst sınır 0.99
    score = 0.5 + min(0.49, extra / (2 * threshold) if threshold > 0 else 0.49)
    return round(score, 4)


# ─────────────────────────────────────────────────────────────
# Detector 1 — Seasonal z-score (weekday bucket)
# ─────────────────────────────────────────────────────────────

def detect_z_score_seasonality(
    series: List[Dict[str, Any]],
    time_col: str,
    value_col: str,
    threshold: float = 2.5,
) -> List[Dict[str, Any]]:
    """Haftanın gününe göre bucket'lanmış z-score anomalisi.

    Algoritma:
        1) (time, value) çiftlerini topla; geçersizleri at.
        2) weekday(0..6) bazında bucket'la.
        3) Her bucket için mean + stdev (en az _MIN_BUCKET_SIZE nokta).
        4) Bucket içindeki her nokta için z = (v - mean) / stdev.
        5) |z| > threshold ise anomaly insight üret.
    """
    if not series or not time_col or not value_col:
        return []

    points: List[Dict[str, Any]] = []
    for row in series:
        if not isinstance(row, dict):
            continue
        d = _to_date(row.get(time_col))
        v = _to_float(row.get(value_col))
        if d is None or v is None:
            continue
        points.append({"date": d, "value": v, "weekday": d.weekday()})

    if not points:
        return []

    # Weekday bucket istatistikleri
    buckets: Dict[int, List[float]] = {}
    for p in points:
        buckets.setdefault(p["weekday"], []).append(p["value"])

    stats: Dict[int, Dict[str, float]] = {}
    for wd, vals in buckets.items():
        if len(vals) < _MIN_BUCKET_SIZE:
            continue
        try:
            sd = statistics.pstdev(vals)
        except statistics.StatisticsError:
            continue
        if sd == 0:
            continue
        stats[wd] = {"mean": statistics.fmean(vals), "stdev": sd}

    insights: List[Dict[str, Any]] = []
    for p in points:
        st = stats.get(p["weekday"])
        if not st:
            continue
        z = (p["value"] - st["mean"]) / st["stdev"]
        if abs(z) <= threshold:
            continue
        insights.append({
            "type": "anomaly_seasonal",
            "severity": _severity_from_z(z),
            "value": float(p["value"]),
            "baseline": round(st["mean"], 4),
            "detector": "z_score_seasonal",
            "confidence": _confidence_from_z(z, threshold),
            "metadata": {
                "time_col": time_col,
                "value_col": value_col,
                "date": p["date"].isoformat(),
                "weekday": _WEEKDAY_NAMES[p["weekday"]],
                "z_score": round(z, 4),
                "threshold": threshold,
                "bucket_stdev": round(st["stdev"], 4),
                "bucket_size": len(buckets[p["weekday"]]),
            },
        })
    return insights


# ─────────────────────────────────────────────────────────────
# Detector 2 — Slope reversal (moving slope sign change)
# ─────────────────────────────────────────────────────────────

def _moving_slopes(values: List[float], window: int) -> List[float]:
    """Sliding pencerelerin (last - first)/(window-1) eğimleri."""
    if window < 2 or len(values) < window:
        return []
    out: List[float] = []
    span = window - 1
    for i in range(len(values) - window + 1):
        seg = values[i:i + window]
        slope = (seg[-1] - seg[0]) / span
        out.append(slope)
    return out


def detect_slope_reversal(
    series: List[Dict[str, Any]],
    time_col: str,
    value_col: str,
    window: int = 3,
) -> List[Dict[str, Any]]:
    """Hareketli eğimde işaret değişimi (trend reversal) tespiti.

    Algoritma:
        1) Seriyi time_col'a göre sırala.
        2) window boyutlu sliding ortalama eğimleri hesapla.
        3) Komşu eğimlerden işaret değişimi (+ → - veya - → +) ara.
        4) Değişim büyüklüğünü confidence'a haritala.
    """
    if not series or not time_col or not value_col or window < 2:
        return []
    if len(series) < max(_MIN_SERIES_FOR_SLOPE, window + 1):
        return []

    pairs: List[Dict[str, Any]] = []
    for row in series:
        if not isinstance(row, dict):
            continue
        t = row.get(time_col)
        v = _to_float(row.get(value_col))
        if v is None or t is None:
            continue
        d = _to_date(t)
        sort_key = d if d is not None else t
        pairs.append({"sort": sort_key, "time": t, "value": v})

    if len(pairs) < window + 1:
        return []

    try:
        pairs.sort(key=lambda x: x["sort"])
    except TypeError:
        # Sıralanamayan karma tipler — orijinal sırayı koru
        pass

    values = [p["value"] for p in pairs]
    slopes = _moving_slopes(values, window)
    if len(slopes) < 2:
        return []

    insights: List[Dict[str, Any]] = []
    max_mag = max((abs(s) for s in slopes), default=0.0) or 1.0
    for i in range(1, len(slopes)):
        prev, curr = slopes[i - 1], slopes[i]
        # İşaret değişimi var mı? (sıfırı düz kabul et — kırılma değil)
        if prev == 0 or curr == 0:
            continue
        if (prev > 0) == (curr > 0):
            continue
        magnitude = (abs(prev) + abs(curr)) / 2.0
        # 0..1 normalize edilmiş güven; max_mag'a göre
        confidence = round(min(0.99, 0.4 + 0.6 * (magnitude / max_mag)), 4)
        severity = "high" if confidence >= 0.8 else ("medium" if confidence >= 0.6 else "low")
        pivot_idx = i + window - 1  # değişim noktasındaki gerçek değer indeksi
        pivot_idx = min(pivot_idx, len(pairs) - 1)
        pivot = pairs[pivot_idx]
        insights.append({
            "type": "trend_reversal",
            "severity": severity,
            "value": float(pivot["value"]),
            "baseline": round(values[max(0, pivot_idx - window)], 4),
            "detector": "slope_reversal",
            "confidence": confidence,
            "metadata": {
                "time_col": time_col,
                "value_col": value_col,
                "window": window,
                "slope_prev": round(prev, 6),
                "slope_curr": round(curr, 6),
                "pivot_time": str(pivot["time"]),
                "direction": "up_to_down" if prev > 0 else "down_to_up",
            },
        })
    return insights


# ─────────────────────────────────────────────────────────────
# Detector 3 — Missing category
# ─────────────────────────────────────────────────────────────

def detect_missing_category(
    data: List[Dict[str, Any]],
    expected: List[str],
    category_col: str,
) -> List[Dict[str, Any]]:
    """expected listesinde olup data[category_col] içinde olmayan kategoriler.

    Karşılaştırma case-sensitive (raporlar genelde normalize edilmiş kategori
    döndürür; case-fold gerekiyorsa caller normalize etmeli).
    """
    if not expected or not category_col:
        return []
    present: set = set()
    for row in data or []:
        if not isinstance(row, dict):
            continue
        val = row.get(category_col)
        if val is None:
            continue
        present.add(str(val))

    insights: List[Dict[str, Any]] = []
    expected_total = len(expected)
    for cat in expected:
        if cat in present:
            continue
        # Eksik kategori oranı confidence'ı belirler; tek eksik = 0.7,
        # tümü eksik = 0.99.
        missing_share = 1.0 / expected_total if expected_total else 1.0
        confidence = round(min(0.99, 0.7 + 0.29 * (1.0 - missing_share)), 4)
        severity = "high" if expected_total <= 3 else "medium"
        insights.append({
            "type": "missing_category",
            "severity": severity,
            "value": 0.0,
            "baseline": None,
            "detector": "missing_category",
            "confidence": confidence,
            "metadata": {
                "category_col": category_col,
                "missing": cat,
                "expected_count": expected_total,
                "present_count": len(present),
            },
        })
    return insights


# ─────────────────────────────────────────────────────────────
# Confidence guard (post-processing)
# ─────────────────────────────────────────────────────────────

def confidence_guard(
    insights: List[Dict[str, Any]],
    threshold: float = 0.6,
) -> List[Dict[str, Any]]:
    """confidence < threshold olan insight'ları filtreler.

    `confidence` alanı yoksa 0.0 sayılır (false-positive suppression).
    threshold=0.0 → tüm insight'lar geçer.
    """
    if not insights:
        return []
    out: List[Dict[str, Any]] = []
    for ins in insights:
        if not isinstance(ins, dict):
            continue
        conf = ins.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            conf_f = 0.0
        if conf_f >= threshold:
            out.append(ins)
    return out
