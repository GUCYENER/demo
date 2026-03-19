"""
VYRA L1 Support API - LDAP Authentication Service
===================================================
Active Directory / LDAP üzerinden kullanıcı doğrulama servisi.

3 Adımlı Auth:
  1. Service Account Bind → Decrypt edilmiş bind password ile bağlan
  2. User Search → sAMAccountName ile kullanıcıyı bul
  3. User Bind → Kullanıcının kendi şifresiyle doğrulama

Direct Bind Fallback:
  Service Account Bind başarısız olursa → kullanıcının kendi bilgileriyle
  doğrudan bind dener (UPN ve NTLM formatları).

Bağlantı Testi:
  3 aşamalı: TCP → LDAP Server Init → Service Bind

Version: 1.0.0 (v2.46.0)
"""

from __future__ import annotations

import logging
import socket
import ssl
from typing import Any, Dict, List, Optional

from ldap3 import ALL, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPSocketOpenError,
)

from app.core.encryption import decrypt_password
from app.services.logging_service import log_error, log_system_event

logger = logging.getLogger(__name__)


# =============================================================================
#  Ana Fonksiyon
# =============================================================================

def ldap_authenticate(
    username: str,
    password: str,
    domain: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    LDAP üzerinden kullanıcı doğrulaması yapar.

    Args:
        username: sAMAccountName (örn: yil2345)
        password: Kullanıcı şifresi
        domain: Hedef domain adı (örn: TURKCELL). None ise tüm aktif domainler denenir.

    Returns:
        Başarılı → kullanıcı bilgileri dict
        Başarısız → None
    """
    from app.core.db import get_db_conn

    conn_db = get_db_conn()
    try:
        cur = conn_db.cursor()

        query = """
            SELECT * FROM ldap_settings 
            WHERE enabled = TRUE AND is_deleted = FALSE
        """
        params: list = []
        if domain:
            query += " AND domain = %s"
            params.append(domain.upper().strip())

        cur.execute(query, tuple(params))
        settings = cur.fetchall()
    finally:
        conn_db.close()

    if not settings:
        log_system_event("WARNING", f"[LDAP] Aktif LDAP ayarı bulunamadı (domain={domain})", "ldap")
        return None

    for setting in settings:
        log_system_event("INFO", f"[LDAP] Deneniyor: {setting['domain']} ({setting['url']})", "ldap")

        # 1) 3 adımlı auth dene
        result = _try_ldap_auth(setting, username, password)
        if result:
            result["domain"] = setting["domain"]
            result["display_domain"] = setting["display_name"]
            return result

        # 2) Fallback: Direct bind
        log_system_event("WARNING", f"[LDAP] 3 adımlı auth başarısız, direct bind deneniyor: {setting['domain']}", "ldap")
        result = _try_direct_bind(setting, username, password)
        if result:
            result["domain"] = setting["domain"]
            result["display_domain"] = setting["display_name"]
            return result

    log_system_event("WARNING", f"[LDAP] Tüm LDAP denemeler başarısız: {username}", "ldap")
    return None


# =============================================================================
#  3 Adımlı Auth
# =============================================================================

def _try_ldap_auth(
    setting: Dict[str, Any],
    username: str,
    password: str,
) -> Optional[Dict[str, Any]]:
    """
    3 adımlı LDAP auth:
    STEP 1: Service Account Bind
    STEP 2: User Search
    STEP 3: User Bind (şifre doğrulama)
    """
    try:
        # ── STEP 1: Service Account Bind ──
        bind_password = decrypt_password(setting["bind_password"])
        server = _create_server(setting)

        # UPN formatı dene
        domain_suffix = _extract_domain_suffix(setting["search_base"])
        bind_dn = setting["bind_dn"]

        # CN'den username çıkar (CN=AOSMART,OU=... → AOSMART)
        service_username = bind_dn.split(",")[0].replace("CN=", "").replace("cn=", "")
        upn = f"{service_username}@{domain_suffix}"

        service_conn = None
        for bind_user in [upn, bind_dn]:
            try:
                service_conn = Connection(
                    server, user=bind_user, password=bind_password, auto_bind=True
                )
                log_system_event("DEBUG", f"[LDAP] Service bind başarılı: {bind_user}", "ldap")
                break
            except LDAPBindError:
                continue

        if not service_conn or not service_conn.bound:
            log_system_event("WARNING", "[LDAP] Service account bind başarısız", "ldap")
            return None

        # ── STEP 2: User Search ──
        search_filter = setting["search_filter"].replace("{{username}}", username)
        service_conn.search(
            search_base=setting["search_base"],
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=[
                "sAMAccountName", "userPrincipalName", "displayName",
                "mail", "cn", "memberOf", "department", "title", "company",
            ],
        )

        if not service_conn.entries:
            log_system_event("WARNING", f"[LDAP] Kullanıcı bulunamadı: {username}", "ldap")
            service_conn.unbind()
            return None

        user_entry = service_conn.entries[0]
        user_dn = str(user_entry.entry_dn)
        log_system_event("DEBUG", f"[LDAP] Kullanıcı bulundu: {user_dn}", "ldap")

        # ── STEP 3: User Bind ──
        user_upn = f"{username}@{domain_suffix}"
        user_conn = None

        for bind_id in [user_upn, user_dn]:
            try:
                user_conn = Connection(server, user=bind_id, password=password, auto_bind=True)
                log_system_event("INFO", f"[LDAP] User bind başarılı: {bind_id}", "ldap")
                break
            except LDAPBindError:
                continue

        if not user_conn or not user_conn.bound:
            log_system_event("WARNING", f"[LDAP] Kullanıcı şifre doğrulama başarısız: {username}", "ldap")
            service_conn.unbind()
            return None

        # Bilgileri çıkar
        result = _extract_user_info(user_entry)

        # Bağlantıları kapat
        user_conn.unbind()
        service_conn.unbind()

        log_system_event("INFO", f"[LDAP] Auth başarılı (3-step): {username} → {result.get('organization', 'N/A')}", "ldap")
        return result

    except LDAPSocketOpenError as e:
        log_error(f"[LDAP] Bağlantı hatası: {e}", "ldap")
        return None
    except Exception as e:
        log_error(f"[LDAP] 3-step auth hatası: {e}", "ldap")
        return None


# =============================================================================
#  Direct Bind Fallback
# =============================================================================

def _try_direct_bind(
    setting: Dict[str, Any],
    username: str,
    password: str,
) -> Optional[Dict[str, Any]]:
    """
    Service Account olmadan kullanıcının kendi bilgileriyle doğrudan bind.
    UPN ve NTLM formatlarını sırayla dener.
    """
    try:
        server = _create_server(setting)
        domain_suffix = _extract_domain_suffix(setting["search_base"])

        bind_formats = [
            (f"{username}@{domain_suffix}", "UPN"),
            (f"{setting['domain']}\\{username}", "NTLM"),
        ]

        for bind_user, fmt in bind_formats:
            try:
                user_conn = Connection(server, user=bind_user, password=password, auto_bind=True)

                if user_conn.bound:
                    log_system_event("INFO", f"[LDAP] Direct bind başarılı ({fmt}): {bind_user}", "ldap")

                    # Search ile kullanıcı bilgilerini almayı dene
                    result = _search_user_info(user_conn, setting, username)
                    user_conn.unbind()

                    if result:
                        return result

                    # Search başarısız olsa da login kabul et (minimal bilgilerle)
                    return {
                        "username": username,
                        "displayName": username,
                        "mail": "",
                        "organization": "",
                        "department": "",
                        "title": "",
                    }

            except LDAPBindError:
                log_system_event("DEBUG", f"[LDAP] Direct bind başarısız ({fmt}): {bind_user}", "ldap")
                continue

        return None

    except Exception as e:
        log_error(f"[LDAP] Direct bind hatası: {e}", "ldap")
        return None


def _search_user_info(
    conn: Connection,
    setting: Dict[str, Any],
    username: str,
) -> Optional[Dict[str, Any]]:
    """Bind edilmiş connection ile kullanıcı bilgilerini arar."""
    try:
        search_filter = setting["search_filter"].replace("{{username}}", username)
        conn.search(
            search_base=setting["search_base"],
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=[
                "sAMAccountName", "userPrincipalName", "displayName",
                "mail", "cn", "memberOf", "department", "title", "company",
            ],
        )

        if conn.entries:
            return _extract_user_info(conn.entries[0])

        return None
    except Exception as e:
        log_system_event("DEBUG", f"[LDAP] Search after direct bind başarısız: {e}", "ldap")
        return None


# =============================================================================
#  Bağlantı Testi
# =============================================================================

def test_ldap_connection(setting_id: int) -> Dict[str, Any]:
    """
    3 aşamalı LDAP bağlantı testi:
    1. TCP Socket → port erişilebilirliği
    2. LDAP Server Init → TLS/SSL başlatma
    3. Service Bind → authenticate
    """
    from app.core.db import get_db_conn

    conn_db = get_db_conn()
    try:
        cur = conn_db.cursor()
        cur.execute("SELECT * FROM ldap_settings WHERE id = %s", (setting_id,))
        setting = cur.fetchone()
    finally:
        conn_db.close()

    if not setting:
        return {"success": False, "message": "LDAP ayarı bulunamadı", "steps": []}

    steps: List[Dict[str, Any]] = []

    # ── STEP 1: TCP ──
    try:
        url = setting["url"]
        host, port = _parse_ldap_url(url)
        timeout = setting.get("timeout", 10)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            steps.append({
                "step": 1, "name": "TCP Bağlantı", "status": "success",
                "message": f"{host}:{port} erişilebilir"
            })
        except (socket.timeout, TimeoutError):
            steps.append({
                "step": 1, "name": "TCP Bağlantı", "status": "error",
                "message": f"{host}:{port} zaman aşımına uğradı ({timeout}s)"
            })
            return {"success": False, "message": f"TCP bağlantı zaman aşımı: {host}:{port}", "steps": steps}
        except OSError as sock_err:
            steps.append({
                "step": 1, "name": "TCP Bağlantı", "status": "error",
                "message": f"{host}:{port} erişilemiyor ({sock_err})"
            })
            return {"success": False, "message": f"TCP bağlantı başarısız: {host}:{port}", "steps": steps}
        finally:
            sock.close()
    except Exception as e:
        steps.append({"step": 1, "name": "TCP Bağlantı", "status": "error", "message": str(e)})
        return {"success": False, "message": f"TCP hatası: {e}", "steps": steps}

    # ── STEP 2: LDAP Server Init ──
    try:
        server = _create_server(setting)
        steps.append({"step": 2, "name": "LDAP Server", "status": "success", "message": f"LDAP Server başlatıldı (SSL: {setting['use_ssl']})"})
    except Exception as e:
        steps.append({"step": 2, "name": "LDAP Server", "status": "error", "message": str(e)})
        return {"success": False, "message": f"LDAP Server hatası: {e}", "steps": steps}

    # ── STEP 3: Service Bind ──
    try:
        bind_password = decrypt_password(setting["bind_password"])
        domain_suffix = _extract_domain_suffix(setting["search_base"])
        bind_dn = setting["bind_dn"]
        service_username = bind_dn.split(",")[0].replace("CN=", "").replace("cn=", "")
        upn = f"{service_username}@{domain_suffix}"

        bound = False
        bind_msg = ""

        for bind_user in [upn, bind_dn]:
            try:
                test_conn = Connection(server, user=bind_user, password=bind_password, auto_bind=True)
                if test_conn.bound:
                    bound = True
                    bind_msg = f"Service bind başarılı: {bind_user}"
                    test_conn.unbind()
                    break
            except LDAPBindError:
                continue

        if bound:
            steps.append({"step": 3, "name": "Service Bind", "status": "success", "message": bind_msg})
        else:
            steps.append({"step": 3, "name": "Service Bind", "status": "error", "message": "Service account bind başarısız (UPN ve DN denendi)"})
            return {"success": False, "message": "Service bind başarısız", "steps": steps}

    except ValueError as e:
        steps.append({"step": 3, "name": "Service Bind", "status": "error", "message": f"Şifre çözme hatası: {e}"})
        return {"success": False, "message": f"Encryption hatası: {e}", "steps": steps}
    except Exception as e:
        steps.append({"step": 3, "name": "Service Bind", "status": "error", "message": str(e)})
        return {"success": False, "message": f"Bind hatası: {e}", "steps": steps}

    return {
        "success": True,
        "message": f"LDAP bağlantısı başarılı! ({host}:{port})",
        "steps": steps,
    }


# =============================================================================
#  Helper Functions
# =============================================================================

def _create_server(setting: Dict[str, Any]) -> Server:
    """LDAP Server nesnesi oluşturur."""
    tls_config = None
    if setting["use_ssl"]:
        tls_config = Tls(validate=ssl.CERT_NONE)  # Self-signed cert desteği

    return Server(
        setting["url"],
        get_info=ALL,
        use_ssl=setting["use_ssl"],
        tls=tls_config,
        connect_timeout=setting["timeout"],
    )


def _extract_domain_suffix(search_base: str) -> str:
    """
    Search base'den domain suffix çıkarır.
    DC=turkcell,DC=entp,DC=tgc → turkcell.entp.tgc
    """
    parts = []
    for component in search_base.split(","):
        component = component.strip()
        if component.upper().startswith("DC="):
            parts.append(component[3:])
    return ".".join(parts) if parts else ""


def _extract_org_from_member_of(member_of_list) -> str:
    """
    memberOf listesinden organizasyon bilgisi çıkarır.
    OU=ORGANIZATION altındaki CN değerini alır.
    Örn: CN=ICT-AO-MD,OU=ORGANIZATION,DC=... → ICT-AO-MD
    """
    if not member_of_list:
        return ""

    for dn in member_of_list:
        dn_str = str(dn)
        if "OU=ORGANIZATION" in dn_str.upper():
            # CN= değerini çıkar
            for part in dn_str.split(","):
                part = part.strip()
                if part.upper().startswith("CN="):
                    return part[3:]

    # Fallback: İlk memberOf'un CN'ini al
    if member_of_list:
        first_dn = str(member_of_list[0])
        for part in first_dn.split(","):
            part = part.strip()
            if part.upper().startswith("CN="):
                return part[3:]

    return ""


def _extract_user_info(entry) -> Dict[str, Any]:
    """LDAP entry'den kullanıcı bilgilerini çıkarır."""

    def _safe_str(attr) -> str:
        """LDAP attribute'u güvenli string'e çevirir."""
        try:
            val = attr.value if hasattr(attr, "value") else attr
            if isinstance(val, list):
                return str(val[0]) if val else ""
            return str(val) if val else ""
        except Exception:
            return ""

    # memberOf listesini al
    member_of = []
    try:
        if hasattr(entry, "memberOf"):
            val = entry.memberOf.value
            member_of = val if isinstance(val, list) else [val] if val else []
    except Exception:
        pass

    return {
        "username": _safe_str(entry.sAMAccountName) if hasattr(entry, "sAMAccountName") else "",
        "displayName": _safe_str(entry.displayName) if hasattr(entry, "displayName") else "",
        "mail": _safe_str(entry.mail) if hasattr(entry, "mail") else "",
        "organization": _extract_org_from_member_of(member_of),
        "department": _safe_str(entry.department) if hasattr(entry, "department") else "",
        "title": _safe_str(entry.title) if hasattr(entry, "title") else "",
    }


def _parse_ldap_url(url: str) -> tuple:
    """LDAP URL'den host ve port çıkarır."""
    # ldap://10.218.130.19:389 → (10.218.130.19, 389)
    clean = url.replace("ldaps://", "").replace("ldap://", "")
    if ":" in clean:
        host, port_str = clean.rsplit(":", 1)
        return host, int(port_str)

    # Port belirtilmemişse
    if url.startswith("ldaps://"):
        return clean, 636
    return clean, 389
