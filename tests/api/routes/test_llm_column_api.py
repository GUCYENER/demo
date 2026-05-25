"""VYRA v3.37.0 — Tests for B5b LLM Column Suggest endpoint.

Coverage:
    - happy path (2 kategori 200)
    - metric_bound formula filtering (formula kolonu zorla metric_bound'da)
    - date kolonu için suggested_grain inferred
    - cache hit (2. çağrı cache_hit=true)
    - Redis down → uncached fallback
    - auth required (401)
    - invalid input (422)
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import llm_column_api
from app.services import llm_column_service


# ─────────────────────────────────────────────────────────────
# Test app fixture (main.py dokunulmuyor)
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def fapi_app() -> FastAPI:
    """Sadece llm_column_api router'ını içeren minimal app.

    NOT: Fixture adı `app` değil — pytest_flask plugin'i `app` fixture'unu
    otomatik yakalayıp Flask app olarak işlemeye çalışıyor.
    """
    a = FastAPI()
    a.include_router(llm_column_api.router)
    return a


@pytest.fixture
def client(fapi_app: FastAPI) -> TestClient:
    return TestClient(fapi_app)


@pytest.fixture
def auth_user() -> Dict[str, Any]:
    return {"id": 7, "username": "tester", "role": "user", "is_admin": False}


@pytest.fixture(autouse=True)
def _reset_cache():
    """Her test öncesi cache singleton'u sıfırla."""
    llm_column_service._reset_cache_for_tests()
    yield
    llm_column_service._reset_cache_for_tests()


@pytest.fixture
def override_auth(fapi_app: FastAPI, auth_user):
    """get_current_user'ı override eder (auth ON)."""
    from app.api.routes.auth import get_current_user

    def _fake_user():
        return auth_user

    fapi_app.dependency_overrides[get_current_user] = _fake_user
    yield
    fapi_app.dependency_overrides.pop(get_current_user, None)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _payload() -> Dict[str, Any]:
    return {
        "source_id": 42,
        "table": "satislar",
        "metric": {
            "metric_name": "Toplam Satış",
            "agg": "SUM",
            "formula": "SUM(tutar)",
        },
        "available_columns": [
            {"name": "tutar", "type": "numeric"},
            {"name": "tarih", "type": "date"},
            {"name": "musteri_id", "type": "int"},
            {"name": "sehir", "type": "varchar"},
        ],
    }


