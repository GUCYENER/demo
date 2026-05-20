"""db_smart_api endpoint contract tests (v3.30.0 FAZ 1 G1.1b).

FastAPI TestClient ile:
    - 12 endpoint'in tamamı kayıtlı mı?
    - Unauth → 401 (Depends(get_current_user))
    - Auth varken stub payload Pydantic kontratına uyuyor mu?

NOT: Gerçek DB bağlantısı yok — `get_db_context` fixture'ı ile patchleniyor.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes.auth import get_current_user
from app.api.routes import db_smart_api


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def app_with_router():
    """Sadece db_smart_api router'ını içeren minimal FastAPI app."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(db_smart_api.router)
    return app


@pytest.fixture
def mock_db(monkeypatch):
    """get_db_context'i fake conn ile patch et (cursor calls'unu yakalar)."""
    fake_cur = MagicMock()
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur

    @contextmanager
    def fake_ctx() -> Iterator[Any]:
        yield fake_conn

    monkeypatch.setattr(db_smart_api, "get_db_context", fake_ctx)
    return fake_cur


@pytest.fixture
def client_authed(app_with_router, mock_db):
    """Authed TestClient — get_current_user override edilmiş."""
    def _fake_user() -> Dict[str, Any]:
        return {"id": 42, "username": "test_user", "company_id": 1, "role": "user", "is_admin": False}

    app_with_router.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app_with_router)


# ─────────────────────────────────────────────────────────────
# Route registration
# ─────────────────────────────────────────────────────────────

def test_router_registers_all_12_endpoints():
    """12 route var ve prefix /api/db-smart altında."""
    paths = {r.path for r in db_smart_api.router.routes}
    expected = {
        "/api/db-smart/sessions",
        "/api/db-smart/sessions/{session_uid}",
        "/api/db-smart/sessions/{session_uid}/step/{step_n}",
        "/api/db-smart/sessions/{session_uid}/preview",
        "/api/db-smart/sessions/{session_uid}/execute",
        "/api/db-smart/sessions/{session_uid}/save-report",
        "/api/db-smart/sessions/{session_uid}/ast/patch",  # FAZ 2 P8 G2.1
        "/api/db-smart/sources",
        "/api/db-smart/sources/{source_id}/tables",
        "/api/db-smart/sources/{source_id}/tables/{table_id}/related",
        "/api/db-smart/sources/{source_id}/tables/{table_id}/columns",
        "/api/db-smart/metrics",
        "/api/db-smart/recommendations/{exec_id}",
    }
    missing = expected - paths
    assert not missing, f"Missing routes: {missing}"


# ─────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────

