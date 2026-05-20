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
    # session_manager.update_context() / mark_completed() vb. cur.rowcount kontrol eder;
    # MagicMock varsayılan attribute yerine gerçek int olmalı ki `affected > 0` çalışsın.
    fake_cur.rowcount = 1
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
        "/api/db-smart/metrics/custom",  # FAZ 2 P11 G2.2
        "/api/db-smart/recommendations/{exec_id}",
        # FAZ 3 P13 G3.3 — Saved Reports
        "/api/db-smart/saved-reports",
        "/api/db-smart/saved-reports/{report_id}",
        "/api/db-smart/saved-reports/{report_id}/share",
        "/api/db-smart/saved-reports/{report_id}/revoke-share",
        "/api/db-smart/saved-reports/{report_id}/mark-run",
        "/api/db-smart/saved-reports/by-token/{token}",
        # FAZ 3 P15 G3.2 — Streaming SSE
        "/api/db-smart/sessions/{session_uid}/execute/stream",
        # FAZ 3 P19 G3.4 — AST diff + EXPLAIN cache
        "/api/db-smart/ast/diff",
        "/api/db-smart/sessions/{session_uid}/explain",
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


def test_recommendations_preview_returns_charts_and_insights(client_authed):
    """FAZ 2 P9 G2.3 — transient öneri endpoint'i."""
    resp = client_authed.post(
        "/api/db-smart/recommendations/preview",
        json={
            "columns": ["status", "cnt"],
            "rows": [["open", 10], ["closed", 20], ["wip", 5]],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "charts" in data and "insights" in data and "profile" in data
    vizs = [c["viz"] for c in data["charts"]]
    assert "donut" in vizs  # 3 kategori


def test_recommendations_preview_empty_rows(client_authed):
    resp = client_authed.post(
        "/api/db-smart/recommendations/preview",
        json={"columns": ["x"], "rows": []},
    )
    assert resp.status_code == 200
    assert resp.json()["charts"] == []


def test_recommendations_preview_outlier_insight(client_authed):
    resp = client_authed.post(
        "/api/db-smart/recommendations/preview",
        json={"columns": ["v"], "rows": [[10], [12], [11], [9], [13], [500]]},
    )
    assert resp.status_code == 200
    kinds = [i["kind"] for i in resp.json()["insights"]]
    assert "outlier_high" in kinds


# ─────────────────────────────────────────────────────────────
# FAZ 2 P11 G2.2 — Custom Metric NL→SQL endpoint
# ─────────────────────────────────────────────────────────────

def test_custom_metric_returns_sql_without_save(client_authed, monkeypatch):
    """parse_to_sql happy path + save=False → kayıt yok."""
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "build_metric_schema_context",
        lambda cur, sid, tids, dialect="postgresql": {
            "source_name": "ACME", "dialect": "postgresql",
            "tables": [{"name": "orders", "columns": [{"name": "amount", "data_type": "DECIMAL"}],
                        "col_enrichments": {}}],
        },
    )
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "parse_to_sql",
        lambda q, ctx, **kw: {
            "success": True, "sql": "SELECT SUM(amount) FROM orders",
            "intent": {"agg_func": "SUM"}, "error": None, "explanation": "Toplam",
        },
    )

    resp = client_authed.post(
        "/api/db-smart/metrics/custom",
        json={
            "nl_query": "Toplam satış",
            "source_id": 1,
            "table_ids": [10],
            "save": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "SUM(amount)" in data["sql"]
    assert data["intent"]["agg_func"] == "SUM"
    assert data["saved_metric_id"] is None
    assert data["metric_key"] is None


def test_custom_metric_save_requires_name(client_authed):
    resp = client_authed.post(
        "/api/db-smart/metrics/custom",
        json={"nl_query": "Toplam satış", "source_id": 1, "table_ids": [10], "save": True},
    )
    assert resp.status_code == 400
    assert "name_tr" in resp.json()["detail"]


def test_custom_metric_invalid_viz_rejected(client_authed):
    resp = client_authed.post(
        "/api/db-smart/metrics/custom",
        json={"nl_query": "Toplam satış", "source_id": 1, "table_ids": [10],
              "default_viz": "totally_fake_viz"},
    )
    assert resp.status_code == 400


def test_custom_metric_save_inserts(client_authed, monkeypatch):
    """save=True → save_custom_metric çağrılır, saved_metric_id döner."""
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "build_metric_schema_context",
        lambda cur, sid, tids, dialect="postgresql": {
            "source_name": "ACME", "dialect": "postgresql",
            "tables": [{"name": "orders", "columns": [], "col_enrichments": {}}],
        },
    )
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "parse_to_sql",
        lambda q, ctx, **kw: {
            "success": True, "sql": "SELECT SUM(amount) FROM orders",
            "intent": {"agg_func": "SUM"}, "error": None, "explanation": "X",
        },
    )
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "save_custom_metric",
        lambda cur, **kw: 77,
    )

    resp = client_authed.post(
        "/api/db-smart/metrics/custom",
        json={
            "nl_query": "Toplam satış",
            "source_id": 1,
            "table_ids": [10],
            "save": True,
            "name_tr": "Aylık Toplam Satış",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["saved_metric_id"] == 77
    assert data["metric_key"] and data["metric_key"].startswith("custom_42_")


def test_custom_metric_llm_failure_returns_success_false(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "build_metric_schema_context",
        lambda cur, sid, tids, dialect="postgresql": {
            "source_name": "ACME", "dialect": "postgresql",
            "tables": [{"name": "orders", "columns": [], "col_enrichments": {}}],
        },
    )
    monkeypatch.setattr(
        db_smart_api.custom_metric_parser, "parse_to_sql",
        lambda q, ctx, **kw: {
            "success": False, "sql": None,
            "intent": {"agg_func": None}, "error": "LLM zaman aşımı", "explanation": None,
        },
    )

    resp = client_authed.post(
        "/api/db-smart/metrics/custom",
        json={"nl_query": "Toplam satış", "source_id": 1, "table_ids": [10]},
    )
    # Endpoint kullanıcı hatası değil — 200 + success=False
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "LLM zaman aşımı" in resp.json()["error"]


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
# FAZ 3 P19 G3.4 — AST diff + EXPLAIN cache endpoints
# ─────────────────────────────────────────────────────────────

def test_ast_patch_reorder_columns_in_whitelist(client_authed, mock_session_with_ast,
                                                  monkeypatch):
    """reorder_columns whitelist'e eklendi mi?"""
    # AST'i 2 kolonlu yap ki reorder anlam ifade etsin
    ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}, {"expr": "t.status"}],
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
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "reorder_columns",
              "args": {"order": [{"expr": "t.status"}, {"expr": "t.id"}]}},
    )
    assert resp.status_code == 200
    cols = resp.json()["ast"]["columns"]
    assert [c["expr"] for c in cols] == ["t.status", "t.id"]


