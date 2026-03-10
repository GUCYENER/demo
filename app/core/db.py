"""
VYRA L1 Support API - Database Module
======================================
PostgreSQL veritabanı bağlantısı ve yardımcı fonksiyonlar.

Modüler Yapı:
- get_db_conn(): Raw psycopg2 connection (legacy uyumluluk)
- get_db_context(): Context manager ile güvenli bağlantı
- init_db(): Şema başlatma ve migration
"""

from __future__ import annotations

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Generator, Optional

from app.core.config import settings
from app.core.schema import SCHEMA_SQL
from app.core.default_data import insert_default_data


# ===========================================================
#  Connection Pool (Singleton)
# ===========================================================

_connection_pool: Optional[pool.ThreadedConnectionPool] = None

def _get_pool() -> pool.ThreadedConnectionPool:
    """Connection pool'u lazy load eder (singleton)"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=2,  # v2.28.0: Minimum 2 connection hazır tut
            maxconn=15, # v2.28.0: Maksimum 15 connection
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            cursor_factory=RealDictCursor
        )
    return _connection_pool


def _reset_pool() -> None:
    """Hatalı pool'u sıfırlar (startup retry için)"""
    global _connection_pool
    if _connection_pool is not None:
        try:
            _connection_pool.closeall()
        except Exception as e:
            print(f"[DB] Pool close hatası (reset sırasında): {e}")
    _connection_pool = None


class PooledConnection:
    """
    🚀 v2.28.0: Connection wrapper - close() çağrıldığında pool'a geri döner.
    
    Bu wrapper sayesinde legacy kod (conn.close()) değişmeden çalışır
    ve connection pool düzgün kullanılır.
    """
    
    def __init__(self, conn, pool_ref):
        self._conn = conn
        self._pool = pool_ref
        self._closed = False
    
    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)
    
    def commit(self):
        return self._conn.commit()
    
    def rollback(self):
        return self._conn.rollback()
    
    def close(self):
        """Connection'ı pool'a geri döndür (kapatma!)"""
        if not self._closed:
            self._closed = True
            try:
                self._pool.putconn(self._conn)
            except Exception as e:
                # Pool kapalıysa gerçekten kapat
                print(f"[DB] Pool putconn hatası, bağlantı kapatılıyor: {e}")
                self._conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_db_conn():
    """
    PostgreSQL connection döndürür (pool'dan).
    
    🚀 v2.28.0: PooledConnection wrapper kullanır.
    close() çağrıldığında connection pool'a geri döner.
    
    Returns:
        PooledConnection: Veritabanı bağlantısı (RealDictCursor ile)
    """
    try:
        pool_ref = _get_pool()
        conn = pool_ref.getconn()
        return PooledConnection(conn, pool_ref)
    except Exception as e:
        # Pool başarısızsa direkt bağlantı aç
        print(f"[DB] Pool bağlantısı alınamadı, direkt bağlanılıyor: {e}")
        conn = psycopg2.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            cursor_factory=RealDictCursor
        )
        return conn


def release_db_conn(conn):
    """Bağlantıyı havuza geri döndürür (deprecated - close() kullanın)"""
    conn.close()


@contextmanager
def get_db_context() -> Generator:
    """
    Context manager ile güvenli veritabanı bağlantısı.
    
    Usage:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users")

    Yields:
        PooledConnection: Auto-commit/rollback connection
    """
    conn = None
    try:
        conn = get_db_conn()
        yield conn
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()  # Pool'a geri döner (PooledConnection sayesinde)


# ===========================================================
#  Initialization
# ===========================================================

def init_db() -> None:
    """
    PostgreSQL veritabanını başlatır.
    
    Strateji:
    1. Alembic migration çalıştır (upgrade head)
    2. Başarısızlık durumunda fallback: SCHEMA_SQL + insert_default_data
    
    Raises:
        psycopg2.Error: Veritabanı bağlantı veya şema hatası
    """
    import time
    
    max_retries = 30  # 30 x 3 saniye = 90 saniye maksimum bekleme
    retry_delay = 3   # Her deneme arasında 3 saniye
    
    # PostgreSQL startup/recovery sırasında dönen bilinen hata mesajları
    RETRYABLE_ERRORS = [
        "starting up",
        "connection refused",
        "not yet accepting connections",
        "recovery state",
    ]
    
    for attempt in range(1, max_retries + 1):
        try:
            # Önce Alembic migration dene
            if _run_alembic_migration():
                # Migration sonrası varsayılan verileri ekle
                with get_db_context() as conn:
                    cur = conn.cursor()
                    insert_default_data(cur)
                print("[VYRA] PostgreSQL database initialized via Alembic migration!")
                print(f"[VYRA] Connection: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
                return
            
            # Alembic başarısızsa fallback: eski yöntem
            with get_db_context() as conn:
                cur = conn.cursor()
                cur.execute(SCHEMA_SQL)
                insert_default_data(cur)
                
            print("[VYRA] PostgreSQL database initialized (fallback: SCHEMA_SQL)!")
            print(f"[VYRA] Connection: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
            return
            
        except psycopg2.OperationalError as e:
            error_msg = str(e).lower()
            
            is_retryable = any(keyword in error_msg for keyword in RETRYABLE_ERRORS)
            
            if is_retryable:
                _reset_pool()
                
                if attempt < max_retries:
                    print(f"[VYRA] PostgreSQL hazırlanıyor... ({attempt}/{max_retries}) - {retry_delay}s bekleniyor")
                    time.sleep(retry_delay)
                    continue
            
            print("[VYRA] ERROR: PostgreSQL connection failed!")
            print(f"[VYRA] Details: {e}")
            print(f"[VYRA] Make sure PostgreSQL is running at {settings.DB_HOST}:{settings.DB_PORT}")
            raise


def _run_alembic_migration() -> bool:
    """
    Alembic migration çalıştırır (upgrade head).
    
    Returns:
        bool: Başarılıysa True, hata oluşursa False (fallback'e bırakır)
    """
    try:
        from alembic.config import Config
        from alembic import command
        import os
        
        # alembic.ini konumunu bul
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ini_path = os.path.join(project_root, "alembic.ini")
        
        if not os.path.exists(ini_path):
            print("[VYRA] alembic.ini bulunamadı, fallback kullanılacak")
            return False
        
        alembic_cfg = Config(ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        
        command.upgrade(alembic_cfg, "head")
        print("[VYRA] Alembic migration başarılı (upgrade head)")
        return True
        
    except Exception as e:
        print(f"[VYRA] Alembic migration hatası (fallback kullanılacak): {e}")
        return False


def check_db_connection() -> bool:
    """
    Veritabanı bağlantısını kontrol eder.
    
    Returns:
        bool: Bağlantı başarılıysa True
    """
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] check_db_connection hatası: {e}")
        return False


def get_pool_stats() -> dict:
    """
    🚀 v2.30.1: Connection pool istatistiklerini döndürür.
    
    Returns:
        dict: min/max conn, kullanılan/boş bağlantı sayıları
    """

    if _connection_pool is None:
        return {"status": "not_initialized"}
    
    try:
        # psycopg2 ThreadedConnectionPool internals
        used = len(_connection_pool._used)
        free = len(_connection_pool._pool)
        total = used + free
        
        return {
            "status": "active",
            "min_connections": _connection_pool.minconn,
            "max_connections": _connection_pool.maxconn,
            "used": used,
            "free": free,
            "total": total,
            "utilization_pct": round((used / _connection_pool.maxconn) * 100, 1) if _connection_pool.maxconn > 0 else 0
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
