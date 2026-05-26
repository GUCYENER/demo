"""VYRA v3.37.0 — LLM Format Suggest API testleri (B8 / TYCHE+ARES).

Test scope:
- test_suggest_formats_happy_path
- test_chart_type_whitelist_enforcement
- test_cache_hit
- test_redis_down_fallback
- test_auth_required
- test_rate_limit (placeholder — rate limit middleware şu an mount edilmiyor)

Coverage hedefi >= %85.

Brief: .agents/in_flight/2026-05-25_2242_v3370_llm_format_suggest.md
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────────
# Test app + fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def format_app() -> FastAPI:
    """LLM format router'ı izole bir test app'e mount eder."""
    from app.api.routes import llm_format_api
    app = FastAPI()
    app.include_router(llm_format_api.router)
    return app


@pytest.fixture
def format_client(format_app: FastAPI) -> TestClient:
    return TestClient(format_app)


@pytest.fixture
def auth_user() -> Dict[str, Any]:
    return {
        "id": 1,
        "username": "testuser",
        "role": "user",
        "role_id": 2,
        "is_admin": False,
        "is_approved": True,
        "company_id": 1,
    }


@pytest.fixture
def auth_headers(auth_user) -> Dict[str, str]:
    """Geçerli Bearer token üret."""
    from app.api.routes.auth import create_access_token
    token = create_access_token(auth_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_payload() -> Dict[str, Any]:
    return {
        "metric": {
            "metric_name": "Toplam Satış",
            "agg": "SUM",
            "formula": "SUM(tutar)",
        },
        "columns": ["tarih", "sehir", "musteri_id"],
        "user_intent": "yönetim raporu",
    }


def _llm_response_4_cards() -> str:
    """Geçerli 4 kartlı LLM JSON yanıtı."""
    return json.dumps({
        "cards": [
            {
                "title": "Aylık Satış Trendi",
                "chart_type": "line",
                "group_by": ["MONTH(tarih)"],
                "order_by": ["MONTH(tarih) ASC"],
                "rationale": "Zaman serisi → line chart",
            },
            {
                "title": "Şehir Bazlı Satış",
                "chart_type": "bar",
                "group_by": ["sehir"],
                "order_by": ["SUM(tutar) DESC"],
                "rationale": "Kategorik kırılım → bar chart",
            },
            {
                "title": "Müşteri Top 10",
                "chart_type": "table",
                "group_by": ["musteri_id"],
                "order_by": ["SUM(tutar) DESC"],
                "rationale": "Detay liste → tablo",
            },
            {
                "title": "Toplam Satış KPI",
                "chart_type": "kpi",
                "group_by": [],
                "order_by": [],
                "rationale": "Tek sayı → KPI",
            },
        ]
    }, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────
# TEST 1 — Happy path
# ──────────────────────────────────────────────────────────────────

class TestHappyPath:
    """Mock LLM → 200 + 3-5 format kartı."""

    def test_suggest_formats_happy_path(
        self, format_client, auth_headers, sample_payload
    ):
        with patch(
            "app.services.llm_format_service.call_llm_api",
            return_value=_llm_response_4_cards(),
        ), patch(
            "app.services.llm_format_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_format_service.get_active_llm",
            return_value={"provider": "openai", "model_name": "gpt-4"},
        ):
            response = format_client.post(
                "/api/db/smart/llm/format-suggest",
                json=sample_payload,
                headers=auth_headers,
            )

        assert response.status_code == 200, response.text
        data = response.json()
        assert "format_cards" in data
        cards = data["format_cards"]
        assert 3 <= len(cards) <= 5, f"3-5 kart beklendi, alındı: {len(cards)}"
        assert data["cache_hit"] is False
        assert data["model"] == "openai/gpt-4"

        # Her kart whitelist'te bir chart_type ile dönmeli
        for c in cards:
            assert c["chart_type"] in {"line", "bar", "pie", "table", "kpi", "area"}
            assert c["title"]
            assert c["id"].startswith("fmt_")


# ──────────────────────────────────────────────────────────────────
# TEST 2 — Chart type whitelist enforcement
# ──────────────────────────────────────────────────────────────────

class TestWhitelistEnforcement:
    """LLM 'scatter' gibi whitelist dışı tür dönerse filtrelenmeli."""

    def test_chart_type_whitelist_enforcement(
        self, format_client, auth_headers, sample_payload
    ):
        llm_payload = json.dumps({
            "cards": [
                {
                    "title": "Geçerli Line",
                    "chart_type": "line",
                    "group_by": ["MONTH(tarih)"],
                    "order_by": [],
                    "rationale": "ok",
                },
                {
                    "title": "Yasak Scatter",
                    "chart_type": "scatter",  # whitelist dışı
                    "group_by": [],
                    "order_by": [],
                    "rationale": "filtrelenmeli",
                },
                {
                    "title": "Yasak Heatmap",
                    "chart_type": "heatmap",  # whitelist dışı
                    "group_by": [],
                    "order_by": [],
                    "rationale": "filtrelenmeli",
                },
                {
                    "title": "Geçerli Bar",
                    "chart_type": "BAR",  # case-insensitive
                    "group_by": ["sehir"],
                    "order_by": [],
                    "rationale": "ok",
                },
            ]
        })

        with patch(
            "app.services.llm_format_service.call_llm_api",
            return_value=llm_payload,
        ), patch(
            "app.services.llm_format_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_format_service.get_active_llm",
            return_value={"provider": "p", "model_name": "m"},
        ):
            response = format_client.post(
                "/api/db/smart/llm/format-suggest",
                json=sample_payload,
                headers=auth_headers,
            )

        assert response.status_code == 200
        cards = response.json()["format_cards"]
        # Sadece line + bar kalmalı (scatter + heatmap filtreli)
        assert len(cards) == 2
        chart_types = {c["chart_type"] for c in cards}
        assert chart_types == {"line", "bar"}
        assert "scatter" not in chart_types
        assert "heatmap" not in chart_types


# ──────────────────────────────────────────────────────────────────
# TEST 3 — Cache hit
# ──────────────────────────────────────────────────────────────────

class TestCacheHit:
    """İkinci çağrı cache'ten dönmeli, LLM çağırılmamalı."""

    def test_cache_hit(
        self, format_client, auth_headers, sample_payload
    ):
        # Sahte cache (dict)
        store: Dict[str, Any] = {}
        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda k: store.get(k)
        def _set(k, v, ttl=None):
            store[k] = v
        mock_cache.set.side_effect = _set

        llm_mock = MagicMock(return_value=_llm_response_4_cards())

        with patch(
            "app.services.llm_format_service.call_llm_api",
            llm_mock,
        ), patch(
            "app.services.llm_format_service._get_cache",
            return_value=mock_cache,
        ), patch(
            "app.services.llm_format_service.get_active_llm",
            return_value={"provider": "p", "model_name": "m"},
        ):
            # 1. çağrı — cache miss, LLM çağırılır
            r1 = format_client.post(
                "/api/db/smart/llm/format-suggest",
                json=sample_payload,
                headers=auth_headers,
            )
            # 2. çağrı — cache hit, LLM çağırılmaz
            r2 = format_client.post(
                "/api/db/smart/llm/format-suggest",
                json=sample_payload,
                headers=auth_headers,
            )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["cache_hit"] is False
        assert r2.json()["cache_hit"] is True
        # LLM yalnızca 1 kez çağırılmalı
        assert llm_mock.call_count == 1


