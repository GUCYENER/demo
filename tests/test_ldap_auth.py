"""
VYRA L1 Support API - LDAP Auth Tests
==========================================
LDAP entegrasyonu için unit testler.

Test Kapsamı:
- Encryption: AES-256 Fernet encrypt/decrypt
- Login: LDAP branch mock, lokal admin-only branch
- Org Sync: Yeni org otomatik oluşturma
- LDAP Settings: CRUD API testleri
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# TEST: Encryption Module
# =============================================================================

class TestEncryption:
    """AES-256 Fernet şifreleme testleri."""

    @patch('app.core.encryption.get_db_conn')
    def test_encrypt_decrypt_roundtrip(self, mock_conn):
        """Şifreleme → çözme döngüsü orijinal metni döndürmeli."""
        from cryptography.fernet import Fernet
        from app.core.encryption import EncryptionManager

        key = Fernet.generate_key().decode()
        manager = EncryptionManager(key=key)

        plaintext = "MySecretPassword123!"
        encrypted = manager.encrypt(plaintext)

        assert encrypted != plaintext
        assert manager.decrypt(encrypted) == plaintext

    @patch('app.core.encryption.get_db_conn')
    def test_different_encrypted_values(self, mock_conn):
        """Aynı metin farklı encrypt çıktıları üretmeli (nonce/IV farklı)."""
        from cryptography.fernet import Fernet
        from app.core.encryption import EncryptionManager

        key = Fernet.generate_key().decode()
        manager = EncryptionManager(key=key)

        enc1 = manager.encrypt("test")
        enc2 = manager.encrypt("test")
        assert enc1 != enc2  # Farklı nonce

    @patch('app.core.encryption.get_db_conn')
    def test_empty_plaintext_raises(self, mock_conn):
        """Boş metin ValueError fırlatmalı."""
        from cryptography.fernet import Fernet
        from app.core.encryption import EncryptionManager

        key = Fernet.generate_key().decode()
        manager = EncryptionManager(key=key)

        with pytest.raises(ValueError):
            manager.encrypt("")


# =============================================================================
# TEST: Login Function - LDAP Branch
# =============================================================================

class TestLdapLogin:
    """LDAP login branch testleri - mock'lu."""

    @patch('app.api.routes.auth._find_or_create_ldap_user')
    @patch('app.api.routes.auth._sync_ldap_org')
    @patch('app.api.routes.auth._get_allowed_orgs')
    @patch('app.services.ldap_auth.ldap_authenticate')
    @patch('app.services.logging_service.log_system_event')
    def test_ldap_login_success(self, mock_log, mock_ldap_auth, mock_orgs, mock_sync, mock_find):
        """Başarılı LDAP login token dönmeli."""
        from app.api.routes.auth import _handle_ldap_login, UserLogin

        mock_ldap_auth.return_value = {
            'username': 'yil2345',
            'displayName': 'Yasin ILHAN',
            'mail': 'yasin@corp.com',
            'organization': 'ICT-AO-MD',
            'department': 'IT',
            'title': 'Engineer',
            'domain': 'TURKCELL',
            'display_domain': 'Turkcell AD'
        }
        mock_orgs.return_value = ['ICT-AO-MD', 'ICT-AO']
        mock_sync.return_value = None
        mock_find.return_value = {
            'id': 1, 'username': 'yil2345', 'role': 'user',
            'is_approved': True, 'is_admin': False
        }

        payload = UserLogin(username='yil2345', password='pass123', domain='TURKCELL')
        result = _handle_ldap_login(payload)

        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

    @patch('app.api.routes.auth._get_allowed_orgs')
    @patch('app.services.ldap_auth.ldap_authenticate')
    @patch('app.services.logging_service.log_system_event')
    def test_ldap_org_rejected(self, mock_log, mock_ldap_auth, mock_orgs):
        """İzinsiz org 403 fırlatmalı."""
        from app.api.routes.auth import _handle_ldap_login, UserLogin

        mock_ldap_auth.return_value = {
            'username': 'user1', 'organization': 'FINANCE',
            'domain': 'TURKCELL', 'display_domain': 'Test',
            'displayName': 'User', 'mail': '', 'department': '', 'title': ''
        }
        mock_orgs.return_value = ['ICT-AO-MD']

        payload = UserLogin(username='user1', password='pass', domain='TURKCELL')
        with pytest.raises(HTTPException) as exc_info:
            _handle_ldap_login(payload)
        assert exc_info.value.status_code == 403
        assert "Yetkisiz" in exc_info.value.detail

    @patch('app.services.ldap_auth.ldap_authenticate', return_value=None)
    @patch('app.services.logging_service.log_system_event')
    def test_ldap_auth_failed(self, mock_log, mock_ldap_auth):
        """LDAP doğrulaması başarısız olursa 403 fırlatmalı."""
        from app.api.routes.auth import _handle_ldap_login, UserLogin

        payload = UserLogin(username='bad', password='pass', domain='TURKCELL')
        with pytest.raises(HTTPException) as exc_info:
            _handle_ldap_login(payload)
        assert exc_info.value.status_code == 403


