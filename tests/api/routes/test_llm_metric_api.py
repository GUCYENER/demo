"""VYRA v3.37.0 — LLM Metric Suggest API Testleri.

Endpoint: POST /api/db/smart/llm/metric-suggest

Test kapsami:
    - test_suggest_metrics_happy_path: mock LLM -> 200 + valid schema
    - test_suggest_metrics_cache_hit: 2. cagri cache_hit=True
    - test_suggest_metrics_redis_down: Redis exception -> uncached passthrough 200
    - test_suggest_metrics_llm_timeout: LLMConnectionError -> 503 + clear error
    - test_suggest_metrics_invalid_columns: bos columns -> 400
    - test_suggest_metrics_auth_required: unauth -> 401
    - test_suggest_metrics_rate_limit: 11. cagri -> 429

Coverage hedef: yeni kod >= 85%
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# -------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------

@pytest.fixture
def metric_client():
    """LLM metric API testleri icin TestClient — DB init atlanir."""
    with patch("app.api.main.init_db"):
        from app.api.main import create_app
        app = create_app()
        client = TestClient(app)
        yield client


@pytest.fixture
def sample_user_payload():
    return {
        "id": 1,
        "username": "tester",
        "email": "tester@vyra.local",
        "full_name": "Test User",
        "role": "user",
        "role_id": 2,
        "is_admin": False,
        "is_approved": True,
        "company_id": 1,
    }


@pytest.fixture
def auth_headers_for(sample_user_payload):
    """Gercek JWT token uret — auth.create_access_token kullanir."""
    from app.api.routes.auth import create_access_token
    token = create_access_token(sample_user_payload)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def valid_request_body():
    return {
        "source_id": 42,
        "table": "satislar",
        "columns": [
            {"name": "tutar", "type": "numeric"},
            {"name": "tarih", "type": "date"},
            {"name": "musteri_id", "type": "int"},
        ],
        "user_intent": "aylik satis raporu",
    }


@pytest.fixture
def fake_llm_json_response():
    """LLM'nin gercekci JSON cevabi (string)."""
    return json.dumps({
        "suggestions": [
            {
                "metric_name": "Toplam Satis",
                "agg": "SUM",
                "formula": "SUM(tutar)",
                "rationale": "tutar numeric -> SUM uygun.",
                "confidence": 0.92,
            },
            {
                "metric_name": "Musteri Basina Ortalama",
                "agg": "AVG",
                "formula": "SUM(tutar) / COUNT(DISTINCT musteri_id)",
                "rationale": "iki kolon bileskesi",
                "confidence": 0.78,
            },
        ]
    }, ensure_ascii=False)


@pytest.fixture
def mock_user_db(sample_user_payload):
    """get_current_user'in DB sorgusunu mock'lar — gercek user dondurur."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = sample_user_payload
    mock_conn.cursor.return_value = mock_cursor

    @contextmanager_factory
    def fake_ctx():
        yield mock_conn

    return fake_ctx


def contextmanager_factory(func):
    """Yardimci — context manager olusturucu."""
    from contextlib import contextmanager
    return contextmanager(func)


@pytest.fixture
def patch_auth_db(sample_user_payload):
    """auth.get_current_user'in get_db_context cagrisini mock'lar."""
    from contextlib import contextmanager

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = sample_user_payload
    mock_conn.cursor.return_value = mock_cursor

    @contextmanager
    def fake_ctx():
        yield mock_conn

    with patch("app.api.routes.auth.get_db_context", fake_ctx):
        yield mock_conn


@pytest.fixture(autouse=True)
def clear_service_cache():
    """Her test oncesi servis-level cache singleton'i sifirla."""
    from app.services import llm_metric_service
    llm_metric_service._CACHE = None
    llm_metric_service._CACHE_INIT_FAILED = False
    yield
    llm_metric_service._CACHE = None
    llm_metric_service._CACHE_INIT_FAILED = False


# -------------------------------------------------------------
# Tests
# -------------------------------------------------------------

