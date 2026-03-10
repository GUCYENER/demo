"""
VYRA L1 Support API - Health Check
====================================
Detaylı sistem sağlık kontrolü: DB, Cache, Configuration durumları.
v2.30.1: Basit health → comprehensive health check
"""

import time
from fastapi import APIRouter

from app.core.config import settings
from app.services.logging_service import log_warning

router = APIRouter()


@router.get("/health")
async def health():
    """
    Sistem sağlık kontrolü ve detaylı durum bilgisi.
    
    Returns:
        - status: overall system status (ok/degraded/error)
        - version: uygulama versiyonu
        - components: her bileşenin durumu
        - uptime: yanıt süresi (ms)
    """
    start = time.time()
    components = {}
    overall_status = "ok"
    
    # 1) Database Check
    try:
        from app.core.db import check_db_connection, get_pool_stats
        db_ok = check_db_connection()
        pool_info = get_pool_stats()
        components["database"] = {
            "status": "ok" if db_ok else "error",
            "type": "postgresql",
            "host": f"{settings.DB_HOST}:{settings.DB_PORT}",
            "database": settings.DB_NAME,
            "pool": pool_info
        }
        if not db_ok:
            overall_status = "error"
    except Exception as e:
        log_warning(f"Health check DB hatası: {e}", "health")
        components["database"] = {"status": "error", "message": str(e)}
        overall_status = "error"
    
    # 2) Cache Check
    try:
        from app.core.cache import cache_service
        cache_stats = cache_service.get_all_stats()
        components["cache"] = {
            "status": "ok",
            "memory": cache_stats.get("memory", {}),
            "query": cache_stats.get("query", {})
        }
    except Exception as e:
        log_warning(f"Health check cache hatası: {e}", "health")
        components["cache"] = {"status": "error", "message": str(e)}
        if overall_status == "ok":
            overall_status = "degraded"
    
    # 3) Configuration Check
    env_loaded = len(settings.JWT_SECRET) >= 32
    components["config"] = {
        "status": "ok" if env_loaded else "warning",
        "env_loaded": env_loaded,
        "debug_mode": settings.debug
    }
    if not env_loaded and overall_status == "ok":
        overall_status = "degraded"
    
    elapsed_ms = round((time.time() - start) * 1000, 1)
    
    return {
        "status": overall_status,
        "version": _get_db_version(),
        "app_name": settings.app_name,
        "components": components,
        "response_time_ms": elapsed_ms
    }


def _get_db_version() -> str:
    """system_settings tablosundan versiyonu oku, hata olursa config fallback."""
    try:
        from app.core.db import get_db_context
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT setting_value FROM system_settings WHERE setting_key = 'app_version'"
                )
                row = cur.fetchone()
                if row:
                    return row["setting_value"]
    except Exception as e:
        log_warning(f"DB versiyon okuma hatası: {e}", "health")
    return settings.APP_VERSION
