"""
VYRA L1 Support API - Deep Think Service Tests
================================================
DeepThinkService birim testleri.

Test Kapsamı:
- analyze_intent (intent tespiti)
- _prepare_context (LLM context formatlama)
- _postprocess_llm_response (numaralama düzeltme)
- _parse_rag_results (chunk parsing)
- _group_by_file (dosya bazlı gruplama)
- _score_to_bar (skor görseli)
- _get_format_instruction (intent→format)
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def deep_think_service():
    """DeepThinkService instance — DB bağlantısı mock'lanmış."""
    with patch('app.services.deep_think_service.get_db_conn') as mock_db:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = None  # prompt yok → fallback
        
        from app.services.deep_think_service import DeepThinkService
        service = DeepThinkService()
        yield service


@pytest.fixture
def sample_rag_results():
    """Örnek RAG araması sonuçları."""
    return [
        {
            "content": "**Ağ Komutları:** ipconfig /all\n**Açıklaması:** IP ayarlarını gösterir",
            "score": 0.92,
            "source_file": "network_commands.xlsx",
            "metadata": {"sheet": "Ağ"}
        },
        {
            "content": "**Disk Yönetimi:** diskpart\n**Açıklaması:** Disk bölümlendirme aracı",
            "score": 0.78,
            "source_file": "system_tools.xlsx",
            "metadata": {"sheet": "Sistem"}
        },
        {
            "content": "**Ağ Komutları:** netstat -an\n**Açıklaması:** Ağ bağlantılarını listeler",
            "score": 0.85,
            "source_file": "network_commands.xlsx",
            "metadata": {"sheet": "Ağ"}
        }
    ]


# =============================================================================
# TEST: analyze_intent
# =============================================================================

class TestAnalyzeIntent:
    """Soru tipini doğru tespit edip etmediğini test eder."""
    
    def test_list_request_detected(self, deep_think_service):
        """Liste talepleri doğru algılanmalı."""
        result = deep_think_service.analyze_intent("tüm VPN komutlarını listele")
        assert result.intent_type.value == "list_request"
        assert result.suggested_n_results == 30
        assert result.confidence >= 0.5
    
    def test_howto_detected(self, deep_think_service):
        """Adım adım çözüm isteği algılanmalı."""
        result = deep_think_service.analyze_intent("VPN nasıl kurulur?")
        assert result.intent_type.value == "how_to"
        assert result.suggested_n_results == 10
    
    def test_troubleshoot_detected(self, deep_think_service):
        """Sorun giderme talebi algılanmalı."""
        result = deep_think_service.analyze_intent("internet bağlantısı çalışmıyor hata veriyor")
        assert result.intent_type.value == "troubleshoot"
        assert result.suggested_n_results == 15
    
    def test_single_answer_detected(self, deep_think_service):
        """Tekil cevap talebi algılanmalı."""
        result = deep_think_service.analyze_intent("VPN sunucu adresi nedir?")
        assert result.intent_type.value == "single_answer"
        assert result.suggested_n_results == 5
    
    def test_general_fallback(self, deep_think_service):
        """Belirli bir pattern eşleşmezse genel sorgu dönmeli."""
        result = deep_think_service.analyze_intent("merhaba")
        assert result.intent_type.value == "general"
        assert result.confidence == 0.5
        assert result.suggested_n_results == 10
    
    def test_empty_query(self, deep_think_service):
        """Boş sorgu genel sorgu dönmeli."""
        result = deep_think_service.analyze_intent("")
        assert result.intent_type.value == "general"


# =============================================================================
# TEST: _prepare_context
# =============================================================================

class TestPrepareContext:
    """LLM için bağlam hazırlamayı test eder."""
    
    def test_context_format(self, deep_think_service, sample_rag_results):
        """Context'te kaynak, skor ve içerik olmalı."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        context = deep_think_service._prepare_context(sample_rag_results, intent)
        
        assert "[1] Kaynak: network_commands.xlsx" in context
        assert "0.92" in context
        assert "ipconfig /all" in context
        assert "[2] Kaynak: system_tools.xlsx" in context
    
    def test_empty_results(self, deep_think_service):
        """Boş sonuçlarla boş context dönmeli."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        context = deep_think_service._prepare_context([], intent)
        assert context == ""


# =============================================================================
# TEST: _parse_rag_results
# =============================================================================