class TestMetricSuggestHappyPath:
    """200 OK + valid schema."""

    def test_suggest_metrics_happy_path(
        self,
        metric_client,
        auth_headers_for,
        valid_request_body,
        fake_llm_json_response,
        patch_auth_db,
    ):
        # LLM cagrisini mock'la, cache'i bypass et (None doner)
        with patch(
            "app.services.llm_metric_service.call_llm_api",
            return_value=fake_llm_json_response,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value={"provider": "openai", "model_name": "gpt-4o-mini"},
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ):
            resp = metric_client.post(
                "/api/db/smart/llm/metric-suggest",
                headers=auth_headers_for,
                json=valid_request_body,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "suggestions" in data
        assert "cache_hit" in data
        assert "model" in data
        assert data["cache_hit"] is False
        assert data["model"] == "openai/gpt-4o-mini"
        assert isinstance(data["suggestions"], list)
        assert len(data["suggestions"]) == 2
        first = data["suggestions"][0]
        assert first["metric_name"] == "Toplam Satis"
        assert first["agg"] == "SUM"
        assert first["formula"] == "SUM(tutar)"
        assert 0.0 <= first["confidence"] <= 1.0


class TestMetricSuggestCache:
    """Cache hit/miss davranisi."""

    def test_suggest_metrics_cache_hit(
        self,
        metric_client,
        auth_headers_for,
        valid_request_body,
        fake_llm_json_response,
        patch_auth_db,
    ):
        # Fake in-memory cache backend (RedisCache yerine)
        from app.services import llm_metric_service

        class FakeCache:
            def __init__(self):
                self.store = {}

            def get_raw(self, key):
                return self.store.get(key)

            def set_raw(self, key, value, ttl=None):
                self.store[key] = value

        fake_cache = FakeCache()

        call_counter = {"n": 0}

        def counted_llm(messages, temperature=None):
            call_counter["n"] += 1
            return fake_llm_json_response

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            side_effect=counted_llm,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value={"provider": "openai", "model_name": "gpt-4o-mini"},
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=fake_cache,
        ):
            # 1. cagri — cache miss, LLM cagrilir
            resp1 = metric_client.post(
                "/api/db/smart/llm/metric-suggest",
                headers=auth_headers_for,
                json=valid_request_body,
            )
            assert resp1.status_code == 200
            assert resp1.json()["cache_hit"] is False
            assert call_counter["n"] == 1

            # 2. cagri (ayni payload) — cache hit, LLM cagrilmaz
            resp2 = metric_client.post(
                "/api/db/smart/llm/metric-suggest",
                headers=auth_headers_for,
                json=valid_request_body,
            )
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2["cache_hit"] is True
            assert call_counter["n"] == 1, "LLM cache hit'te tekrar cagrilmamali"
            # Suggestions yine donmeli
            assert len(data2["suggestions"]) == 2


class TestMetricSuggestRedisDown:
    """Redis dustugunde graceful fallback — uncached passthrough."""

    def test_suggest_metrics_redis_down(
        self,
        metric_client,
        auth_headers_for,
        valid_request_body,
        fake_llm_json_response,
        patch_auth_db,
    ):
        # _get_cache None doner (Redis init failed senaryosu)
        with patch(
            "app.services.llm_metric_service.call_llm_api",
            return_value=fake_llm_json_response,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value={"provider": "openai", "model_name": "gpt-4o-mini"},
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ):
            resp = metric_client.post(
                "/api/db/smart/llm/metric-suggest",
                headers=auth_headers_for,
                json=valid_request_body,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["cache_hit"] is False
        # Redis down olsa bile suggestions donmeli
        assert len(data["suggestions"]) >= 1


class TestMetricSuggestLLMErrors:
    """LLM hata akisi."""

    def test_suggest_metrics_llm_timeout(
        self,
        metric_client,
        auth_headers_for,
        valid_request_body,
        patch_auth_db,
    ):
        from app.core.llm import LLMConnectionError

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            side_effect=LLMConnectionError("LLM timeout 60s"),
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ):
            resp = metric_client.post(
                "/api/db/smart/llm/metric-suggest",
                headers=auth_headers_for,
                json=valid_request_body,
            )

        assert resp.status_code == 503
        body = resp.json()
        assert "detail" in body
        assert "LLM" in body["detail"] or "ulasilamadi" in body["detail"].lower()


class TestMetricSuggestInvalidColumns:
    """Bos columns -> 400."""

    def test_suggest_metrics_invalid_columns(
        self,
        metric_client,
        auth_headers_for,
        patch_auth_db,
    ):
        body = {
            "source_id": 42,
            "table": "satislar",
            "columns": [],
            "user_intent": "test",
        }
        resp = metric_client.post(
            "/api/db/smart/llm/metric-suggest",
            headers=auth_headers_for,
            json=body,
        )
        # Pydantic min_length veya endpoint 400'u — her ikisi de kabul
        assert resp.status_code == 400, resp.text


