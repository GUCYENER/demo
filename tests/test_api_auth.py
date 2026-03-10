"""
VYRA L1 Support API - Auth Tests
==================================
Authentication helper fonksiyonları ve JWT yönetimi için unit testler.

Test Kapsamı:
- hash_password / verify_password (bcrypt)
- create_access_token / create_refresh_token (JWT oluşturma)
- decode_token (JWT decode & hata durumu)
- get_current_user (dependency, DB mock ile)
- login fonksiyonu (get_db_context mock ile)
- register fonksiyonu (get_db_context mock ile)
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# TEST: Password Hashing
# =============================================================================

class TestPasswordHashing:
    """bcrypt şifreleme/doğrulama testleri."""
    
    def test_hash_returns_string(self):
        """Hash sonucu string olmalı."""
        from app.api.routes.auth import hash_password
        hashed = hash_password("test123")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2b$")
    
    def test_verify_correct_password(self):
        """Doğru şifre True dönmeli."""
        from app.api.routes.auth import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True
    
    def test_verify_wrong_password(self):
        """Yanlış şifre False dönmeli."""
        from app.api.routes.auth import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert verify_password("wrongpassword", hashed) is False
    
    def test_different_hashes_for_same_password(self):
        """Aynı şifre farklı salt ile farklı hash üretmeli."""
        from app.api.routes.auth import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Salt farklı olduğu için


# =============================================================================
# TEST: JWT Token Creation
# =============================================================================

class TestJWTTokenCreation:
    """JWT token oluşturma testleri."""
    
    def test_access_token_created(self):
        """Access token oluşturulmalı."""
        from app.api.routes.auth import create_access_token
        user = {"id": 1, "role": "user"}
        token = create_access_token(user)
        assert isinstance(token, str)
        assert len(token) > 10
    
    def test_refresh_token_created(self):
        """Refresh token oluşturulmalı."""
        from app.api.routes.auth import create_refresh_token
        user = {"id": 1, "role": "user"}
        token = create_refresh_token(user)
        assert isinstance(token, str)
        assert len(token) > 10
    
    def test_access_and_refresh_different(self):
        """Access ve refresh tokenlar farklı olmalı."""
        from app.api.routes.auth import create_access_token, create_refresh_token
        user = {"id": 1, "role": "user"}
        access = create_access_token(user)
        refresh = create_refresh_token(user)
        assert access != refresh


# =============================================================================
# TEST: JWT Token Decode
# =============================================================================

class TestJWTTokenDecode:
    """JWT decode testleri."""
    
    def test_decode_valid_access_token(self):
        """Geçerli access token decode edilmeli."""
        from app.api.routes.auth import create_access_token, decode_token
        user = {"id": 1, "role": "admin"}
        token = create_access_token(user)
        payload = decode_token(token)
        assert payload.sub == "1"
        assert payload.type == "access"
        assert payload.role == "admin"
    
    def test_decode_valid_refresh_token(self):
        """Geçerli refresh token decode edilmeli."""
        from app.api.routes.auth import create_refresh_token, decode_token
        user = {"id": 42, "role": "user"}
        token = create_refresh_token(user)
        payload = decode_token(token)
        assert payload.sub == "42"
        assert payload.type == "refresh"
    
    def test_decode_invalid_token_raises(self):
        """Geçersiz token HTTPException fırlatmalı."""
        from app.api.routes.auth import decode_token
        with pytest.raises(HTTPException) as exc_info:
            decode_token("invalid.token.here")
        assert exc_info.value.status_code == 401


# =============================================================================
# TEST: Login Function (Unit)
# =============================================================================

class TestLoginFunction:
    """Login route fonksiyonu unit testleri - DB mock'lu."""
    
    @patch('app.api.routes.auth.get_db_context')
    def test_login_success(self, mock_ctx):
        """Başarılı login token dönmeli."""
        from app.api.routes.auth import login, hash_password, UserLogin
        
        hashed_pw = hash_password("correctpass")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": 1, "username": "testuser", "password": hashed_pw,
            "email": "t@t.com", "full_name": "Test Admin", "phone": "555",
            "role_id": 1, "role_name": "admin", "is_admin": True,
            "is_approved": True
        }
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_request = MagicMock()
        mock_response = MagicMock()
        
        payload = UserLogin(username="testuser", password="correctpass")
        # __wrapped__ ile rate limiter decorator'ünü bypass ediyoruz
        result = login.__wrapped__(mock_request, mock_response, payload)
        
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"
    
    @patch('app.api.routes.auth.get_db_context')
    def test_login_user_not_found(self, mock_ctx):
        """Kullanıcı bulunamazsa 401 fırlatmalı."""
        from app.api.routes.auth import login, UserLogin
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_request = MagicMock()
        mock_response = MagicMock()
        
        with pytest.raises(HTTPException) as exc_info:
            login.__wrapped__(mock_request, mock_response, UserLogin(username="no", password="x"))
        assert exc_info.value.status_code == 401
    
    @patch('app.api.routes.auth.get_db_context')
    def test_login_wrong_password(self, mock_ctx):
        """Yanlış şifre 401 fırlatmalı."""
        from app.api.routes.auth import login, hash_password, UserLogin
        
        hashed_pw = hash_password("correctpass")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": 1, "username": "testuser", "password": hashed_pw,
            "role_name": "user", "is_approved": True
        }
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_request = MagicMock()
        mock_response = MagicMock()
        
        with pytest.raises(HTTPException) as exc_info:
            login.__wrapped__(mock_request, mock_response, UserLogin(username="testuser", password="wrong"))
        assert exc_info.value.status_code == 401
    
    @patch('app.api.routes.auth.get_db_context')
    def test_login_not_approved(self, mock_ctx):
        """Onaylanmamış kullanıcı 403 fırlatmalı."""
        from app.api.routes.auth import login, hash_password, UserLogin
        
        hashed_pw = hash_password("correctpass")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": 1, "username": "testuser", "password": hashed_pw,
            "role_name": "user", "is_approved": False
        }
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_request = MagicMock()
        mock_response = MagicMock()
        
        with pytest.raises(HTTPException) as exc_info:
            login.__wrapped__(mock_request, mock_response, UserLogin(username="testuser", password="correctpass"))
        assert exc_info.value.status_code == 403


# =============================================================================
# TEST: Register Function (Unit)
# =============================================================================

class TestRegisterFunction:
    """Register route fonksiyonu unit testleri."""
    
    @patch('app.api.routes.auth.get_db_context')
    def test_register_duplicate_username(self, mock_ctx):
        """Var olan username 400 fırlatmalı."""
        from app.api.routes.auth import register_user, UserCreate
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # İlk fetchone = username zaten var
        mock_cursor.fetchone.return_value = {"id": 1}
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_response = MagicMock()
        
        payload = UserCreate(
            full_name="Test User", username="existing",
            email="x@x.com", phone="555", password="pass123"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            register_user.__wrapped__(mock_request, mock_response, payload)
        assert exc_info.value.status_code == 400


# =============================================================================
# TEST: read_current_user Endpoint (Unit)
# =============================================================================

class TestMeEndpoint:
    """GET /me endpoint unit testi."""
    
    def test_returns_user_out(self):
        """Doğru kullanıcı bilgisi dönmeli."""
        from app.api.routes.auth import read_current_user
        
        user_dict = {
            "id": 1, "full_name": "Test User",
            "username": "testuser", "email": "t@t.com",
            "phone": "555", "role": "user", "is_admin": False
        }
        
        result = read_current_user(user_dict)
        assert result.id == 1
        assert result.username == "testuser"
        assert result.is_admin is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