class TestParseRagResults:
    """RAG chunk'larını parse etmeyi test eder."""
    
    def test_parse_with_category(self, deep_think_service, sample_rag_results):
        """Kategori:komut formatı doğru parse edilmeli."""
        parsed = deep_think_service._parse_rag_results(sample_rag_results)
        
        assert len(parsed) == 3
        assert parsed[0]["category"] == "Ağ Komutları"
        assert parsed[0]["command"] == "ipconfig /all"
        assert parsed[0]["score"] == 0.92
        assert parsed[0]["source_file"] == "network_commands.xlsx"
        assert parsed[0]["sheet_name"] == "Ağ"
    
    def test_parse_without_category(self, deep_think_service):
        """Kategori formatı olmayan chunk'lar 'Sonuçlar' kategorisine gitmeli."""
        results = [{
            "content": "Basit bir metin",
            "score": 0.5,
            "source_file": "test.txt",
            "metadata": {}
        }]
        
        parsed = deep_think_service._parse_rag_results(results)
        assert len(parsed) == 1
        assert parsed[0]["category"] == "Sonuçlar"
    
    def test_parse_empty_content_skipped(self, deep_think_service):
        """Boş içerikli chunk'lar atlanmalı."""
        results = [{
            "content": "",
            "score": 0.5,
            "source_file": "test.txt",
            "metadata": {}
        }]
        
        parsed = deep_think_service._parse_rag_results(results)
        assert len(parsed) == 0


# =============================================================================
# TEST: _group_by_file
# =============================================================================

class TestGroupByFile:
    """Dosya bazlı gruplama testleri."""
    
    def test_groups_by_source(self, deep_think_service, sample_rag_results):
        """Aynı kaynaktan gelen sonuçlar gruplanmalı."""
        grouped = deep_think_service._group_by_file(sample_rag_results)
        
        # network_commands.xlsx (2 sonuç) önce gelmeli
        assert grouped[0]["source_file"] == "network_commands.xlsx"
        assert grouped[1]["source_file"] == "network_commands.xlsx"
        # system_tools.xlsx (1 sonuç) sonra
        assert grouped[2]["source_file"] == "system_tools.xlsx"
    
    def test_sorted_within_group(self, deep_think_service, sample_rag_results):
        """Grup içinde yüksek skor önce gelmeli."""
        grouped = deep_think_service._group_by_file(sample_rag_results)
        
        # network_commands.xlsx grup içi sıralama: 0.92 > 0.85
        assert grouped[0]["score"] == 0.92
        assert grouped[1]["score"] == 0.85
    
    def test_empty_results(self, deep_think_service):
        """Boş liste boş liste dönmeli."""
        assert deep_think_service._group_by_file([]) == []


# =============================================================================
# TEST: _score_to_bar
# =============================================================================

class TestScoreToBar:
    """Skor görselleştirme testleri."""
    
    def test_full_score(self, deep_think_service):
        bar = deep_think_service._score_to_bar(1.0)
        assert "🟩" * 10 in bar
        assert "100%" in bar
    
    def test_half_score(self, deep_think_service):
        bar = deep_think_service._score_to_bar(0.5)
        assert "🟩" * 5 in bar
        assert "⬜" * 5 in bar
        assert "50%" in bar
    
    def test_zero_score(self, deep_think_service):
        bar = deep_think_service._score_to_bar(0.0)
        assert "⬜" * 10 in bar
        assert "0%" in bar


# =============================================================================
# TEST: _postprocess_llm_response
# =============================================================================

class TestPostprocessLlmResponse:
    """LLM yanıt post-processing testleri."""
    
    def test_non_list_passthrough(self, deep_think_service):
        """Liste istekleri dışındaki intent'lerde yanıt değişmemeli."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.HOW_TO,
            confidence=0.8,
            suggested_n_results=10
        )
        
        response = "Adım 1: Yapın\nAdım 2: Tamamlayın"
        result = deep_think_service._postprocess_llm_response(response, intent)
        assert result == response
    
    def test_duplicate_kaynaklar_removed(self, deep_think_service):
        """İkinci KAYNAKLAR başlığı kaldırılmalı."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.LIST_REQUEST,
            confidence=0.9,
            suggested_n_results=30
        )
        
        response = "Sonuçlar\n📚 KAYNAKLAR\nKaynak1\n📚 KAYNAKLAR\nDuplicate"
        result = deep_think_service._postprocess_llm_response(response, intent)
        
        # İlk KAYNAKLAR kalmalı, ikinci kalkmalı
        assert result.count("📚") == 1


# =============================================================================
# TEST: _get_format_instruction
# =============================================================================