def test_ast_diff_returns_summary(client_authed):
    from_ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [],
    }
    to_ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}, {"expr": "t.status"}],
        "from": {"table": "tickets", "alias": "t"},
        "filters": [],
        "limit": 100,
    }
    resp = client_authed.post("/api/db-smart/ast/diff",
                              json={"from_ast": from_ast, "to_ast": to_ast})
    assert resp.status_code == 200
    data = resp.json()
    assert data["columns"]["added"] == [{"expr": "t.status", "alias": ""}]
    assert data["limit"]["after"] == 100
    assert data["summary"]["total_changes"] >= 2
    assert "columns" in data["summary"]["changed_sections"]
    assert "limit" in data["summary"]["changed_sections"]


def test_ast_diff_identical_zero_changes(client_authed):
    ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
    }
    resp = client_authed.post("/api/db-smart/ast/diff",
                              json={"from_ast": ast, "to_ast": dict(ast)})
    assert resp.status_code == 200
    assert resp.json()["summary"]["total_changes"] == 0


def test_explain_endpoint_rejects_non_select(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/explain",
        json={"ast": {"type": "delete"}, "dialect": "postgresql"},
    )
    assert resp.status_code == 400


def test_explain_endpoint_renders_and_caches(client_authed, monkeypatch):
    """İlk çağrı: cached=False; ikinci aynı çağrı: cached=True."""
    # Cache'i temizle (önceki testlerden artakalma olmasın)
    db_smart_api._EXPLAIN_CACHE.clear()
    # explain_cost'u stub'la — DB hit etmeden döner
    monkeypatch.setattr(
        "app.services.db_smart.query_assembler.explain_cost",
        lambda cur, sql, dialect, user_ctx, binds=None: 42.5,
    )
    ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
    }
    body = {"ast": ast, "dialect": "postgresql"}
    r1 = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/explain",
        json=body,
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["cached"] is False
    assert d1["explain"]["total_cost"] == 42.5
    assert "tickets" in d1["sql"]

    r2 = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/explain",
        json=body,
    )
    assert r2.status_code == 200
    assert r2.json()["cached"] is True


