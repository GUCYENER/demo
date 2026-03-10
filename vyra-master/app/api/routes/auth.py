"""
VYRA L1 Support API - Authentication Routes
============================================
Kullanıcı kaydı, giriş ve JWT token yönetimi.
v2.46.0: LDAP/Active Directory dual-auth desteği eklendi.
"""

import bcrypt
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.db import get_db_context
from app.core.rate_limiter import limiter, RATE_LIMITS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------
#  Security / JWT config
# ---------------------------------------------------------
security = HTTPBearer(auto_error=False)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    exp: int
    type: str
    role: str


class UserBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150)
    username: str = Field(..., min_length=3, max_length=100, pattern=r'^[a-zA-Z0-9._@-]+$')
    email: str = Field(..., max_length=254)
    phone: str = Field(..., max_length=20)


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=256)


class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)
    domain: Optional[str] = Field(None, max_length=100)  # LDAP domain adı (boşsa lokal auth)


class UserOut(BaseModel):
    id: int
    full_name: str
    username: str
    email: str
    phone: str
    role: str
    is_admin: bool


# ---------------------------------------------------------
#  Helpers
# ---------------------------------------------------------
def hash_password(password: str) -> str:
    """Saf bcrypt ile şifreleme"""
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Saf bcrypt ile doğrulama"""
    pwd_bytes = plain_password.encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(pwd_bytes, hash_bytes)


def create_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta],
    token_type: str,
) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire, "type": token_type})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def create_access_token(user: Dict[str, Any]) -> str:
    return create_token(
        data={"sub": str(user["id"]), "role": user["role"]},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(user: Dict[str, Any]) -> str:
    return create_token(
        data={"sub": str(user["id"]), "role": user["role"]},
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


def decode_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return TokenPayload(**payload)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş token",
        )


# ---------------------------------------------------------
#  Dependencies
# ---------------------------------------------------------
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """JWT token'dan kullanıcıyı doğrular ve döndürür."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kimlik doğrulama bilgisi yok (Authorization header eksik)",
        )

    token = credentials.credentials
    payload = decode_token(token)

    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz token türü",
        )

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.*, r.name as role
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE u.id = %s
        """, (payload.sub,))
        row = cur.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı bulunamadı",
        )

    # 🔒 Kullanıcı aktiflik kontrolü - Admin sonradan deaktif ederse engelle
    if not row.get("is_approved", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesabınız deaktif edilmiş. Lütfen yöneticinizle iletişime geçin.",
        )

    return dict(row)


def get_current_admin(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Admin yetkisi kontrolü."""
    if current_user["role"] != "admin" and not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için admin yetkisi gerekli",
        )
    return current_user


# ---------------------------------------------------------
#  Routes
# ---------------------------------------------------------
@router.post("/register", response_model=UserOut)
@limiter.limit(RATE_LIMITS["register"])
def register_user(request: Request, response: Response, payload: UserCreate):
    """Yeni kullanıcı kaydı oluşturur."""
    with get_db_context() as conn:
        cur = conn.cursor()

        # Username zaten kayıtlı mı?
        cur.execute("SELECT * FROM users WHERE username = %s", (payload.username,))
        if cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bu kullanıcı adı zaten kullanılıyor.",
            )

        # Email zaten kayıtlı mı?
        cur.execute("SELECT * FROM users WHERE email = %s", (payload.email,))
        if cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bu e-posta adresi zaten kayıtlı.",
            )

        hashed = hash_password(payload.password)

        # Default user role_id = 2
        cur.execute("SELECT id FROM roles WHERE name = 'user'")
        role_row = cur.fetchone()
        role_id = role_row['id'] if role_row else 2

        cur.execute(
            """
            INSERT INTO users (full_name, username, email, phone, password, role_id, is_admin)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, full_name, username, email, phone, role_id, is_admin
            """,
            (payload.full_name, payload.username, payload.email, payload.phone, hashed, role_id, False),
        )
        row = cur.fetchone()
        conn.commit()

    return UserOut(
        id=row["id"],
        full_name=row["full_name"],
        username=row["username"],
        email=row["email"],
        phone=row["phone"],
        role="user",
        is_admin=row["is_admin"],
    )


