"""
VYRA L1 Support API - Data Sources Routes
===========================================
Veri kaynakları CRUD endpoint'leri.
v2.56.0
"""

import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query, Body, BackgroundTasks
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context
from app.services.permission_audit import log_permission_change

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


class CollectSamplesRequest(BaseModel):
    schemas: Optional[List[str]] = None  # None = tüm şemalar, liste = belirli şemalar


# v3.17.0: Kaynak bazlı yetkilendirme
class DataSourcePermissionsUpdate(BaseModel):
    user_ids: List[int] = Field(default_factory=list)
    org_ids: List[int] = Field(default_factory=list)
    can_execute_user_ids: List[int] = Field(default_factory=list)
    can_execute_org_ids: List[int] = Field(default_factory=list)


# --- Helpers ---

def _encrypt_password(plain: str) -> str:
    """Şifreyi Fernet ile şifreler. Key yoksa encryption modülünden alır."""
    try:
        from app.core.encryption import encrypt_password
        return encrypt_password(plain)
    except Exception:
        pass
    # Fallback: Fernet key environment'tan
    try:
        from cryptography.fernet import Fernet
        import os
        key = os.environ.get("VYRA_ENCRYPT_KEY")
        if key:
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.encrypt(plain.encode()).decode()
    except ImportError:
        pass
    # Son çare: base64 (güvensiz — log uyarısı)
    import base64
    logger.warning("[DataSources] UYARI: Fernet key bulunamadı, şifre base64 ile saklanıyor (güvensiz)")
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
    Admin: Tüm firmalar veya company_id ile filtreli (yetki kontrolü uygulanmaz).
    User: Yalnızca kendisine veya üye olduğu org gruplarına yetki verilmiş kaynaklar.
    (v3.17.0) Yetki listesi boş olan kaynaklar admin dışı kullanıcılara görünmez.
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
            user_id = current_user.get("id")
            if not user_id:
                return []
            # v3.17.0: Yetki tablosundan filtreli liste. Yetki yoksa kullanıcı hiçbir kaynağı görmez.
            cur.execute("""
                SELECT DISTINCT ds.*, c.name as company_name
                FROM data_sources ds
                JOIN companies c ON c.id = ds.company_id
                JOIN data_source_permissions p ON p.source_id = ds.id AND p.can_view = TRUE
                LEFT JOIN user_organizations uo
                       ON uo.user_id = %s AND p.subject_type = 'org' AND uo.org_id = p.subject_id
                WHERE (p.subject_type = 'user' AND p.subject_id = %s)
                   OR (p.subject_type = 'org' AND uo.id IS NOT NULL)
                ORDER BY ds.name
            """, (user_id, user_id))

        rows = cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            # Şifreyi maskele
            item["db_password_encrypted"] = _mask_password(item.get("db_password_encrypted"))
            result.append(item)
        return result


