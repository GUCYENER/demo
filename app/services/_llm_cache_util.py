"""Bulgular3 / Review fix #5 — Shared LLM Redis cache helper.

llm_metric_service ve llm_report_meta_service'in cache patterni %90 ayni:
- Lazy singleton RedisCache init (Redis dustugunde sessizce None doner)
- _sha256_short, _make_cache_key (servise gore custom)
- _cache_get / _cache_set raw JSON bytes
- TTL ortak (15 dk)

Bu modul ortak prefix + TTL bazli minik bir cache facade saglar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def sha256_short(text: str, length: int = 16) -> str:
    """Sabit-uzunluk hex digest — cache key fragmanlari icin."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


class LlmRedisCache:
    """Bir LLM servisi icin lazy-init Redis cache facade'i.

    Kullanim:
        _CACHE = LlmRedisCache(prefix="vyra:llm:metric:", ttl_seconds=900)
        cached = _CACHE.get(key)
        _CACHE.set(key, payload_dict)

    Redis baglanamazsa get None, set no-op doner — caller akisi degismez.
    """

    def __init__(self, prefix: str, ttl_seconds: int = 900) -> None:
        self._prefix = str(prefix or "vyra:llm:")
        self._ttl = int(ttl_seconds or 900)
        self._cache: Any = None
        self._init_failed = False
        self._lock = threading.Lock()

    def _get_backend(self):
        if self._cache is not None:
            return self._cache
        if self._init_failed:
            return None
        with self._lock:
            if self._cache is not None:
                return self._cache
            if self._init_failed:
                return None
            try:
                from app.core.config import settings
                from app.core.redis_cache import RedisCache
                url = getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
                self._cache = RedisCache(
                    redis_url=url,
                    default_ttl=self._ttl,
                    key_prefix=self._prefix,
                )
            except Exception as e:
                logger.info("[llm_cache] %s init skipped: %s", self._prefix, e)
                self._init_failed = True
                self._cache = None
        return self._cache

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        backend = self._get_backend()
        if backend is None:
            return None
        try:
            raw = backend.get_raw(key)
            if not raw:
                return None
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.debug("[llm_cache] %s get failed key=%s: %s", self._prefix, key, e)
            return None

    def set(self, key: str, payload: Dict[str, Any]) -> None:
        backend = self._get_backend()
        if backend is None:
            return
        try:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            backend.set_raw(key, raw, ttl=self._ttl)
        except Exception as e:
            logger.debug("[llm_cache] %s set failed key=%s: %s", self._prefix, key, e)