@router.post("/login", response_model=Token)
@limiter.limit(RATE_LIMITS["login"])
def login(request: Request, response: Response, payload: UserLogin):
    """
    Kullanıcı girişi ve JWT token döndürür.
    
    v2.46.0: Dual-auth desteği:
    - domain varsa → LDAP auth + org kontrolü + auto-create/approve
    - domain yoksa → Lokal auth (sadece admin)
    """
    if payload.domain:
        # ─── LDAP AUTH ───
        return _handle_ldap_login(payload)
    else:
        # ─── LOKAL AUTH (Sadece Admin) ───
        return _handle_local_login(payload)


def _handle_ldap_login(payload: UserLogin) -> Token:
    """LDAP domain üzerinden kullanıcı doğrulama ve otomatik hesap yönetimi."""
    from app.services.ldap_auth import ldap_authenticate
    from app.services.logging_service import log_system_event

    domain = payload.domain.upper().strip()

    # LDAP doğrulama
    try:
        ldap_result = ldap_authenticate(payload.username, payload.password, domain=domain)
    except Exception as e:
        logger.error(f"[Auth] LDAP auth exception: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LDAP sunucusuna bağlanılamadı. Lütfen daha sonra tekrar deneyin.",
        )

    if not ldap_result:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LDAP doğrulaması başarısız. Kullanıcı adı veya şifre hatalı.",
        )

    # Organizasyon erişim kontrolü
    user_org = ldap_result.get("organization", "")
    allowed_orgs = _get_allowed_orgs(domain)

    if allowed_orgs:
        if not user_org or user_org not in allowed_orgs:
            log_system_event(
                "WARNING",
                f"[Auth] LDAP org reddedildi: {payload.username} → org='{user_org}', izinli={allowed_orgs}",
                "auth"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yetkisiz erişim. '{user_org or 'Bilinmeyen'}' organizasyonu bu domain için erişime kapalı.",
            )

    # Org sync: organization_groups tablosunda yoksa oluştur
    _sync_ldap_org(user_org)

    # Kullanıcı bul veya oluştur + auto-approve
    try:
        user_dict = _find_or_create_ldap_user(ldap_result)
    except Exception as e:
        logger.error(f"[Auth] Kullanıcı oluşturma/güncelleme hatası: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Kullanıcı hesabı oluşturulurken bir hata oluştu.",
        )

    # Aktiflik kontrolü (admin tarafından pasife alınmış olabilir)
    if not user_dict.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesabınız pasife alınmıştır. Lütfen yöneticinize başvurun.",
        )

    # Token üret
    access_token = create_access_token(user_dict)
    refresh_token_str = create_refresh_token(user_dict)

    log_system_event(
        "INFO",
        f"[Auth] LDAP login başarılı: {payload.username} (domain={domain}, org={user_org})",
        "auth"
    )

    return Token(access_token=access_token, refresh_token=refresh_token_str)


def _handle_local_login(payload: UserLogin) -> Token:
    """Lokal veritabanı üzerinden kullanıcı doğrulama (sadece admin)."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.*, r.name as role_name 
            FROM users u 
            LEFT JOIN roles r ON u.role_id = r.id 
            WHERE u.username = %s
        """, (payload.username,))
        user = cur.fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya şifre hatalı",
        )

    # 🔒 LDAP kullanıcısı lokal login denerse veya password None/empty ise
    stored_password = user.get("password") or ""
    if not stored_password or not verify_password(payload.password, stored_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya şifre hatalı",
        )

    # Lokal login → sadece admin
    role_name = user.get("role_name", "user")
    is_admin = user.get("is_admin", False) or role_name == "admin"

    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lokal giriş sadece yöneticiler için aktiftir. Lütfen domain seçerek giriş yapın.",
        )

    # Onay kontrolü
    if not user.get("is_approved", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesabınız henüz onaylanmadı. Lütfen admin onayını bekleyin.",
        )

    # Aktiflik kontrolü
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hesabınız pasife alınmıştır. Lütfen yöneticinize başvurun.",
        )

    # last_login güncelle
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (user["id"],))
        conn.commit()

    user_dict = dict(user)
    user_dict["role"] = role_name

    access_token = create_access_token(user_dict)
    refresh_token_str = create_refresh_token(user_dict)

    return Token(access_token=access_token, refresh_token=refresh_token_str)


