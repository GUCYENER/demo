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
            print(f"[DB] Pool close error (during reset): {e}")
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
                print(f"[DB] Pool putconn error, closing connection: {e}")
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
        print(f"[DB] Pool connection failed, connecting directly: {e}")
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
#  Faz 1: Row-Level Security (RLS) Scoped Context
# ===========================================================

@contextmanager
def get_db_context_scoped(
    source_id: Optional[int] = None,
    *,
    bypass: bool = False,
) -> Generator:
    """
    RLS-scoped DB context manager.

    Faz 1 (v3.20.0) — `ds_db_objects`, `ds_db_relationships`, `ds_db_samples`,
    `ds_learning_results` tablolarında source-bazlı izolasyon.

    Transaction kapsamında `SET LOCAL app.current_source_id = <id>` (veya
    bypass=True ise `app.bypass_rls = 'on'`) çalıştırır. LOCAL scope sayesinde
    pool'a dönen connection bir sonraki request için temizdir.

    Args:
        source_id: data_sources.id — RLS policy bu değerle eşleşen satırları
            görünür kılar. `bypass=True` iken None bırakılabilir.
        bypass: True ise admin bypass (tüm source'lar görünür). Sadece
            admin/system endpoint'lerinde kullanılmalı.

    Yields:
        PooledConnection: SET LOCAL uygulanmış, auto-commit/rollback connection

    Raises:
        ValueError: source_id None ve bypass=False ise.

    Usage (normal scoping):
        with get_db_context_scoped(source_id=current_source_id) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ds_db_objects")  # sadece source_id satırları

    Usage (admin bypass):
        with get_db_context_scoped(bypass=True) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ds_db_objects")  # tüm satırlar
    """
    if not bypass and source_id is None:
        raise ValueError(
            "get_db_context_scoped: source_id zorunlu (veya bypass=True). "
            "Kapsamsız sorgu için get_db_context() kullanın."
        )

    conn = None
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        if bypass:
            # set_config(setting, value, is_local) — parametrize-safe
            cur.execute("SELECT set_config('app.bypass_rls', 'on', true)")
        else:
            cur.execute(
                "SELECT set_config('app.current_source_id', %s, true)",
                (str(int(source_id)),),
            )
        cur.close()
        yield conn
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


# ===========================================================
#  v3.26.0 — Company-scoped RLS context (Migration 017)
# ===========================================================

@contextmanager
def get_db_context_scoped_company(
    company_id: Optional[int] = None,
    *,
    bypass: bool = False,
) -> Generator:
    """
    Company (tenant) RLS-scoped DB context manager.

    v3.26.0 (Migration 017) — `agentic_query_feedback`, `few_shot_examples`,
    `catboost_models`, `pipeline_events` tablolarında tenant izolasyonu.

    Transaction kapsamında `SET LOCAL app.current_company_id = <id>` (veya
    bypass=True ise `app.bypass_rls = 'on'`) çalıştırır.

    NOT: Migration 017 PERMISSIVE — setting boşsa passthrough. Strict policy'ye
    geçince (018) bu helper zorunlu olur.

    Args:
        company_id: companies.id — RLS policy bu değerle eşleşen satırları görünür kılar.
        bypass: True ise admin bypass (cross-tenant analytics endpoint'leri için).

    Yields:
        PooledConnection
    """
    if not bypass and company_id is None:
        raise ValueError(
            "get_db_context_scoped_company: company_id zorunlu (veya bypass=True)."
        )
    conn = None
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        if bypass:
            cur.execute("SELECT set_config('app.bypass_rls', 'on', true)")
        else:
            cur.execute(
                "SELECT set_config('app.current_company_id', %s, true)",
                (str(int(company_id)),),
            )
        cur.close()
        yield conn
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def apply_company_scope(cur, company_id: Optional[int] = None, *, bypass: bool = False) -> None:
    """
    Aktif transaction'a company scope uygular (mevcut cursor üzerinden).

    Pipeline cursor'ı zaten get_db_context içinden geliyor — bu helper o cursor'a
    SET LOCAL uygular, yeni connection açmaz.

    Kullanım:
        with get_db_context() as conn:
            cur = conn.cursor()
            apply_company_scope(cur, company_id=state["company_id"])
            # ... pipeline işlemleri
    """
    if bypass:
        cur.execute("SELECT set_config('app.bypass_rls', 'on', true)")
        return
    if company_id is None:
        return  # PERMISSIVE policy nedeniyle güvenli; strict policy'ye geçince hata atılmalı
    # R006 (v3.33.0): company_id verildiyse set_config başarısız olursa fail-loud.
    # Önceki `except: pass`, mig 044 strict WITH CHECK ile birlikte sessiz veri
    # kaybına yol açıyordu (setting set edilmemiş → INSERT reject → exception
    # yutulduğu için caller hiç görmüyordu). Artık RuntimeError raise eder.
    try:
        cur.execute(
            "SELECT set_config('app.current_company_id', %s, true)",
            (str(int(company_id)),),
        )
    except Exception as e:
        raise RuntimeError(
            f"apply_company_scope: set_config failed for company_id={company_id} "
            f"({type(e).__name__}: {e})"
        ) from e


