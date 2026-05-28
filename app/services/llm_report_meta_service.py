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
    extract_json_obj,
    get_active_llm,
)
from app.services._llm_cache_util import LlmRedisCache, sha256_short

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 900
_CACHE_KEY_PREFIX = "vyra:llm:report-meta:"
MAX_TITLE_LEN = 120
MAX_DESC_LEN = 280

# Bulgular3 / Review fix #5: shared LlmRedisCache facade (DRY)
_CACHE = LlmRedisCache(prefix=_CACHE_KEY_PREFIX, ttl_seconds=_CACHE_TTL_SECONDS)


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
    return sha256_short(canonical)


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    return _CACHE.get(key)


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    _CACHE.set(key, payload)


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


# Bulgular3 / Review fix #3: shared balanced-brace parser (app.core.llm).
_extract_json_obj = extract_json_obj


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
