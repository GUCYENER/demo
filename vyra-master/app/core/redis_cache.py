"""
VYRA L1 Support API - Redis Cache
===================================
Redis-backed persistent cache. MemoryCache ile aynı interface.

🆕 v2.50.0: Sunucu restart'ta cache korunur.

Fallback:
- Redis bağlantı kurulamazsa → MemoryCache otomatik kullanılır
- Redis komutu başarısızsa → None döner (graceful degradation)
"""

import pickle
import time
from typing import Any, Optional, Dict
from app.services.logging_service import log_system_event, log_error

# Redis bağlantı kurulamazsa in-memory fallback
_redis_available = False
_redis_client = None

try:
    import redis
    _redis_available = True
except ImportError:
    pass


class RedisCache:
    """
    Redis-backed cache. MemoryCache ile aynı interface.
    
    Bağlantı kurulamazsa otomatik olarak in-memory dict'e fallback yapar.
    Tüm value'lar pickle ile serialized edilir.
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/1",
        max_size: int = 200,
        default_ttl: int = 3600,
        key_prefix: str = "vyra:"
    ):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._redis = None
        self._fallback_cache: Dict[str, Any] = {}
        self._fallback_ttls: Dict[str, float] = {}
        self._stats = {"hits": 0, "misses": 0, "errors": 0}
        self._using_redis = False
        
        if _redis_available:
            try:
                self._redis = redis.from_url(
                    redis_url,
                    decode_responses=False,  # Pickle binary
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    retry_on_timeout=True
                )
                # Bağlantı testi
                self._redis.ping()
                self._using_redis = True
                log_system_event("INFO", f"Redis cache aktif: {redis_url}", "cache")
            except Exception as e:
                self._redis = None
                self._using_redis = False
                log_system_event(
                    "WARNING",
                    f"Redis bağlantı kurulamadı, in-memory fallback aktif: {e}",
                    "cache"
                )
        else:
            log_system_event(
                "WARNING",
                "redis paketi yüklü değil, in-memory fallback aktif",
                "cache"
            )
    
    def _full_key(self, key: str) -> str:
        return f"{self._key_prefix}{key}"
    
    def get(self, key: str) -> Optional[Any]:
        """Cache'den değer al."""
        if self._using_redis:
            try:
                data = self._redis.get(self._full_key(key))
                if data is None:
                    self._stats["misses"] += 1
                    return None
                self._stats["hits"] += 1
                return pickle.loads(data)
            except Exception as e:
                self._stats["errors"] += 1
                log_error(f"Redis GET hatası: {e}", "cache")
                return None
        else:
            # Fallback: in-memory
            fk = self._full_key(key)
            if fk not in self._fallback_cache:
                self._stats["misses"] += 1
                return None
            # TTL kontrolü
            expire_at = self._fallback_ttls.get(fk, 0)
            if expire_at and time.time() > expire_at:
                del self._fallback_cache[fk]
                del self._fallback_ttls[fk]
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            return self._fallback_cache[fk]
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Cache'e değer kaydet."""
        if ttl is None:
            ttl = self._default_ttl
        
        if self._using_redis:
            try:
                data = pickle.dumps(value)
                if ttl > 0:
                    self._redis.setex(self._full_key(key), ttl, data)
                else:
                    self._redis.set(self._full_key(key), data)
            except Exception as e:
                self._stats["errors"] += 1
                log_error(f"Redis SET hatası: {e}", "cache")
        else:
            # Fallback: in-memory
            fk = self._full_key(key)
            # Boyut kontrolü
            if len(self._fallback_cache) >= self._max_size:
                # İlk giren çıkar
                oldest_key = next(iter(self._fallback_cache))
                del self._fallback_cache[oldest_key]
                self._fallback_ttls.pop(oldest_key, None)
            self._fallback_cache[fk] = value
            if ttl > 0:
                self._fallback_ttls[fk] = time.time() + ttl
    
    def delete(self, key: str) -> bool:
        """Cache'den sil."""
        if self._using_redis:
            try:
                return bool(self._redis.delete(self._full_key(key)))
            except Exception:
                return False
        else:
            fk = self._full_key(key)
            if fk in self._fallback_cache:
                del self._fallback_cache[fk]
                self._fallback_ttls.pop(fk, None)
                return True
            return False
    
    def clear(self) -> None:
        """Tüm cache'i temizle."""
        if self._using_redis:
            try:
                # Sadece bu prefix'in key'lerini sil
                pattern = f"{self._key_prefix}*"
                cursor = 0
                while True:
                    cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        self._redis.delete(*keys)
                    if cursor == 0:
                        break
                log_system_event("INFO", "Redis cache temizlendi", "cache")
            except Exception as e:
                log_error(f"Redis CLEAR hatası: {e}", "cache")
        else:
            self._fallback_cache.clear()
            self._fallback_ttls.clear()
        
        self._stats = {"hits": 0, "misses": 0, "errors": 0}
    
    def get_stats(self) -> dict:
        """Cache istatistikleri."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
        
        size = 0
        if self._using_redis:
            try:
                pattern = f"{self._key_prefix}*"
                cursor, keys = self._redis.scan(0, match=pattern, count=1000)
                size = len(keys)
            except Exception:
                pass
        else:
            size = len(self._fallback_cache)
        
        return {
            "type": "redis" if self._using_redis else "memory_fallback",
            "backend": "redis" if self._using_redis else "in-memory",
            "size": size,
            "max_size": self._max_size,
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "errors": self._stats["errors"],
            "hit_rate": f"{hit_rate:.1f}%"
        }
