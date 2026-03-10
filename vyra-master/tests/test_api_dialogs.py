"""
VYRA L1 Support API - Dialog API Tests
========================================
Dialog route fonksiyonları için unit testler.
Service katmanı test_dialog_service.py'de test ediliyor,
burada endpoint/route seviyesi testler yapılır.

Test Kapsamı:
- Dialog response model doğrulamaları
- Request model validation
- get_current_user dependency (token → user dict)
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# TEST: Request/Response Model Validation
# =============================================================================

class TestDialogModels:
    """Dialog API model testleri."""
    
    def test_dialog_create_request_optional_title(self):
        """DialogCreateRequest - title opsiyonel olmalı."""
        from app.api.routes.dialog import DialogCreateRequest
        req = DialogCreateRequest()
        assert req.title is None
    
    def test_dialog_create_request_with_title(self):
        """DialogCreateRequest - title ile oluşturulabilmeli."""
        from app.api.routes.dialog import DialogCreateRequest
        req = DialogCreateRequest(title="Test Dialog")
        assert req.title == "Test Dialog"
    
    def test_message_request_min_length(self):
        """MessageRequest - boş content kabul edilmemeli."""
        from app.api.routes.dialog import MessageRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            MessageRequest(content="")
    
    def test_message_request_valid(self):
        """MessageRequest - geçerli content."""
        from app.api.routes.dialog import MessageRequest
        req = MessageRequest(content="VPN bağlantı sorunu")
        assert req.content == "VPN bağlantı sorunu"
        assert req.images is None
    
    def test_quick_reply_request(self):
        """QuickReplyRequest - action zorunlu."""
        from app.api.routes.dialog import QuickReplyRequest
        req = QuickReplyRequest(action="yes")
        assert req.action == "yes"
        assert req.selection_id is None
    
    def test_feedback_request(self):
        """FeedbackRequest - message_id ve type zorunlu."""
        from app.api.routes.dialog import FeedbackRequest
        req = FeedbackRequest(message_id=1, feedback_type="helpful")
        assert req.message_id == 1
        assert req.feedback_type == "helpful"
    
    def test_dialog_response_model(self):
        """DialogResponse model alanları."""
        from app.api.routes.dialog import DialogResponse
        resp = DialogResponse(
            id=1, user_id=1, title="Test",
            status="active", created_at="2026-02-07",
            updated_at="2026-02-07"
        )
        assert resp.id == 1
        assert resp.message_count == 0  # default


# =============================================================================
# TEST: Auth Dependency for Dialog Routes
# =============================================================================

class TestDialogAuthDependency:
    """Dialog route'larındaki authentication kontrolü."""
    
    def test_get_current_user_no_credentials(self):
        """Credentials yoksa 401 fırlatmalı."""
        from app.api.routes.auth import get_current_user
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=None)
        assert exc_info.value.status_code == 401
    
    @patch('app.api.routes.auth.get_db_context')
    def test_get_current_user_valid_token(self, mock_ctx):
        """Geçerli token ile kullanıcı bilgisi dönmeli."""
        from app.api.routes.auth import get_current_user, create_access_token
        from fastapi.security import HTTPAuthorizationCredentials
        
        # Valid token oluştur
        user = {"id": 1, "role": "user"}
        token = create_access_token(user)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        
        # DB mock
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {
            "id": 1, "username": "testuser", "email": "t@t.com",
            "full_name": "Test", "phone": "555",
            "role": "user", "is_admin": False, "is_approved": True
        }
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
        
        result = get_current_user(credentials=creds)
        assert result["id"] == 1
        assert result["username"] == "testuser"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