# ===========================================================
#  Initialization
# ===========================================================

def _warn_if_db_user_bypasses_rls() -> None:
    """
    Faz 1 (v3.20.0): RLS efektifliği için DB rolünün superuser veya BYPASSRLS
    olmadığını kontrol eder. Aksi halde RLS policy'ler sessizce bypass olur.

    Sadece log üretir, başlatmayı engellemez (deployment kararı).
    Bkz: app/core/config.py:111 → DB_USER önerisi `vyra_app` (non-superuser).
    """
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = current_user
            """)
            row = cur.fetchone()
        if not row:
            return
        is_super = bool(row.get("rolsuper"))
        is_bypass = bool(row.get("rolbypassrls"))
        if is_super or is_bypass:
            print(
                f"[VYRA][RLS-WARN] DB rolü '{settings.DB_USER}' "
                f"(rolsuper={is_super}, rolbypassrls={is_bypass}) → "
                f"Row-Level Security policy'leri OTOMATİK BYPASS olacak. "
                f"Production'da non-superuser rol kullanın (örn. vyra_app). "
                f"Bkz: app/core/config.py:111"
            )
    except Exception as e:
        # Non-critical — RLS check başarısız olursa startup'ı engelleme
        print(f"[VYRA][RLS-WARN] DB role kontrolü başarısız (non-critical): {e}")


def init_db() -> None:
    """
    PostgreSQL veritabanını başlatır.
    
    Strateji:
    1. pg_advisory_lock ile multi-worker koruması (deadlock önleme)
    2. Alembic migration çalıştır (upgrade head)
    3. SCHEMA_SQL çalıştır (IF NOT EXISTS — migration'da eksik kalanlar için)
    4. insert_default_data çalıştır
    
    Raises:
        psycopg2.Error: Veritabanı bağlantı veya şema hatası
    """
    import time
    
    # Advisory lock key — tüm worker'lar arasında benzersiz
    SCHEMA_LOCK_ID = 999888777
    
    max_retries = 30  # 30 x 3 saniye = 90 saniye maksimum bekleme
    retry_delay = 3   # Her deneme arasında 3 saniye
    
    # PostgreSQL startup/recovery sırasında dönen bilinen hata mesajları
    RETRYABLE_ERRORS = [
        "starting up",
        "connection refused",
        "not yet accepting connections",
        "recovery state",
        "deadlock detected",
    ]
    
    for attempt in range(1, max_retries + 1):
        try:
            # Advisory lock al — sadece bir worker şema başlatsın
            lock_conn = get_db_conn()
            try:
                lock_cur = lock_conn.cursor()
                lock_cur.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK_ID,))
                lock_conn.commit()
                print(f"[VYRA] Schema lock acquired (attempt {attempt})")
                
                # 1) Alembic migration
                _run_alembic_migration()
                
                # 2) SCHEMA_SQL — IF NOT EXISTS ile migration'da eksik kalanları tamamlar
                with get_db_context() as conn:
                    cur = conn.cursor()
                    cur.execute(SCHEMA_SQL)
                    insert_default_data(cur)
                
                print("[VYRA] PostgreSQL database initialized (Alembic + SCHEMA_SQL)!")
                print(f"[VYRA] Connection: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
                
                # v3.4.8: DB'deki app_version'ı koddaki APP_VERSION ile senkronize et
                # Canlıya deploy edildiğinde DB versiyonu eski kalabilir — otomatik güncelle
                try:
                    with get_db_context() as vc:
                        vcur = vc.cursor()
                        vcur.execute(
                            "SELECT setting_value FROM system_settings WHERE setting_key = 'app_version'"
                        )
                        vrow = vcur.fetchone()
                        db_ver = vrow["setting_value"] if vrow else None
                        if db_ver != settings.APP_VERSION:
                            vcur.execute(
                                "UPDATE system_settings SET setting_value = %s, updated_at = NOW() WHERE setting_key = 'app_version'",
                                (settings.APP_VERSION,)
                            )
                            print(f"[VYRA] DB app_version updated: {db_ver} -> {settings.APP_VERSION}")
                except Exception as ve:
                    print(f"[VYRA] DB version sync error (non-critical): {ve}")

                # v3.20.0 (Faz 1): RLS efektifliği için DB role kontrolü
                _warn_if_db_user_bypasses_rls()
                return
                
            finally:
                # Advisory lock'u her durumda serbest bırak
                try:
                    lock_cur = lock_conn.cursor()
                    lock_cur.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK_ID,))
                    lock_conn.commit()
                except Exception:
                    pass
                try:
                    lock_conn.close()
                except Exception:
                    pass
            
        except psycopg2.OperationalError as e:
            error_msg = str(e).lower()
            
            is_retryable = any(keyword in error_msg for keyword in RETRYABLE_ERRORS)
            
            if is_retryable:
                _reset_pool()
                
                if attempt < max_retries:
                    print(f"[VYRA] PostgreSQL waiting... ({attempt}/{max_retries}) - {retry_delay}s delay")
                    time.sleep(retry_delay)
                    continue
            
            print("[VYRA] ERROR: PostgreSQL connection failed!")
            print(f"[VYRA] Details: {e}")
            print(f"[VYRA] Make sure PostgreSQL is running at {settings.DB_HOST}:{settings.DB_PORT}")
            raise
        
        except psycopg2.errors.DeadlockDetected:
            _reset_pool()
            if attempt < max_retries:
                print(f"[VYRA] Deadlock detected, retrying... ({attempt}/{max_retries})")
                time.sleep(retry_delay)
                continue
            raise


def _run_alembic_migration() -> bool:
    """
    Alembic migration çalıştırır (upgrade head).
    Thread-based timeout ile 30 saniyede tamamlanamazsa fallback'e bırakır.

    Returns:
        bool: Başarılıysa True, hata oluşursa False (fallback'e bırakır)
    """
    import threading
    import os

    result = {"success": False, "error": None}

    def _run():
        try:
            from alembic.config import Config
            from alembic import command

            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            ini_path = os.path.join(project_root, "alembic.ini")

            if not os.path.exists(ini_path):
                print("[VYRA] alembic.ini not found, using fallback")
                return

            alembic_cfg = Config(ini_path)
            alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

            command.upgrade(alembic_cfg, "head")
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=10)  # 10 saniye timeout

    if t.is_alive():
        print("[VYRA] Alembic migration timeout (10s), using SCHEMA_SQL fallback")
        return False

    if result["success"]:
        print("[VYRA] Alembic migration successful (upgrade head)")
        return True

    if result["error"]:
        print(f"[VYRA] Alembic migration error (using fallback): {result['error']}")
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
        print(f"[DB] check_db_connection error: {e}")
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
