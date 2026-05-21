"""Narrative Generation for DB Smart Wizard insights (FAZ 4 P33).

Template-fill LLM ile sayısal insight'ları doğal dil cümlesine çevirir.
Feature-gated: system_settings.narrative_enabled (default FALSE).

Güvenlik:
    - Sayılar SQL/recommendation'dan gelir (LLM'den değil).
    - LLM sadece template placeholder'ları dolduruyor.
    - Rationality guard: LLM çıktısındaki sayılar template verisiyle
      eşleşmezse narrative drop edilir (hallucination koruması).

Tasarım:
    - Temperature 0.4, max 120 token.
    - LLM yoksa veya hata verirse sessizce None döner.
    - Prometheus counter: narrative_dropped_total (guard trigger).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Template registry
# ─────────────────────────────────────────────────────────────

_TEMPLATES: Dict[str, Dict[str, str]] = {
    "trend_up": {
        "tr": "{metric} geçen {period}'a göre **{pct}** artış gösterdi, en yüksek artış {top_dim}'de (**{top_pct}**).",
        "en": "{metric} is up **{pct}** vs last {period}, with the largest increase in {top_dim} (**{top_pct}**).",
    },
    "trend_down": {
        "tr": "{metric} geçen {period}'a göre **{pct}** düşüş gösterdi, en belirgin azalma {top_dim}'de (**{top_pct}**).",
        "en": "{metric} is down **{pct}** vs last {period}, with the steepest decline in {top_dim} (**{top_pct}**).",
    },
    "outlier_high": {
        "tr": "{dim}'deki {metric} değeri (**{value}**) ortalamanın {z_score}σ üzerinde — olağandışı yüksek.",
        "en": "{metric} in {dim} (**{value}**) is {z_score}σ above the mean — unusually high.",
    },
    "anomaly_seasonal": {
        "tr": "{date}'de {metric} mevsimsel beklentinin **{pct}** üzerinde — {detector} ile tespit edildi.",
        "en": "{metric} on {date} was **{pct}** above seasonal expectation — detected by {detector}.",
    },
    "missing_category": {
        "tr": "{dim} boyutunda beklenen {expected_count} kategoriden {missing_count} tanesi mevcut dönemde hiç görülmedi.",
        "en": "Of {expected_count} expected categories in {dim}, {missing_count} were absent in the current period.",
    },
    "stable": {
        "tr": "{metric} son {period} boyunca sabit seyretti (±{range_pct}). Önemli bir değişiklik tespit edilmedi.",
        "en": "{metric} remained stable over the last {period} (±{range_pct}). No significant change detected.",
    },
}


def _load_template(insight_type: str, lang: str = "tr") -> Optional[str]:
    """Template registry'den insight tipine göre şablon döner."""
    templates = _TEMPLATES.get(insight_type)
    if not templates:
        return None
    return templates.get(lang) or templates.get("tr")


# ─────────────────────────────────────────────────────────────
# Rationality guard
# ─────────────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?%?")


def _apply_rationality_guard(
    narrative: str,
    expected_numbers: Dict[str, str],
    tolerance: float = 0.01,
) -> bool:
    """LLM çıktısındaki sayıların template verisiyle tutarlılığını kontrol eder.

    Returns True if all expected numbers found in narrative (within tolerance).
    """
    if not expected_numbers or not narrative:
        return True

    found_numbers = _NUMBER_RE.findall(narrative)
    found_clean = set()
    for n in found_numbers:
        clean = n.replace(",", ".").replace("%", "").replace("+", "")
        try:
            found_clean.add(float(clean))
        except ValueError:
            continue

    for key, expected_str in expected_numbers.items():
        clean_exp = str(expected_str).replace(",", ".").replace("%", "").replace("+", "")
        try:
            expected_val = float(clean_exp)
        except ValueError:
            continue

        # Check if any found number matches within tolerance
        matched = any(
            abs(f - expected_val) <= abs(expected_val * tolerance) + 0.01
            for f in found_clean
        )
        if not matched:
            logger.warning(
                "[narrative] rationality guard: expected %s=%s not found in output",
                key, expected_str,
            )
            return False

    return True


# ─────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────