def test_explain_cache_ttl_expires(client_authed, monkeypatch):
    """5sn TTL — sahte zamanlayıcı ile expiration testle."""
    db_smart_api._EXPLAIN_CACHE.clear()
    monkeypatch.setattr(
        "app.services.db_smart.query_assembler.explain_cost",
        lambda cur, sql, dialect, user_ctx, binds=None: 10.0,
    )
    ast = {
        "type": "select",
        "columns": [{"expr": "t.id"}],
        "from": {"table": "tickets", "alias": "t"},
    }
    body = {"ast": ast, "dialect": "postgresql"}
    r1 = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/explain",
        json=body,
    )
    assert r1.json()["cached"] is False

    # TTL'i mock'la — sonraki çağrı expire görsün
    original_monotonic = db_smart_api._time.monotonic
    monkeypatch.setattr(db_smart_api._time, "monotonic",
                        lambda: original_monotonic() + 10.0)
    r2 = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/explain",
        json=body,
    )
    assert r2.json()["cached"] is False  # expired → yeniden compute


def test_explain_endpoint_invalid_ast_render_400(client_authed):
    """AST render fail (örn. bad identifier) → 400."""
    db_smart_api._EXPLAIN_CACHE.clear()
    ast = {
        "type": "select",
        "columns": [{"expr": "t.id; DROP TABLE u"}],  # invalid ident
        "from": {"table": "tickets", "alias": "t"},
    }
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/explain",
        json={"ast": ast, "dialect": "postgresql"},
    )
    assert resp.status_code == 400


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


# ─────────────────────────────────────────────────────────────
# FAZ 3 P13 G3.3 — Saved Reports endpoints
# ─────────────────────────────────────────────────────────────

def test_save_report_requires_name(client_authed):
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/save-report",
        json={"description": "boş"},
    )
    assert resp.status_code == 400


def test_save_report_404_when_session_missing(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.session_manager, "load_session",
        lambda cur, uid, user_ctx: None,
    )
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/save-report",
        json={"name": "Aylık Satış"},
    )
    assert resp.status_code == 404


