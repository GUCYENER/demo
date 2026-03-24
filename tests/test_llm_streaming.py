"""
VYRA L1 Support API - LLM Streaming Tests
==========================================
call_llm_api_stream ve DeepThinkService.process_stream birim testleri.

🆕 v2.50.0: Streaming pipeline test kapsamı.

Test Kapsamı:
- call_llm_api_stream: Token yield, timeout, config hatası
- process_stream: Cache hit, RAG sonuç, token yield, done event
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_llm_config():
    """Örnek LLM konfigürasyonu."""
    return {
        "provider": "corpix",
        "model_name": "test-model",
        "api_url": "http://localhost:8080/v1/chat/completions",
        "api_token": "test-token",
        "temperature": 0.7,
        "top_p": 0.9,
        "timeout_seconds": 30
    }


@pytest.fixture
def mock_sse_response():
    """Örnek SSE streaming response."""
    lines = [
        b'data: {"choices":[{"delta":{"content":"Merhaba"}}]}',
        b'data: {"choices":[{"delta":{"content":", "}}]}',
        b'data: {"choices":[{"delta":{"content":"ben"}}]}',
        b'data: {"choices":[{"delta":{"content":" VYRA"}}]}',
        b'data: [DONE]',
    ]
    return lines


@pytest.fixture
def deep_think_service():
    """DeepThinkService instance — DB bağlantısı mock'lanmış."""
    with patch("app.services.deep_think_service.get_db_conn") as mock_db:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor
        mock_db.return_value = mock_conn

        from app.services.deep_think_service import DeepThinkService
        service = DeepThinkService()
        return service


# =============================================================================
# TEST: call_llm_api_stream
# =============================================================================

class TestCallLlmApiStream:
    """Streaming LLM API çağrısı testleri."""

    @patch("app.core.llm.requests.post")
    @patch("app.core.llm.get_active_llm")
    def test_yields_tokens(self, mock_get_llm, mock_post, mock_llm_config, mock_sse_response):
        """Token'lar doğru yield edilmeli."""
        mock_get_llm.return_value = mock_llm_config

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_lines.return_value = iter(mock_sse_response)
        mock_post.return_value = mock_response

        from app.core.llm import call_llm_api_stream

        messages = [{"role": "user", "content": "Merhaba"}]
        tokens = list(call_llm_api_stream(messages))

        assert tokens == ["Merhaba", ", ", "ben", " VYRA"]
        assert "".join(tokens) == "Merhaba, ben VYRA"

    @patch("app.core.llm.get_active_llm")
    def test_no_config_raises_error(self, mock_get_llm):
        """LLM config yoksa LLMConfigError fırlatmalı."""
        mock_get_llm.return_value = None

        from app.core.llm import call_llm_api_stream, LLMConfigError

        with pytest.raises(LLMConfigError):
            list(call_llm_api_stream([{"role": "user", "content": "test"}]))

    @patch("app.core.llm.requests.post")
    @patch("app.core.llm.get_active_llm")
    def test_timeout_raises_connection_error(self, mock_get_llm, mock_post, mock_llm_config):
        """Timeout durumunda LLMConnectionError fırlatmalı."""
        import requests

        mock_get_llm.return_value = mock_llm_config
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")

        from app.core.llm import call_llm_api_stream, LLMConnectionError

        with pytest.raises(LLMConnectionError):
            list(call_llm_api_stream([{"role": "user", "content": "test"}]))

    @patch("app.core.llm.requests.post")
    @patch("app.core.llm.get_active_llm")
    def test_empty_delta_skipped(self, mock_get_llm, mock_post, mock_llm_config):
        """Boş delta token'ları atlanmalı."""
        mock_get_llm.return_value = mock_llm_config

        lines = [
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            b'data: {"choices":[{"delta":{"content":"OK"}}]}',
            b'data: {"choices":[{"delta":{}}]}',
            b'data: [DONE]',
        ]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_lines.return_value = iter(lines)
        mock_post.return_value = mock_response

        from app.core.llm import call_llm_api_stream

        tokens = list(call_llm_api_stream([{"role": "user", "content": "test"}]))
        assert tokens == ["OK"]

    @patch("app.core.llm.requests.post")
    @patch("app.core.llm.get_active_llm")
    def test_stream_true_in_payload(self, mock_get_llm, mock_post, mock_llm_config):
        """Payload'da stream=True olmalı."""
        mock_get_llm.return_value = mock_llm_config

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_lines.return_value = iter([b'data: [DONE]'])
        mock_post.return_value = mock_response

        from app.core.llm import call_llm_api_stream

        list(call_llm_api_stream([{"role": "user", "content": "test"}]))

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["stream"] is True


# =============================================================================
# TEST: DeepThinkService.process_stream
# =============================================================================

class TestProcessStream:
    """Deep Think streaming pipeline testleri."""

    @patch("app.core.cache.cache_service")
    def test_cache_hit_yields_cached_event(self, mock_cache, deep_think_service):
        """Cache hit durumunda 'cached' event yield etmeli."""
        mock_result = MagicMock()
        mock_result.synthesized_response = "Cached yanıt"
        mock_result.intent.intent_type.value = "general"
        mock_result.sources = ["test.pdf"]
        mock_result.rag_result_count = 3
        mock_result.best_score = 0.85
        mock_result.image_ids = []
        mock_result.heading_images = {}
        mock_cache.deep_think.get.return_value = mock_result

        events = list(deep_think_service.process_stream("VPN bağlantı sorunu çözümü nedir", 1))

        assert len(events) == 1
        assert events[0]["type"] == "cached"
        assert events[0]["data"]["content"] == "Cached yanıt"

    @patch("app.core.cache.cache_service")
    def test_no_results_yields_done(self, mock_cache, deep_think_service):
        """RAG sonuç yoksa done event döndürmeli."""
        mock_cache.deep_think.get.return_value = None

        with patch.object(deep_think_service, "expanded_retrieval", return_value=[]):
            events = list(deep_think_service.process_stream("bilinmeyen soru", 1))

        event_types = [e["type"] for e in events]
        assert "rag_complete" in event_types
        assert "done" in event_types

        done_event = [e for e in events if e["type"] == "done"][0]
        assert "bulunamadı" in done_event["data"]["content"]
