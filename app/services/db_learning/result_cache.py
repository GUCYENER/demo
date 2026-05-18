"""VYRA v3.27.0 — Result Fingerprint Cache (C.G7).

SQL sonuçlarını Redis'te kısa süreli cache'ler. Aynı SQL aynı kaynak
üzerinde TTL içinde tekrar çalıştırılırsa DB'ye gitmeden döndürür.

Key formatı: ``sql_result:{sha256(canonical_sql)}:{source_id}``
TTL: 300 saniye (varsayılan, settings.SQL_RESULT_CACHE_TTL ile override).

Backend: ``app.core.redis_cache.RedisCache``. Redis yoksa in-memory
fallback (RedisCache içinde zaten var). Hatalı backend → cache miss
davranışı (graceful degradation).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from app.services.db_learning.dedupe_service import canonicalize_sql

logger = logging.getLogger(__name__)


# Lazy singleton — Redis bağlantı testi ilk kullanımda
_cache_instance = None
_DEFAULT_TTL = 300


def _get_cache():
    global _cache_instance
    if _cache_instance is None:
        try:
            from app.core.config import settings
            from app.core.redis_cache import RedisCache
            url = getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
            _cache_instance = RedisCache(
                redis_url=url,
                default_ttl=getattr(settings, "SQL_RESULT_CACHE_TTL", _DEFAULT_TTL),
                key_prefix="vyra:result:",
            )
        except Exception as e:
            logger.warning("[result_cache] init failed: %s", e)
            _cache_instance = None
    return _cache_instance


def _fingerprint(sql: str, source_id: int) -> str:
    """Canonical SQL + source_id → stabil key."""
    canon = canonicalize_sql(sql or "")
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return f"sql_result:{h}:{source_id}"


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def get_cached_result(sql: str, source_id: int) -> Optional[Any]:
    """Cache hit varsa SQLResult döndür, yoksa None.

    Returns:
        SQLResult-like (önceden cache'lenmiş) veya None
    """
    cache = _get_cache()
    if cache is None:
        return None
    try:
        return cache.get(_fingerprint(sql, source_id))
    except Exception as e:
        logger.debug("[result_cache.get] miss with error: %s", e)
        return None


def set_cached_result(sql: str, source_id: int, result: Any, ttl: Optional[int] = None) -> bool:
    """Sonucu cache'le. Yalnızca başarılı + non-truncated sonuçlar yazılır.

    Args:
        sql: orijinal SQL
        source_id: data_sources.id
        result: SQLResult (dataclass)
        ttl: saniye, None → default

    Returns:
        True if cached, False otherwise
    """
    cache = _get_cache()
    if cache is None:
        return False
    # Kalite kontrol: hatalı / iptal / timeout sonuçlar cache'lenmez
    try:
        success = getattr(result, "success", None)
        if success is None and isinstance(result, dict):
            success = result.get("success")
        if not success:
            return False
        # Truncated sonuçları cache'lemek tehlikeli (kullanıcı tam sonucu bekleyebilir)
        truncated = getattr(result, "truncated", False)
        if isinstance(result, dict):
            truncated = result.get("truncated", False)
        if truncated:
            return False
        # Boyut sınırı — 1MB üzerini cache'leme
        try:
            import pickle as _pickle
            payload_size = len(_pickle.dumps(result))
            if payload_size > 1024 * 1024:
                return False
        except Exception:
            pass
        cache.set(_fingerprint(sql, source_id), result, ttl=ttl)
        return True
    except Exception as e:
        logger.debug("[result_cache.set] err: %s", e)
        return False


def flush_all() -> dict:
    """Tüm result cache'i temizle (admin endpoint)."""
    cache = _get_cache()
    if cache is None:
        return {"ok": False, "reason": "cache_unavailable"}
    try:
        cache.clear()
        return {"ok": True, "stats": cache.get_stats()}
    except Exception as e:
        logger.warning("[result_cache.flush] err: %s", e)
        return {"ok": False, "reason": str(e)[:200]}


def stats() -> dict:
    """Cache istatistikleri."""
    cache = _get_cache()
    if cache is None:
        return {"available": False}
    try:
        s = cache.get_stats()
        s["available"] = True
        return s
    except Exception as e:
        return {"available": False, "error": str(e)[:200]}


__all__ = [
    "get_cached_result",
    "set_cached_result",
    "flush_all",
    "stats",
]
