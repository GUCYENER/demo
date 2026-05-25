"""VYRA v3.37.0 — LLM Column Suggest Service (B5b).

Bir metrik (metric_name + agg + formula) ve aday kolon listesi verildiğinde
LLM çağırıp kolonları iki kategoriye ayırır:

    1. metric_bound        — metriğe DOĞRUDAN katkı veren kolonlar
                             (örn. SUM(tutar) → "tutar")
    2. related_dimensions  — boyut/grup kırılımı için ANLAMLI kolonlar
                             (örn. tarih, sehir, musteri_id)

Tarih kolonları için ek olarak `suggested_grain` (day/month/quarter/year)
istenir.

Cache:
    - Redis (vyra:llm:column:* prefix), TTL 900 sn (15 dk).
    - Redis down → uncached passthrough.

Provider:
    - app.core.llm.call_llm_api kullanılır (DB aktif config).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────

CACHE_TTL_SECONDS = 900  # 15 dk
CACHE_KEY_PREFIX = "llm:column:"
VALID_GRAINS = {"day", "week", "month", "quarter", "year"}
DATE_TYPE_TOKENS = ("date", "time", "timestamp", "datetime")

_SYSTEM_PROMPT = (
    "Sen VYRA Akıllı Veri Keşfi asistanısın. Görevin: verilen METRİK için "
    "aday kolonları iki kategoriye ayırmak.\n"
    "1) metric_bound   : Metriğin formülüne DOĞRUDAN giren kolonlar.\n"
    "2) related_dimensions : Metriği gruplamak/kırılım almak için anlamlı boyutlar.\n"
    "Tarih/timestamp kolonları için 'suggested_grain' alanı doldur "
    "(day, month, quarter, year değerlerinden biri).\n"
    "Yanıtı SADECE JSON formatında ver. Açıklama yazma. Backtick kullanma."
)


# ─────────────────────────────────────────────────────────────
# Cache backend
# ─────────────────────────────────────────────────────────────

_cache_instance = None
_cache_lock = threading.Lock()


def _get_cache():
    """Lazy Redis cache singleton. Hata → None (uncached fallback)."""
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance
    with _cache_lock:
        if _cache_instance is not None:
            return _cache_instance
        try:
            from app.core.config import settings
            from app.core.redis_cache import RedisCache
            url = getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
            _cache_instance = RedisCache(
                redis_url=url,
                default_ttl=CACHE_TTL_SECONDS,
                key_prefix="vyra:llm:column:",
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[llm_column_service] cache init failed: %s", e)
            _cache_instance = None
    return _cache_instance


def _reset_cache_for_tests() -> None:
    """Test yardımcısı — singleton'u sıfırla."""
    global _cache_instance
    with _cache_lock:
        _cache_instance = None


# ─────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _build_cache_key(
    metric_name: str,
    table: str,
    columns: List[Dict[str, Any]],
) -> str:
    cols_canon = json.dumps(
        sorted(
            [{"name": c.get("name"), "type": c.get("type")} for c in columns],
            key=lambda x: (x.get("name") or ""),
        ),
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"{CACHE_KEY_PREFIX}{_sha256(metric_name)}:{table}:{_sha256(cols_canon)}"


def _is_date_column(col_type: Optional[str]) -> bool:
    if not col_type:
        return False
    t = str(col_type).lower()
    return any(tok in t for tok in DATE_TYPE_TOKENS)


def _columns_in_formula(formula: Optional[str], columns: List[Dict[str, Any]]) -> List[str]:
    """Formula içinde geçen kolon adlarını döner (case-insensitive token match)."""
    if not formula:
        return []
    f = formula.lower()
    hits: List[str] = []
    for c in columns:
        name = (c.get("name") or "").strip()
        if name and name.lower() in f:
            hits.append(name)
    return hits


def _build_user_prompt(
    table: str,
    metric: Dict[str, Any],
    columns: List[Dict[str, Any]],
) -> str:
    payload = {
        "table": table,
        "metric": {
            "metric_name": metric.get("metric_name"),
            "agg": metric.get("agg"),
            "formula": metric.get("formula"),
        },
        "available_columns": [
            {"name": c.get("name"), "type": c.get("type")} for c in columns
        ],
    }
    return (
        "Aşağıdaki METRİK ve aday kolonları değerlendir.\n\n"
        f"GIRDI:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "ÇIKTI ŞEMASI (sadece JSON):\n"
        "{\n"
        '  "metric_bound": [\n'
        '    {"column": "<ad>", "rationale": "<kısa>", "confidence": 0.0-1.0}\n'
        "  ],\n"
        '  "related_dimensions": [\n'
        '    {"column": "<ad>", "rationale": "<kısa>", "confidence": 0.0-1.0, "suggested_grain": "month"}\n'
        "  ]\n"
        "}\n"
        "Kurallar:\n"
        "- metric_bound: formüldeki kolonlar mutlaka burada olmalı.\n"
        "- related_dimensions: gruplama/kırılım için anlamlı boyutlar.\n"
        "- suggested_grain SADECE tarih/timestamp kolonlarında zorunlu; diğerlerinde yazma.\n"
        "- Hiç uygun yoksa boş liste dön."
    )


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # Üç-backtick blokları sıyır
        t = t.strip("`")
        # Olası "json\n..." prefix'i
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
        # Sondaki ``` kalıntısı
        if t.endswith("```"):
            t = t[:-3].strip()
    return t


def _coerce_entry(
    raw: Any,
    valid_names: set,
    *,
    require_grain: bool = False,
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    col = raw.get("column") or raw.get("name")
    if not col or col not in valid_names:
        return None
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else 0.7
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))
    entry: Dict[str, Any] = {
        "column": col,
        "rationale": str(raw.get("rationale") or "").strip()[:280],
        "confidence": round(confidence, 3),
    }
    grain = raw.get("suggested_grain")
    if grain and grain in VALID_GRAINS:
        entry["suggested_grain"] = grain
    elif require_grain:
        entry["suggested_grain"] = "month"
    return entry


