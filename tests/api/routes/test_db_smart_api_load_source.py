"""VYRA v3.37.0 B1 — `_load_source` normalize regression suite.

Brief: .agents/in_flight/2026-05-25_2235_v3370_b1_load_source_fix.md
Owner: TYCHE+ARES (test author) — kod fix: ATHENA-BE

Kapsam:
    - `_load_source` source_dict["db_type"] alanını _SUPPORTED_DIALECTS
      whitelist'i ile normalize ediyor mu?
    - Bozuk db_type ("db_type", None, "") değerleri downstream
      `_get_db_connector` çağrısında açıklayıcı ValueError veriyor mu?
    - Saved-report rerun yolunun regression smoke testi (mock).
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER = {"id": 1, "company_id": 7, "is_admin": False}


def _fake_cursor(row: tuple) -> MagicMock:
    """data_sources SELECT'i için fetchone() = row dönen mock cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    return cur


def _row(db_type: str) -> tuple:
    """`_load_source` SELECT'inin kolon sırasıyla uyumlu satır.

    keys = ["id", "company_id", "name", "db_type", "host", "port",
            "db_name", "db_user", "db_password_encrypted"]
    """
    return (
        42,            # id
        7,             # company_id
        "test_src",    # name
        db_type,       # db_type
        "localhost",   # host
        5432,          # port
        "vyra",        # db_name
        "vyra_user",   # db_user
        None,          # db_password_encrypted
    )


def _call_load_source(db_type: str) -> tuple:
    """`_load_source` çağırırken permission gate'i bypass et."""
    from app.api.routes import db_smart_api

    cur = _fake_cursor(_row(db_type))
    with patch(
        "app.services.data_source_access.user_can_access_source",
        return_value=True,
    ):
        result = db_smart_api._load_source(cur, 42, USER)
    assert result is not None, "permission gate yanlış kapanmış olmamalı"
    return result


# ---------------------------------------------------------------------------
# Normalize tests (B1 root cause)
# ---------------------------------------------------------------------------

def test_load_source_normalizes_postgres():
    src_dict, _password, dialect = _call_load_source("postgres")
    assert dialect == "postgresql"
    assert src_dict["db_type"] == "postgresql"


def test_load_source_normalizes_mssql():
    src_dict, _password, dialect = _call_load_source("sqlserver")
    assert dialect == "mssql"
    assert src_dict["db_type"] == "mssql"


def test_load_source_normalizes_mysql():
    src_dict, _password, dialect = _call_load_source("mysql")
    assert dialect == "mysql"
    assert src_dict["db_type"] == "mysql"


def test_load_source_normalizes_oracle():
    src_dict, _password, dialect = _call_load_source("oracledb")
    assert dialect == "oracle"
    assert src_dict["db_type"] == "oracle"


def test_load_source_fallback_for_garbage_db_type():
    """Bozuk literal "db_type" — fallback postgresql + downstream artık 'db_type' GÖRMEZ."""
    src_dict, _password, dialect = _call_load_source("db_type")
    assert dialect == "postgresql"
    # Kritik: source_dict["db_type"] artık literal "db_type" DEĞİL.
    assert src_dict["db_type"] != "db_type"
    assert src_dict["db_type"] == "postgresql"


# ---------------------------------------------------------------------------
# Saved-report rerun regression smoke
# ---------------------------------------------------------------------------

def test_rerun_saved_report_b1_regression():
    """B1: rerun yolu artık `Desteklenmeyen veritabanı tipi: db_type` raise etmiyor.

    Smoke: `_load_source` çıktısı `_get_db_connector`'a verildiğinde
    ValueError("Desteklenmeyen ...") DEĞİL açıklayıcı/normal connector
    açılışı denenir. Burada `connect`'i mock'layıp normalize'in geçtiğini
    doğruluyoruz.
    """
    from app.services import ds_learning_service as dsl

    src_dict, _password, _dialect = _call_load_source("db_type")
    # _load_source artık "postgresql"e fallback ediyor.
    assert src_dict["db_type"] == "postgresql"

    # _get_db_connector'a normalize edilmiş dict gidiyor — psycopg2.connect mock.
    fake_conn = MagicMock()
    with patch("psycopg2.connect", return_value=fake_conn) as mock_connect:
        conn, dialect = dsl._get_db_connector(src_dict, "pw")
    assert dialect == "postgresql"
    assert conn is fake_conn
    mock_connect.assert_called_once()


# ---------------------------------------------------------------------------
# Defensive guard — _get_db_connector clear error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["db_type", "", None])
def test_invalid_db_type_raises_clear_error(bad):
    """`_get_db_connector("db_type"/""/None) → ValueError mesajı 'Geçersiz/normalleştirilmemiş' içeriyor."""
    from app.services import ds_learning_service as dsl

    src: Dict[str, Any] = {
        "db_type": bad,
        "host": "h",
        "port": 5432,
        "db_name": "d",
        "db_user": "u",
    }
    with pytest.raises(ValueError) as exc_info:
        dsl._get_db_connector(src, "pw")
    assert "Geçersiz/normalleştirilmemiş" in str(exc_info.value)


def test_unsupported_db_type_still_raises_legacy_message():
    """Defensive guard mevcut 'Desteklenmeyen veritabanı tipi' fallback'ini KORUMALI."""
    from app.services import ds_learning_service as dsl

    src: Dict[str, Any] = {
        "db_type": "snowflake",  # ne whitelist'te ne de "bad-value" listesinde
        "host": "h",
        "port": 5432,
        "db_name": "d",
        "db_user": "u",
    }
    with pytest.raises(ValueError) as exc_info:
        dsl._get_db_connector(src, "pw")
    assert "Desteklenmeyen veritabanı tipi" in str(exc_info.value)
