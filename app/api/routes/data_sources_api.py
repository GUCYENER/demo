"""
VYRA L1 Support API - Data Sources Routes
===========================================
Veri kaynakları CRUD endpoint'leri.
v2.56.0
"""

import logging
import threading
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-sources", tags=["data_sources"])


# --- Pydantic Models ---

class DataSourceCreate(BaseModel):
    company_id: int
    name: str = Field(..., min_length=2, max_length=200)
    source_type: str = Field(..., pattern=r'^(database|file_server|manual_file|ftp|sharepoint)$')
    db_type: Optional[str] = Field(None, pattern=r'^(postgresql|mssql|mysql|oracle|ftp|ftps|sftp)$')
    host: Optional[str] = Field(None, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    db_name: Optional[str] = Field(None, max_length=200)
    db_user: Optional[str] = Field(None, max_length=200)
    db_password: Optional[str] = Field(None, max_length=500)
    file_server_path: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = None
    is_active: bool = True


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    source_type: Optional[str] = Field(None, pattern=r'^(database|file_server|manual_file|ftp|sharepoint)$')
    db_type: Optional[str] = Field(None, pattern=r'^(postgresql|mssql|mysql|oracle|ftp|ftps|sftp)$')
    host: Optional[str] = Field(None, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    db_name: Optional[str] = Field(None, max_length=200)
    db_user: Optional[str] = Field(None, max_length=200)
    db_password: Optional[str] = Field(None, max_length=500)
    file_server_path: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = None
    is_active: Optional[bool] = None


# --- Helpers ---

def _encrypt_password(plain: str) -> str:
    """Basit şifreleme (Fernet yoksa base64 fallback)."""
    try:
        from cryptography.fernet import Fernet
        import os
        key = os.environ.get("VYRA_ENCRYPT_KEY")
        if key:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.encrypt(plain.encode()).decode()
    except ImportError:
        pass
    # Fallback: base64
    import base64
    return "b64:" + base64.b64encode(plain.encode()).decode()


def _mask_password(encrypted: str) -> str:
    """Şifreyi maskeleyerek döndürür."""
    if not encrypted:
        return None
    return "••••••••"


# --- Endpoints ---

@router.get("/")
def list_data_sources(
    company_id: Optional[int] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Veri kaynağı listesi.
    Admin: Tüm firmalar veya company_id ile filtreli.
    User: Sadece kendi firması.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        if is_admin:
            if company_id:
                cur.execute("""
                    SELECT ds.*, c.name as company_name
                    FROM data_sources ds
                    JOIN companies c ON c.id = ds.company_id
                    WHERE ds.company_id = %s
                    ORDER BY ds.name
                """, (company_id,))
            else:
                cur.execute("""
                    SELECT ds.*, c.name as company_name
                    FROM data_sources ds
                    JOIN companies c ON c.id = ds.company_id
                    ORDER BY c.name, ds.name
                """)
        else:
            user_company_id = current_user.get("company_id")
            if not user_company_id:
                return []
            cur.execute("""
                SELECT ds.*, c.name as company_name
                FROM data_sources ds
                JOIN companies c ON c.id = ds.company_id
                WHERE ds.company_id = %s
                ORDER BY ds.name
            """, (user_company_id,))

        rows = cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            # Şifreyi maskele
            item["db_password_encrypted"] = _mask_password(item.get("db_password_encrypted"))
            result.append(item)
        return result


@router.post("/")
def create_data_source(
    data: DataSourceCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Yeni veri kaynağı oluşturur."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    # Admin değilse sadece kendi firmasına ekleyebilir
    if not is_admin:
        user_company_id = current_user.get("company_id")
        if not user_company_id or user_company_id != data.company_id:
            raise HTTPException(status_code=403, detail="Bu firmaya kaynak ekleme yetkiniz yok.")

    # Firma kontrolü
    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id FROM companies WHERE id = %s AND is_active = TRUE", (data.company_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Firma bulunamadı.")

        # Şifreyi şifrele
        encrypted_pw = None
        if data.db_password:
            encrypted_pw = _encrypt_password(data.db_password)

        cur.execute("""
            INSERT INTO data_sources (
                company_id, name, source_type, db_type,
                host, port, db_name, db_user, db_password_encrypted,
                file_server_path, description, is_active, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, company_id, name, source_type, db_type,
                      host, port, db_name, db_user,
                      file_server_path, description, is_active,
                      created_at, updated_at, created_by
        """, (
            data.company_id, data.name, data.source_type, data.db_type,
            data.host, data.port, data.db_name, data.db_user, encrypted_pw,
            data.file_server_path, data.description, data.is_active,
            current_user["id"]
        ))
        row = cur.fetchone()
        conn.commit()

    logger.info(f"[DataSources] Yeni kaynak oluşturuldu: {data.name} (id={row['id']})")
    result = dict(row)
    result["db_password_encrypted"] = _mask_password(encrypted_pw)
    return result


@router.put("/{source_id}")
def update_data_source(
    source_id: int,
    data: DataSourceUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Veri kaynağını günceller."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

        # Yetki kontrolü
        if not is_admin and current_user.get("company_id") != existing["company_id"]:
            raise HTTPException(status_code=403, detail="Bu kaynağı düzenleme yetkiniz yok.")

        update_data = data.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Güncellenecek veri yok.")

        # Şifre güncelleme
        if "db_password" in update_data:
            pw = update_data.pop("db_password")
            if pw:
                update_data["db_password_encrypted"] = _encrypt_password(pw)

        set_parts = []
        values = []
        for key, value in update_data.items():
            set_parts.append(f"{key} = %s")
            values.append(value)

        values.append(source_id)
        set_clause = ", ".join(set_parts)

        cur.execute(
            f"UPDATE data_sources SET {set_clause}, updated_at = NOW() WHERE id = %s",
            values
        )
        conn.commit()

        cur.execute("""
            SELECT ds.*, c.name as company_name
            FROM data_sources ds
            JOIN companies c ON c.id = ds.company_id
            WHERE ds.id = %s
        """, (source_id,))
        row = cur.fetchone()

    logger.info(f"[DataSources] Kaynak güncellendi: id={source_id}")
    result = dict(row)
    result["db_password_encrypted"] = _mask_password(result.get("db_password_encrypted"))
    return result


@router.delete("/{source_id}")
def delete_data_source(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Veri kaynağını siler."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, name, company_id FROM data_sources WHERE id = %s", (source_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

        # Yetki kontrolü
        if not is_admin and current_user.get("company_id") != existing["company_id"]:
            raise HTTPException(status_code=403, detail="Bu kaynağı silme yetkiniz yok.")

        cur.execute("DELETE FROM data_sources WHERE id = %s", (source_id,))
        conn.commit()

    logger.info(f"[DataSources] Kaynak silindi: {existing['name']} (id={source_id})")
    return {"message": f"\"{existing['name']}\" kaynağı silindi."}


# --- Connection Test ---

def _decrypt_stored_password(encrypted: str) -> str:
    """DB'deki şifreli parolayı çözer. Fernet → base64 fallback."""
    if not encrypted:
        return ""
    # base64 fallback ile kaydedilmişse
    if encrypted.startswith("b64:"):
        import base64
        return base64.b64decode(encrypted[4:]).decode()
    # Fernet ile kaydedilmişse
    try:
        from app.core.encryption import decrypt_password
        return decrypt_password(encrypted)
    except Exception:
        logger.debug("[DataSources] Fernet decrypt başarısız, metin olarak döndürülüyor")
        return encrypted


def _test_database_connection(source: dict, password: str) -> dict:
    """Veritabanı bağlantı testi (PostgreSQL / MSSQL / MySQL / Oracle)."""
    import time
    db_type = source.get("db_type", "")
    host = source.get("host", "")
    port = source.get("port", 5432)
    db_name = source.get("db_name", "")
    db_user = source.get("db_user", "")

    start = time.time()

    if db_type == "postgresql":
        import psycopg2
        conn = psycopg2.connect(
            host=host, port=port, dbname=db_name,
            user=db_user, password=password,
            connect_timeout=10
        )
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        conn.close()
        elapsed = int((time.time() - start) * 1000)
        return {"success": True, "message": "Bağlantı başarılı", "server_info": version, "elapsed_ms": elapsed}

    elif db_type == "mssql":
        import pymssql
        conn = pymssql.connect(
            server=host, port=str(port), database=db_name,
            user=db_user, password=password,
            login_timeout=10
        )
        cur = conn.cursor()
        cur.execute("SELECT @@VERSION")
        version = cur.fetchone()[0]
        conn.close()
        elapsed = int((time.time() - start) * 1000)
        return {"success": True, "message": "Bağlantı başarılı", "server_info": version, "elapsed_ms": elapsed}

    elif db_type == "mysql":
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, database=db_name,
            user=db_user, password=password,
            connect_timeout=10
        )
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        conn.close()
        elapsed = int((time.time() - start) * 1000)
        return {"success": True, "message": "Bağlantı başarılı", "server_info": version, "elapsed_ms": elapsed}

    elif db_type == "oracle":
        import cx_Oracle
        dsn = cx_Oracle.makedsn(host, port, service_name=db_name)
        conn = cx_Oracle.connect(user=db_user, password=password, dsn=dsn)
        version = conn.version
        conn.close()
        elapsed = int((time.time() - start) * 1000)
        return {"success": True, "message": "Bağlantı başarılı", "server_info": f"Oracle {version}", "elapsed_ms": elapsed}

    else:
        return {"success": False, "message": f"Desteklenmeyen veritabanı tipi: {db_type}"}


def _test_ftp_connection(source: dict, password: str) -> dict:
    """FTP / FTPS / SFTP bağlantı testi."""
    import time
    protocol = (source.get("db_type") or "ftp").lower()
    host = source.get("host", "")
    port = source.get("port", 21)
    username = source.get("db_user", "")

    start = time.time()

    if protocol in ("ftp", "ftps"):
        import ftplib
        if protocol == "ftps":
            ftp = ftplib.FTP_TLS()
        else:
            ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=10)
        ftp.login(username, password)
        welcome = ftp.getwelcome()
        ftp.quit()
        elapsed = int((time.time() - start) * 1000)
        return {"success": True, "message": "Bağlantı başarılı", "server_info": welcome, "elapsed_ms": elapsed}

    elif protocol == "sftp":
        import paramiko
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.close()
        transport.close()
        elapsed = int((time.time() - start) * 1000)
        return {"success": True, "message": "Bağlantı başarılı", "server_info": f"SFTP {host}:{port}", "elapsed_ms": elapsed}

    else:
        return {"success": False, "message": f"Desteklenmeyen protokol: {protocol}"}


def _test_file_server_connection(source: dict) -> dict:
    """File Server erişilebilirlik testi."""
    import time
    import os
    path = source.get("file_server_path", "")
    start = time.time()

    if not path:
        return {"success": False, "message": "Dosya yolu tanımlı değil"}

    exists = os.path.exists(path)
    is_dir = os.path.isdir(path) if exists else False
    elapsed = int((time.time() - start) * 1000)

    if exists and is_dir:
        try:
            entries = os.listdir(path)
            return {
                "success": True,
                "message": "Klasör erişilebilir",
                "server_info": f"{len(entries)} dosya/klasör bulundu",
                "elapsed_ms": elapsed
            }
        except PermissionError:
            return {"success": False, "message": "Erişim reddedildi (PermissionError)", "elapsed_ms": elapsed}
    elif exists:
        return {"success": False, "message": "Yol bir dosyaya işaret ediyor, klasör bekleniyor", "elapsed_ms": elapsed}
    else:
        return {"success": False, "message": f"Yol bulunamadı: {path}", "elapsed_ms": elapsed}


@router.post("/{source_id}/test-connection")
def test_connection(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Kayıtlı veri kaynağına bağlantı testi yapar.
    DB'deki bilgileri kullanarak gerçek bağlantı denemesi gerçekleştirir.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
        source = cur.fetchone()

    if not source:
        raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

    source = dict(source)

    # Yetki kontrolü
    if not is_admin and current_user.get("company_id") != source.get("company_id"):
        raise HTTPException(status_code=403, detail="Bu kaynağa erişim yetkiniz yok.")

    source_type = source.get("source_type", "")

    try:
        # Şifreyi çöz
        password = _decrypt_stored_password(source.get("db_password_encrypted", ""))

        if source_type == "database":
            result = _test_database_connection(source, password)
        elif source_type == "ftp":
            result = _test_ftp_connection(source, password)
        elif source_type == "file_server":
            result = _test_file_server_connection(source)
        elif source_type == "sharepoint":
            # SharePoint testi şu an bilgi amaçlı
            result = {
                "success": True,
                "message": "SharePoint bağlantı bilgileri kaydedildi (bağlantı testi Azure AD token gerektirir)",
                "server_info": source.get("file_server_path", ""),
                "elapsed_ms": 0
            }
        elif source_type == "manual_file":
            result = {
                "success": True,
                "message": "Manuel dosya kaynağı — bağlantı testi gerekmez",
                "elapsed_ms": 0
            }
        else:
            result = {"success": False, "message": f"Bilinmeyen kaynak tipi: {source_type}"}

        logger.info(f"[DataSources] Bağlantı testi: {source.get('name')} → {'BAŞARILI' if result.get('success') else 'BAŞARISIZ'}")
        return result

    except Exception as e:
        logger.debug(f"[DataSources] Bağlantı testi hatası: {type(e).__name__}")
        # Hata mesajını kullanıcıya anlamlı şekilde döndür (güvenlik: traceback yok)
        error_type = type(e).__name__
        error_msg = str(e)

        # Bilinen hata tiplerini kullanıcı dostu mesaja çevir
        friendly_messages = {
            "OperationalError": "Veritabanına bağlanılamadı. Sunucu adresi, port veya kimlik bilgilerini kontrol edin.",
            "ConnectionRefusedError": "Bağlantı reddedildi. Sunucu çalışıyor mu?",
            "timeout": "Bağlantı zaman aşımına uğradı. Sunucu erişilebilir mi?",
            "gaierror": "Sunucu adresi çözümlenemedi. DNS ayarlarını kontrol edin.",
            "AuthenticationError": "Kimlik doğrulama başarısız. Kullanıcı adı veya şifreyi kontrol edin.",
        }

        friendly = friendly_messages.get(error_type, None)
        display_msg = friendly if friendly else f"{error_type}: {error_msg}"

        return {"success": False, "message": display_msg}


# --- DB Discovery / Learning Endpoints (v2.56.0) ---

from app.services import ds_learning_service


@router.post("/{source_id}/discover")
def discover_technology(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Adım 1: Veritabanı teknoloji keşfi (versiyon, şemalar)."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
            source = cur.fetchone()

            if not source:
                raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")
            source = dict(source)

            if not is_admin and current_user.get("company_id") != source.get("company_id"):
                raise HTTPException(status_code=403, detail="Bu kaynağa erişim yetkiniz yok.")

            if source.get("source_type") != "database":
                raise HTTPException(status_code=400, detail="Bu kaynak tipi keşif desteklemiyor.")

            # Çalışan iş kontrolü
            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {"success": False, "message": f"Bu kaynak için zaten çalışan bir iş var: {rj['job_type']}", "running_job": rj}

            # Job oluştur
            job_id = ds_learning_service.create_job(conn, source_id, source["company_id"], "technology", current_user.get("id"))

            # Keşfi çalıştır
            result = ds_learning_service.discover_technology(source, conn)

            # Job'ı güncelle
            ds_learning_service.complete_job(conn, job_id, result)

            if result.get("success"):
                return {"success": True, "job_id": job_id, **result["data"]}
            else:
                return {"success": False, "job_id": job_id, "message": result.get("error", "Keşif başarısız")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DataSources] Teknoloji keşfi sırasında hata oluştu")
        logger.debug("[DataSources] discover_technology detay: %s", type(e).__name__)
        return {"success": False, "message": f"Teknoloji keşfi sırasında hata: {type(e).__name__}"}


@router.post("/{source_id}/detect-objects")
def detect_objects(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Adım 2: DB objeleri (tablo, view, sütun) ve FK ilişkilerini tespit et."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
            source = cur.fetchone()

            if not source:
                raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")
            source = dict(source)

            if not is_admin and current_user.get("company_id") != source.get("company_id"):
                raise HTTPException(status_code=403, detail="Bu kaynağa erişim yetkiniz yok.")

            if source.get("source_type") != "database":
                raise HTTPException(status_code=400, detail="Bu kaynak tipi keşif desteklemiyor.")

            # Çalışan iş kontrolü
            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {"success": False, "message": f"Bu kaynak için zaten çalışan bir iş var: {rj['job_type']}", "running_job": rj}

            job_id = ds_learning_service.create_job(conn, source_id, source["company_id"], "objects", current_user.get("id"))
            result = ds_learning_service.detect_objects(source, conn)
            ds_learning_service.complete_job(conn, job_id, result)

            if result.get("success"):
                return {"success": True, "job_id": job_id, **result["data"]}
            else:
                return {"success": False, "job_id": job_id, "message": result.get("error", "Obje tespiti başarısız")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DataSources] Obje tespiti sırasında hata oluştu")
        logger.debug("[DataSources] detect_objects detay: %s", type(e).__name__)
        return {"success": False, "message": f"Obje tespiti sırasında hata: {type(e).__name__}"}


@router.post("/{source_id}/collect-samples")
def collect_samples(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Adım 3: Tablolardan örnek veri topla."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
            source = cur.fetchone()

            if not source:
                raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")
            source = dict(source)

            if not is_admin and current_user.get("company_id") != source.get("company_id"):
                raise HTTPException(status_code=403, detail="Bu kaynağa erişim yetkiniz yok.")

            if source.get("source_type") != "database":
                raise HTTPException(status_code=400, detail="Bu kaynak tipi keşif desteklemiyor.")

            # Çalışan iş kontrolü
            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {"success": False, "message": f"Bu kaynak için zaten çalışan bir iş var: {rj['job_type']}", "running_job": rj}

            job_id = ds_learning_service.create_job(conn, source_id, source["company_id"], "samples", current_user.get("id"))
            result = ds_learning_service.collect_samples(source, conn)
            ds_learning_service.complete_job(conn, job_id, result)

            if result.get("success"):
                return {"success": True, "job_id": job_id, **result["data"]}
            else:
                return {"success": False, "job_id": job_id, "message": result.get("error", "Örnek toplama başarısız")}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DataSources] Örnek veri toplama sırasında hata oluştu")
        logger.debug("[DataSources] collect_samples detay: %s", type(e).__name__)
        return {"success": False, "message": f"Veri toplama sırasında hata: {type(e).__name__}"}


@router.get("/{source_id}/check-running-job")
def check_running_job(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Bu kaynak için çalışan bir iş var mı kontrol eder (frontend guard için)."""
    try:
        with get_db_context() as conn:
            result = ds_learning_service.check_running_job(conn, source_id)
            return {"success": True, **result}
    except Exception as e:
        logger.error("[DataSources] Running job kontrolü sırasında hata: %s", type(e).__name__)
        return {"success": True, "has_running": False, "job": None}


@router.get("/{source_id}/discovery-status")
def get_discovery_status(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Keşif adımlarının güncel durumunu döner."""
    try:
        with get_db_context() as conn:
            return ds_learning_service.get_discovery_status(conn, source_id)
    except Exception as e:
        logger.error("[DataSources] Keşif durumu sorgulanırken hata oluştu")
        logger.debug("[DataSources] discovery-status detay: %s", type(e).__name__)
        return {"technology": {"status": "not_started"}, "objects": {"status": "not_started"}, "samples": {"status": "not_started"}, "total_objects": 0, "total_relationships": 0, "total_samples": 0}


@router.get("/{source_id}/discovery-details")
def get_discovery_details(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Keşfedilmiş objelerin detaylı listesini döner."""
    try:
        with get_db_context() as conn:
            return ds_learning_service.get_discovery_details(conn, source_id)
    except Exception as e:
        logger.error("[DataSources] Keşif detayları yüklenirken hata oluştu")
        logger.debug("[DataSources] discovery-details detay: %s", type(e).__name__)
        return {"objects": [], "relationships": []}


@router.post("/{source_id}/learning-schedule")
def save_learning_schedule(
    source_id: int,
    body: dict = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Öğrenme zamanlaması oluştur/güncelle."""
    try:
        schedule_type = body.get("schedule_type", "manual_only")
        interval_value = body.get("interval_value", 24)
        is_active = body.get("is_active", True)

        with get_db_context() as conn:
            result = ds_learning_service.upsert_schedule(
                conn, source_id, schedule_type, interval_value, is_active
            )
            return result
    except Exception:
        logger.error("[DataSources] Schedule kaydetme sırasında hata oluştu")
        raise HTTPException(status_code=500, detail="Zamanlama kaydedilemedi")



@router.get("/{source_id}/learning-history")
def get_learning_history(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Keşif ve öğrenme iş geçmişini döner."""
    try:
        with get_db_context() as conn:
            history = ds_learning_service.get_learning_history(conn, source_id)
            return {"history": history}
    except Exception as e:
        logger.error("[DataSources] Öğrenme geçmişi yüklenirken hata oluştu")
        logger.debug("[DataSources] learning-history detay: %s", type(e).__name__)
        return {"history": []}


@router.get("/{source_id}/learning-results")
def api_get_learning_results(
    source_id: int,
    content_type: str = None,
    job_id: int = None,
    limit: int = 50,
    offset: int = 0,
    search: str = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """ML pipeline'ın ürettiği öğrenme sonuçlarını (QA çiftleri) döner. v3.7.0: Pagination ve arama."""
    try:
        with get_db_context() as conn:
            data = ds_learning_service.get_learning_results(
                conn, source_id, content_type, job_id, limit, offset, search
            )
            return data
    except Exception as e:
        logger.error("[DataSources] Öğrenme sonuçları yüklenirken hata oluştu")
        logger.debug("[DataSources] learning-results detay: %s", type(e).__name__)
        return {"results": [], "type_counts": {}, "total": 0, "total_filtered": 0, "page": 1, "page_size": limit, "total_pages": 0}


@router.get("/{source_id}/job-result-stats")
def api_get_job_result_stats(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Her job_id bazlı sonuç istatistiklerini döner."""
    try:
        with get_db_context() as conn:
            stats = ds_learning_service.get_job_result_stats(conn, source_id)
            return {"stats": stats}
    except Exception as e:
        logger.error("[DataSources] İş sonuç istatistikleri yüklenirken hata oluştu")
        logger.debug("[DataSources] job-result-stats detay: %s", type(e).__name__)
        return {"stats": []}



# generate-qa endpoint kaldırıldı (v3.0.0)
# QA üretimi artık sadece run-full-learning pipeline'ı içinden çağrılır.
# Bağımsız QA üretim butonu/endpoint'i gereksizdir.


@router.post("/{source_id}/run-full-learning")
def run_full_learning(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """4 adımlı tam öğrenme pipeline'ı çalıştırır (background)."""
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
            source = cur.fetchone()
            if not source:
                return {"success": False, "message": "Kaynak bulunamadı"}
            source = dict(source)
            current_user_id = current_user.get("id")

            # Çalışan iş kontrolü
            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {"success": False, "message": f"Bu kaynak için zaten çalışan bir iş var: {rj['job_type']}", "running_job": rj}

        # Background thread
        def _bg_full_learning():
            bg_conn = None
            try:
                from app.core.db import get_db_conn
                bg_conn = get_db_conn()
                ds_learning_service.run_full_learning(source, bg_conn, current_user_id)
            except Exception:
                logger.error("[BG] Tam öğrenme pipeline sırasında hata oluştu")
            finally:
                if bg_conn:
                    try:
                        bg_conn.close()
                    except Exception:
                        pass

        threading.Thread(target=_bg_full_learning, daemon=True).start()
        return {"success": True, "message": "Tam öğrenme pipeline başlatıldı"}

    except Exception as e:
        logger.error("[DataSources] Tam öğrenme pipeline başlatılırken hata oluştu")
        logger.debug("[DataSources] run-full-learning detay: %s", type(e).__name__)
        return {"success": False, "message": f"Pipeline başlatılamadı: {type(e).__name__}"}

@router.post("/{source_id}/run-approved-learning")
def run_approved_learning(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Sadece onaylı tablolar için şema öğrenimini çalıştırır (v5.0)."""
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
            source = cur.fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="Data source not found")
            source = dict(source) if hasattr(source, 'keys') else source

            # Running job guard — aynı kaynak için çalışan iş varsa reddet
            cur.execute("""
                SELECT id, job_type, started_at
                FROM ds_discovery_jobs
                WHERE source_id = %s AND status = 'running'
                ORDER BY started_at DESC LIMIT 1
            """, (source_id,))
            running = cur.fetchone()
            if running:
                return {
                    "success": False,
                    "message": f"Bu kaynak için zaten bir '{running['job_type']}' işi çalışıyor. Lütfen tamamlanmasını bekleyin."
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DataSources] Error validating source: %s", str(e))
        raise HTTPException(status_code=500, detail="Database validation error")

    user_id = getattr(current_user, "id", None) or current_user.get("id")

    def run_pipeline():
        bg_conn = None
        try:
            from app.core.db import get_db_conn
            bg_conn = get_db_conn()
            ds_learning_service.run_approved_qa_learning(source, bg_conn, user_id=user_id)
        except Exception as e:
            logger.error("[DataSources] Onaylı Öğrenme arka plan hatası: %s", str(e))
        finally:
            if bg_conn:
                try:
                    bg_conn.close()
                except Exception:
                    pass

    import threading
    threading.Thread(target=run_pipeline, daemon=True).start()
    return {"success": True, "message": "Onaylı tablolar için şema öğrenimi arka planda başlatıldı."}


@router.get("/{source_id}/schedule")
def get_schedule(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kaynağın öğrenme zamanlamasını döner."""
    try:
        with get_db_context() as conn:
            schedule = ds_learning_service.get_schedule(conn, source_id)
            return schedule
    except Exception as e:
        logger.error("[DataSources] Schedule yüklenirken hata oluştu")
        logger.debug("[DataSources] schedule detay: %s", type(e).__name__)
        return {"schedule_type": "manual_only", "is_active": False}


# =====================================================
# Enrichment API (v3.0.0)
# =====================================================

@router.get("/{source_id}/enrichment-stats")
def get_enrichment_stats(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kaynak için enrichment istatistiklerini döner."""
    try:
        from app.services import ds_enrichment_service
        with get_db_context() as conn:
            stats = ds_enrichment_service.get_enrichment_stats(conn, source_id)
            return {"success": True, **stats}
    except Exception as e:
        logger.error("[DataSources] Enrichment stats hatası: %s", type(e).__name__)
        return {"success": False, "total": 0}


@router.get("/{source_id}/enrichment-pending")
def get_pending_enrichments(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Admin onayı bekleyen tablo enrichment'larını döner."""
    try:
        from app.services import ds_enrichment_service
        with get_db_context() as conn:
            pending = ds_enrichment_service.get_pending_approvals(conn, source_id)
            return {"success": True, "pending": pending, "count": len(pending)}
    except Exception as e:
        logger.error("[DataSources] Pending enrichments hatası: %s", type(e).__name__)
        return {"success": False, "pending": [], "count": 0}


@router.get("/{source_id}/enrichment-approved")
def get_approved_enrichments(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Admin onayı almış ve RAG sistemine dahil edilmiş tabloları döner."""
    try:
        from app.services import ds_enrichment_service
        with get_db_context() as conn:
            approved = ds_enrichment_service.get_approved_enrichments(conn, source_id)
            return {"success": True, "approved": approved, "count": len(approved)}
    except Exception as e:
        logger.error("[DataSources] Approved enrichments hatası: %s", type(e).__name__)
        return {"success": False, "approved": [], "count": 0}


@router.get("/{source_id}/enrichment-all")
def get_all_enrichments(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Tüm tabloların keşif durumlarını beraber döner."""
    try:
        from app.services import ds_enrichment_service
        with get_db_context() as conn:
            all_tables = ds_enrichment_service.get_all_tables_status(conn, source_id)
            return {"success": True, "tables": all_tables, "count": len(all_tables)}
    except Exception as e:
        logger.error("[DataSources] All enrichments hatası: %s", type(e).__name__)
        return {"success": False, "tables": [], "count": 0}


class PartialEnrichmentRequest(BaseModel):
    object_ids: list[int]


@router.post("/{source_id}/enrich-selected")
def enrich_selected_tables(
    source_id: int,
    body: PartialEnrichmentRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    if not body.object_ids:
        return {"success": False, "message": "Seçili tablo yok."}
    try:
        from app.services import ds_learning_service
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
            source = cur.fetchone()
            if not source:
                return {"success": False, "message": "Kaynak bulunamadı"}
            source = dict(source) if hasattr(source, 'keys') else dict(zip([c[0] for c in cur.description], source))
            current_user_id = current_user.get("id")

            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {"success": False, "message": f"Devam eden bir işlem var ({rj['job_type']})."}
                
        def _bg_partial_enrich():
            bg_conn = None
            try:
                from app.core.db import get_db_conn
                bg_conn = get_db_conn()
                ds_learning_service.run_partial_enrichment(source, body.object_ids, bg_conn, current_user_id)
            except Exception as e:
                logger.error("[DataSources] BG Partial Enrichment hatası: %s", str(e))
            finally:
                if bg_conn:
                    try:
                        bg_conn.close()
                    except Exception:
                        pass

        import threading
        threading.Thread(target=_bg_partial_enrich, daemon=True).start()
        return {"success": True, "message": "Seçili tablolar için keşif başlatıldı"}
    except Exception as e:
        logger.error("[DataSources] enrich-selected hatası: %s", type(e).__name__)
        return {"success": False, "message": f"Hata: {type(e).__name__}"}


class EnrichmentApproveRequest(BaseModel):
    admin_label_tr: Optional[str] = None
    admin_notes: Optional[str] = None


@router.post("/{source_id}/enrichment-approve/{enrichment_id}")
def approve_enrichment(
    source_id: int,
    enrichment_id: int,
    body: EnrichmentApproveRequest = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Bir tablo enrichment'ını admin olarak onaylar.
    v3.9.0: Onay sonrası otomatik schema_record + embedding oluşturma.
    """
    try:
        from app.services import ds_enrichment_service
        from app.services import ds_learning_service
        label = body.admin_label_tr if body else None
        notes = body.admin_notes if body else None
        with get_db_context() as conn:
            # Çalışan iş kontrolü
            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {"success": False, "message": f"Bu kaynak için şu anda çalışan bir iş var ({rj['job_type']}). Onay işlemi yapmak için tamamlanmasını bekleyin."}

            success = ds_enrichment_service.approve_enrichment(
                conn, enrichment_id,
                current_user.get("id"),
                label, notes
            )
            if success:
                # v3.9.0: Onay sonrası otomatik schema_record + embedding oluştur
                try:
                    _generate_schema_record_for_enrichment(conn, source_id, enrichment_id)
                    logger.info(f"[DataSources] Enrichment #{enrichment_id} onaylandı → schema_record oluşturuldu")
                except Exception as sr_err:
                    logger.warning(f"[DataSources] schema_record oluşturulamadı: {sr_err}")
                    # Ana onay başarılı, schema_record hatası critical değil

                return {"success": True, "message": "Etiket onaylandı ve şema kaydı oluşturuldu"}
            return {"success": False, "message": "Onay işlemi başarısız"}
    except Exception as e:
        logger.error("[DataSources] Enrichment onay hatası: %s — %s", type(e).__name__, str(e)[:200])
        return {"success": False, "message": "Onay işlemi sırasında beklenmeyen bir hata oluştu."}


def _generate_schema_record_for_enrichment(conn, source_id: int, enrichment_id: int):
    """
    v3.9.0: Admin onayı sonrası otomatik schema_record ve embedding oluşturur.

    1. Onaylanan tablo enrichment + kolon bilgilerini toplar
    2. Yapılandırılmış schema_record metni üretir
    3. ds_learning_results tablosuna kaydeder
    4. Embedding hesaplayıp günceller

    Bu sayede search_db_knowledge() fonksiyonu onaylanan tabloyu
    cosine similarity ile bulabilir hale gelir.
    """
    import json

    cur = conn.cursor()

    # 1. Enrichment bilgisini al
    cur.execute("""
        SELECT te.id, te.source_id, te.schema_name, te.table_name,
               te.business_name_tr, te.admin_label_tr, te.description_tr,
               te.category, te.enrichment_score
        FROM ds_table_enrichments te
        WHERE te.id = %s AND te.admin_approved = TRUE
    """, (enrichment_id,))
    te_row = cur.fetchone()
    if not te_row:
        return  # Enrichment bulunamadı veya onaysız

    # company_id'yi data_sources'dan al (ds_learning_results NOT NULL constraint)
    cur.execute("SELECT company_id FROM data_sources WHERE id = %s", (source_id,))
    ds_row = cur.fetchone()
    company_id = ds_row["company_id"] if ds_row else None

    schema_name = te_row["schema_name"] or ""
    table_name = te_row["table_name"]
    full_table = f"{schema_name}.{table_name}" if schema_name else table_name
    bname = te_row["admin_label_tr"] or te_row["business_name_tr"] or table_name
    desc = te_row["description_tr"] or ""
    category = te_row["category"] or ""

    # 2. Kolon enrichment bilgilerini al
    cur.execute("""
        SELECT ce.column_name, ce.business_name_tr, ce.admin_label_tr,
               ce.synonyms_json, ce.semantic_type, ce.is_searchable
        FROM ds_column_enrichments ce
        WHERE ce.table_enrichment_id = %s
        ORDER BY ce.column_name
    """, (enrichment_id,))
    col_rows = cur.fetchall()

    # 3. Orijinal kolon bilgilerini al (veri tipleri için)
    cur.execute("""
        SELECT columns_json, row_count_estimate
        FROM ds_db_objects
        WHERE source_id = %s AND object_name = %s
          AND COALESCE(schema_name, '') = COALESCE(%s, '')
        LIMIT 1
    """, (source_id, table_name, schema_name))
    obj_row = cur.fetchone()
    columns_json = []
    row_estimate = 0
    if obj_row:
        col_data = obj_row["columns_json"]
        if isinstance(col_data, str):
            try:
                columns_json = json.loads(col_data)
            except Exception:
                columns_json = []
        elif isinstance(col_data, list):
            columns_json = col_data
        row_estimate = obj_row.get("row_count_estimate", 0) or 0

    # Kolon dtype haritası
    col_dtype_map = {c["name"]: c.get("data_type", "unknown") for c in columns_json if isinstance(c, dict)}

    # 4. Schema record metni oluştur
    lines = [
        f"Tablo: {full_table}",
        f"İş Adı: {bname}",
    ]
    if desc:
        lines.append(f"Açıklama: {desc}")
    if category:
        lines.append(f"Kategori: {category}")
    lines.append(f"Tahmini Satır: {row_estimate}")
    lines.append("")
    lines.append("Sütunlar:")

    for cr in col_rows:
        col_name = cr["column_name"]
        col_bname = cr.get("admin_label_tr") or cr.get("business_name_tr") or ""
        dtype = col_dtype_map.get(col_name, "unknown")
        synonyms = []
        raw_syn = cr.get("synonyms_json")
        if raw_syn:
            try:
                synonyms = json.loads(raw_syn) if isinstance(raw_syn, str) else (raw_syn or [])
            except Exception:
                synonyms = []

        col_line = f"  - {col_name} ({dtype})"
        if col_bname:
            col_line += f" [{col_bname}]"
        if synonyms:
            col_line += f" synonyms: {', '.join(synonyms[:5])}"
        if cr.get("is_searchable"):
            col_line += " [aranabilir]"
        lines.append(col_line)

    content_text = "\n".join(lines)

    # 5. ds_learning_results'a kaydet (UPSERT — aynı tablo için varsa güncelle)
    metadata = {
        "table_name": table_name,
        "schema_name": schema_name,
        "full_table": full_table,
        "business_name": bname,
        "category": category,
        "enrichment_id": enrichment_id,
        "auto_generated": True,
    }

    cur.execute("""
        SELECT id FROM ds_learning_results
        WHERE source_id = %s AND content_type = 'schema_record'
          AND metadata->>'full_table' = %s
        LIMIT 1
    """, (source_id, full_table))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE ds_learning_results
            SET content_text = %s, metadata = %s, embedding = NULL, updated_at = NOW()
            WHERE id = %s
        """, (content_text, json.dumps(metadata), existing["id"]))
        record_id = existing["id"]
    else:
        cur.execute("""
            INSERT INTO ds_learning_results
            (source_id, company_id, content_type, content_text, metadata, is_valid, created_at)
            VALUES (%s, %s, 'schema_record', %s, %s, TRUE, NOW())
            RETURNING id
        """, (source_id, company_id, content_text, json.dumps(metadata)))
        record_id = cur.fetchone()["id"]

    conn.commit()

    # 6. Embedding hesapla (async-safe, hata tolere edilir)
    try:
        from app.services.rag.embedding import EmbeddingManager
        emb_mgr = EmbeddingManager()
        embedding = emb_mgr.get_embedding(content_text)
        if embedding is not None:
            cur.execute(
                "UPDATE ds_learning_results SET embedding = %s WHERE id = %s",
                (json.dumps(embedding), record_id)
            )
            conn.commit()
            logger.info(f"[DataSources] schema_record embedding oluşturuldu: {full_table} (id={record_id})")
    except Exception as emb_err:
        logger.warning(f"[DataSources] Embedding hesaplanamadı: {emb_err}")


@router.get("/enrichment/{enrichment_id}/columns")
def get_column_enrichments(
    enrichment_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Bir tablo enrichment'ına ait sütun zenginleştirmelerini döner."""
    try:
        from app.services import ds_enrichment_service
        with get_db_context() as conn:
            columns = ds_enrichment_service.get_column_enrichments(conn, enrichment_id)
            return {"success": True, "columns": columns}
    except Exception as e:
        logger.error("[DataSources] Column enrichments hatası: %s", type(e).__name__)
        return {"success": False, "columns": []}


@router.get("/{source_id}/schema-history")
def get_schema_history(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kaynağın schema snapshot geçmişini döner."""
    try:
        from app.services import ds_diff_service
        with get_db_context() as conn:
            history = ds_diff_service.get_snapshot_history(conn, source_id)
            return {"success": True, "history": history}
    except Exception as e:
        logger.error("[DataSources] Schema history hatası: %s", type(e).__name__)
        return {"success": False, "history": []}
