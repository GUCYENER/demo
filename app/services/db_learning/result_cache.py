"""VYRA v3.27.0 — Result Fingerprint Cache (C.G7).

SQL sonuçlarını Redis'te kısa süreli cache'ler. Aynı SQL aynı kaynak
üzerinde TTL içinde tekrar çalıştırılırsa DB'ye gitmeden döndürür.

Key formatı: ``sql_result:{sha256(canonical_sql)}:{source_id}``
TTL: 300 saniye (varsayılan, settings.SQL_RESULT_CACHE_TTL ile override).

Serialization: JSON (dataclasses.asdict). v3.27.1'de pickle → JSON
geçişi yapıldı; pickle.loads üzerinden RCE riski (paylaşımlı Redis senaryosu)
ortadan kalktı. SQLResult tüm alanları JSON-serializable (data: list[dict],
columns: list[str], primitif sayısal alanlar).

Backend: ``app.core.redis_cache.RedisCache``. Redis yoksa in-memory
fallback (RedisCache içinde zaten var). Hatalı backend → cache miss
davranışı (graceful degradation).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from app.services.db_learning.dedupe_service import canonicalize_sql

logger = logging.getLogger(__name__)


# Lazy singleton — Redis bağlantı testi ilk kullanımda
_cache_instance = None
_cache_init_lock = threading.Lock()
_DEFAULT_TTL = 300
_SQL_RESULT_TYPE_MARKER = "__vyra_sql_result_v1__"


def _get_cache():
    """Thread-safe singleton accessor for the underlying RedisCache."""
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance
    with _cache_init_lock:
        # Double-checked locking
        if _cache_instance is not None:
            return _cache_instance
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


# ─────────────────────────────────────────────────────────────
# JSON serialization (pickle yerine — RCE risk azaltma)
# ─────────────────────────────────────────────────────────────

def _serialize_sql_result(result: Any) -> Optional[bytes]:
    """SQLResult → JSON bytes. dict tabanlı yapıdan dolayı pickle gerekmez."""
    try:
        if is_dataclass(result):
            payload = asdict(result)
        elif isinstance(result, dict):
            payload = dict(result)
        else:
            return None
        payload[_SQL_RESULT_TYPE_MARKER] = True
        return json.dumps(payload, default=str).encode("utf-8")
    except Exception as e:
        logger.debug("[result_cache._serialize] err: %s", e)
        return None


def _deserialize_sql_result(blob: Any) -> Optional[Any]:
    """JSON bytes / dict → SQLResult. Legacy pickle değerini de tolere et."""
    if blob is None:
        return None
    try:
        # RedisCache.get_raw mevcut değil; backend bizim için pickle.loads
        # yapmış olabilir → dict döner. Yeni format JSON string/bytes olarak da gelebilir.
        data: Any = blob
        if isinstance(blob, (bytes, bytearray)):
            data = json.loads(blob.decode("utf-8"))
        elif isinstance(blob, str):
            data = json.loads(blob)
        if not isinstance(data, dict):
            return None
        # Type marker kontrolü — emin olmadığımız payload'ı reddet
        if not data.pop(_SQL_RESULT_TYPE_MARKER, False):
            # marker yok → büyük olasılıkla legacy pickle SQLResult instance
            # (RedisCache pickle yapmış olabilir); attribute access edilebiliyorsa kullan
            if hasattr(blob, "success"):
                return blob
            return None
        from app.services.safe_sql_executor import SQLResult
        # Bilinmeyen alanları yok say — geriye dönük uyumluluk için
        allowed = {"success", "data", "columns", "row_count", "sql_executed",
                   "elapsed_ms", "error", "truncated", "timeout", "cancelled"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        return SQLResult(**filtered)
    except Exception as e:
        logger.debug("[result_cache._deserialize] err: %s", e)
        return None


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

    JSON üzerinden deserialize edilir; pickle yolu kullanılmaz.
    """
    cache = _get_cache()
    if cache is None:
        return None
    key = _fingerprint(sql, source_id)
    try:
        get_raw = getattr(cache, "get_raw", None)
        if callable(get_raw):
            blob = get_raw(key)
        else:
            blob = cache.get(key)  # legacy fallback
        return _deserialize_sql_result(blob)
    except Exception as e:
        logger.debug("[result_cache.get] miss with error: %s", e)
        return None


def set_cached_result(sql: str, source_id: int, result: Any, ttl: Optional[int] = None) -> bool:
    """Sonucu cache'le. Yalnızca başarılı + non-truncated sonuçlar yazılır.

    Serialization: JSON (pickle değil). 1MB üzeri payload reddedilir.
    """
    cache = _get_cache()
    if cache is None:
        return False
    try:
        success = getattr(result, "success", None)
        if success is None and isinstance(result, dict):
            success = result.get("success")
        if not success:
            return False
        truncated = getattr(result, "truncated", False)
        if isinstance(result, dict):
            truncated = result.get("truncated", False)
        if truncated:
            return False
        blob = _serialize_sql_result(result)
        if blob is None:
            return False
        if len(blob) > 1024 * 1024:
            return False
        key = _fingerprint(sql, source_id)
        set_raw = getattr(cache, "set_raw", None)
        if callable(set_raw):
            set_raw(key, blob, ttl=ttl)
        else:
            cache.set(key, blob, ttl=ttl)  # legacy fallback
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
