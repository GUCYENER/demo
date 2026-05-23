"""Anomaly detection — multi-algorithm ensemble (v3.30.0 FAZ 4 P32).

Z-score (seasonal-aware), IQR (rolling), ESD (Rosner) ve opsiyonel Prophet
detector'larını çalıştırır; ≥2 detector aynı noktayı flag ederse insight
emit eder (ensemble vote, ±1 gün tolerans).

Tasarım:
    - 3rd-party numerik dep YOK (stdlib `statistics` + math). Prophet lazy import.
    - Çıktı şeması insight_detector.py (FAZ 2 P28) ile uyumlu:
      {type:"anomaly", severity, value, baseline, detector, confidence, metadata}
    - Saf hesap; DB'ye gitmez. Hedef <50ms/300pt.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_METHODS: Tuple[str, ...] = ("z_score", "iqr", "esd")
_Z_THRESHOLD = 3.0
_IQR_K = 1.5
_IQR_WINDOW = 30
_ESD_TOP_K = 5
_ESD_ALPHA = 0.05
_PROPHET_SIGMA = 2.0
_VOTE_TOLERANCE_DAYS = 1
_MIN_BUCKET_POINTS = 3
_MIN_POINTS = 5
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def _coerce_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _coerce_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _normalize(series: Iterable[Dict[str, Any]], time_col: str, value_col: str) -> List[Tuple[datetime, float]]:
    pts: List[Tuple[datetime, float]] = []
    for row in series or []:
        if not isinstance(row, dict):
            continue
        ts = _coerce_ts(row.get(time_col))
        val = _coerce_float(row.get(value_col))
        if ts is None or val is None:
            continue
        pts.append((ts, val))
    pts.sort(key=lambda p: p[0])
    return pts


def _severity_from_z(z: float) -> str:
    az = abs(z)
    if az >= 5.0:
        return "high"
    if az >= 4.0:
        return "medium"
    return "low"


def _confidence(score: float, scale: float) -> float:
    try:
        x = abs(score) / max(scale, 1e-9)
    except (TypeError, ValueError):
        return 0.0
    return round(min(0.99, 1.0 - math.exp(-x / 2.0)), 4)


def _flag(detector: str, ts: datetime, value: float, baseline: Optional[float],
          severity: str, confidence: float, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "anomaly",
        "severity": severity,
        "value": value,
        "baseline": baseline,
        "detector": detector,
        "confidence": confidence,
        "timestamp": ts.isoformat(),
        "metadata": metadata,
    }


def _detect_z_score(points: List[Tuple[datetime, float]], seasonality: Optional[str]) -> List[Dict[str, Any]]:
    """Seasonal-aware (weekday-bucket) Z-score; bucket yetersizse seri-geneli fallback."""
    if len(points) < _MIN_POINTS:
        return []
    use_buckets = seasonality in (None, "auto", "weekday")
    buckets: Dict[Any, List[float]] = {}
    for ts, val in points:
        key = ts.weekday() if use_buckets else 0
        buckets.setdefault(key, []).append(val)

    stats: Dict[Any, Tuple[float, float]] = {}
    for key, vals in buckets.items():
        if len(vals) < _MIN_BUCKET_POINTS:
            continue
        sd = statistics.pstdev(vals)
        if sd > 0:
            stats[key] = (statistics.fmean(vals), sd)

    if not stats:
        vals = [v for _, v in points]
        sd = statistics.pstdev(vals)
        if sd <= 0:
            return []
        stats = {0: (statistics.fmean(vals), sd)}
        use_buckets = False

    all_vals = [v for _, v in points]
    fallback_mu = statistics.fmean(all_vals)
    fallback_sd = statistics.pstdev(all_vals)

    out: List[Dict[str, Any]] = []
    for ts, val in points:
        key = ts.weekday() if use_buckets else 0
        if key in stats:
            mu, sd = stats[key]
        elif fallback_sd > 0:
            mu, sd = fallback_mu, fallback_sd
        else:
            continue
        z = (val - mu) / sd
        if abs(z) >= _Z_THRESHOLD:
            out.append(_flag(
                "z_score", ts, val, mu, _severity_from_z(z),
                _confidence(z, _Z_THRESHOLD),
                {"z": round(z, 4), "bucket": key if use_buckets else None,
                 "threshold": _Z_THRESHOLD},
            ))
    return out


def _detect_iqr(points: List[Tuple[datetime, float]]) -> List[Dict[str, Any]]:
    """Rolling 30-window IQR; outside Q3+1.5*IQR / Q1-1.5*IQR → flag."""
    n = len(points)
    if n < _MIN_POINTS:
        return []
    out: List[Dict[str, Any]] = []
    for i in range(n):
        lo = max(0, i - _IQR_WINDOW + 1)
        window = [v for _, v in points[lo:i + 1]]
        if len(window) < _MIN_POINTS:
            continue
        try:
            q1, _med, q3 = statistics.quantiles(window, n=4, method="inclusive")
        except statistics.StatisticsError:
            continue
        iqr = q3 - q1
        if iqr <= 0:
            continue
        upper = q3 + _IQR_K * iqr
        lower = q1 - _IQR_K * iqr
        ts, val = points[i]
        if val > upper or val < lower:
            dist = (val - upper) if val > upper else (lower - val)
            sev = "high" if dist >= 2 * iqr else ("medium" if dist >= iqr else "low")
            out.append(_flag(
                "iqr", ts, val, (q1 + q3) / 2.0, sev,
                _confidence(dist, iqr),
                {"q1": round(q1, 4), "q3": round(q3, 4),
                 "iqr": round(iqr, 4), "window": len(window)},
            ))
    return out


def _detect_esd(points: List[Tuple[datetime, float]], top_k: int = _ESD_TOP_K) -> List[Dict[str, Any]]:
    """Rosner's ESD: iteratif olarak en uç noktayı çıkararak top-k aday seçer."""
    if len(points) < max(_MIN_POINTS, top_k + 2):
        return []
    remaining = list(range(len(points)))
    flagged: List[int] = []
    for _ in range(min(top_k, len(remaining) - 2)):
        if len(remaining) < 3:
            break
        vals = [points[j][1] for j in remaining]
        mu = statistics.fmean(vals)
        sd = statistics.pstdev(vals)
        if sd <= 0:
            break
        best_local = max(range(len(remaining)), key=lambda k: abs(vals[k] - mu))
        best_global = remaining[best_local]
        r = abs(points[best_global][1] - mu) / sd
        if r < _Z_THRESHOLD:
            break
        flagged.append(best_global)
        remaining.pop(best_local)

    if not flagged:
        return []
    all_vals = [v for _, v in points]
    full_mu = statistics.fmean(all_vals)
    full_sd = statistics.pstdev(all_vals) or 1.0
    out: List[Dict[str, Any]] = []
    for gi in flagged:
        ts, val = points[gi]
        r = abs(val - full_mu) / full_sd
        out.append(_flag(
            "esd", ts, val, full_mu, _severity_from_z(r),
            _confidence(r, _Z_THRESHOLD),
            {"r": round(r, 4), "alpha": _ESD_ALPHA, "top_k": top_k},
        ))
    return out


