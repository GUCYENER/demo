"""VYRA v3.37.0 — LLM Metrik Oneri Servisi (METIS).

Smart Discovery Wizard Step 2 (Metrik) icin dinamik metrik onerisi uretir.

Sorumluluklar:
    - suggest_metrics(source_id, table, columns, user_intent) -> Dict
    - Merkezi LLM client (app.core.llm.call_llm_api) ile cagri yapar.
    - JSON response'unu parse + Pydantic validation.
    - Redis L1 cache (TTL 15 dk) — Redis dustugunde uncached passthrough.

Tasarim notlari:
    - Yeni LLM provider client KURULMAZ — DB'deki aktif config kullanilir.
    - Cache key: llm:metric:{source_id}:{table}:{sha256(columns_json)}:{sha256(user_intent or '')}
    - Cache backend: app.core.redis_cache.RedisCache (lazy singleton).
    - LLM cagrisi LLMConnectionError firlatabilir; caller (API layer) 503'e cevirir.
    - Bos columns listesi caller (API) tarafindan reddedilir (400).
    - Token budget: 30 kolon ile sinirli (RedisCache prompt size guard).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional

from app.core.llm import (
    LLMConfigError,
    LLMConnectionError,
    LLMResponseError,
    call_llm_api,
    get_active_llm,
)

logger = logging.getLogger(__name__)

# Cache parametreleri
_CACHE_TTL_SECONDS = 900  # 15 dk
_CACHE_KEY_PREFIX = "vyra:llm:metric:"
MAX_COLUMNS_FOR_PROMPT = 30
MAX_SUGGESTIONS = 5

# Izin verilen agregasyon enum'lari
ALLOWED_AGGS = {"SUM", "AVG", "COUNT", "MIN", "MAX", "COUNT_DISTINCT"}


# -------------------------------------------------------------
# Lazy Redis cache singleton (graceful fallback)
# -------------------------------------------------------------

_CACHE = None
_CACHE_LOCK = threading.Lock()
_CACHE_INIT_FAILED = False


def _get_cache():
    """Lazy singleton — Redis yoksa None doner, caller fallback yapar."""
    global _CACHE, _CACHE_INIT_FAILED
    if _CACHE is not None:
        return _CACHE
    if _CACHE_INIT_FAILED:
        return None
    with _CACHE_LOCK:
        if _CACHE is not None:
            return _CACHE
        if _CACHE_INIT_FAILED:
            return None
        try:
            from app.core.config import settings
            from app.core.redis_cache import RedisCache
            url = getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
            _CACHE = RedisCache(
                redis_url=url,
                default_ttl=_CACHE_TTL_SECONDS,
                key_prefix=_CACHE_KEY_PREFIX,
            )
        except Exception as e:
            logger.info("[llm_metric] cache init skipped: %s", e)
            _CACHE_INIT_FAILED = True
            _CACHE = None
    return _CACHE


def _sha256_short(text: str) -> str:
    """Sabit uzunluk hash — cache key icin."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _make_cache_key(
    source_id: int,
    table: str,
    columns: List[Dict[str, Any]],
    user_intent: Optional[str],
) -> str:
    """llm:metric:{source_id}:{table}:{sha256(columns)}:{sha256(intent)} formatinda key."""
    cols_canonical = json.dumps(
        [{"name": c.get("name"), "type": c.get("type")} for c in columns],
        sort_keys=True,
        ensure_ascii=False,
    )
    intent_norm = (user_intent or "").strip()
    return (
        f"{int(source_id)}:{table}:"
        f"{_sha256_short(cols_canonical)}:{_sha256_short(intent_norm)}"
    )


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    cache = _get_cache()
    if cache is None:
        return None
    try:
        raw = cache.get_raw(key)
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.debug("[llm_metric] cache_get failed key=%s: %s", key, e)
        return None


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    cache = _get_cache()
    if cache is None:
        return
    try:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cache.set_raw(key, raw, ttl=_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.debug("[llm_metric] cache_set failed key=%s: %s", key, e)


# -------------------------------------------------------------
# Prompt builder
# -------------------------------------------------------------

def _build_prompt(
    table: str,
    columns: List[Dict[str, Any]],
    user_intent: Optional[str],
) -> List[Dict[str, str]]:
    """Sistem + user mesajlarini olusturur."""
    cols_lines: List[str] = []
    for c in columns[:MAX_COLUMNS_FOR_PROMPT]:
        name = (c.get("name") or "").strip()
        ctype = (c.get("type") or "?").strip()
        if name:
            cols_lines.append(f"- {name} ({ctype})")
    cols_block = "\n".join(cols_lines) if cols_lines else "(kolon yok)"

    intent_block = ""
    if user_intent and user_intent.strip():
        intent_block = f"\n\nKullanici niyeti: {user_intent.strip()}"

    system_prompt = (
        "Sen veri analisti METIS'sin. Verilen kolonlar uzerinden BI metrikleri "
        "onerirsin. Cevabin SADECE JSON olmali, baska metin EKLEME. "
        "Maksimum 5 metrik oner. Her metrik icin: "
        "metric_name (kisa Turkce isim), agg (SUM/AVG/COUNT/MIN/MAX/COUNT_DISTINCT), "
        "formula (SQL ifadesi), rationale (kisa Turkce gerekce), "
        "confidence (0-1 arasi float)."
    )

    user_prompt = (
        f"Tablo: {table}\n"
        f"Kolonlar:\n{cols_block}"
        f"{intent_block}\n\n"
        "Cikti SADECE su JSON formatinda olsun:\n"
        "{\n"
        "  \"suggestions\": [\n"
        "    {\n"
        "      \"metric_name\": \"...\",\n"
        "      \"agg\": \"SUM\",\n"
        "      \"formula\": \"SUM(kolon_adi)\",\n"
        "      \"rationale\": \"...\",\n"
        "      \"confidence\": 0.9\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# -------------------------------------------------------------
# LLM JSON parsing — defensive
# -------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    """LLM cevabindan ilk {...} JSON nesnesini cek. ```json fence'i temizle."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, count=1)
        s = re.sub(r"\s*```\s*$", "", s, count=1)
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _validate_suggestions(raw_suggestions: Any) -> List[Dict[str, Any]]:
    """LLM cevabindaki suggestions listesini validate eder. Bozuk item'lar atilir."""
    if not isinstance(raw_suggestions, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw_suggestions[:MAX_SUGGESTIONS]:
        if not isinstance(item, dict):
            continue
        metric_name = (item.get("metric_name") or "").strip()
        agg_raw = (item.get("agg") or "").strip().upper()
        formula = (item.get("formula") or "").strip()
        rationale = (item.get("rationale") or "").strip()
        confidence = item.get("confidence")
        if not metric_name or not formula:
            continue
        if agg_raw not in ALLOWED_AGGS:
            # Bilinmeyen agg'i bypass: COUNT'a normalize etmek riskli, atla.
            continue
        try:
            conf_f = float(confidence) if confidence is not None else 0.5
        except (TypeError, ValueError):
            conf_f = 0.5
        # Confidence clamp [0,1]
        if conf_f < 0.0:
            conf_f = 0.0
        elif conf_f > 1.0:
            conf_f = 1.0
        out.append({
            "metric_name": metric_name[:200],
            "agg": agg_raw,
            "formula": formula[:500],
            "rationale": rationale[:500],
            "confidence": round(conf_f, 3),
        })
    return out


# -------------------------------------------------------------
# Public API
# -------------------------------------------------------------

def suggest_metrics(
    source_id: int,
    table: str,
    columns: List[Dict[str, Any]],
    user_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """Verilen kolonlar icin maks 5 metrik onerisi uretir.

    Returns:
        {
            "suggestions": [{metric_name, agg, formula, rationale, confidence}, ...],
            "cache_hit": bool,
            "model": "provider/model_name"  (best-effort, hata olursa "unknown")
        }

    Raises:
        LLMConnectionError: LLM ulasilamaz / timeout — caller 503 doner.
        LLMConfigError: Aktif LLM yapilandirilmamis — caller 503 doner.
        LLMResponseError: LLM JSON parse edilemedi — caller 502 doner.
    """
    if not columns:
        # Defensive — caller (API) zaten 400 firlatir; servis seviyesinde bos liste = bos cevap.
        return {"suggestions": [], "cache_hit": False, "model": "unknown"}

    cache_key = _make_cache_key(source_id, table, columns, user_intent)

    # 1) Cache lookup (Redis dustugunde sessizce gec)
    cached = _cache_get(cache_key)
    if cached and isinstance(cached.get("suggestions"), list):
        logger.info("[llm_metric] cache HIT key=%s", cache_key)
        return {
            "suggestions": cached.get("suggestions", []),
            "cache_hit": True,
            "model": cached.get("model", "unknown"),
        }

    # 2) Model adi (best-effort; LLM cagrisi oncesi)
    model_label = "unknown"
    try:
        cfg = get_active_llm()
        if cfg:
            provider = cfg.get("provider") or "?"
            model_name = cfg.get("model_name") or "?"
            model_label = f"{provider}/{model_name}"
    except Exception:
        # Model labeling kritik degil
        pass

    # 3) LLM cagrisi
    messages = _build_prompt(table=table, columns=columns, user_intent=user_intent)
    try:
        raw_response = call_llm_api(messages, temperature=0.2)
    except (LLMConnectionError, LLMConfigError):
        # Caller (API) bunu 503'e cevirir
        raise
    except Exception as e:
        # Beklenmeyen hata — LLMConnectionError'a wrap et
        logger.error("[llm_metric] unexpected LLM error: %s", e)
        raise LLMConnectionError(f"LLM cagrisi sirasinda beklenmeyen hata: {e}")

    # 4) JSON parse + validation
    parsed = _extract_json_obj(raw_response or "")
    if not parsed:
        logger.warning("[llm_metric] LLM JSON parse edilemedi, response=%r", (raw_response or "")[:200])
        raise LLMResponseError("LLM cevabi JSON formatinda degil.")

    suggestions = _validate_suggestions(parsed.get("suggestions"))
    payload = {
        "suggestions": suggestions,
        "model": model_label,
    }

    # 5) Cache yaz (Redis dustugunde sessizce gec)
    _cache_set(cache_key, payload)

    return {
        "suggestions": suggestions,
        "cache_hit": False,
        "model": model_label,
    }