def _validate_and_normalize(
    parsed: Dict[str, Any],
    metric: Dict[str, Any],
    columns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    valid_names = {c.get("name") for c in columns if c.get("name")}
    date_names = {c.get("name") for c in columns if _is_date_column(c.get("type"))}

    metric_bound_raw = parsed.get("metric_bound") or []
    related_raw = parsed.get("related_dimensions") or []
    if not isinstance(metric_bound_raw, list):
        metric_bound_raw = []
    if not isinstance(related_raw, list):
        related_raw = []

    metric_bound: List[Dict[str, Any]] = []
    seen_mb: set = set()
    for raw in metric_bound_raw:
        entry = _coerce_entry(raw, valid_names)
        if entry and entry["column"] not in seen_mb:
            # Grain metric_bound'da nadiren anlamlı — sadece date ise tut
            if "suggested_grain" in entry and entry["column"] not in date_names:
                entry.pop("suggested_grain", None)
            metric_bound.append(entry)
            seen_mb.add(entry["column"])

    # Formula'daki kolonları metric_bound'a zorla
    formula_cols = _columns_in_formula(metric.get("formula"), columns)
    for fc in formula_cols:
        if fc not in seen_mb:
            metric_bound.append({
                "column": fc,
                "rationale": "Metriğin formülünde geçiyor.",
                "confidence": 1.0,
            })
            seen_mb.add(fc)

    related: List[Dict[str, Any]] = []
    seen_rel: set = set()
    for raw in related_raw:
        entry = _coerce_entry(
            raw,
            valid_names,
            require_grain=(raw.get("column") in date_names) if isinstance(raw, dict) else False,
        )
        if not entry:
            continue
        # metric_bound'a giren kolon related'da tekrar etmesin
        if entry["column"] in seen_mb:
            continue
        if entry["column"] in seen_rel:
            continue
        # Date kolonu ise grain garantile
        if entry["column"] in date_names and "suggested_grain" not in entry:
            entry["suggested_grain"] = "month"
        related.append(entry)
        seen_rel.add(entry["column"])

    return {
        "metric_bound": metric_bound,
        "related_dimensions": related,
    }


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def suggest_columns(
    source_id: int,
    table: str,
    metric: Dict[str, Any],
    columns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """LLM ile kolon önerisi.

    Args:
        source_id: data_source.id
        table: tablo adı (cache key + prompt)
        metric: {"metric_name": str, "agg": str, "formula": str}
        columns: [{"name": str, "type": str}, ...]

    Returns:
        {
            "metric_bound": [...],
            "related_dimensions": [...],
            "cache_hit": bool,
            "model": str,
        }
    """
    metric_name = (metric or {}).get("metric_name") or ""
    if not metric_name:
        raise ValueError("metric.metric_name boş olamaz")
    if not table:
        raise ValueError("table boş olamaz")
    if not isinstance(columns, list) or not columns:
        raise ValueError("available_columns boş olamaz")

    cache_key = _build_cache_key(metric_name, table, columns)
    cache = _get_cache()

    # 1) Cache lookup
    if cache is not None:
        try:
            cached = cache.get(cache_key)
            if cached and isinstance(cached, dict):
                resp = dict(cached)
                resp["cache_hit"] = True
                return resp
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("[llm_column_service] cache get error: %s", e)

    # 2) LLM çağrısı
    from app.core.llm import call_llm_api  # lazy import → test kolaylığı

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(table, metric, columns)},
    ]

    raw_response = call_llm_api(messages, temperature=0.2)
    cleaned = _strip_code_fences(raw_response or "")

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("[llm_column_service] JSON parse failed: %s | raw=%r", e, cleaned[:200])
        # Boş ama formula-fallback ile minimal bir cevap
        parsed = {"metric_bound": [], "related_dimensions": []}

    normalized = _validate_and_normalize(parsed, metric, columns)

    model_name = _resolve_active_model()

    payload = {
        "metric_bound": normalized["metric_bound"],
        "related_dimensions": normalized["related_dimensions"],
        "model": model_name,
    }

    # 3) Cache yaz
    if cache is not None:
        try:
            cache.set(cache_key, payload, ttl=CACHE_TTL_SECONDS)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("[llm_column_service] cache set error: %s", e)

    out = dict(payload)
    out["cache_hit"] = False
    return out


def _resolve_active_model() -> str:
    """Aktif LLM model adını DB'den çek. Hata → 'unknown'."""
    try:
        from app.core.llm import get_active_llm
        cfg = get_active_llm()
        if cfg:
            return str(cfg.get("model_name") or cfg.get("provider") or "unknown")
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("[llm_column_service] resolve model error: %s", e)
    return "unknown"
