"""VYRA v3.37.4 — Save modal LLM baslik+aciklama oneri servisi.

Bulgular3 / Bulgu 8: "Raporu Kaydet" pop-up acildiginda kullaniciya
otomatik bir baslik + 1-2 cumlelik aciklama oner.

Endpoint: POST /api/db-smart/llm/report-meta-suggest
Cache:    Redis L1, TTL 15 dk (wizard_state hash).
"""
from __future__ import annotations

import hashlib
import json
import logging
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

_CACHE_TTL_SECONDS = 900
_CACHE_KEY_PREFIX = "vyra:llm:report-meta:"
MAX_TITLE_LEN = 120
MAX_DESC_LEN = 280

_CACHE = None
_CACHE_LOCK = threading.Lock()
_CACHE_INIT_FAILED = False


def _get_cache():
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
            logger.info("[llm_report_meta] cache init skipped: %s", e)
            _CACHE_INIT_FAILED = True
            _CACHE = None
    return _CACHE


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _make_cache_key(
    table_label: Optional[str],
    metric_names: List[str],
    columns: List[str],
    filters_count: int,
    user_intent: Optional[str],
) -> str:
    canonical = json.dumps(
        {
            "t": (table_label or "").strip(),
            "m": sorted([(n or "").strip() for n in metric_names if n]),
            "c": sorted([(c or "").strip() for c in columns if c]),
            "f": int(filters_count or 0),
            "u": (user_intent or "").strip(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return _sha256_short(canonical)


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
        logger.debug("[llm_report_meta] cache_get failed: %s", e)
        return None


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    cache = _get_cache()
    if cache is None:
        return
    try:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        cache.set_raw(key, raw, ttl=_CACHE_TTL_SECONDS)
    except Exception as e:
        logger.debug("[llm_report_meta] cache_set failed: %s", e)


def _build_prompt(
    table_label: Optional[str],
    metric_names: List[str],
    columns: List[str],
    filters_count: int,
    user_intent: Optional[str],
) -> List[Dict[str, str]]:
    system_prompt = (
        "Sen veri analisti METIS'sin. Verilen rapor konfigurasyonu icin "
        "kullaniciya kisa, anlamli bir Turkce baslik ve 1-2 cumlelik aciklama "
        "onerirsin. Cevabin SADECE JSON, baska metin EKLEME.\n"
        "- title: 8 kelimeyi gecmesin, ust-cumle (Title Case veya Cumlede Buyuk).\n"
        "- description: 1-2 cumle, raporun ne anlattigini ozetlesin.\n"
        "- Emoji veya markdown YASAK.\n"
        "Format: {\"title\": \"...\", \"description\": \"...\"}"
    )

    metric_block = ", ".join([m for m in metric_names if m]) or "(metrik secilmemis)"
    cols_block = ", ".join(columns[:20]) or "(kolon yok)"
    intent_block = (user_intent or "").strip() or "(kullanici niyeti belirtilmemis)"
    table_line = (table_label or "").strip() or "(tablo bilinmiyor)"

    user_prompt = (
        f"Tablo: {table_line}\n"
        f"Metrikler: {metric_block}\n"
        f"Raporda gorunen kolonlar: {cols_block}\n"
        f"Filtre sayisi: {int(filters_count or 0)}\n"
        f"Kullanici niyeti: {intent_block}\n\n"
        "JSON ciktisini SADECE su sablona uygun ver:\n"
        "{\n"
        "  \"title\": \"...\",\n"
        "  \"description\": \"...\"\n"
        "}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    import re
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
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def suggest_report_meta(
    table_label: Optional[str],
    metric_names: List[str],
    columns: List[str],
    filters_count: int = 0,
    user_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """Save modal icin baslik + aciklama oner.

    Returns: {"title": str, "description": str, "cache_hit": bool, "model": str}
    Raises:  LLMConnectionError / LLMConfigError / LLMResponseError
    """
    cache_key = _make_cache_key(
        table_label, metric_names, columns, filters_count, user_intent,
    )

    cached = _cache_get(cache_key)
    if cached and cached.get("title"):
        return {
            "title": str(cached.get("title") or "")[:MAX_TITLE_LEN],
            "description": str(cached.get("description") or "")[:MAX_DESC_LEN],
            "cache_hit": True,
            "model": str(cached.get("model") or "unknown"),
        }

    model_label = "unknown"
    try:
        cfg = get_active_llm()
        if cfg:
            model_label = f"{cfg.get('provider') or '?'}/{cfg.get('model_name') or '?'}"
    except Exception:
        pass

    messages = _build_prompt(
        table_label=table_label,
        metric_names=metric_names,
        columns=columns,
        filters_count=filters_count,
        user_intent=user_intent,
    )
    try:
        raw_response = call_llm_api(messages, temperature=0.4)
    except (LLMConnectionError, LLMConfigError):
        raise
    except Exception as e:
        logger.error("[llm_report_meta] unexpected LLM error: %s", e)
        raise LLMConnectionError(f"LLM cagrisi sirasinda beklenmeyen hata: {e}")

    parsed = _extract_json_obj(raw_response or "")
    if not parsed:
        raise LLMResponseError("LLM cevabi JSON formatinda degil.")

    title = str(parsed.get("title") or "").strip()[:MAX_TITLE_LEN]
    description = str(parsed.get("description") or "").strip()[:MAX_DESC_LEN]
    if not title:
        raise LLMResponseError("LLM bos baslik dondu.")

    payload = {"title": title, "description": description, "model": model_label}
    _cache_set(cache_key, payload)

    return {
        "title": title,
        "description": description,
        "cache_hit": False,
        "model": model_label,
    }