# =============================================================================
# TEST: Login Function - Local Branch
# =============================================================================

class TestLocalLogin:
    """Lokal login branch testleri."""

    @patch('app.api.routes.auth.get_db_context')
    def test_local_non_admin_rejected(self, mock_ctx):
        """Admin olmayan lokal kullanıcı 403 fırlatmalı."""
        from app.api.routes.auth import _handle_local_login, hash_password, UserLogin

        hashed_pw = hash_password("pass123")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": 2, "username": "regular_user", "password": hashed_pw,
            "role_name": "user", "is_admin": False, "is_approved": True
        }
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        payload = UserLogin(username="regular_user", password="pass123")
        with pytest.raises(HTTPException) as exc_info:
            _handle_local_login(payload)
        assert exc_info.value.status_code == 403
        assert "yöneticiler" in exc_info.value.detail

    @patch('app.api.routes.auth.get_db_context')
    def test_local_admin_success(self, mock_ctx):
        """Admin lokal login başarılı token dönmeli."""
        from app.api.routes.auth import _handle_local_login, hash_password, UserLogin

        hashed_pw = hash_password("admin1234")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": 1, "username": "admin", "password": hashed_pw,
            "role_name": "admin", "is_admin": True, "is_approved": True
        }
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        payload = UserLogin(username="admin", password="admin1234")
        result = _handle_local_login(payload)
        assert result.access_token
        assert result.refresh_token


# =============================================================================
# TEST: Org Sync
# =============================================================================

class TestOrgSync:
    """Organizasyon senkronizasyonu testleri."""

    @patch('app.api.routes.auth.get_db_context')
    def test_new_org_created(self, mock_ctx):
        """LDAP'tan gelen yeni org otomatik oluşturulmalı."""
        from app.api.routes.auth import _sync_ldap_org

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # İlk fetchone: org yok
        mock_cursor.fetchone.return_value = None
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        _sync_ldap_org("NEW-ORG")

        # INSERT çağrılmalı
        assert mock_cursor.execute.call_count >= 2
        insert_call = mock_cursor.execute.call_args_list[-1]
        assert "INSERT INTO organization_groups" in insert_call[0][0]
        assert "NEW-ORG" in insert_call[0][1]

    @patch('app.api.routes.auth.get_db_context')
    def test_existing_org_skipped(self, mock_ctx):
        """Var olan org tekrar oluşturulmamalı."""
        from app.api.routes.auth import _sync_ldap_org

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # fetchone: org zaten var
        mock_cursor.fetchone.return_value = {"id": 1}
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        _sync_ldap_org("EXISTING-ORG")

        # INSERT çağrılmamalı (sadece SELECT yapılmalı)
        assert mock_cursor.execute.call_count == 1


# =============================================================================
# TEST: LDAP Auth Service Helpers
# =============================================================================

class TestLdapAuthHelpers:
    """LDAP auth servisi helper fonksiyonları testleri."""

    def test_extract_domain_suffix(self):
        """DC componentlerinden domain suffix çıkarılmalı."""
        from app.services.ldap_auth import _extract_domain_suffix

        result = _extract_domain_suffix("DC=turkcell,DC=entp,DC=tgc")
        assert result == "turkcell.entp.tgc"

    def test_extract_domain_suffix_single(self):
        """Tek DC components."""
        from app.services.ldap_auth import _extract_domain_suffix

        result = _extract_domain_suffix("DC=example")
        assert result == "example"

    def test_extract_org_from_member_of(self):
        """memberOf'tan organizasyon CN çıkarılmalı."""
        from app.services.ldap_auth import _extract_org_from_member_of

        member_of = [
            "CN=ICT-AO-MD,OU=ORGANIZATION,DC=turkcell,DC=entp,DC=tgc",
            "CN=DomainUsers,OU=Groups,DC=turkcell,DC=entp,DC=tgc"
        ]
        result = _extract_org_from_member_of(member_of)
        assert result == "ICT-AO-MD"

    def test_parse_ldap_url(self):
        """LDAP URL'den host ve port çıkarılmalı."""
        from app.services.ldap_auth import _parse_ldap_url

        host, port = _parse_ldap_url("ldap://10.218.130.19:389")
        assert host == "10.218.130.19"
        assert port == 389

    def test_parse_ldaps_url_default_port(self):
        """LDAPS URL port olmadan 636 döndürmeli."""
        from app.services.ldap_auth import _parse_ldap_url

        host, port = _parse_ldap_url("ldaps://10.218.130.19")
        assert host == "10.218.130.19"
        assert port == 636


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
