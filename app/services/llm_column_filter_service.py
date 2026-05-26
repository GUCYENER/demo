"""VYRA v3.37.1 — Metric-Aware Column Filter Service (Bulgu D).

POST /api/db-smart/llm/column-filter-suggest endpoint'inin servis katmani.

Amac
----
Step3'te kullaniciya "secili metrik ile uyumlu kolonlar" listesi sunmak ve
metrikle uyumsuz kolon eklendiginde uyari uretmek.

Tasarim karari (ZEUS direct-apply, 2026-05-26):
- Bu v3.37.1 MVP icin **deterministik** kurallarla calisir; LLM cagrisi YOK.
- Kullanici bulgusu (Madde 5) once "validation toast + ayri kategori" istiyor.
- POSEIDON tarafindan onaylanan kurallar (brief D Acceptance #1-#3):
    * Metric kind 'amount'/'sum'   -> numeric semantic_type tercih
    * Metric kind 'growth'/'trend' -> datetime + numeric ikilisi gerekir
    * Metric kind 'count'          -> herhangi PK/kategorik OK
- LLM tabanli "rationale" + cache'leme v3.37.2'ye birakildi (Phase 2).

API kontrati
------------
Input  : source_id, metric_key (str veya None), metric_kind (opsiyonel),
         candidates: [{name, semantic_type, table_id, ...}], user_intent (opsiyonel)
Output : {recommended: [{column_name, table_id, rationale, relevance}],
          warn_columns: [{column_name, reason}],
          cache_hit: bool}

Cache
-----
Su an cache yok (deterministik kurallar < 1ms). Phase 2'de LLM eklendiginde
llm_column_service paterni (Redis 15dk TTL) buraya da uygulanir.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# POSEIDON: Metric kind <-> semantic_type compatibility matrix
# ─────────────────────────────────────────────────────────────

NUMERIC_TOKENS = ("numeric", "number", "integer", "int", "float", "decimal",
                  "double", "real", "money", "amount", "currency")
DATETIME_TOKENS = ("date", "time", "timestamp", "datetime")
CATEGORICAL_TOKENS = ("text", "string", "varchar", "char", "category",
                      "categorical", "enum")
IDENTIFIER_TOKENS = ("id", "uuid", "key", "pk", "primary_key")

# Metric kind ipuclari (metric_key veya metric_kind'tan cikar)
AMOUNT_KEYWORDS = ("amount", "sum", "total", "tutar", "ciro", "revenue",
                   "gelir", "gider", "cost", "maliyet", "kazanc", "kar")
GROWTH_KEYWORDS = ("growth", "trend", "change", "delta", "buyume", "artis",
                   "ratio", "rate", "oran")
COUNT_KEYWORDS = ("count", "adet", "say", "frequency", "siklik")
AVG_KEYWORDS = ("avg", "average", "ortalama", "mean")


def _semantic_bucket(semantic_type: Optional[str]) -> str:
    """Map raw semantic_type string to one of: numeric|datetime|categorical|identifier|unknown."""
    if not semantic_type:
        return "unknown"
    s = str(semantic_type).lower().strip()
    if any(tok in s for tok in IDENTIFIER_TOKENS) and "id" in s:
        return "identifier"
    if any(tok in s for tok in NUMERIC_TOKENS):
        return "numeric"
    if any(tok in s for tok in DATETIME_TOKENS):
        return "datetime"
    if any(tok in s for tok in CATEGORICAL_TOKENS):
        return "categorical"
    return "unknown"


def _infer_metric_kind(metric_key: Optional[str], metric_kind: Optional[str]) -> str:
    """Return one of: amount|growth|count|avg|unknown."""
    if metric_kind:
        mk = metric_kind.lower().strip()
        if mk in {"amount", "sum"}:
            return "amount"
        if mk in {"growth", "trend"}:
            return "growth"
        if mk in {"count"}:
            return "count"
        if mk in {"avg", "average", "mean"}:
            return "avg"
    if metric_key:
        mk = metric_key.lower()
        if any(k in mk for k in GROWTH_KEYWORDS):
            return "growth"
        if any(k in mk for k in COUNT_KEYWORDS):
            return "count"
        if any(k in mk for k in AVG_KEYWORDS):
            return "avg"
        if any(k in mk for k in AMOUNT_KEYWORDS):
            return "amount"
    return "unknown"


# ─────────────────────────────────────────────────────────────
# Skor + uyari kurallari
# ─────────────────────────────────────────────────────────────

def _score_candidate(
    bucket: str, metric_kind: str
) -> tuple[float, str]:
    """Return (relevance 0..1, rationale)."""
    if metric_kind == "amount":
        if bucket == "numeric":
            return 0.95, "Toplam/tutar metrigi numeric kolonlarla hesaplanir."
        if bucket == "datetime":
            return 0.55, "Donem/grup kirilimi icin yararli (tarih)."
        if bucket == "categorical":
            return 0.40, "Boyut kirilimi icin kullanilabilir."
        if bucket == "identifier":
            return 0.30, "Kimlik kolonu; gruplamada PK olarak kullanilabilir."
        return 0.20, "Semantik belirsiz."

    if metric_kind == "growth":
        if bucket == "datetime":
            return 0.95, "Buyume/trend metrigi tarih ekseni gerektirir."
        if bucket == "numeric":
            return 0.85, "Trend hesabi icin numeric deger gerekli."
        if bucket == "categorical":
            return 0.40, "Boyut kirilimi (segment-bazli trend)."
        return 0.25, "Semantik trend icin uygunsuz."

    if metric_kind == "count":
        if bucket == "identifier":
            return 0.90, "Adet metrigi PK/UUID sayimi icin uygun."
        if bucket == "categorical":
            return 0.70, "Kategori bazli sayim icin uygun."
        if bucket == "datetime":
            return 0.60, "Donem icindeki adet kirilimi."
        if bucket == "numeric":
            return 0.40, "Sayim icin sart degil ama kullanilabilir."
        return 0.30, "Semantik belirsiz."

    if metric_kind == "avg":
        if bucket == "numeric":
            return 0.90, "Ortalama icin numeric sart."
        if bucket == "datetime":
            return 0.50, "Donem kirilimi."
        if bucket == "categorical":
            return 0.40, "Grup bazli ortalama."
        return 0.25, "Semantik belirsiz."

    # unknown metric kind -> orta seviye, hicbirini ele
    return 0.50, "Metrik tipi cikartilamadi; manuel inceleyin."


def _warn_reason(bucket: str, metric_kind: str) -> Optional[str]:
    """Return reason if the column is incompatible with metric, else None."""
    if metric_kind == "amount" and bucket in {"identifier"}:
        return "semantic_mismatch: amount/sum metrigi icin numeric kolon onerilir"
    if metric_kind == "growth" and bucket in {"identifier", "categorical"}:
        return "semantic_mismatch: trend/growth metrigi datetime+numeric gerektirir"
    if metric_kind == "avg" and bucket in {"identifier", "categorical"}:
        return "semantic_mismatch: ortalama metrigi numeric kolon gerektirir"
    return None


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def suggest_metric_aware_columns(
    source_id: int,
    metric_key: Optional[str],
    metric_kind: Optional[str],
    candidates: Sequence[Dict[str, Any]],
    user_intent: Optional[str] = None,
    top_n: int = 10,
) -> Dict[str, Any]:
    """Deterministik POSEIDON degerlendirme.

    Returns
    -------
    {
      "recommended": [{column_name, table_id, rationale, relevance}],
      "warn_columns": [{column_name, reason}],
      "cache_hit": False,
      "metric_kind_inferred": str,
    }
    """
    inferred_kind = _infer_metric_kind(metric_key, metric_kind)
    recommended: List[Dict[str, Any]] = []
    warn_columns: List[Dict[str, Any]] = []

    for col in candidates:
        name = (col.get("name") or col.get("column_name") or "").strip()
        if not name:
            continue
        bucket = _semantic_bucket(col.get("semantic_type") or col.get("type"))
        relevance, rationale = _score_candidate(bucket, inferred_kind)
        table_id = col.get("table_id")
        recommended.append({
            "column_name": name,
            "table_id": table_id,
            "rationale": rationale,
            "relevance": round(relevance, 2),
            "semantic_bucket": bucket,
        })
        warn = _warn_reason(bucket, inferred_kind)
        if warn:
            warn_columns.append({
                "column_name": name,
                "reason": warn,
                "table_id": table_id,
            })

    # Sort by relevance desc, kes top_n
    recommended.sort(key=lambda r: r["relevance"], reverse=True)
    recommended = recommended[:top_n]

    logger.info(
        "[column_filter_service] source_id=%s metric_key=%r kind=%s "
        "candidates=%d recommended=%d warns=%d",
        source_id, metric_key, inferred_kind,
        len(candidates), len(recommended), len(warn_columns),
    )

    return {
        "recommended": recommended,
        "warn_columns": warn_columns,
        "cache_hit": False,
        "metric_kind_inferred": inferred_kind,
    }