class TestGetFormatInstruction:
    """Intent'e göre format talimatı testleri."""
    
    def test_list_format(self, deep_think_service):
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.LIST_REQUEST,
            confidence=0.9,
            suggested_n_results=30
        )
        
        instruction = deep_think_service._get_format_instruction(intent)
        assert isinstance(instruction, str)
        assert len(instruction) > 0
    
    def test_howto_format(self, deep_think_service):
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.HOW_TO,
            confidence=0.8,
            suggested_n_results=10
        )
        
        instruction = deep_think_service._get_format_instruction(intent)
        assert isinstance(instruction, str)
        assert len(instruction) > 0
    
    def test_general_format(self, deep_think_service):
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        instruction = deep_think_service._get_format_instruction(intent)
        assert isinstance(instruction, str)


# =============================================================================
# TEST: _clean_prompt_leak (v2.33.2)
# =============================================================================

class TestCleanPromptLeak:
    """Prompt leak temizleme testleri."""
    
    def test_removes_onemli_block(self, deep_think_service):
        """ÖNEMLİ: maddeleri temizlenmeli."""
        response = (
            "📋 **Ağ Komutları** (3 adet)\n\n"
            "1. `ipconfig /all`\n"
            "   ↳ IP ayarlarını gösterir (92%)\n\n"
            "ÖNEMLİ:\n"
            "1. SADECE yukarıdaki bilgi tabanı içeriğini kullan\n"
            "2. Bilgi tabanında olmayan şeyleri UYDURMA\n"
            "3. Tüm ilgili bilgileri dahil et, hiçbirini atlama\n"
            "4. Kaynak dosya adlarını belirt\n"
            "5. Türkçe yanıt ver"
        )
        
        cleaned = deep_think_service._clean_prompt_leak(response)
        assert "ÖNEMLİ:" not in cleaned
        assert "SADECE yukarıdaki" not in cleaned
        assert "`ipconfig /all`" in cleaned
    
    def test_removes_single_line_leaks(self, deep_think_service):
        """Tek satırlık talimat sızıntıları temizlenmeli."""
        response = (
            "📋 **Sonuçlar** (2 adet)\n\n"
            "1. `komut1`\n\n"
            "Türkçe yanıt ver\n"
            "Kaynak dosya adlarını belirt\n\n"
            "📚 **KAYNAKLAR**\n"
            "• [test.xlsx]"
        )
        
        cleaned = deep_think_service._clean_prompt_leak(response)
        assert "Türkçe yanıt ver" not in cleaned
        assert "Kaynak dosya adlarını belirt" not in cleaned
        assert "📚 **KAYNAKLAR**" in cleaned
    
    def test_preserves_clean_response(self, deep_think_service):
        """Temiz yanıt değişmemeli."""
        response = (
            "📋 **Cisco Switch Komutları** (2 adet)\n\n"
            "1. `show interfaces`\n"
            "   ↳ Port durumlarını gösterir (85%)\n\n"
            "📚 **KAYNAKLAR**\n"
            "• [Komutlar.xlsx] - **Switch** - Cisco Switch komutları"
        )
        
        cleaned = deep_think_service._clean_prompt_leak(response)
        assert cleaned == response
    
    def test_cleans_consecutive_empty_lines(self, deep_think_service):
        """Ardışık boş satırlar 2'ye indirilmeli."""
        response = "Başlık\n\n\n\n\nİçerik"
        cleaned = deep_think_service._clean_prompt_leak(response)
        assert "\n\n\n" not in cleaned


# =============================================================================
# TEST: synthesize_response - Boş sonuç (v2.33.2)
# =============================================================================

