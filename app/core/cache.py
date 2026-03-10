"""
VYRA L1 Support API - Cache Service
====================================
Modüler cache sistemi.

Desteklenen cache türleri:
1. Memory Cache (LRU) - Hızlı, geçici
2. Query Cache - Aynı sorular için sonuç cache'i
3. Deep Think Cache - LLM yanıt cache'i (1 saat TTL)
4. DB Cache - PostgreSQL tabanlı persistent cache

Kullanım:
    from app.core.cache import cache_service
    
    # Cache'e kaydet
    cache_service.set("key", "value", ttl=300)  # 5 dakika
    
    # Cache'den oku
    value = cache_service.get("key")
    
    # Decorator ile
    @cached(ttl=300, prefix="rag")
    def search_rag(query):
        ...
"""

import hashlib
import time
import json
from typing import Any, Optional, Dict, Callable
from functools import wraps
from dataclasses import dataclass, field
from threading import Lock
from app.services.logging_service import log_system_event


# ============================================
# Cache Entry
# ============================================

@dataclass
class CacheEntry:
    """Cache girişi"""
    value: Any
    created_at: float
    ttl: int  # saniye, 0 = sonsuz
    hits: int = 0
    
    @property
    def is_expired(self) -> bool:
        if self.ttl == 0:
            return False
        return time.time() > (self.created_at + self.ttl)


# ============================================
# Memory Cache (LRU)
# ============================================

