"""
VYRA - Answer Merger Testleri
================================
HYBRID intent'te DB + RAG sonuçlarının birleştirilmesi testleri.

Version: 2.58.0
"""

import pytest
from unittest.mock import patch, MagicMock


def _make_hybrid_result(db_results=None, sql="SELECT 1", source_db="TestDB"):
    """Test HybridResult nesnesi oluşturur."""
    result = MagicMock()
    result.db_results = db_results or [{"id": 1, "name": "Test"}]
    result.sql_executed = sql
    result.source_db = source_db
    result.db_error = None
    result.elapsed_ms = 50.0
    return result


def _make_intent(intent_type="hybrid"):
    """Test IntentResult nesnesi oluşturur."""
    intent = MagicMock()
    intent.intent_type = MagicMock()
    intent.intent_type.value = intent_type
    return intent


def _create_service():
    """DeepThinkService'i init atlanarak oluşturur."""
    from app.services.deep_think_service import DeepThinkService
    svc = object.__new__(DeepThinkService)
    svc._synthesis_prompt = "Test synthesis prompt"
    return svc


class TestMergeHybridAnswer:
    """Answer Merger metodu testleri."""

    def test_merge_returns_llm_response(self):
        """LLM'den gelen yanıtı döndürür."""
        service = _create_service()
        
        with patch('app.services.deep_think_service.call_llm_api') as mock_llm:
            mock_llm.return_value = "## Birleştirilmiş Sonuç\nDB ve doküman bilgileri."
            
            result = service._merge_hybrid_answer(
                query="Toplam sipariş ne kadar?",
                hybrid_result=_make_hybrid_result(),
                rag_results=[{"content": "Sipariş prosedürü...", "source_file": "manual.pdf"}],
                intent=_make_intent(),
            )
            
            assert len(result) > 0
            mock_llm.assert_called_once()

    def test_merge_with_empty_rag(self):
        """RAG sonucu boş olsa da çalışır."""
        service = _create_service()
        
        with patch('app.services.deep_think_service.call_llm_api') as mock_llm:
            mock_llm.return_value = "Veritabanından sonuçlar burada."
            
            result = service._merge_hybrid_answer(
                query="Kaç kullanıcı var?",
                hybrid_result=_make_hybrid_result(),
                rag_results=[],
                intent=_make_intent(),
            )
            
            assert len(result) > 0

    def test_merge_with_empty_db(self):
        """DB sonucu boş olsa da çalışır."""
        service = _create_service()
        
        with patch('app.services.deep_think_service.call_llm_api') as mock_llm:
            mock_llm.return_value = "Doküman bilgileri burada."
            
            result = service._merge_hybrid_answer(
                query="Politika nedir?",
                hybrid_result=_make_hybrid_result(db_results=[]),
                rag_results=[{"content": "Politika detayları...", "source_file": "policy.pdf"}],
                intent=_make_intent(),
            )
            
            assert len(result) > 0

    def test_merge_fallback_on_llm_error(self):
        """LLM hatası olursa fallback kullanılır."""
        service = _create_service()
        service._synthesize_hybrid = MagicMock(return_value="DB sonuçları burada")
        
        with patch('app.services.deep_think_service.call_llm_api') as mock_llm:
            mock_llm.side_effect = Exception("LLM timeout")
            
            result = service._merge_hybrid_answer(
                query="Test sorgusu",
                hybrid_result=_make_hybrid_result(),
                rag_results=[{"content": "Doküman", "source_file": "doc.pdf"}],
                intent=_make_intent(),
            )
            
            assert "DB sonuçları" in result

    def test_merge_prompt_contains_both_sources(self):
        """LLM prompt'u hem DB hem RAG'dan bilgi içerir."""
        service = _create_service()
        
        with patch('app.services.deep_think_service.call_llm_api') as mock_llm:
            mock_llm.return_value = "Birleşik yanıt"
            
            service._merge_hybrid_answer(
                query="Müşteri bilgileri",
                hybrid_result=_make_hybrid_result(
                    db_results=[{"name": "Ahmet"}],
                    source_db="CRM_DB"
                ),
                rag_results=[{"content": "CRM prosedürü", "source_file": "crm.pdf"}],
                intent=_make_intent(),
            )
            
            call_args = mock_llm.call_args[0][0]
            user_msg = call_args[1]["content"]
            assert "CRM_DB" in user_msg
            assert "CRM prosedürü" in user_msg