def _llm_json_response(extra_grain: bool = True) -> str:
    body = {
        "metric_bound": [
            {
                "column": "tutar",
                "rationale": "Metrik bu kolonun toplamı.",
                "confidence": 1.0,
            }
        ],
        "related_dimensions": [
            {
                "column": "tarih",
                "rationale": "Zaman bazlı grup için.",
                "confidence": 0.95,
                "suggested_grain": "month" if extra_grain else None,
            },
            {
                "column": "sehir",
                "rationale": "Coğrafi kırılım için.",
                "confidence": 0.78,
            },
        ],
    }
    return json.dumps(body, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────

class TestColumnSuggestHappyPath:
    def test_suggest_columns_happy_path(self, client, override_auth):
        with patch(
            "app.core.llm.call_llm_api",
            return_value=_llm_json_response(),
        ), patch(
            "app.core.llm.get_active_llm",
            return_value={"model_name": "gpt-test", "provider": "openai"},
        ):
            r = client.post(
                "/api/db/smart/llm/column-suggest",
                json=_payload(),
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "metric_bound" in data
        assert "related_dimensions" in data
        assert isinstance(data["metric_bound"], list)
        assert isinstance(data["related_dimensions"], list)
        assert data["cache_hit"] is False
        assert data["model"] == "gpt-test"
        # En az birer eleman
        assert any(x["column"] == "tutar" for x in data["metric_bound"])
        assert any(x["column"] == "tarih" for x in data["related_dimensions"])


class TestMetricBoundFiltering:
    def test_metric_bound_kategori_filtering(self, client, override_auth):
        """LLM 'tutar'ı dahil etmese bile formula → metric_bound'a zorla."""
        bad_response = json.dumps({
            "metric_bound": [],  # LLM hatası: boş bıraktı
            "related_dimensions": [
                {"column": "tutar", "rationale": "yanlış kategori", "confidence": 0.5},
                {"column": "sehir", "rationale": "boyut", "confidence": 0.8},
            ],
        })
        with patch("app.core.llm.call_llm_api", return_value=bad_response), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 200
        data = r.json()
        mb_cols = [x["column"] for x in data["metric_bound"]]
        rel_cols = [x["column"] for x in data["related_dimensions"]]
        # tutar formula'da → metric_bound'a zorlanmalı
        assert "tutar" in mb_cols
        # ve related'dan dedupe edilmeli
        assert "tutar" not in rel_cols
        # sehir hâlâ related'da
        assert "sehir" in rel_cols


class TestDateGrainInference:
    def test_date_grain_inferred(self, client, override_auth):
        """Date kolonu LLM'den grain gelmese bile default 'month' atanmalı."""
        no_grain_resp = json.dumps({
            "metric_bound": [
                {"column": "tutar", "rationale": "formula", "confidence": 1.0},
            ],
            "related_dimensions": [
                {"column": "tarih", "rationale": "zaman", "confidence": 0.9},
                # grain YOK
            ],
        })
        with patch("app.core.llm.call_llm_api", return_value=no_grain_resp), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 200
        data = r.json()
        tarih_entry = next(
            (x for x in data["related_dimensions"] if x["column"] == "tarih"),
            None,
        )
        assert tarih_entry is not None
        assert tarih_entry.get("suggested_grain") in {"day", "week", "month", "quarter", "year"}

    def test_explicit_grain_preserved(self, client, override_auth):
        """LLM 'quarter' verirse korunmalı."""
        resp = json.dumps({
            "metric_bound": [{"column": "tutar", "rationale": "x", "confidence": 1.0}],
            "related_dimensions": [
                {"column": "tarih", "rationale": "y", "confidence": 0.9, "suggested_grain": "quarter"},
            ],
        })
        with patch("app.core.llm.call_llm_api", return_value=resp), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        data = r.json()
        tarih = next(x for x in data["related_dimensions"] if x["column"] == "tarih")
        assert tarih["suggested_grain"] == "quarter"


class TestCacheBehavior:
    def test_cache_hit_on_second_call(self, client, override_auth):
        """2. çağrıda cache_hit=true ve LLM tekrar çağrılmamalı."""
        # In-memory fake cache (RedisCache fallback davranışı)
        store: Dict[str, Any] = {}

        class FakeCache:
            def get(self, k):
                return store.get(k)

            def set(self, k, v, ttl=None):
                store[k] = v

        with patch.object(llm_column_service, "_get_cache", return_value=FakeCache()), \
             patch("app.core.llm.call_llm_api", return_value=_llm_json_response()) as mock_llm, \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r1 = client.post("/api/db/smart/llm/column-suggest", json=_payload())
            r2 = client.post("/api/db/smart/llm/column-suggest", json=_payload())

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["cache_hit"] is False
        assert r2.json()["cache_hit"] is True
        # LLM yalnız 1 kez çağrılmalı
        assert mock_llm.call_count == 1


class TestRedisDownFallback:
    def test_redis_down_fallback(self, client, override_auth):
        """Cache None ise endpoint hâlâ çalışmalı; cache_hit=False."""
        with patch.object(llm_column_service, "_get_cache", return_value=None), \
             patch("app.core.llm.call_llm_api", return_value=_llm_json_response()), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 200
        assert r.json()["cache_hit"] is False

    def test_cache_get_exception_swallowed(self, client, override_auth):
        """Cache.get patlasa bile endpoint çalışır."""
        class BrokenCache:
            def get(self, k):
                raise RuntimeError("redis nuked")

            def set(self, k, v, ttl=None):
                raise RuntimeError("redis nuked")

        with patch.object(llm_column_service, "_get_cache", return_value=BrokenCache()), \
             patch("app.core.llm.call_llm_api", return_value=_llm_json_response()), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 200


class TestAuth:
    def test_auth_required(self, client):
        """Authorization header yoksa 401/403."""
        r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        # FastAPI HTTPBearer credentials None → 401/403 her ikisi de kabul
        assert r.status_code in (401, 403)

    def test_user_id_missing_returns_401(self, client, fapi_app):
        """Auth override user'ı {} verirse 401."""
        from app.api.routes.auth import get_current_user
        fapi_app.dependency_overrides[get_current_user] = lambda: {}
        try:
            with patch("app.core.llm.call_llm_api", return_value=_llm_json_response()):
                r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
            assert r.status_code == 401
        finally:
            fapi_app.dependency_overrides.pop(get_current_user, None)


class TestInputValidation:
    def test_missing_metric_name(self, client, override_auth):
        bad = _payload()
        bad["metric"]["metric_name"] = ""
        r = client.post("/api/db/smart/llm/column-suggest", json=bad)
        assert r.status_code == 422

    def test_empty_columns(self, client, override_auth):
        bad = _payload()
        bad["available_columns"] = []
        r = client.post("/api/db/smart/llm/column-suggest", json=bad)
        assert r.status_code == 422

    def test_duplicate_columns(self, client, override_auth):
        bad = _payload()
        bad["available_columns"].append({"name": "tutar", "type": "numeric"})
        r = client.post("/api/db/smart/llm/column-suggest", json=bad)
        assert r.status_code == 422


class TestLLMFailure:
    def test_llm_returns_garbage_json(self, client, override_auth):
        """LLM bozuk JSON dönerse → metric_bound formula fallback ile dolu."""
        with patch("app.core.llm.call_llm_api", return_value="not a json {{["), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 200
        data = r.json()
        # tutar formula'dan geliyor
        assert any(x["column"] == "tutar" for x in data["metric_bound"])

    def test_llm_returns_code_fence_wrapped_json(self, client, override_auth):
        """LLM ```json ... ``` ile sararsa parse edilmeli."""
        resp = "```json\n" + _llm_json_response() + "\n```"
        with patch("app.core.llm.call_llm_api", return_value=resp), \
             patch("app.core.llm.get_active_llm", return_value={"model_name": "m"}):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 200
        data = r.json()
        assert any(x["column"] == "tarih" for x in data["related_dimensions"])

    def test_llm_raises_exception_returns_502(self, client, override_auth):
        with patch(
            "app.core.llm.call_llm_api",
            side_effect=RuntimeError("LLM down"),
        ):
            r = client.post("/api/db/smart/llm/column-suggest", json=_payload())
        assert r.status_code == 502


class TestServiceUnit:
    """llm_column_service'in helper'larını doğrudan test."""

    def test_columns_in_formula_match(self):
        cols = [{"name": "tutar", "type": "numeric"}, {"name": "adet", "type": "int"}]
        assert llm_column_service._columns_in_formula("SUM(tutar)", cols) == ["tutar"]
        assert llm_column_service._columns_in_formula("SUM(tutar*adet)", cols) == ["tutar", "adet"]
        assert llm_column_service._columns_in_formula(None, cols) == []
        assert llm_column_service._columns_in_formula("", cols) == []

    def test_is_date_column(self):
        assert llm_column_service._is_date_column("date")
        assert llm_column_service._is_date_column("timestamp without time zone")
        assert llm_column_service._is_date_column("datetime")
        assert not llm_column_service._is_date_column("varchar")
        assert not llm_column_service._is_date_column(None)

    def test_strip_code_fences(self):
        assert llm_column_service._strip_code_fences("```json\n{\"a\":1}\n```") == '{"a":1}'
        assert llm_column_service._strip_code_fences("  {\"a\":1}  ") == '{"a":1}'

    def test_build_cache_key_deterministic(self):
        cols = [
            {"name": "a", "type": "int"},
            {"name": "b", "type": "text"},
        ]
        k1 = llm_column_service._build_cache_key("M", "t", cols)
        # Sıra değişse de aynı key
        k2 = llm_column_service._build_cache_key("M", "t", list(reversed(cols)))
        assert k1 == k2
        assert k1.startswith("llm:column:")

    def test_suggest_columns_validation_errors(self):
        with pytest.raises(ValueError):
            llm_column_service.suggest_columns(1, "t", {}, [{"name": "a"}])
        with pytest.raises(ValueError):
            llm_column_service.suggest_columns(1, "", {"metric_name": "x"}, [{"name": "a"}])
        with pytest.raises(ValueError):
            llm_column_service.suggest_columns(1, "t", {"metric_name": "x"}, [])