def test_create_session_returns_uuid(client_authed):
    resp = client_authed.post("/api/db-smart/sessions", json={"source_id": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_uid" in data and len(data["session_uid"]) >= 8
    assert data["current_step"] == 0
    assert data["status"] == "active"


def test_get_session_stub_returns_envelope(client_authed):
    resp = client_authed.get("/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc")
    assert resp.status_code == 200
    assert "session_uid" in resp.json()


def test_post_step_returns_step_response(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/step/0",
        json={"payload": {"source_id": 1}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_step"] == 0
    assert data["node"]  # node string must be set


def test_post_step_rejects_out_of_range_step(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/step/99",
        json={"payload": {}},
    )
    # 9-node FSM (0..8) — 99 hatalı
    assert resp.status_code == 422


def test_preview_returns_pydantic_shape(client_authed):
    resp = client_authed.post("/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert "sql" in data and "dialect" in data and "streaming_strategy" in data


def test_execute_returns_stub_payload(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/execute",
        json={"stream": False, "limit": 100},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "stub"
    assert data["rows"] == []


def test_save_report_validates_viz_enum(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/save-report",
        json={"title": "Test", "default_viz": "INVALID_VIZ"},
    )
    assert resp.status_code == 422


def test_save_report_happy_path(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/save-report",
        json={"title": "Aylık Trend", "default_viz": "line"},
    )
    assert resp.status_code == 200
    assert "report_id" in resp.json()


def test_save_report_accepts_full_viz_enum(client_authed):
    """TYCHE/HEBE code review carry-over: viz enum DB CHECK ile uyumlu olmalı.

    Migration 032 ck_dbsmart_metric_viz 17 değer kabul ediyor; router'ın da
    aynı seti kabul etmesi gerekiyor (önceki regex sadece 6 değer içeriyordu).
    """
    from app.api.routes.db_smart_api import VALID_VIZ_TYPES
    assert len(VALID_VIZ_TYPES) == 17
    for viz in VALID_VIZ_TYPES:
        resp = client_authed.post(
            "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/save-report",
            json={"title": f"T-{viz}", "default_viz": viz},
        )
        assert resp.status_code == 200, f"viz '{viz}' rejected: {resp.text}"


# ─────────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────────

def test_list_sources_returns_items_envelope(client_authed):
    resp = client_authed.get("/api/db-smart/sources")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "count": 0}


def test_search_tables_passes_query(client_authed):
    resp = client_authed.get("/api/db-smart/sources/5/tables?q=ticket&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_id"] == 5
    assert data["query"] == "ticket"


def test_related_tables_returns_neighbors_envelope(client_authed):
    resp = client_authed.get("/api/db-smart/sources/5/tables/12/related?depth=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_id"] == 5 and data["table_id"] == 12
    assert "neighbors" in data and "junctions" in data


def test_list_columns_envelope(client_authed):
    resp = client_authed.get("/api/db-smart/sources/5/tables/12/columns")
    assert resp.status_code == 200
    assert "columns" in resp.json()


# ─────────────────────────────────────────────────────────────
# Metrics & Recommendations
# ─────────────────────────────────────────────────────────────

def test_list_metrics_requires_source_id(client_authed):
    resp = client_authed.get("/api/db-smart/metrics")
    # source_id Query(..., ge=1) — eksik = 422
    assert resp.status_code == 422


def test_list_metrics_happy_path(client_authed):
    resp = client_authed.get("/api/db-smart/metrics?source_id=5&table_signature=abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source_id"] == 5 and data["table_signature"] == "abc123"


def test_get_recommendations_envelope(client_authed):
    resp = client_authed.get("/api/db-smart/recommendations/exec-uuid-123")
    assert resp.status_code == 200
    assert resp.json()["exec_id"] == "exec-uuid-123"


# ─────────────────────────────────────────────────────────────
# FAZ 2 P8 G2.1 — AST patch endpoint
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_session_with_ast(monkeypatch):
    """load_session AST içeren context döner, update_context True döner."""
    ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [],
    }
    monkeypatch.setattr(
        db_smart_api.session_manager, "load_session",
        lambda cur, uid, user_ctx: {
            "session_uid": uid, "current_step": 0, "status": "active",
            "source_id": 1, "context": {"ast": ast},
            "dialect": "postgresql", "generated_sql": None,
            "created_at": None, "last_activity_at": None, "completed_at": None,
        },
    )
    monkeypatch.setattr(
        db_smart_api.session_manager, "update_context",
        lambda cur, uid, partial, user_ctx=None, current_step=None: True,
    )
    return ast


def test_ast_patch_unknown_op_400(client_authed, mock_session_with_ast):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "DROP_TABLE", "args": {}},
    )
    assert resp.status_code == 400
    assert "Bilinmeyen AST op" in resp.json()["detail"]


def test_ast_patch_add_column_success(client_authed, mock_session_with_ast):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "add_column", "args": {"column": {"expr": "t.status"}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["ast"]["columns"]) == 2
    assert data["sql"] is None  # render_preview False


def test_ast_patch_add_column_with_render_preview(client_authed, mock_session_with_ast):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={
            "op": "add_column",
            "args": {"column": {"expr": "t.status"}},
            "render_preview": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sql"] is not None
    assert "tickets" in data["sql"]
    assert data["dialect"] == "postgresql"


def test_ast_patch_injection_blocked(client_authed, mock_session_with_ast):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "add_column", "args": {"column": {"expr": "id; DROP TABLE u"}}},
    )
    assert resp.status_code == 400


def test_ast_patch_args_mismatch_400(client_authed, mock_session_with_ast):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "add_column", "args": {"wrong_kwarg": 1}},
    )
    assert resp.status_code == 400


def test_ast_patch_no_ast_in_session_409(client_authed, monkeypatch):
    """AST henüz oluşturulmamışsa 409."""
    monkeypatch.setattr(
        db_smart_api.session_manager, "load_session",
        lambda cur, uid, user_ctx: {
            "session_uid": uid, "current_step": 0, "status": "active",
            "source_id": 1, "context": {},  # AST yok
            "dialect": "postgresql", "generated_sql": None,
            "created_at": None, "last_activity_at": None, "completed_at": None,
        },
    )
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "add_column", "args": {"column": {"expr": "t.id"}}},
    )
    assert resp.status_code == 409


def test_ast_patch_session_not_found_404(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.session_manager, "load_session",
        lambda cur, uid, user_ctx: None,
    )
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "add_column", "args": {"column": {"expr": "t.id"}}},
    )
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# RLS context injection (ARES carry-over)
# ─────────────────────────────────────────────────────────────

def test_create_session_invokes_rls_context(client_authed, mock_db):
    """Endpoint apply_vyra_user_context çağırmalı → cursor.execute kayıt etmiş olmalı."""
    resp = client_authed.post("/api/db-smart/sessions", json={"source_id": 1})
    assert resp.status_code == 200
    # En az 3 set_config çağrısı (vyra.user_id, company_id, is_admin)
    calls = mock_db.execute.call_args_list
    set_config_calls = [c for c in calls if "set_config" in str(c)]
    assert len(set_config_calls) >= 3