# v3.17.0: Kaynak bazlı yetki endpointleri
@router.get("/{source_id}/permissions")
def get_source_permissions(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Kaynağa atanmış kullanıcı ve org gruplarını döner."""
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    if not is_admin:
        raise HTTPException(status_code=403, detail="Yetki yönetimi sadece admin yapabilir.")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM data_sources WHERE id = %s", (source_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

        cur.execute("""
            SELECT subject_type, subject_id, can_view, can_execute
            FROM data_source_permissions
            WHERE source_id = %s
        """, (source_id,))
        rows = cur.fetchall()

    user_ids: List[int] = []
    org_ids: List[int] = []
    can_execute_user_ids: List[int] = []
    can_execute_org_ids: List[int] = []
    for r in rows:
        item = dict(r)
        if item["subject_type"] == "user":
            if item.get("can_view"):
                user_ids.append(item["subject_id"])
            if item.get("can_execute"):
                can_execute_user_ids.append(item["subject_id"])
        elif item["subject_type"] == "org":
            if item.get("can_view"):
                org_ids.append(item["subject_id"])
            if item.get("can_execute"):
                can_execute_org_ids.append(item["subject_id"])

    return {
        "user_ids": user_ids,
        "org_ids": org_ids,
        "can_execute_user_ids": can_execute_user_ids,
        "can_execute_org_ids": can_execute_org_ids,
    }


@router.put("/{source_id}/permissions")
def update_source_permissions(
    source_id: int,
    data: DataSourcePermissionsUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Kaynağa atanmış yetkileri tam liste replace ile günceller.
    user_ids/org_ids → can_view; can_execute_*_ids → can_execute.
    can_execute verilen subject otomatik view'a da sahip sayılır.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    if not is_admin:
        raise HTTPException(status_code=403, detail="Yetki yönetimi sadece admin yapabilir.")

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, company_id FROM data_sources WHERE id = %s", (source_id,))
        ds_row = cur.fetchone()
        if not ds_row:
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")

        # Audit için ÖNCEKİ durumu yakala
        cur.execute("""
            SELECT subject_type, subject_id, can_view, can_execute
            FROM data_source_permissions
            WHERE source_id = %s
            ORDER BY subject_type, subject_id
        """, (source_id,))
        before_rows = [dict(r) for r in cur.fetchall()]

        # Eski yetkileri temizle, yeni listeyi yaz (replace semantiği)
        cur.execute("DELETE FROM data_source_permissions WHERE source_id = %s", (source_id,))

        # can_execute olan subject'lar view'a da otomatik sahip
        view_users = set(data.user_ids) | set(data.can_execute_user_ids)
        view_orgs = set(data.org_ids) | set(data.can_execute_org_ids)
        exec_users = set(data.can_execute_user_ids)
        exec_orgs = set(data.can_execute_org_ids)

        granted_by = current_user.get("id")
        rows_to_insert = []
        for uid in view_users:
            rows_to_insert.append((source_id, "user", uid, True, uid in exec_users, granted_by))
        for oid in view_orgs:
            rows_to_insert.append((source_id, "org", oid, True, oid in exec_orgs, granted_by))

        for row in rows_to_insert:
            cur.execute("""
                INSERT INTO data_source_permissions
                (source_id, subject_type, subject_id, can_view, can_execute, granted_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, row)

        # Audit log (v3.18.0 — aynı transaction içinde)
        after_rows = [
            {"subject_type": r[1], "subject_id": r[2], "can_view": r[3], "can_execute": r[4]}
            for r in rows_to_insert
        ]
        ds_company_id = ds_row["company_id"] if isinstance(ds_row, dict) else (ds_row[1] if len(ds_row) > 1 else None)
        log_permission_change(
            cur,
            actor_user_id=current_user.get("id"),
            company_id=ds_company_id,
            permission_type="data_source",
            target_key=str(source_id),
            action="replace",
            before={"permissions": before_rows},
            after={"permissions": after_rows},
        )

        conn.commit()

    logger.info(
        "[DataSources] Yetkiler güncellendi: source_id=%s, users=%d, orgs=%d (exec users=%d, exec orgs=%d)",
        source_id, len(view_users), len(view_orgs), len(exec_users), len(exec_orgs)
    )
    return {
        "success": True,
        "message": "Yetkiler güncellendi.",
        "user_count": len(view_users),
        "org_count": len(view_orgs),
    }


@router.get("/permissions/subjects")
def list_permission_subjects(
    company_id: Optional[int] = Query(None),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Yetki modal'ında seçim için kullanıcı ve org grubu listelerini döner.
    Sadece admin erişebilir.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    if not is_admin:
        raise HTTPException(status_code=403, detail="Yetki yönetimi sadece admin yapabilir.")

    with get_db_context() as conn:
        cur = conn.cursor()

        # Kullanıcılar
        if company_id:
            cur.execute("""
                SELECT id, full_name, username, email, company_id
                FROM users
                WHERE is_approved = TRUE AND (company_id = %s OR company_id IS NULL)
                ORDER BY full_name
            """, (company_id,))
        else:
            cur.execute("""
                SELECT id, full_name, username, email, company_id
                FROM users
                WHERE is_approved = TRUE
                ORDER BY full_name
            """)
        users = [dict(r) for r in cur.fetchall()]

        # Org grupları
        if company_id:
            cur.execute("""
                SELECT id, org_code, org_name, description, company_id
                FROM organization_groups
                WHERE is_active = TRUE AND (company_id = %s OR company_id IS NULL)
                ORDER BY org_code
            """, (company_id,))
        else:
            cur.execute("""
                SELECT id, org_code, org_name, description, company_id
                FROM organization_groups
                WHERE is_active = TRUE
                ORDER BY org_code
            """)
        orgs = [dict(r) for r in cur.fetchall()]

    return {"users": users, "orgs": orgs}


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


_oracle_thick_initialized = False

def _init_oracle_thick_mode():
    """Oracle Instant Client varsa thick mode'u başlat (DPY-3015 hatası için gerekli)."""
    global _oracle_thick_initialized
    if _oracle_thick_initialized:
        return
    import oracledb
    try:
        # Proje içindeki Instant Client'ı dene
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        ic_candidates = [
            project_root / "setup" / "windows" / "instantclient",
            project_root / "instantclient",
            Path(r"C:\oracle\instantclient"),
        ]
        lib_dir = None
        for candidate in ic_candidates:
            if candidate.exists() and (candidate / "oci.dll").exists():
                lib_dir = str(candidate)
                break

        if lib_dir:
            oracledb.init_oracle_client(lib_dir=lib_dir)
            logger.info(f"[Oracle] Thick mode aktif: {lib_dir}")
        else:
            oracledb.init_oracle_client()
            logger.info("[Oracle] Thick mode aktif (PATH'ten)")
        _oracle_thick_initialized = True
    except oracledb.ProgrammingError:
        # Zaten init edilmiş
        _oracle_thick_initialized = True
    except Exception as e:
        logger.warning(f"[Oracle] Thick mode baslatılamadı, thin mode kullanılacak: {e}")


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
        import oracledb
        _init_oracle_thick_mode()
        dsn = oracledb.makedsn(host, port, service_name=db_name)
        conn = oracledb.connect(user=db_user, password=password, dsn=dsn)
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
        error_type = type(e).__name__
        error_msg = str(e)
        logger.warning(f"[DataSources] Bağlantı testi hatası: {error_type}: {error_msg}")

        # Bilinen hata tiplerini kullanıcı dostu mesaja çevir
        friendly_messages = {
            "OperationalError": f"Veritabanına bağlanılamadı. Sunucu adresi, port veya kimlik bilgilerini kontrol edin.\n\nDetay: {error_msg}",
            "InterfaceError": f"Veritabanı sürücüsü bağlantı kuramadı.\n\nDetay: {error_msg}",
            "DatabaseError": f"Veritabanı hatası.\n\nDetay: {error_msg}",
            "ConnectionRefusedError": f"Bağlantı reddedildi. Sunucu çalışıyor mu? Port açık mı?\n\nDetay: {error_msg}",
            "ConnectionResetError": f"Bağlantı sunucu tarafından kesildi.\n\nDetay: {error_msg}",
            "TimeoutError": f"Bağlantı zaman aşımına uğradı. Sunucu erişilebilir mi?\n\nDetay: {error_msg}",
            "timeout": f"Bağlantı zaman aşımına uğradı.\n\nDetay: {error_msg}",
            "gaierror": f"Sunucu adresi çözümlenemedi. DNS ayarlarını veya host adresini kontrol edin.\n\nDetay: {error_msg}",
            "AuthenticationError": f"Kimlik doğrulama başarısız. Kullanıcı adı veya şifreyi kontrol edin.\n\nDetay: {error_msg}",
            "ModuleNotFoundError": f"Gerekli veritabanı sürücüsü kurulu değil.\n\nDetay: {error_msg}",
            "ImportError": f"Gerekli veritabanı sürücüsü yüklenemedi.\n\nDetay: {error_msg}",
            "NotSupportedError": f"Oracle bağlantısı için thick mode gerekli. setup/windows/instantclient/ klasörünün sunucuda mevcut olduğundan emin olun.\n\nDetay: {error_msg}",
            "ProgrammingError": f"SQL veya bağlantı parametresi hatası.\n\nDetay: {error_msg}",
            "InternalError": f"Veritabanı iç hatası.\n\nDetay: {error_msg}",
            "OSError": f"Ağ bağlantısı kurulamadı. Sunucu adresi ve portu kontrol edin.\n\nDetay: {error_msg}",
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
        return {"success": False, "message": "Teknoloji keşfi sırasında beklenmeyen bir hata oluştu."}


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
        return {"success": False, "message": "Obje tespiti sırasında beklenmeyen bir hata oluştu."}


@router.get("/{source_id}/discovered-schemas")
def get_discovered_schemas(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Adım 2 sonrası: DS_DB_OBJECTS içindeki distinct şemaları ve tablo sayılarını döner."""
    try:
        # v3.20.0 Faz 1c: ds_db_objects RLS koruma altında — source_id ile scope
        from app.core.db import get_db_context_scoped
        with get_db_context_scoped(source_id) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT schema_name, COUNT(*) AS table_count
                FROM ds_db_objects
                WHERE source_id = %s AND object_type = 'table'
                GROUP BY schema_name
                ORDER BY schema_name
            """, (source_id,))
            rows = cur.fetchall()
            schemas = [
                {"schema": row["schema_name"] or "(varsayılan)", "table_count": row["table_count"]}
                for row in rows
            ]
            return {"success": True, "schemas": schemas}
    except Exception as e:
        logger.error("[DataSources] discovered-schemas hatası: %s", type(e).__name__)
        return {"success": False, "schemas": []}


@router.get("/{source_id}/samples")
def get_table_samples(
    source_id: int,
    schema: Optional[str] = Query(None, max_length=128, description="Şema adı (NULL/boş = varsayılan)"),
    table: str = Query(..., min_length=1, max_length=256, description="Tablo adı"),
    limit: int = Query(5, ge=1, le=50, description="Döndürülecek satır sayısı (1-50)"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    v3.28.2 G3 — Sample Data Preview (cached).

    `ds_db_samples` cache'inden önceden toplanmış örnek satırları okur, kolon
    tipleri için `ds_db_objects.columns_json`'a, Türkçe etiket için
    `ds_table_enrichments.business_name_tr`'ye join atar.

    Cache miss → 404 + "discover/collect-samples job çalıştırılmalı" hint'i.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    try:
        with get_db_context() as conn:
            cur = conn.cursor()

            # Permission: source'un sahipliği (company_id) kontrol et
            cur.execute("SELECT id, company_id FROM data_sources WHERE id = %s", (source_id,))
            src = cur.fetchone()
            if not src:
                raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")
            src = dict(src)
            if not is_admin and current_user.get("company_id") != src.get("company_id"):
                raise HTTPException(status_code=403, detail="Bu kaynağa erişim yetkiniz yok.")

            # ds_db_objects ile join: schema NULL ise IS NULL match, değilse eşitlik
            if schema is None or schema.strip() == "":
                obj_where = "schema_name IS NULL"
                obj_args = (source_id, table)
            else:
                obj_where = "schema_name = %s"
                obj_args = (source_id, schema, table)

            cur.execute(f"""
                SELECT s.sample_data, s.row_count, s.fetched_at,
                       o.columns_json, o.schema_name, o.object_name
                FROM ds_db_samples s
                JOIN ds_db_objects o ON o.id = s.object_id
                WHERE s.source_id = %s
                  AND o.{obj_where}
                  AND o.object_name = %s
                  AND o.object_type = 'table'
                ORDER BY s.fetched_at DESC
                LIMIT 1
            """, obj_args)
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Bu tablo için örnek veri bulunamadı. Yöneticinizden 'Örnek Veri Topla' job'ını çalıştırmasını isteyin."
                )
            row = dict(row)

            sample_data = row.get("sample_data") or []
            if not isinstance(sample_data, list):
                sample_data = []

            # Limit uygula (cache'de daha fazla olabilir)
            rows_out = sample_data[:limit]

            # Kolon meta: columns_json içindeki sırayı koru, ds_table_enrichments'ten label
            columns_meta: List[Dict[str, Any]] = []
            cols_json = row.get("columns_json") or []
            if isinstance(cols_json, list):
                col_names = []
                for c in cols_json:
                    if isinstance(c, dict):
                        cname = c.get("name") or c.get("column_name")
                        ctype = c.get("type") or c.get("data_type") or ""
                        if cname:
                            columns_meta.append({"name": cname, "type": str(ctype)})
                            col_names.append(cname)

            # Eğer columns_json boş ya da eksikse: sample_data'nın ilk satırından kolonları çıkar
            if not columns_meta and rows_out:
                first = rows_out[0] if isinstance(rows_out[0], dict) else {}
                for k in first.keys():
                    columns_meta.append({"name": k, "type": ""})

            # ds_table_enrichments → business_name_tr
            business_name_tr = None
            try:
                if row.get("schema_name") is None:
                    cur.execute("""
                        SELECT business_name_tr FROM ds_table_enrichments
                        WHERE source_id = %s AND schema_name IS NULL AND table_name = %s
                        LIMIT 1
                    """, (source_id, row.get("object_name")))
                else:
                    cur.execute("""
                        SELECT business_name_tr FROM ds_table_enrichments
                        WHERE source_id = %s AND schema_name = %s AND table_name = %s
                        LIMIT 1
                    """, (source_id, row.get("schema_name"), row.get("object_name")))
                enr = cur.fetchone()
                if enr:
                    business_name_tr = dict(enr).get("business_name_tr")
            except Exception:
                # Enrichment join opsiyonel — hata olursa label'sız döner
                pass

            return {
                "success": True,
                "source_id": source_id,
                "schema": row.get("schema_name"),
                "table": row.get("object_name"),
                "business_name_tr": business_name_tr,
                "columns": columns_meta,
                "rows": rows_out,
                "row_count": row.get("row_count") or len(rows_out),
                "fetched_at": row.get("fetched_at").isoformat() if row.get("fetched_at") else None,
                "cached": True,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DataSources] get_table_samples hatası: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Örnek veri okunamadı.")


@router.post("/{source_id}/collect-samples")
def collect_samples(
    source_id: int,
    body: CollectSamplesRequest = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Adım 3: Tablolardan örnek veri topla (arka planda çalışır, hemen döner).
    body.schemas: Sadece bu şemalar örneklenir. None = tüm şemalar.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    schema_filter = (body.schemas if body else None) or None

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

            # Job'ı oluştur, hemen dön — veri toplama arka planda çalışır
            job_id = ds_learning_service.create_job(conn, source_id, source["company_id"], "samples", current_user.get("id"))

        schema_log = f"{len(schema_filter)} şema" if schema_filter else "tüm şemalar"
        logger.info("[DataSources] Veri toplama başlatıldı (arka plan): source_id=%s, %s", source_id, schema_log)

        def _bg_collect():
            bg_conn = None
            try:
                from app.core.db import get_db_conn
                bg_conn = get_db_conn()
                result = ds_learning_service.collect_samples(source, bg_conn, schema_filter=schema_filter)
                ds_learning_service.complete_job(bg_conn, job_id, result)
            except Exception:
                logger.error("[BG] Veri toplama arka plan hatası: source_id=%s", source_id)
            finally:
                if bg_conn:
                    try:
                        bg_conn.close()
                    except Exception:
                        pass

        threading.Thread(target=_bg_collect, daemon=True).start()
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Veri toplama başlatıldı ({schema_log}). İlerlemeyi check-running-job ile takip edebilirsiniz."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DataSources] Örnek veri toplama sırasında hata oluştu")
        logger.debug("[DataSources] collect_samples detay: %s", type(e).__name__)
        return {"success": False, "message": "Veri toplama sırasında beklenmeyen bir hata oluştu."}


@router.get("/{source_id}/check-running-job")
def check_running_job(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Bu kaynak için çalışan bir iş var mı kontrol eder (frontend guard için).

    v3.32.0 ARES Y1-recur fix: Cross-tenant ACL guard + source-scoped RLS.
    Frontend bu endpoint'i 3s'de bir poll'ladığı için company-level ACL kontrolü
    yapılmadan kullanılması cross-tenant job state enumeration'a yol açıyordu.
    Ayrıca `check_running_job` service'i stuck job'ları UPDATE ediyor — bu cross-
    tenant write riski demek. Bulk approve'daki Y1 fix pattern'i ile aynı.
    """
    from app.core.db import get_db_context_scoped

    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    try:
        # ACL: source.company_id == caller.company_id ?
        with get_db_context() as _acl_conn:
            _acl_cur = _acl_conn.cursor()
            _acl_cur.execute(
                "SELECT company_id FROM data_sources WHERE id = %s",
                (source_id,)
            )
            _row = _acl_cur.fetchone()
            if not _row:
                raise HTTPException(status_code=404, detail="Veri kaynagi bulunamadi.")
            source_company_id = _row["company_id"] if hasattr(_row, "keys") else _row[0]
        if not is_admin and current_user.get("company_id") != source_company_id:
            logger.warning(
                "[DataSources] check-running-job ACL reddi: user_company=%s source_company=%s source_id=%s user=%s",
                current_user.get("company_id"), source_company_id, source_id, current_user.get("id")
            )
            raise HTTPException(status_code=403, detail="Bu kaynaga erisim yetkiniz yok.")

        with get_db_context_scoped(source_id) as conn:
            result = ds_learning_service.check_running_job(conn, source_id)
            return {"success": True, **result}
    except HTTPException:
        # ACL guard (403/404) FastAPI'ye olduğu gibi geçsin — frontend gate'i için kritik
        raise
    except Exception as e:
        logger.error("[DataSources] Running job kontrolü sırasında hata: %s", type(e).__name__)
        # D1 fix: swallow yerine açık hata bildir; frontend poll loop exponential backoff yapar.
        # has_running=False döndürmek "double-bulk" riskine yol açar.
        return {"success": False, "has_running": False, "job": None, "error": "check_failed"}


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
        return {"success": False, "message": "Pipeline başlatılırken beklenmeyen bir hata oluştu."}

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
        return {"success": False, "message": "Seçili tablolar için keşif başlatılırken hata oluştu."}


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
        # v3.20.0 Faz 1c: schema_record üretimi ds_db_objects + ds_learning_results
        # tablolarına yazar (RLS koruma altında) → source_id ile scoped context
        from app.core.db import get_db_context_scoped
        with get_db_context_scoped(source_id) as conn:
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


# ==========================================================================
# v3.31.0 (Faz 1) — Bulk approve endpoint
# v3.32.0 (Faz 2) — BackgroundTasks + async warnings (IMPLEMENTED)
# ==========================================================================
# Plan: .agents/plans/2026-05-23_1430_bulk_enrichment_endpoints_v1.md (Faz 1)
#       .agents/plans/2026-05-23_1454_bulk_phase2_backgroundtasks_v1.md (Faz 2)
#
# Tasarim:
#   1) ARES validation: enrichment_ids hepsi source_id'ye ait mi (cross-source)
#      Faz 2 (mig 043): composite index (source_id, id) — index-only scan.
#   2) check_running_job preflight
#   3) Tek connection icinde per-item SAVEPOINT loop -> UPDATE ds_table_enrichments
#      - stop_on_error=False (default): partial success; basarisizlar
#        ROLLBACK TO SAVEPOINT ile temizlenir, basarililar outer COMMIT'te kalir
#      - stop_on_error=True: ilk hatada outer ROLLBACK -> hicbir kayit degismez
#   4) Outer COMMIT
#   5) Faz 2: schema_record + embedding üretimi fastapi.BackgroundTasks ile
#      response gönderildikten SONRA çalışır (önceden blocking 13-60s idi).
#      ThreadPoolExecutor(max_workers=max_parallel) — her thread kendi
#      company-RLS scoped connection'unu acar. Hatalar artık response'a
#      eklenmiyor; ds_schema_record_warnings tablosuna INSERT edilir
#      (mig 043). Admin warning panel'inden poll edilir.
#
# Notlar:
#   - approve_enrichment service func'i kendi commit'ini yapiyor -> bu
#     endpoint'te kullanilamaz (SAVEPOINT'leri bozardi). UPDATE inline.
#   - Response shape: schema_record_warnings (sync) -> schema_record_pending
#     (bool) bayrağı ile değiştirildi. Frontend bu bayrağa göre "embedding
#     arka planda işleniyor" toast'u gösterir.
# ==========================================================================

class EnrichmentApproveBulkRequest(BaseModel):
    enrichment_ids: List[int]
    stop_on_error: bool = False
    max_parallel: int = 5  # 1..10 clamp; embedding ThreadPool worker sayisi


@router.post("/{source_id}/enrichment-approve-bulk")
def approve_enrichment_bulk(
    source_id: int,
    body: EnrichmentApproveBulkRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    v3.31.0: Toplu enrichment onay endpoint'i.
    v3.32.0 Faz 2: schema_record üretimi BackgroundTasks ile post-response;
    response süresi 13-60s'den <500ms'e düşer. Hatalar
    ds_schema_record_warnings tablosuna INSERT edilir (mig 043).
    """
    if not body.enrichment_ids:
        # v3.32.0 TYCHE Y1 fix: response contract — diğer 6 branch'a uyumlu hale getirdi
        return {
            "success": False, "message": "Onaylanacak enrichment_id yok.", "code": "empty",
            "total": 0, "approved": 0, "failed": 0, "approved_ids": [],
            "errors": [], "schema_record_pending": False
        }

    # max_parallel server-side clamp.
    # Pool guard: maxconn=15. Outer conn release sonrasi N worker conn acilir; 3 user x 5 = 15.
    # Tavan 3 -> 3 user x 3 = 9 conn parallel phase'de; outer dahil dahi limit altinda.
    max_parallel = max(1, min(3, body.max_parallel or 3))
    enrichment_ids = list(dict.fromkeys(body.enrichment_ids))  # dedupe, order korunur
    user_id = current_user.get("id")
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"

    approved_ids: List[int] = []
    failed: List[Dict[str, Any]] = []
    schema_record_pending: bool = False
    source_company_id: Optional[int] = None

    try:
        from app.services import ds_learning_service
        from app.core.db import get_db_context_scoped

        # ARES: Company-level ACL guard — caller'in tenant'i source.company_id ile esit mi?
        # Source-only RLS scope cross-tenant'i tek basina engellemez; bulk POST = N satir blast.
        with get_db_context() as _acl_conn:
            _acl_cur = _acl_conn.cursor()
            _acl_cur.execute(
                "SELECT company_id FROM data_sources WHERE id = %s",
                (source_id,)
            )
            _row = _acl_cur.fetchone()
            if not _row:
                raise HTTPException(status_code=404, detail="Veri kaynagi bulunamadi.")
            source_company_id = _row["company_id"] if hasattr(_row, "keys") else _row[0]
        if not is_admin and current_user.get("company_id") != source_company_id:
            logger.warning(
                "[DataSources] Bulk approve ACL reddi: user_company=%s source_company=%s source_id=%s user=%s",
                current_user.get("company_id"), source_company_id, source_id, user_id
            )
            raise HTTPException(status_code=403, detail="Bu kaynaga erisim yetkiniz yok.")

        with get_db_context_scoped(source_id) as conn:
            # 1) Calisan is kontrolu
            running_check = ds_learning_service.check_running_job(conn, source_id)
            if running_check["has_running"]:
                rj = running_check["job"]
                return {
                    "success": False,
                    "code": "running_job",
                    "message": f"Bu kaynak icin calisan bir is var ({rj['job_type']}). Tamamlanmasini bekleyin.",
                    "total": len(enrichment_ids), "approved": 0, "failed": 0,
                    "errors": [], "schema_record_pending": False
                }

            cur = conn.cursor()

            # 2) ARES: enrichment_ids hepsi bu source_id'ye ait mi?
            cur.execute("""
                SELECT id FROM ds_table_enrichments
                WHERE source_id = %s AND id = ANY(%s)
            """, (source_id, enrichment_ids))
            rows = cur.fetchall()
            valid_set = set()
            for r in rows:
                rid = r["id"] if hasattr(r, "keys") else r[0]
                valid_set.add(rid)
            invalid_ids = [i for i in enrichment_ids if i not in valid_set]
            if invalid_ids:
                logger.warning(
                    "[DataSources] Bulk approve: cross-source/unknown eid'ler reddedildi "
                    "user=%s source=%s ids=%s", user_id, source_id, invalid_ids[:10]
                )
                return {
                    "success": False,
                    "code": "cross_source_or_unknown",
                    "message": (
                        f"Bu kaynakta bulunmayan {len(invalid_ids)} enrichment_id var. "
                        "Onay reddedildi."
                    ),
                    "invalid_ids": invalid_ids[:50],
                    "total": len(enrichment_ids), "approved": 0,
                    "failed": len(invalid_ids), "errors": [], "schema_record_pending": False
                }

            # 3) Per-item SAVEPOINT loop — UPDATE only.
            # SAVEPOINT name: int(eid) defensive cast (Pydantic List[int] zaten dogrular,
            # f-string ile yine de baglam-bagimsiz guvende olsun).
            for eid in enrichment_ids:
                sp_name = f"sp_appr_{int(eid)}"
                try:
                    cur.execute(f"SAVEPOINT {sp_name}")
                    cur.execute("""
                        UPDATE ds_table_enrichments
                        SET admin_approved = TRUE,
                            approved_by = %s,
                            approved_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s AND source_id = %s
                    """, (user_id, eid, source_id))
                    if cur.rowcount == 0:
                        # Row vanished or filtered out (race) — savepoint geri al + release
                        # PG semantics: ROLLBACK TO sonrasi savepoint aktif kalir; 100 fail
                        # senaryosunda sub-tx state birikmesin diye RELEASE zorunlu.
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                        cur.execute(f"RELEASE SAVEPOINT {sp_name}")
                        failed.append({"enrichment_id": eid, "reason": "row_not_found"})
                        if body.stop_on_error:
                            conn.rollback()
                            return {
                                "success": False, "code": "stopped",
                                "total": len(enrichment_ids),
                                "approved": 0, "failed": len(failed),
                                "approved_ids": [],
                                "errors": failed, "schema_record_pending": False,
                                "message": f"stop_on_error: enrichment #{eid} bulunamadi"
                            }
                        continue
                    cur.execute(f"RELEASE SAVEPOINT {sp_name}")
                    approved_ids.append(eid)
                except Exception as item_err:
                    # Item-level rollback + release (state birikmesini onle)
                    try:
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                        cur.execute(f"RELEASE SAVEPOINT {sp_name}")
                    except Exception:
                        pass
                    logger.error(
                        "[DataSources] Bulk approve item hata eid=%s: %s",
                        eid, type(item_err).__name__
                    )
                    failed.append({
                        "enrichment_id": eid,
                        "reason": type(item_err).__name__
                    })
                    if body.stop_on_error:
                        conn.rollback()
                        return {
                            "success": False, "code": "stopped",
                            "total": len(enrichment_ids),
                            "approved": 0, "failed": len(failed),
                            "approved_ids": [],
                            "errors": failed, "schema_record_pending": False,
                            "message": (
                                f"stop_on_error: enrichment #{eid} "
                                f"({type(item_err).__name__})"
                            )
                        }

            # 4) Outer COMMIT — basarili olanlar kalici
            conn.commit()

        # 5) Faz 2: schema_record + embedding üretimi BackgroundTasks ile.
        # Response gönderildikten SONRA çalışır; hatalar ds_schema_record_warnings
        # tablosuna INSERT edilir (mig 043). company_id worker'a geçirilir —
        # company-RLS'li tablolara (agentic_query_feedback, few_shot_examples,
        # pipeline_events — mig 017) yazdığında RLS reddi yememesi için.
        if approved_ids:
            background_tasks.add_task(
                _generate_schema_records_background,
                source_id, source_company_id, approved_ids, max_parallel
            )
            schema_record_pending = True

        success_flag = len(approved_ids) > 0
        msg_parts = [f"{len(approved_ids)} tablo onaylandi"]
        if failed:
            msg_parts.append(f"{len(failed)} basarisiz")
        if schema_record_pending:
            msg_parts.append("embedding arka planda isleniyor")
        return {
            "success": success_flag,
            "total": len(enrichment_ids),
            "approved": len(approved_ids),
            "failed": len(failed),
            "approved_ids": approved_ids,
            "errors": failed,
            "schema_record_pending": schema_record_pending,
            "message": ", ".join(msg_parts)
        }

    except HTTPException:
        # ACL guard (403/404) FastAPI'ye olduğu gibi geçsin
        raise
    except Exception as e:
        logger.error(
            "[DataSources] Bulk approve beklenmeyen hata: %s — %s",
            type(e).__name__, str(e)[:200]
        )
        return {
            "success": False, "code": "unexpected",
            "message": "Toplu onay sirasinda beklenmeyen hata olustu.",
            "total": len(enrichment_ids),
            "approved": len(approved_ids), "failed": len(failed),
            "approved_ids": approved_ids,
            "errors": failed, "schema_record_pending": schema_record_pending
        }


def _generate_schema_records_background(source_id: int,
                                         company_id: Optional[int],
                                         enrichment_ids: List[int],
                                         max_workers: int) -> None:
    """
    v3.32.0 Faz 2: BackgroundTask — bulk approve sonrası response gönderildikten
    SONRA çalışır. Onaylanan enrichment'lar için schema_record + embedding
    üretir. Her worker kendi DB connection'unu açar.

    company_id: source.company_id — worker cursor'una SET LOCAL ile uygulanır
    (mig 017 company-RLS'li tablolar için gerekli).

    Hata semantiği:
      - Schema record/embedding hataları critical değil; approve UPDATE
        zaten commit edilmiş.
      - Failure'lar ds_schema_record_warnings tablosuna INSERT edilir
        (mig 043 — PERMISSIVE company-RLS).
      - Bu fonksiyon ASLA raise etmez (response zaten gönderildi).
      - reason = type(e).__name__ (sanitized, client-safe).
      - detail = str(e)[:500] (server-side; admin endpoint'ten görünür).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.core.db import get_db_context_scoped, apply_company_scope, get_db_context

    def _worker(eid: int) -> Optional[Dict[str, Any]]:
        try:
            with get_db_context_scoped(source_id) as w_conn:
                # Company-RLS scope (mig 017)
                w_cur = w_conn.cursor()
                apply_company_scope(w_cur, company_id=company_id)
                w_cur.close()
                _generate_schema_record_for_enrichment(w_conn, source_id, eid)
            return None  # success
        except Exception as e:
            logger.warning(
                "[DSEnrich] BG schema_record warn eid=%s: %s — %s",
                eid, type(e).__name__, str(e)[:200]
            )
            return {
                "eid": eid,
                "reason": type(e).__name__,
                "detail": str(e)[:500]
            }

    failures: List[Dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_worker, eid): eid for eid in enrichment_ids}
            for fut in as_completed(futures):
                r = fut.result()
                if r is not None:
                    failures.append(r)
    except Exception as e:
        logger.error(
            "[DSEnrich] BG ThreadPool fatal: %s — %s",
            type(e).__name__, str(e)[:200]
        )

    # Persist failures to ds_schema_record_warnings (mig 043)
    if failures and company_id is not None:
        try:
            with get_db_context() as conn:
                cur = conn.cursor()
                for f in failures:
                    cur.execute(
                        """INSERT INTO ds_schema_record_warnings
                           (enrichment_id, source_id, company_id, reason, detail)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (f["eid"], source_id, company_id, f["reason"], f["detail"])
                    )
                conn.commit()
                logger.warning(
                    "[DSEnrich] BG: %d schema_record warning(s) persisted source=%s",
                    len(failures), source_id
                )
        except Exception as persist_err:
            # Yine raise etmiyoruz — sadece log
            logger.error(
                "[DSEnrich] BG warning persistence failed: %s — %s",
                type(persist_err).__name__, str(persist_err)[:200]
            )


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
            logger.info("[DataSources] Column enrichments: enrichment_id=%s → %d sütun döndü", enrichment_id, len(columns))
            return {"success": True, "columns": columns}
    except Exception as e:
        logger.error("[DataSources] Column enrichments hatası: enrichment_id=%s, hata=%s — %s", enrichment_id, type(e).__name__, str(e)[:200])
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


@router.get("/{source_id}/suggested-queries")
def get_suggested_queries(
    source_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    v3.14.0: Proaktif sorgu önerileri — öğrenilmiş tablolardan otomatik rapor önerileri.
    Kullanıcı 'veritabanında ara' sekmesini açtığında gösterilir.
    """
    try:
        # v3.20.0 Faz 1c: ds_learning_results RLS koruma altında — source_id ile scoped
        from app.core.db import get_db_context_scoped
        with get_db_context_scoped(source_id) as conn:
            cur = conn.cursor()

            # 1. Golden SQL'den en çok kullanılan sorgular
            cur.execute("""
                SELECT question_text, usage_count
                FROM golden_sql
                WHERE source_id = %s AND verified = TRUE
                ORDER BY usage_count DESC, created_at DESC
                LIMIT 5
            """, (source_id,))
            golden = [{"text": r[0] if not isinstance(r, dict) else r["question_text"],
                        "type": "golden"} for r in cur.fetchall()]

            # 2. İş süreci şablonlarından öneriler
            cur.execute("""
                SELECT process_name_tr, typical_queries
                FROM business_process_templates
                WHERE source_id = %s AND is_active = TRUE
                LIMIT 5
            """, (source_id,))
            process_suggestions = []
            for row in cur.fetchall():
                r = dict(row) if hasattr(row, 'keys') else {"process_name_tr": row[0], "typical_queries": row[1]}
                queries = r.get("typical_queries") or []
                if isinstance(queries, str):
                    import json
                    try:
                        queries = json.loads(queries)
                    except Exception:
                        queries = []
                for q in queries[:2]:
                    q_text = q.get("question", "") if isinstance(q, dict) else str(q)
                    if q_text:
                        process_suggestions.append({
                            "text": q_text,
                            "type": "process",
                            "process": r.get("process_name_tr", ""),
                        })

            # 3. Enriched tablolardan sample_questions
            cur.execute("""
                SELECT lr.metadata, lr.content_text
                FROM ds_learning_results lr
                WHERE lr.source_id = %s
                  AND lr.content_type = 'schema_record'
                  AND lr.is_valid = TRUE
                LIMIT 10
            """, (source_id,))
            table_suggestions = []
            for row in cur.fetchall():
                r = dict(row) if hasattr(row, 'keys') else {"metadata": row[0], "content_text": row[1]}
                meta = r.get("metadata") or {}
                if isinstance(meta, str):
                    import json
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                bname = meta.get("business_name", "")
                # content_text'ten sample_questions çıkar (varsa)
                content = r.get("content_text", "")
                if "Örnek Sorular:" in content:
                    sq_section = content.split("Örnek Sorular:")[-1]
                    for line in sq_section.strip().split("\n")[:2]:
                        line = line.strip().lstrip("- •")
                        if line and len(line) > 10:
                            table_suggestions.append({
                                "text": line,
                                "type": "table",
                                "table": bname,
                            })

            all_suggestions = golden + process_suggestions + table_suggestions
            return {"success": True, "suggestions": all_suggestions[:10]}

    except Exception as e:
        logger.error("[DataSources] Suggested queries hatası: %s", type(e).__name__)
        return {"success": True, "suggestions": []}