# ──────────────────────────────────────────────────────────────────
# TEST 4 — Redis down fallback
# ──────────────────────────────────────────────────────────────────

class TestRedisDownFallback:
    """Cache None ise (Redis yok) endpoint hala 200 dönmeli."""

    def test_redis_down_fallback(
        self, format_client, auth_headers, sample_payload
    ):
        with patch(
            "app.services.llm_format_service.call_llm_api",
            return_value=_llm_response_4_cards(),
        ), patch(
            "app.services.llm_format_service._get_cache",
            return_value=None,  # Redis yok
        ), patch(
            "app.services.llm_format_service.get_active_llm",
            return_value={"provider": "p", "model_name": "m"},
        ):
            response = format_client.post(
                "/api/db/smart/llm/format-suggest",
                json=sample_payload,
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["format_cards"]) >= 3
        assert data["cache_hit"] is False

    def test_cache_exception_does_not_break_endpoint(
        self, format_client, auth_headers, sample_payload
    ):
        """Cache GET/SET exception fırlatsa bile 200 dönmeli."""
        bad_cache = MagicMock()
        bad_cache.get.side_effect = RuntimeError("redis connection refused")
        bad_cache.set.side_effect = RuntimeError("redis connection refused")

        with patch(
            "app.services.llm_format_service.call_llm_api",
            return_value=_llm_response_4_cards(),
        ), patch(
            "app.services.llm_format_service._get_cache",
            return_value=bad_cache,
        ), patch(
            "app.services.llm_format_service.get_active_llm",
            return_value={"provider": "p", "model_name": "m"},
        ):
            response = format_client.post(
                "/api/db/smart/llm/format-suggest",
                json=sample_payload,
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert len(response.json()["format_cards"]) >= 3


# ──────────────────────────────────────────────────────────────────
# TEST 5 — Auth required
# ──────────────────────────────────────────────────────────────────

class TestAuthRequired:
    """Bearer token olmadan 401/403 dönmeli."""

    def test_auth_required_no_token(self, format_client, sample_payload):
        response = format_client.post(
            "/api/db/smart/llm/format-suggest",
            json=sample_payload,
        )
        assert response.status_code in (401, 403), (
            f"401/403 beklendi, alındı: {response.status_code}"
        )

    def test_auth_required_invalid_token(self, format_client, sample_payload):
        response = format_client.post(
            "/api/db/smart/llm/format-suggest",
            json=sample_payload,
            headers={"Authorization": "Bearer invalid-token-xxx"},
        )
        assert response.status_code in (401, 403)


# ──────────────────────────────────────────────────────────────────
# TEST 6 — Rate limit (placeholder)
# ──────────────────────────────────────────────────────────────────

class TestRateLimit:
    """Rate limit middleware henüz bu endpoint'te mount edilmediği için
    placeholder. İleride brief güncellenirse aktive edilecek."""

    def test_rate_limit_placeholder(
        self, format_client, auth_headers, sample_payload
    ):
        # Şu an no-op: ardışık 3 çağrı 200 dönmeli (rate limit yok).
        with patch(
            "app.services.llm_format_service.call_llm_api",
            return_value=_llm_response_4_cards(),
        ), patch(
            "app.services.llm_format_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_format_service.get_active_llm",
            return_value={"provider": "p", "model_name": "m"},
        ):
            for _ in range(3):
                r = format_client.post(
                    "/api/db/smart/llm/format-suggest",
                    json=sample_payload,
                    headers=auth_headers,
                )
                assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────
# Ek — service-level kapsamı arttıran küçük testler
# ──────────────────────────────────────────────────────────────────

class TestServiceInternals:
    """Coverage > 85% için service yardımcılarını da kapsamak."""

    def test_extract_json_from_markdown_fence(self):
        from app.services.llm_format_service import _extract_json_block
        raw = "```json\n{\"cards\": [{\"title\": \"a\", \"chart_type\": \"bar\"}]}\n```"
        parsed = _extract_json_block(raw)
        assert parsed is not None
        assert parsed["cards"][0]["chart_type"] == "bar"

    def test_extract_json_with_preamble(self):
        from app.services.llm_format_service import _extract_json_block
        raw = "İşte cevap: {\"cards\": [{\"title\": \"x\", \"chart_type\": \"line\"}]}"
        parsed = _extract_json_block(raw)
        assert parsed is not None
        assert parsed["cards"][0]["title"] == "x"

    def test_extract_json_invalid_returns_none(self):
        from app.services.llm_format_service import _extract_json_block
        assert _extract_json_block("tamamen geçersiz yanıt") is None
        assert _extract_json_block("") is None

    def test_sanitize_drops_empty_title(self):
        from app.services.llm_format_service import _sanitize_cards
        out = _sanitize_cards([
            {"title": "", "chart_type": "line"},
            {"title": "ok", "chart_type": "bar"},
        ])
        assert len(out) == 1
        assert out[0]["title"] == "ok"

    def test_sanitize_caps_at_max(self):
        from app.services.llm_format_service import _sanitize_cards, MAX_CARDS
        raw = [
            {"title": f"c{i}", "chart_type": "line"} for i in range(MAX_CARDS + 5)
        ]
        out = _sanitize_cards(raw)
        assert len(out) == MAX_CARDS

    def test_sanitize_non_list_groupby(self):
        from app.services.llm_format_service import _sanitize_cards
        out = _sanitize_cards([
            {"title": "x", "chart_type": "kpi", "group_by": "sehir", "order_by": "sehir DESC"},
        ])
        assert out[0]["group_by"] == ["sehir"]
        assert out[0]["order_by"] == ["sehir DESC"]

    def test_cache_key_deterministic(self):
        from app.services.llm_format_service import _cache_key
        k1 = _cache_key({"a": 1}, ["x", "y"], "intent")
        k2 = _cache_key({"a": 1}, ["y", "x"], "intent")  # cols sorted
        assert k1 == k2
        k3 = _cache_key({"a": 2}, ["x", "y"], "intent")
        assert k1 != k3
