"""
VYRA L1 Support API - Rate Limiter
===================================
API rate limiting için merkezi konfigürasyon.

slowapi kullanarak endpoint başına istek sınırlaması sağlar.
Brute force ve DoS saldırılarına karşı koruma.

Version: 1.0.0 (2026-02-06)
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from typing import Optional


def _get_client_identifier(request: Request) -> str:
    """
    İstemci tanımlayıcısı oluşturur.
    
    Öncelik:
    1. X-Forwarded-For header (proxy arkasında ise)
    2. X-Real-IP header
    3. Client IP adresi
    
    Returns:
        IP adresi string
    """
    # Proxy arkasında ise forwarded header'ı kontrol et
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # İlk IP adresi gerçek client IP'dir
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Direkt bağlantı
    return get_remote_address(request)


# =============================================================================
# RATE LIMIT KONFIGÜRASYONU
# =============================================================================

# Endpoint bazlı limitler
RATE_LIMITS = {
    "login": "5/minute",       # Brute force koruması
    "register": "3/minute",    # Spam hesap engelleme
    "refresh": "10/minute",    # Token yenileme
    "default": "60/minute",    # Genel API limiti
}


# Merkezi limiter instance
limiter = Limiter(
    key_func=_get_client_identifier,
    default_limits=[RATE_LIMITS["default"]],
    headers_enabled=True,  # X-RateLimit-* headerları ekle
    strategy="fixed-window",  # Sabit pencere stratejisi
)


def get_rate_limit_handler():
    """Rate limit aşım handler'ını döndürür."""
    return _rate_limit_exceeded_handler


def get_rate_limit_exception():
    """Rate limit exception class'ını döndürür."""
    return RateLimitExceeded


# =============================================================================
# DEKORATÖR YARDIMCILARI
# =============================================================================

def limit_login():
    """Login endpoint için rate limit dekoratörü."""
    return limiter.limit(RATE_LIMITS["login"])


def limit_register():
    """Register endpoint için rate limit dekoratörü."""
    return limiter.limit(RATE_LIMITS["register"])


def limit_refresh():
    """Refresh token endpoint için rate limit dekoratörü."""
    return limiter.limit(RATE_LIMITS["refresh"])