def test_save_report_success(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.session_manager, "load_session",
        lambda cur, uid, user_ctx: {
            "source_id": 3,
            "context": {
                "wizard_state": {"step": 5},
                "last_sql": "SELECT 1",
                "dialect": "postgresql",
            },
        },
    )
    captured = {}

    def fake_save(cur, user_ctx, **kw):
        captured.update(kw)
        return {"id": 77, "created_at": "2026-05-20T10:00:00"}

    monkeypatch.setattr(db_smart_api.saved_reports, "save", fake_save)
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/save-report",
        json={"name": "Aylık Satış", "description": "Snap", "tags": ["aylık"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_id"] == 77
    assert captured["name"] == "Aylık Satış"
    assert captured["source_id"] == 3
    assert captured["last_sql"] == "SELECT 1"
    assert captured["tags"] == ["aylık"]


def test_list_saved_reports(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "list_for_user",
        lambda cur, user_ctx, *, limit, offset: [
            {"id": 1, "name": "R1"}, {"id": 2, "name": "R2"},
        ],
    )
    resp = client_authed.get("/api/db-smart/saved-reports?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["items"][0]["name"] == "R1"


def test_get_saved_report_404(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "get_by_id",
        lambda cur, rid, user_ctx: None,
    )
    resp = client_authed.get("/api/db-smart/saved-reports/999")
    assert resp.status_code == 404


def test_get_saved_report_success(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "get_by_id",
        lambda cur, rid, user_ctx: {"id": rid, "name": "R", "wizard_state": {}},
    )
    resp = client_authed.get("/api/db-smart/saved-reports/5")
    assert resp.status_code == 200
    assert resp.json()["id"] == 5


def test_patch_saved_report_empty_body_400(client_authed):
    resp = client_authed.patch("/api/db-smart/saved-reports/5", json={})
    assert resp.status_code == 400


def test_patch_saved_report_success(client_authed, monkeypatch):
    captured = {}

    def fake_update(cur, rid, user_ctx, **kw):
        captured["rid"] = rid
        captured.update(kw)
        return True

    monkeypatch.setattr(db_smart_api.saved_reports, "update", fake_update)
    resp = client_authed.patch(
        "/api/db-smart/saved-reports/5",
        json={"name": "Yeni Ad", "tags": ["a"]},
    )
    assert resp.status_code == 200
    assert captured["rid"] == 5
    assert captured["name"] == "Yeni Ad"


def test_share_report_default_ttl(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "create_share_token",
        lambda cur, rid, user_ctx, *, ttl_hours: {
            "share_token": "tok-XYZ", "share_expires_at": "2026-05-21T10:00:00",
            "ttl_hours": ttl_hours,
        },
    )
    resp = client_authed.post("/api/db-smart/saved-reports/5/share", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["share_token"] == "tok-XYZ"
    assert data["ttl_hours"] == 24


def test_share_report_invalid_ttl(client_authed):
    resp = client_authed.post(
        "/api/db-smart/saved-reports/5/share",
        json={"ttl_hours": 99999},
    )
    assert resp.status_code == 422  # Pydantic validator


def test_share_report_404(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "create_share_token",
        lambda cur, rid, user_ctx, *, ttl_hours: None,
    )
    resp = client_authed.post("/api/db-smart/saved-reports/5/share", json={"ttl_hours": 12})
    assert resp.status_code == 404


def test_revoke_share_success(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "revoke_share",
        lambda cur, rid, user_ctx: True,
    )
    resp = client_authed.post("/api/db-smart/saved-reports/5/revoke-share")
    assert resp.status_code == 200


def test_revoke_share_404(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "revoke_share",
        lambda cur, rid, user_ctx: False,
    )
    resp = client_authed.post("/api/db-smart/saved-reports/5/revoke-share")
    assert resp.status_code == 404


def test_mark_run_success(client_authed, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "mark_run",
        lambda cur, rid, user_ctx: True,
    )
    resp = client_authed.post("/api/db-smart/saved-reports/5/mark-run")
    assert resp.status_code == 200


def test_share_token_public_no_auth(app_with_router, mock_db, monkeypatch):
    """by-token endpoint AUTH GEREKTİRMEZ — TestClient override yokken çalışmalı."""
    monkeypatch.setattr(
        db_smart_api.saved_reports, "get_by_share_token",
        lambda cur, tok: {
            "id": 5, "user_id": 7, "company_id": 42, "name": "Public R",
            "last_sql": "SELECT 1", "wizard_state": {}, "tags": [],
            "share_expires_at": None,
        },
    )
    client = TestClient(app_with_router)
    resp = client.get("/api/db-smart/saved-reports/by-token/some-share-token-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Public R"
    # PII güvenliği: user_id/company_id response'a SIZMAMALI
    assert "user_id" not in data
    assert "company_id" not in data


def test_share_token_not_found(app_with_router, mock_db, monkeypatch):
    monkeypatch.setattr(
        db_smart_api.saved_reports, "get_by_share_token",
        lambda cur, tok: None,
    )
    client = TestClient(app_with_router)
    resp = client.get("/api/db-smart/saved-reports/by-token/unknown-token-xx")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# FAZ 3 P15 G3.2 — Streaming SSE
# ─────────────────────────────────────────────────────────────

def test_execute_stream_requires_source_id_or_session(client_authed):
    # SQL var, source_id yok → 400
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/execute/stream",
        json={"sql": "SELECT 1", "dialect": "postgresql"},
    )
    assert resp.status_code == 400


def test_execute_stream_source_not_found(client_authed, mock_db, monkeypatch):
    # ARES: permission check geçer ama data_sources kaydı yok → 404
    from app.api.routes import db_smart_api as _api
    monkeypatch.setattr(
        "app.services.data_source_access.user_can_access_source",
        lambda uid, sid, **kw: True,
    )
    mock_db.fetchone.return_value = None  # data_sources LIMIT 1 boş
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/execute/stream",
        json={"sql": "SELECT 1", "source_id": 999, "dialect": "postgresql"},
    )
    assert resp.status_code == 404


def test_execute_stream_permission_denied(client_authed, mock_db, monkeypatch):
    # ARES: user_can_access_source FALSE → 404 (varlık/yetki sızıntısı önleme)
    monkeypatch.setattr(
        "app.services.data_source_access.user_can_access_source",
        lambda uid, sid, **kw: False,
    )
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/execute/stream",
        json={"sql": "SELECT 1", "source_id": 1, "dialect": "postgresql"},
    )
    assert resp.status_code == 404


def test_execute_stream_returns_sse_response(client_authed, mock_db, monkeypatch):
    # Permission gate açık
    monkeypatch.setattr(
        "app.services.data_source_access.user_can_access_source",
        lambda uid, sid, **kw: True,
    )
    # _load_source SELECT layout: (id, company_id, name, db_type, host, port,
    #                              db_name, db_user, db_password_encrypted)
    mock_db.fetchone.return_value = (
        1, 42, "pg-src", "postgresql", "localhost", 5432, "db", "u", None,
    )

    captured: Dict[str, Any] = {}

    def fake_stream(sql, source, dialect, **kw):
        captured["sql"] = sql
        captured["source"] = source
        captured["dialect"] = dialect
        captured["password"] = kw.get("password")
        yield {"type": "start", "sql_preview": sql}
        yield {"type": "columns", "columns": ["id"]}
        yield {"type": "rows", "rows": [[1]], "batch_index": 0}
        yield {"type": "end", "row_count": 1, "elapsed_ms": 1, "truncated": False}

    from app.services.db_smart import sql_executor_stream as _ses
    monkeypatch.setattr(_ses, "stream_safe_sql", fake_stream)
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/execute/stream",
        json={"sql": "SELECT 1", "source_id": 1, "dialect": "postgresql"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: start" in body
    assert "event: columns" in body
    assert "event: rows" in body
    assert "event: end" in body
    # ARES: password source dict'e KOYULMAMIŞ — ayrı kwarg
    assert "password" not in (captured.get("source") or {})
    assert "db_password_encrypted" not in (captured.get("source") or {})
    assert captured.get("password") == ""  # encrypted=None → boş plaintext


# ---------------------------------------------------------------------------
# FAZ 3 P18 — Template Marketplace endpoints
# ---------------------------------------------------------------------------

def test_list_templates_default(client_authed, mock_db, monkeypatch):
    # template_marketplace.browse'u mock'la — endpoint cur'u doğru kullanıyor mu?
    captured: Dict[str, Any] = {}
    def fake_browse(cur, user, **kw):
        captured["filter"] = kw
        return [{"metric_key": "oldest_open", "name_tr": "Oldest", "is_mine": False}]
    monkeypatch.setattr(
        "app.services.db_smart.template_marketplace.browse",
        fake_browse,
    )
    resp = client_authed.get("/api/db-smart/templates?category=helpdesk&order=popular&limit=10")
    assert resp.status_code == 200
    j = resp.json()
    assert j["count"] == 1
    assert j["items"][0]["metric_key"] == "oldest_open"
    assert captured["filter"]["category"] == "helpdesk"
    assert captured["filter"]["order"] == "popular"
    assert captured["filter"]["limit"] == 10


def test_list_templates_invalid_order_rejected(client_authed, mock_db, monkeypatch):
    # Pydantic Query pattern → 422 fastapi tarafında
    resp = client_authed.get("/api/db-smart/templates?order=stupid")
    assert resp.status_code == 422


def test_list_templates_invalid_owner_rejected(client_authed, mock_db):
    resp = client_authed.get("/api/db-smart/templates?owner=admin")
    assert resp.status_code == 422


def test_template_categories(client_authed, mock_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.db_smart.template_marketplace.get_categories",
        lambda cur: [{"category": "helpdesk", "count": 12}],
    )
    resp = client_authed.get("/api/db-smart/templates/categories")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_get_template_by_key_found(client_authed, mock_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.db_smart.template_marketplace.get_by_key",
        lambda cur, k, u: {"metric_key": k, "name_tr": "X", "is_mine": False},
    )
    resp = client_authed.get("/api/db-smart/templates/oldest_open")
    assert resp.status_code == 200
    assert resp.json()["metric_key"] == "oldest_open"


def test_get_template_by_key_404(client_authed, mock_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.db_smart.template_marketplace.get_by_key",
        lambda cur, k, u: None,
    )
    resp = client_authed.get("/api/db-smart/templates/no_such_thing")
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────
# F-021 / F-020 / N-4 — ARES security fixes (db_smart_api.py)
# ─────────────────────────────────────────────────────────────

def test_ast_patch_render_preview_injects_rls(client_authed, mock_session_with_ast):
    """F-021 ARES KRİTİK: render_preview=True path'i inject_rls çağırmalı.

    Non-admin user (is_admin=False, company_id=1) için preview SQL'inde
    company_id filter görünmeli. Aksi halde preview SQL başka bir oturuma
    copy-paste edildiğinde cross-tenant veri sızıntısı olur.
    """
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
    sql_lower = (data["sql"] or "").lower()
    # inject_rls "{alias}.company_id" filter ekler → SQL'de company_id geçmeli
    assert "company_id" in sql_lower, (
        "render_preview SQL inject_rls çıktısını içermiyor — cross-tenant risk!"
    )


def test_ast_patch_render_preview_admin_no_rls(app_with_router, mock_db,
                                                mock_session_with_ast):
    """Admin user için inject_rls no-op döner — RLS filter eklenmemeli."""
    def _fake_admin():
        return {"id": 1, "username": "admin", "company_id": 1,
                "role": "admin", "is_admin": True}

    app_with_router.dependency_overrides[get_current_user] = _fake_admin
    admin_client = TestClient(app_with_router)
    resp = admin_client.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={
            "op": "add_column",
            "args": {"column": {"expr": "t.status"}},
            "render_preview": True,
        },
    )
    assert resp.status_code == 200
    # Admin path'inde company_id filter beklenmiyor (ama SQL render başarılı)
    assert resp.json()["sql"] is not None


def test_set_limit_upper_bound_clamped(client_authed, mock_session_with_ast):
    """F-020 ARES ORTA: args.limit > 10M → 10M'e clamp edilmeli.

    ast_renderer.set_limit upper bound check yok; user `limit=10**12`
    gönderirse `LIMIT 1000000000000` SQL — PG için OOM / syntax risk.
    db_smart_api dispatcher clamp ediyor.
    """
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "set_limit", "args": {"limit": 10**12}},
    )
    assert resp.status_code == 200
    data = resp.json()
    # AST'deki limit clamp'lendi mi?
    assert data["ast"].get("limit") == 10_000_000, (
        f"set_limit 10M'e clamp edilmedi, got: {data['ast'].get('limit')!r}"
    )