class TestMetricSuggestAuth:
    """Auth eksikse 401/403."""

    def test_suggest_metrics_auth_required(self, metric_client, valid_request_body):
        # Authorization header'siz cagri
        resp = metric_client.post(
            "/api/db/smart/llm/metric-suggest",
            json=valid_request_body,
        )
        # HTTPBearer no-creds varsayilan 403; auth.get_current_user da 401 firlatabilir.
        assert resp.status_code in (401, 403), resp.text


class TestMetricSuggestRateLimit:
    """Rate limit — 10/minute. 11. cagri 429 donmeli."""

    def test_suggest_metrics_rate_limit(
        self,
        metric_client,
        auth_headers_for,
        valid_request_body,
        fake_llm_json_response,
        patch_auth_db,
    ):
        # Onceki testlerde harcanan rate limit slot'larini sifirla.
        # SlowAPI limiter in-memory storage'i reset edilir.
        from app.core.rate_limiter import limiter
        try:
            limiter.reset()
        except Exception:
            # storage'da reset yoksa, dahili dict'i temizle
            try:
                limiter._storage.storage.clear()  # type: ignore[attr-defined]
            except Exception:
                pass

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            return_value=fake_llm_json_response,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value={"provider": "openai", "model_name": "gpt-4o-mini"},
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ):
            statuses = []
            for i in range(12):
                # Her cagri farkli body — cache hit'i devre disi birak (table degisiyor)
                body = dict(valid_request_body)
                body["table"] = f"satislar_{i}"
                resp = metric_client.post(
                    "/api/db/smart/llm/metric-suggest",
                    headers=auth_headers_for,
                    json=body,
                )
                statuses.append(resp.status_code)

        # Ilk 10 cagri 200, 11+ 429
        assert statuses[:10].count(200) == 10, f"Ilk 10 cagri 200 olmali, statuses={statuses}"
        assert 429 in statuses[10:], f"11. cagridan sonra rate limit (429) beklenir, statuses={statuses}"


# -------------------------------------------------------------
# Service-level unit testleri — coverage tamamlama
# -------------------------------------------------------------

