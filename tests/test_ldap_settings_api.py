"""
LDAP Settings API — hata-dayanıklılık testleri (v3.59.0)
=========================================================
Kapsam:
  - Boş/whitespace bind_password → encrypt'e GİTMEDEN net 400 (yakalanmamış 500 değil).
  - create endpoint'i DB hatasında log_exception ile loglayıp 500'e çevirir (HTTPException re-raise korunur).

Not: Boş-şifre guard'ı get_db_context()'ten ÖNCE çalışır → DB bağlantısı gerekmez.
"""
from contextlib import contextmanager
from unittest.mock import patch

import psycopg2
import pytest
from fastapi import HTTPException

from app.api.routes.ldap_settings import LdapSettingCreate, create_ldap_setting


_ADMIN = {"id": 1, "username": "admin"}


def _revived_row():
    return {
        "id": 5, "domain": "EXAMPLE.COM", "display_name": "Example",
        "url": "ldap://10.0.0.1:389", "bind_dn": "CN=svc", "bind_password": "ENC",
        "search_base": "DC=example,DC=com", "search_filter": "(x={{u}})",
        "allowed_orgs": ["ICT-AO-MD"], "enabled": True, "use_ssl": False, "timeout": 10,
        "company_id": 7,
        "created_at": "2026-06-02", "updated_at": "2026-06-02", "is_deleted": False,
    }


class _FakeCursor:
    """active-check→None, soft-deleted-check→{id}, UPDATE→revived, INSERT→opsiyonel raise."""

    def __init__(self, *, dead, insert_raises=None):
        self._dead = dead
        self._insert_raises = insert_raises
        self._last = ""

    def execute(self, q, params=None):
        self._last = q
        if "INSERT INTO ldap_settings" in q and self._insert_raises is not None:
            raise self._insert_raises

    def fetchone(self):
        q = self._last
        if "UPDATE ldap_settings" in q:
            return _revived_row()
        if "is_deleted = TRUE" in q:
            return {"id": 5} if self._dead else None
        if "is_deleted = FALSE" in q:
            return None  # aktif duplicate yok
        return None

    def close(self):
        pass


@contextmanager
def _fake_db(cur):
    class _Conn:
        def cursor(self_inner):
            return cur

        def commit(self_inner):
            pass

        def close(self_inner):
            pass

    yield _Conn()


def _payload(bind_password: str) -> LdapSettingCreate:
    return LdapSettingCreate(
        domain="example.com",
        display_name="Example",
        url="ldap://10.0.0.1:389",
        bind_dn="CN=svc,DC=example,DC=com",
        bind_password=bind_password,
        search_base="DC=example,DC=com",
    )


@pytest.mark.parametrize("pwd", ["", "   ", "\t"])
def test_empty_bind_password_returns_400_not_500(pwd):
    """Boş/whitespace bind_password → 400, encrypt() ValueError 500'üne düşmez."""
    with pytest.raises(HTTPException) as exc_info:
        create_ldap_setting(_payload(pwd), current_admin=_ADMIN)
    assert exc_info.value.status_code == 400
    assert "Bind password" in exc_info.value.detail


def test_db_error_is_logged_and_converted_to_500():
    """DB katmanı patlarsa: log_exception çağrılır + HTTPException(500) (ham 500 değil)."""
    boom = RuntimeError("db down")
    with patch("app.api.routes.ldap_settings.get_db_context", side_effect=boom), \
         patch("app.api.routes.ldap_settings.log_exception") as mock_log:
        with pytest.raises(HTTPException) as exc_info:
            create_ldap_setting(_payload("secret"), current_admin=_ADMIN)
    assert exc_info.value.status_code == 500
    assert mock_log.called
    # exc pozisyonel + module/context kwarg geçildi
    logged_exc = mock_log.call_args.args[0]
    assert logged_exc is boom
    assert mock_log.call_args.kwargs.get("module") == "ldap_settings"


def test_http_exception_is_not_swallowed():
    """İçeride bilinçli atılan HTTPException (ör. duplicate 400) 500'e DÖNÜŞMEZ."""
    dup = HTTPException(status_code=400, detail="zaten kayıtlı")

    class _RaisingCtx:
        def __enter__(self):
            raise dup

        def __exit__(self, *a):
            return False

    with patch("app.api.routes.ldap_settings.get_db_context", return_value=_RaisingCtx()), \
         patch("app.api.routes.ldap_settings.log_exception") as mock_log:
        with pytest.raises(HTTPException) as exc_info:
            create_ldap_setting(_payload("secret"), current_admin=_ADMIN)
    assert exc_info.value.status_code == 400
    assert not mock_log.called  # HTTPException loglanmaz, re-raise edilir


def test_soft_deleted_domain_is_revived_not_500():
    """Soft-delete edilmiş aynı domain → UNIQUE 500 yerine CANLANDIR (un-delete + güncelle)."""
    cur = _FakeCursor(dead=True)
    with patch("app.api.routes.ldap_settings.get_db_context", return_value=_fake_db(cur)), \
         patch("app.api.routes.ldap_settings.encrypt_password", return_value="ENC"):
        result = create_ldap_setting(_payload("secret"), current_admin=_ADMIN)
    assert result["success"] is True
    assert "yeniden etkinleştir" in result["message"]
    assert result["setting"]["id"] == 5
    assert result["setting"]["is_deleted"] is False
    # v3.59.0: company_id response'ta dönmeli (edit modalında firma ön-seçili gelsin)
    assert result["setting"]["company_id"] == 7


def test_unique_violation_race_returns_400_not_500():
    """Soft-deleted yok ama INSERT yarışta UniqueViolation atarsa → ham 500 değil net 400."""
    cur = _FakeCursor(dead=False, insert_raises=psycopg2.errors.UniqueViolation("dup"))
    with patch("app.api.routes.ldap_settings.get_db_context", return_value=_fake_db(cur)), \
         patch("app.api.routes.ldap_settings.encrypt_password", return_value="ENC"), \
         patch("app.api.routes.ldap_settings.log_exception") as mock_log:
        with pytest.raises(HTTPException) as exc_info:
            create_ldap_setting(_payload("secret"), current_admin=_ADMIN)
    assert exc_info.value.status_code == 400
    assert "zaten kayıtlı" in exc_info.value.detail
    assert not mock_log.called  # UniqueViolation ERROR olarak loglanmaz (beklenen iş kuralı)