def generate_narrative(
    insights: List[Dict[str, Any]],
    recommendation: Dict[str, Any],
    lang: str = "tr",
    *,
    _settings_check: bool = True,
) -> Optional[str]:
    """insight + recommendation'dan doğal dil özet cümlesi üretir.

    Feature-gated: system_settings.narrative_enabled=FALSE ise None döner.
    LLM hatası, adapter yokluğu, rationality guard tetiklenirse → None.

    Args:
        insights: detect_* fonksiyonlarından gelen insight dict listesi.
        recommendation: recommend_charts/detect_insights çıktısı.
        lang: 'tr' veya 'en'.
        _settings_check: test'lerde False geçilebilir (feature flag bypass).

    Returns:
        Natural language paragraph or None.
    """
    # Feature gate
    if _settings_check:
        try:
            from app.core.config import settings
            if not getattr(settings, "NARRATIVE_ENABLED", False):
                return None
        except Exception:
            return None

    if not insights:
        return None

    # Pick the most significant insight
    primary = max(insights, key=lambda i: i.get("confidence", 0))
    insight_type = primary.get("type", "")

    # Build template params from insight + recommendation
    params: Dict[str, str] = {}
    meta = primary.get("metadata", {}) or {}
    params["metric"] = meta.get("metric_name") or recommendation.get("metric_name", "Metrik")
    params["period"] = meta.get("period") or "ay"
    params["dim"] = meta.get("dimension") or meta.get("top_dimension", "")
    params["top_dim"] = meta.get("top_dimension") or params["dim"] or "bilinmiyor"
    params["date"] = meta.get("date", "")
    params["detector"] = primary.get("detector", "")

    # Numeric values for template + guard
    value = primary.get("value")
    baseline = primary.get("baseline")
    if value is not None and baseline and baseline != 0:
        pct = (value - baseline) / abs(baseline)
        params["pct"] = f"{pct:+.1%}"
    elif value is not None:
        params["pct"] = str(value)
    else:
        params["pct"] = "N/A"

    params["value"] = str(value) if value is not None else ""
    params["z_score"] = f"{meta.get('z_score', 0):.1f}" if "z_score" in meta else ""
    params["top_pct"] = meta.get("top_pct", params["pct"])
    params["expected_count"] = str(meta.get("expected_count", ""))
    params["missing_count"] = str(meta.get("missing_count", ""))
    params["range_pct"] = meta.get("range_pct", "2%")

    # Map insight type to template key
    template_key = insight_type
    if insight_type in ("anomaly", "anomaly_seasonal"):
        template_key = "anomaly_seasonal"
    elif insight_type == "trend_reversal":
        template_key = "trend_down" if value is not None and baseline is not None and value < baseline else "trend_up"

    template = _load_template(template_key, lang)
    if not template:
        logger.debug("[narrative] no template for insight_type=%s", insight_type)
        return None

    # Try simple template fill first (no LLM needed for basic cases)
    try:
        narrative = template.format(**params)
    except (KeyError, IndexError):
        logger.debug("[narrative] template fill failed, attempting LLM")
        narrative = None

    if narrative:
        # Rationality guard on template output
        expected_nums = {k: v for k, v in params.items()
                         if k in ("pct", "value", "z_score", "top_pct") and v and v != "N/A"}
        if _apply_rationality_guard(narrative, expected_nums):
            return narrative
        else:
            _increment_dropped_counter()
            return None

    # Fallback: try LLM for richer narrative
    try:
        from app.core.llm import call_llm_api
    except ImportError:
        logger.debug("[narrative] LLM adapter not found, narrative disabled")
        return None

    prompt = (
        f"Aşağıdaki veri analizini kısa bir Türkçe paragraf olarak özetle. "
        f"Sadece verilen sayıları kullan, yeni sayı üretme.\n\n"
        f"Insight: {primary}\nÖneri: {recommendation.get('chart_type', 'tablo')}\n"
        f"Template: {template}\nParametreler: {json.dumps(params, ensure_ascii=False)}"
    )

    try:
        import json as _json
        response = call_llm_api(
            [{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=120,
        )
        if not response:
            return None

        llm_text = response if isinstance(response, str) else str(response)

        # Rationality guard on LLM output
        expected_nums = {k: v for k, v in params.items()
                         if k in ("pct", "value", "z_score", "top_pct") and v and v != "N/A"}
        if _apply_rationality_guard(llm_text, expected_nums):
            return llm_text.strip()
        else:
            _increment_dropped_counter()
            logger.warning("[narrative] LLM output failed rationality guard, dropped")
            return None
    except Exception as e:
        logger.warning("[narrative] LLM call failed: %s", e)
        return None


def _increment_dropped_counter():
    """Prometheus counter artır (varsa)."""
    try:
        from app.services.observability.prometheus_metrics import get as _metric
        _metric("narrative_dropped_total").inc()
    except Exception:
        pass
