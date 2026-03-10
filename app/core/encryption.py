"""
VYRA L1 Support API - Encryption Service
==========================================
AES-256 Fernet şifreleme servisi.
LDAP bind password gibi hassas verilerin veritabanında güvenli saklanması için kullanılır.

Encryption key, system_settings tablosunda 'ENCRYPTION_KEY' olarak saklanır.
Key yoksa otomatik oluşturulur.

Version: 1.0.0 (v2.46.0 - LDAP Integration)
"""

from __future__ import annotations

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.db import get_db_conn

logger = logging.getLogger(__name__)

# Global lazy singleton
_encryption_manager: Optional["EncryptionManager"] = None


class EncryptionManager:
    """AES-256 Fernet şifreleme yöneticisi."""

    def __init__(self, key: Optional[str] = None):
        if key:
            self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
        else:
            db_key = self._load_key_from_db()
            self.fernet = Fernet(db_key.encode() if isinstance(db_key, str) else db_key)

    # ---------------------------------------------------------
    #  Key Management
    # ---------------------------------------------------------

    @staticmethod
    def _load_key_from_db() -> str:
        """
        system_settings tablosundan ENCRYPTION_KEY'i okur.
        Yoksa yeni bir key oluşturur ve kaydeder.
        """
        conn = get_db_conn()
        try:
            cur = conn.cursor()

            cur.execute(
                "SELECT setting_value FROM system_settings WHERE setting_key = %s",
                ("ENCRYPTION_KEY",),
            )
            row = cur.fetchone()

            if row:
                logger.debug("[Encryption] Key loaded from DB")
                return row["setting_value"]

            # Key yok → oluştur ve kaydet
            new_key = Fernet.generate_key().decode()
            cur.execute(
                """
                INSERT INTO system_settings (setting_key, setting_value, description)
                VALUES (%s, %s, %s)
                ON CONFLICT (setting_key) DO NOTHING
                """,
                ("ENCRYPTION_KEY", new_key, "AES-256 Fernet encryption key (LDAP bind passwords)"),
            )
            conn.commit()
            logger.info("[Encryption] New encryption key generated and saved to DB")
            return new_key

        finally:
            conn.close()

    # ---------------------------------------------------------
    #  Encrypt / Decrypt
    # ---------------------------------------------------------

    def encrypt(self, plaintext: str) -> str:
        """Düz metni şifreler ve base64 encoded string döndürür."""
        if not plaintext:
            raise ValueError("Şifrelenecek metin boş olamaz")
        return self.fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, encrypted_text: str) -> str:
        """Şifreli metni çözer ve düz metin döndürür."""
        if not encrypted_text:
            raise ValueError("Çözülecek metin boş olamaz")
        try:
            return self.fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.error("[Encryption] Decryption failed — invalid token or key mismatch")
            raise ValueError("Şifre çözme başarısız. Key uyumsuzluğu olabilir.")


# =============================================================================
#  Module-Level Helper Functions (Lazy Singleton)
# =============================================================================

def _get_manager() -> EncryptionManager:
    """Lazy singleton EncryptionManager döndürür."""
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


def encrypt_password(password: str) -> str:
    """Şifreyi AES-256 Fernet ile şifreler."""
    return _get_manager().encrypt(password)


def decrypt_password(encrypted_password: str) -> str:
    """AES-256 ile şifrelenmiş şifreyi çözer."""
    return _get_manager().decrypt(encrypted_password)


def generate_new_key() -> str:
    """Yeni Fernet key oluşturur (yardımcı fonksiyon)."""
    return Fernet.generate_key().decode()