# ---------------------------------------------------------
#  LDAP Helper Functions
# ---------------------------------------------------------

def _get_allowed_orgs(domain: str) -> List[str]:
    """Belirtilen domain için izinli organizasyon listesini domain_org_permissions tablosundan çeker."""
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT org_code FROM domain_org_permissions WHERE domain = %s AND is_active = TRUE",
                (domain,)
            )
            rows = cur.fetchall()

        if rows:
            return [row["org_code"] for row in rows]
    except Exception as e:
        logger.warning(f"[Auth] allowed_orgs sorgusu başarısız (tablo yok?): {e}")
    return []


def _sync_ldap_org(org_code: str) -> None:
    """
    LDAP'tan gelen organizasyon kodu organization_groups tablosunda yoksa oluşturur.
    Varsa hiçbir şey yapmaz.
    """
    if not org_code:
        return

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM organization_groups WHERE org_code = %s", (org_code,))
        if cur.fetchone():
            return  # Zaten var

        cur.execute(
            """
            INSERT INTO organization_groups (org_code, org_name, description, is_active)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (org_code) DO NOTHING
            """,
            (org_code, org_code, f"LDAP'tan otomatik oluşturuldu ({datetime.utcnow().strftime('%Y-%m-%d %H:%M')})"),
        )
        conn.commit()
        logger.info(f"[Auth] Yeni org oluşturuldu (LDAP sync): {org_code}")