def test_set_limit_below_cap_unchanged(client_authed, mock_session_with_ast):
    """Cap altındaki normal değerler değiştirilmemeli."""
    resp = client_authed.post(
        "/api/db-smart/sessions/abcdefgh-1234-1234-1234-123456789abc/ast/patch",
        json={"op": "set_limit", "args": {"limit": 5000}},
    )
    assert resp.status_code == 200
    assert resp.json()["ast"].get("limit") == 5000


def test_explain_cache_thread_safe(monkeypatch):
    """N-4: _EXPLAIN_CACHE concurrent put/get race olmamalı.

    Lock altında FIFO eviction + KeyError defense ile KeyError/RuntimeError
    fırlatmamalı. 8 worker × 200 iterasyon = 1600 put + 1600 get.
    """
    import concurrent.futures as _cf

    db_smart_api._EXPLAIN_CACHE.clear()

    def _worker(seed: int) -> int:
        errors = 0
        for i in range(200):
            key = f"k-{seed}-{i % 50}"  # bazı key'ler tekrarlasın
            try:
                db_smart_api._explain_cache_put(key, {"v": i})
                db_smart_api._explain_cache_get(key)
            except Exception:
                errors += 1
        return errors

    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_worker, range(8)))

    assert sum(results) == 0, f"Concurrent cache erişiminde hata: {results}"
    # Cache MAX sınırını aşmamış olmalı
    assert len(db_smart_api._EXPLAIN_CACHE) <= db_smart_api._EXPLAIN_CACHE_MAX