class TestServiceUnit:
    """llm_metric_service.suggest_metrics dogrudan unit testleri."""

    def test_empty_columns_returns_empty(self):
        from app.services.llm_metric_service import suggest_metrics
        result = suggest_metrics(
            source_id=1,
            table="t",
            columns=[],
            user_intent=None,
        )
        assert result["suggestions"] == []
        assert result["cache_hit"] is False

    def test_invalid_json_response_raises(self):
        from app.services.llm_metric_service import suggest_metrics
        from app.core.llm import LLMResponseError

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            return_value="bu valid json degil!!!",
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value=None,
        ):
            with pytest.raises(LLMResponseError):
                suggest_metrics(
                    source_id=1,
                    table="t",
                    columns=[{"name": "a", "type": "int"}],
                    user_intent="x",
                )

    def test_invalid_suggestions_filtered(self):
        """Bozuk suggestion item'lar filtrelenir."""
        from app.services.llm_metric_service import suggest_metrics

        bad_response = json.dumps({
            "suggestions": [
                # Valid
                {"metric_name": "Toplam", "agg": "SUM", "formula": "SUM(a)",
                 "rationale": "ok", "confidence": 0.9},
                # Invalid: bos metric_name
                {"metric_name": "", "agg": "SUM", "formula": "SUM(a)",
                 "rationale": "", "confidence": 0.5},
                # Invalid: bilinmeyen agg
                {"metric_name": "X", "agg": "FOOBAR", "formula": "FOOBAR(a)",
                 "rationale": "", "confidence": 0.5},
                # Invalid: dict degil
                "not a dict",
                # Confidence clamp testi (>1)
                {"metric_name": "Sayim", "agg": "COUNT", "formula": "COUNT(*)",
                 "rationale": "", "confidence": 5.0},
                # Confidence clamp testi (<0)
                {"metric_name": "Min", "agg": "MIN", "formula": "MIN(a)",
                 "rationale": "", "confidence": -1.0},
            ]
        })

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            return_value=bad_response,
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value={"provider": "openai", "model_name": "gpt-4"},
        ):
            result = suggest_metrics(
                source_id=1,
                table="t",
                columns=[{"name": "a", "type": "int"}],
                user_intent=None,
            )

        # MAX_SUGGESTIONS=5 kapsami: ilk 5 item validate edilir, sonrasi atilir.
        # Item sirasi (validate-loop): valid Toplam -> skip(bos) -> skip(agg) -> skip(non-dict)
        # -> Sayim (clamp 5.0 -> 1.0). Min item'i 6. siradadir, slice'a girmez.
        names = [s["metric_name"] for s in result["suggestions"]]
        assert "Toplam" in names
        assert "Sayim" in names
        # Clamping kontrol: tum confidence 0..1 aralinda
        for s in result["suggestions"]:
            assert 0.0 <= s["confidence"] <= 1.0
        # Sayim icin clamp 5.0 -> 1.0
        sayim = next(s for s in result["suggestions"] if s["metric_name"] == "Sayim")
        assert sayim["confidence"] == 1.0

    def test_extract_json_with_code_fence(self):
        """LLM cevabi ```json fence ile sarili olabilir."""
        from app.services.llm_metric_service import _extract_json_obj
        s = "```json\n{\"suggestions\": [{\"a\": 1}]}\n```"
        obj = _extract_json_obj(s)
        assert obj is not None
        assert obj.get("suggestions") == [{"a": 1}]

    def test_extract_json_with_prose_prefix(self):
        """LLM cevabi prose + JSON karisik olabilir."""
        from app.services.llm_metric_service import _extract_json_obj
        s = "Iste sonuc: {\"suggestions\": []}"
        obj = _extract_json_obj(s)
        assert obj is not None
        assert obj.get("suggestions") == []

    def test_extract_json_returns_none_for_invalid(self):
        from app.services.llm_metric_service import _extract_json_obj
        assert _extract_json_obj("") is None
        assert _extract_json_obj("hicbir json yok") is None

    def test_cache_key_changes_with_intent(self):
        from app.services.llm_metric_service import _make_cache_key
        cols = [{"name": "a", "type": "int"}]
        k1 = _make_cache_key(1, "t", cols, None)
        k2 = _make_cache_key(1, "t", cols, "aylik")
        k3 = _make_cache_key(1, "t", cols, "haftalik")
        assert k1 != k2
        assert k2 != k3

    def test_cache_singleton_lazy_init(self):
        """_get_cache lazy singleton — Redis kurulamazsa None doner."""
        from app.services import llm_metric_service

        # Reset
        llm_metric_service._CACHE = None
        llm_metric_service._CACHE_INIT_FAILED = False

        # RedisCache'i exception firlatacak sekilde mock'la
        with patch("app.core.redis_cache.RedisCache", side_effect=Exception("redis off")):
            cache = llm_metric_service._get_cache()
            assert cache is None
            assert llm_metric_service._CACHE_INIT_FAILED is True

        # 2. cagri da None doner (cached failure)
        cache2 = llm_metric_service._get_cache()
        assert cache2 is None

    def test_active_llm_none_model_label_unknown(self):
        """get_active_llm None donerse model label 'unknown' kalir."""
        from app.services.llm_metric_service import suggest_metrics

        ok_response = json.dumps({
            "suggestions": [
                {"metric_name": "A", "agg": "SUM", "formula": "SUM(x)",
                 "rationale": "", "confidence": 0.5}
            ]
        })

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            return_value=ok_response,
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value=None,
        ):
            result = suggest_metrics(
                source_id=1,
                table="t",
                columns=[{"name": "x", "type": "int"}],
                user_intent=None,
            )

        assert result["model"] == "unknown"

    def test_unexpected_llm_error_wrapped(self):
        """Beklenmeyen exception LLMConnectionError'a wrap edilir."""
        from app.services.llm_metric_service import suggest_metrics
        from app.core.llm import LLMConnectionError

        with patch(
            "app.services.llm_metric_service.call_llm_api",
            side_effect=RuntimeError("garip hata"),
        ), patch(
            "app.services.llm_metric_service._get_cache",
            return_value=None,
        ), patch(
            "app.services.llm_metric_service.get_active_llm",
            return_value=None,
        ):
            with pytest.raises(LLMConnectionError):
                suggest_metrics(
                    source_id=1,
                    table="t",
                    columns=[{"name": "x", "type": "int"}],
                    user_intent=None,
                )