class MemoryCache:
    """
    Thread-safe in-memory LRU cache.
    Uygulama yeniden başlatılınca sıfırlanır.
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def get(self, key: str) -> Optional[Any]:
        """Cache'den değer al"""
        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                return None
            
            entry = self._cache[key]
            
            # Süresi dolmuş mu?
            if entry.is_expired:
                del self._cache[key]
                self._stats["misses"] += 1
                return None
            
            entry.hits += 1
            self._stats["hits"] += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Cache'e değer kaydet"""
        if ttl is None:
            ttl = self._default_ttl
        
        with self._lock:
            # Boyut kontrolü
            if len(self._cache) >= self._max_size:
                self._evict_oldest()
            
            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl
            )
    
    def delete(self, key: str) -> bool:
        """Cache'den sil"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Tüm cache'i temizle"""
        with self._lock:
            self._cache.clear()
            self._stats = {"hits": 0, "misses": 0, "evictions": 0}
        log_system_event("INFO", "Memory cache temizlendi", "cache")
    
    def _evict_oldest(self) -> None:
        """En eski %20'yi sil (LRU)"""
        if not self._cache:
            return
        
        # Oluşturma zamanına göre sırala
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].created_at
        )
        
        # İlk %20'yi sil
        evict_count = max(1, len(sorted_keys) // 5)
        for key in sorted_keys[:evict_count]:
            del self._cache[key]
            self._stats["evictions"] += 1
    
    def get_stats(self) -> dict:
        """Cache istatistikleri"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            
            return {
                "type": "memory",
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "evictions": self._stats["evictions"],
                "hit_rate": f"{hit_rate:.1f}%"
            }


# ============================================
# Query Cache (Sorgu sonuçları)
# ============================================

class QueryCache:
    """
    Sorgu sonuçlarını cache'ler.
    Aynı sorular için tekrar hesaplama yapmaz.
    """
    
    def __init__(self, max_size: int = 500, default_ttl: int = 600):
        self._cache = MemoryCache(max_size=max_size, default_ttl=default_ttl)
    
    def _make_key(self, query: str, prefix: str = "") -> str:
        """Sorgu için cache key oluştur"""
        # Sorguyu normalize et
        normalized = query.lower().strip()
        hash_val = hashlib.md5(normalized.encode('utf-8')).hexdigest()[:16]
        return f"{prefix}:{hash_val}" if prefix else hash_val
    
    def get(self, query: str, prefix: str = "") -> Optional[Any]:
        """Sorgu sonucunu cache'den al"""
        key = self._make_key(query, prefix)
        return self._cache.get(key)
    
    def set(self, query: str, result: Any, prefix: str = "", ttl: int = None) -> None:
        """Sorgu sonucunu cache'e kaydet"""
        key = self._make_key(query, prefix)
        self._cache.set(key, result, ttl)
    
    def invalidate(self, query: str, prefix: str = "") -> bool:
        """Belirli sorgu cache'ini sil"""
        key = self._make_key(query, prefix)
        return self._cache.delete(key)
    
    def clear(self) -> None:
        """Tüm sorgu cache'ini temizle"""
        self._cache.clear()
        log_system_event("INFO", "Query cache temizlendi", "cache")
    
    def get_stats(self) -> dict:
        stats = self._cache.get_stats()
        stats["type"] = "query"
        return stats


# ============================================
# Cache Service (Unified Interface)
# ============================================

class CacheService:
    """
    Birleşik cache servisi.
    Farklı cache türlerini tek arayüz üzerinden yönetir.
    """
    
    def __init__(self):
        self.memory = MemoryCache(max_size=1000, default_ttl=300)  # 5 dakika
        self.query = QueryCache(max_size=500, default_ttl=600)     # 10 dakika
        self.embedding = MemoryCache(max_size=2000, default_ttl=0) # Sonsuz (uygulama süresince)
        
        # 🆕 v2.50.0: Deep Think cache → Redis persistent (fallback: in-memory)
        try:
            from app.core.redis_cache import RedisCache
            redis_url = "redis://localhost:6379/1"
            try:
                from app.core.config import settings as _cfg
                redis_url = _cfg.REDIS_URL
            except (ImportError, AttributeError):
                pass
            self.deep_think = RedisCache(
                redis_url=redis_url,
                max_size=200,
                default_ttl=3600,
                key_prefix="vyra:dt:"
            )
        except Exception as e:
            log_system_event("WARNING", f"RedisCache başlatılamadı, MemoryCache fallback: {e}", "cache")
            self.deep_think = MemoryCache(max_size=200, default_ttl=3600)
        
        log_system_event("INFO", "Cache service başlatıldı", "cache")
    
    def get(self, key: str, cache_type: str = "memory") -> Optional[Any]:
        """Genel cache get"""
        if cache_type == "query":
            return self.query.get(key)
        elif cache_type == "embedding":
            return self.embedding.get(key)
        else:
            return self.memory.get(key)
    
    def set(self, key: str, value: Any, ttl: int = None, cache_type: str = "memory") -> None:
        """Genel cache set"""
        if cache_type == "query":
            self.query.set(key, value, ttl=ttl)
        elif cache_type == "embedding":
            self.embedding.set(key, value, ttl=ttl)
        else:
            self.memory.set(key, value, ttl)
    
    def clear_all(self) -> None:
        """Tüm cache'leri temizle"""
        self.memory.clear()
        self.query.clear()
        self.embedding.clear()
        self.deep_think.clear()
        log_system_event("INFO", "Tüm cache'ler temizlendi", "cache")
    
    def get_all_stats(self) -> dict:
        """Tüm cache istatistikleri"""
        return {
            "memory": self.memory.get_stats(),
            "query": self.query.get_stats(),
            "embedding": self.embedding.get_stats(),
            "deep_think": self.deep_think.get_stats(),
        }


# ============================================
# Global Instance
# ============================================

cache_service = CacheService()


# ============================================
# Decorators
# ============================================

def cached(ttl: int = 300, prefix: str = "", cache_type: str = "query"):
    """
    Fonksiyon sonuçlarını cache'leyen decorator.
    
    Kullanım:
        @cached(ttl=600, prefix="rag")
        def search_documents(query: str):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # İlk argüman genelde sorgu
            query = str(args[0]) if args else str(kwargs.get('query', ''))
            cache_key = f"{prefix}:{func.__name__}:{query}"
            
            # Cache'de var mı?
            cached_value = cache_service.get(cache_key, cache_type)
            if cached_value is not None:
                log_system_event("DEBUG", f"Cache HIT: {cache_key[:50]}", "cache")
                return cached_value
            
            # Hesapla ve cache'e kaydet
            result = func(*args, **kwargs)
            cache_service.set(cache_key, result, ttl, cache_type)
            log_system_event("DEBUG", f"Cache SET: {cache_key[:50]}", "cache")
            
            return result
        return wrapper
    return decorator


def clear_cache(prefix: str = None):
    """Belirli prefix'e sahip cache'leri temizle veya tümünü temizle"""
    if prefix is None:
        cache_service.clear_all()
    else:
        # TODO: Prefix bazlı temizleme
        cache_service.clear_all()