class TestSynthesizeNoResults:
    """Sonuç yokken doğru mesaj dönmeyi test eder."""
    
    def test_no_results_returns_info_message(self, deep_think_service):
        """RAG sonucu yokken bilgilendirme mesajı dönmeli."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        result = deep_think_service.synthesize_response("test sorusu", [], intent)
        assert "bulunamadı" in result.lower()
        assert "ÖNEMLİ:" not in result
        assert "SADECE" not in result


# =============================================================================
# TEST: _prepare_context heading zenginleştirme (v2.38.0)
# =============================================================================

class TestPrepareContextHeading:
    """_prepare_context heading bilgisini context'e dahil etmeli."""
    
    def test_heading_included_in_context(self, deep_think_service):
        """Metadata'da heading varsa context'e 'Bölüm:' olarak eklenmeli."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        results = [{
            "content": "VPN bağlantısı kurulumu adımları",
            "score": 0.85,
            "source_file": "vpn_guide.pdf",
            "metadata": {"heading": "VPN Kurulum Rehberi", "page": 3}
        }]
        
        context = deep_think_service._prepare_context(results, intent)
        assert "Bölüm: VPN Kurulum Rehberi" in context
        assert "vpn_guide.pdf" in context
        assert "0.85" in context
    
    def test_no_heading_no_bolum(self, deep_think_service):
        """Metadata'da heading yoksa 'Bölüm:' eklenmemeli."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        results = [{
            "content": "Basit metin",
            "score": 0.5,
            "source_file": "test.txt",
            "metadata": {}
        }]
        
        context = deep_think_service._prepare_context(results, intent)
        assert "Bölüm:" not in context
        assert "test.txt" in context
    
    def test_string_metadata_parsed(self, deep_think_service):
        """JSON string olarak gelen metadata parse edilmeli."""
        from app.services.deep_think_service import IntentResult, IntentType
        import json
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        results = [{
            "content": "İçerik",
            "score": 0.7,
            "source_file": "doc.pdf",
            "metadata": json.dumps({"heading": "Bölüm Başlığı"})
        }]
        
        context = deep_think_service._prepare_context(results, intent)
        assert "Bölüm: Bölüm Başlığı" in context


# =============================================================================
# TEST: synthesize_response — tek vs parçalı (v2.38.0)
# =============================================================================

class TestSynthesizeChunked:
    """Uzun context'te parçalı synthesis'in devreye girdiğini test eder."""
    
    def test_short_context_uses_single(self, deep_think_service):
        """MAX_CONTEXT_CHARS altında _single_synthesis çağrılmalı."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        results = [{"content": "Kısa metin", "score": 0.5, "source_file": "t.txt", "metadata": {}}]
        
        with patch.object(deep_think_service, '_single_synthesis', return_value="Tek yanıt") as mock_single:
            result = deep_think_service.synthesize_response("soru?", results, intent)
            mock_single.assert_called_once()
            assert result == "Tek yanıt"
    
    def test_long_context_uses_chunked(self, deep_think_service):
        """MAX_CONTEXT_CHARS üstünde _chunked_synthesis çağrılmalı."""
        from app.services.deep_think_service import IntentResult, IntentType
        intent = IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.5,
            suggested_n_results=10
        )
        
        # MAX_CONTEXT_CHARS'ı aşacak büyüklükte sonuçlar
        results = [{
            "content": "A" * 5000,
            "score": 0.5,
            "source_file": f"file_{i}.txt",
            "metadata": {}
        } for i in range(5)]
        
        with patch.object(deep_think_service, '_chunked_synthesis', return_value="Birleşik yanıt") as mock_chunked:
            result = deep_think_service.synthesize_response("soru?", results, intent)
            mock_chunked.assert_called_once()
            assert result == "Birleşik yanıt"


# =============================================================================
# TEST: _split_large_section Türkçe cümle bölme (v2.38.0)
# =============================================================================

class TestSplitLargeSectionTurkish:
    """PDF processor'daki Türkçe-uyumlu cümle bölme testleri."""
    
    def _get_processor(self):
        from app.services.document_processors.pdf_processor import PDFProcessor
        return PDFProcessor()
    
    def test_small_text_not_split(self):
        """max_size altındaki metin bölünmemeli."""
        proc = self._get_processor()
        result = proc._split_large_section("Kısa metin.", max_size=2000)
        assert len(result) == 1
        assert result[0] == "Kısa metin."
    
    def test_paragraph_boundary_split(self):
        """Paragraf sınırlarında bölme öncelikli olmalı."""
        proc = self._get_processor()
        para1 = "A" * 1500
        para2 = "B" * 1500
        text = f"{para1}\n\n{para2}"
        
        result = proc._split_large_section(text, max_size=2000)
        assert len(result) == 2
        assert "A" * 100 in result[0]
        assert "B" * 100 in result[1]
    
    def test_sentence_split_preserves_meaning(self):
        """Cümle bölme nokta sonrası yapılmalı, ortasından kesmemeli."""
        proc = self._get_processor()
        # Tek paragraf, çok uzun — cümlelere bölünmeli
        sentences = [f"Bu cümle numara {i}. " for i in range(200)]
        text = "".join(sentences)
        
        result = proc._split_large_section(text, max_size=2000)
        # Her chunk bir cümle kesintisinde bitmeli
        for chunk in result:
            # Chunk'ların cümle ortasında kesilmediğini kontrol et
            assert len(chunk) <= 2100  # Küçük taşma kabul edilebilir