def _find_or_create_ldap_user(ldap_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    LDAP doğrulanmış kullanıcıyı veritabanında bulur veya oluşturur.
    
    - Varsa → profil güncelle + auto-approve
    - Yoksa → yeni oluştur (role=user, is_approved=True)
    """
    username = ldap_result.get("username", "")
    display_name = ldap_result.get("displayName", username)
    email = ldap_result.get("mail", "")
    organization = ldap_result.get("organization", "")
    department = ldap_result.get("department", "")
    title = ldap_result.get("title", "")
    domain = ldap_result.get("domain", "")

    user_dict = None

    with get_db_context() as conn:
        cur = conn.cursor()

        # Kullanıcı var mı? (username VEYA email ile ara)
        cur.execute("""
            SELECT u.*, r.name as role_name
            FROM users u
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE u.username = %s
        """, (username,))
        user = cur.fetchone()

        # Username ile bulunamadıysa email ile dene
        if not user and email:
            cur.execute("""
                SELECT u.*, r.name as role_name
                FROM users u
                LEFT JOIN roles r ON u.role_id = r.id
                WHERE u.email = %s
            """, (email,))
            user = cur.fetchone()
            if user:
                # Username'i güncelle (LDAP username ile eşitle)
                logger.info(f"[Auth] Kullanıcı email ile eşleştirildi: {user['username']} → {username}")
                cur.execute("UPDATE users SET username = %s WHERE id = %s", (username, user["id"]))
                conn.commit()

        if user:
            # ── MEVCUT KULLANICI → Güncelle ──
            cur.execute("""
                UPDATE users SET
                    full_name = %s,
                    email = COALESCE(NULLIF(%s, ''), email),
                    organization = %s,
                    department = %s,
                    title = %s,
                    domain = %s,
                    auth_type = 'ldap',
                    is_approved = TRUE,
                    last_login = NOW()
                WHERE id = %s
            """, (display_name, email, organization, department, title, domain, user["id"]))
            conn.commit()

            user_dict = dict(user)
            user_dict["full_name"] = display_name
            user_dict["role"] = user.get("role_name", "user")
            user_dict["is_approved"] = True

            logger.info(f"[Auth] LDAP kullanıcı güncellendi: {username}")

    if user_dict:
        # Org atamasını güncelle (ayrı context — commit sonrası cursor sorunu önlenir)
        _assign_user_org(user_dict["id"], organization)
        return user_dict

    # ── YENİ KULLANICI → Oluştur ──
    with get_db_context() as conn:
        cur = conn.cursor()

        # Default user role_id = 2
        cur.execute("SELECT id FROM roles WHERE name = 'user'")
        role_row = cur.fetchone()
        role_id = role_row["id"] if role_row else 2

        # Random password (LDAP kullanıcısı lokal şifre kullanmaz)
        random_password = hash_password(secrets.token_urlsafe(32))

        # domain boş string güvenliği
        email_domain = domain.lower() if domain else "ldap.local"

        cur.execute("""
            INSERT INTO users (
                full_name, username, email, phone, password,
                role_id, is_admin, is_approved,
                auth_type, domain, organization, department, title,
                last_login
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id, full_name, username, email, phone, role_id, is_admin, is_approved
        """, (
            display_name, username, email or f"{username}@{email_domain}",
            "", random_password,
            role_id, False, True,
            "ldap", domain, organization, department, title,
        ))
        new_user = cur.fetchone()
        conn.commit()

    user_dict = dict(new_user)
    user_dict["role"] = "user"

    # Org ataması (ayrı context)
    _assign_user_org(new_user["id"], organization)

    logger.info(f"[Auth] Yeni LDAP kullanıcı oluşturuldu: {username} (org={organization})")
    return user_dict


def _assign_user_org(user_id: int, org_code: str) -> None:
    """
    Kullanıcıyı belirtilen organizasyon grubuna atar.
    Sil-Yaz mantığı: Önce eski tüm org bağlantılarını kaldırır, sonra yeni org'u atar.
    Kendi DB context'ini açar — diğer transaction'lardan bağımsızdır.
    """
    if not org_code:
        return

    with get_db_context() as conn:
        cur = conn.cursor()

        # 1) Eski org bağlantılarını kaldır
        cur.execute("DELETE FROM user_organizations WHERE user_id = %s", (user_id,))

        # 2) Yeni org'u bul ve ata
        cur.execute("SELECT id FROM organization_groups WHERE org_code = %s", (org_code,))
        org = cur.fetchone()
        if org:
            cur.execute(
                "INSERT INTO user_organizations (user_id, org_id) VALUES (%s, %s)",
                (user_id, org["id"]),
            )

        conn.commit()


@router.post("/refresh", response_model=Token)
@limiter.limit(RATE_LIMITS["refresh"])
def refresh_token(request: Request, response: Response, refresh_token: str):
    """Refresh token ile yeni access token alır."""
    payload = decode_token(refresh_token)

    if payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz token türü",
        )

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (payload.sub,))
        user = cur.fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı bulunamadı",
        )

    new_access = create_access_token(dict(user))
    new_refresh = create_refresh_token(dict(user))
    return Token(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Mevcut kullanıcı bilgisini döndürür."""
    return UserOut(
        id=current_user["id"],
        full_name=current_user.get("full_name", ""),
        username=current_user.get("username", ""),
        email=current_user.get("email", ""),
        phone=current_user.get("phone", ""),
        role=current_user.get("role", "user"),
        is_admin=current_user.get("is_admin", False) or current_user.get("role") == "admin",
    )


@router.get("/ldap-domains")
def get_ldap_domains():
    """
    Aktif LDAP domain'lerini döndürür (login formu için).
    
    ⚠️ Auth gerektirmez — login formu doldurulmadan önce domain listesi gerekir.
    Öncelik: domain_org_permissions tablosu, fallback: ldap_settings tablosu.
    """
    domains = []

    # 1) domain_org_permissions tablosundan distinct domain’leri çek
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT dop.domain, 
                       COALESCE(ls.display_name, dop.domain) as display_name
                FROM domain_org_permissions dop
                LEFT JOIN ldap_settings ls ON ls.domain = dop.domain AND ls.enabled = TRUE AND ls.is_deleted = FALSE
                WHERE dop.is_active = TRUE
                ORDER BY display_name
            """)
            rows = cur.fetchall()
            domains = [
                {"domain": row["domain"], "display_name": row["display_name"]}
                for row in rows
            ]
    except Exception as e:
        logger.warning(f"[Auth] domain_org_permissions sorgusu başarısız: {e}")

    # 2) Fallback: ldap_settings tablosundan (domain_org_permissions boşsa)
    if not domains:
        try:
            with get_db_context() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT domain, display_name 
                    FROM ldap_settings 
                    WHERE enabled = TRUE AND is_deleted = FALSE
                    ORDER BY display_name
                """)
                rows = cur.fetchall()
                domains = [
                    {"domain": row["domain"], "display_name": row["display_name"]}
                    for row in rows
                ]
        except Exception as e:
            logger.warning(f"[Auth] LDAP domains sorgusu başarısız: {e}")

    return {"domains": domains}