def _detect_prophet(points: List[Tuple[datetime, float]]) -> List[Dict[str, Any]]:
    """Prophet wrapper — lazy import. Paket/runtime hatasında graceful skip."""
    if len(points) < 2 * _MIN_POINTS:
        return []
    try:
        from prophet import Prophet  # type: ignore
    except Exception as exc:
        logger.debug("prophet unavailable, skipping: %s", exc)
        return []
    try:
        model = Prophet()
        fit_input = [{"ds": t.isoformat(), "y": v} for t, v in points]
        model.fit(fit_input)  # type: ignore[arg-type]
        forecast = model.predict(fit_input)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover — real prophet runtime path
        logger.debug("prophet predict failed: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    for (ts, val), f in zip(points, forecast or []):
        if not isinstance(f, dict):
            continue
        yhat = _coerce_float(f.get("yhat"))
        if yhat is None:
            continue
        lo = _coerce_float(f.get("yhat_lower"))
        hi = _coerce_float(f.get("yhat_upper"))
        sigma = max(((hi - lo) / 4.0) if (hi is not None and lo is not None and hi > lo) else 1.0, 1e-9)
        dev = (val - yhat) / sigma
        if abs(dev) >= _PROPHET_SIGMA:
            out.append(_flag(
                "prophet", ts, val, yhat, _severity_from_z(dev),
                _confidence(dev, _PROPHET_SIGMA),
                {"yhat": yhat, "sigma": sigma, "deviation": round(dev, 4)},
            ))
    return out


def _ensemble_vote(flags: List[Dict[str, Any]], tolerance_days: int = _VOTE_TOLERANCE_DAYS) -> List[Dict[str, Any]]:
    """≥2 farklı detector aynı zaman penceresinde flag → insight."""
    if not flags:
        return []
    enriched: List[Tuple[datetime, Dict[str, Any]]] = []
    for fl in flags:
        try:
            ts = datetime.fromisoformat(fl["timestamp"])
        except (KeyError, ValueError):
            continue
        enriched.append((ts, fl))
    enriched.sort(key=lambda x: x[0])

    tol = timedelta(days=tolerance_days)
    clusters: List[List[Tuple[datetime, Dict[str, Any]]]] = []
    for ts, fl in enriched:
        if clusters and (ts - clusters[-1][-1][0]) <= tol:
            clusters[-1].append((ts, fl))
        else:
            clusters.append([(ts, fl)])

    out: List[Dict[str, Any]] = []
    for cluster in clusters:
        detectors = {item[1]["detector"] for item in cluster}
        if len(detectors) < 2:
            continue
        best = max(cluster, key=lambda x: x[1].get("confidence", 0.0))[1]
        merged = dict(best)
        meta = dict(merged.get("metadata") or {})
        meta["detectors"] = sorted(detectors)
        meta["vote_count"] = len(detectors)
        merged["metadata"] = meta
        worst = max(cluster, key=lambda x: _SEVERITY_RANK.get(x[1].get("severity", "low"), 0))[1]
        merged["severity"] = worst["severity"]
        out.append(merged)
    return out


def detect_anomalies(
    series: List[Dict[str, Any]],
    time_col: str,
    value_col: str,
    methods: Optional[List[str]] = None,
    seasonality: Optional[str] = "auto",
) -> List[Dict[str, Any]]:
    """Multi-algorithm anomaly detection + ensemble vote.

    Args:
        series: list[dict] satırlar.
        time_col: timestamp/date kolon adı.
        value_col: sayısal hedef kolon adı.
        methods: detector listesi; None → default (z_score+iqr+esd, +prophet if available).
        seasonality: "auto"/"weekday"/None → Z-score bucket modu.
    """
    if not isinstance(series, list) or not series:
        return []
    if not time_col or not value_col:
        return []
    points = _normalize(series, time_col, value_col)
    if len(points) < _MIN_POINTS:
        return []

    chosen = list(methods) if methods else list(_DEFAULT_METHODS)
    if methods is None and "prophet" not in chosen:
        chosen.append("prophet")

    all_flags: List[Dict[str, Any]] = []
    if "z_score" in chosen:
        all_flags.extend(_detect_z_score(points, seasonality))
    if "iqr" in chosen:
        all_flags.extend(_detect_iqr(points))
    if "esd" in chosen:
        all_flags.extend(_detect_esd(points))
    if "prophet" in chosen:
        all_flags.extend(_detect_prophet(points))

    return _ensemble_vote(all_flags)
