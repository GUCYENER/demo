"""
VYRA - Enrichment-Aware Routing & Hallucination Guard Tests
=============================================================
v3.1.0: Gap kapatma testleri

Coverage:
- Türkçe iş adı ile tablo eşleştirme
- Admin label ile tablo eşleştirme
- Schema context enrichment entegrasyonu
- LLM context formatında Türkçe açıklama
- Halüsinasyon doğrulaması (3 katman)
"""

from unittest.mock import patch, MagicMock


# =============================================================================
# TEST: match_template_query() — Enrichment Alias Eşleştirme
# =============================================================================

class TestEnrichmentTableMatching:
    """Türkçe iş adı ile tablo eşleştirme testleri."""

    @staticmethod
    def _make_schema_context(tables=None):
        """Test için schema context oluşturur."""
        if tables is None:
            tables = [
                {
                    "schema": "public",
                    "name": "invoices",
                    "type": "table",
                    "columns": [
                        {"name": "id", "data_type": "integer", "is_pk": True},
                        {"name": "amount", "data_type": "numeric"},
                        {"name": "created_at", "data_type": "timestamp"},
                    ],
                    "column_count": 3,
                    "row_estimate": 15000,
                    "business_name_tr": "Faturalar",
                    "admin_label_tr": "",
                    "category": "finance",
                    "description_tr": "Müşteri faturaları tablosu",
                },
                {
                    "schema": "public",
                    "name": "customers",
                    "type": "table",
                    "columns": [
                        {"name": "id", "data_type": "integer", "is_pk": True},
                        {"name": "name", "data_type": "varchar"},
                    ],
                    "column_count": 2,
                    "row_estimate": 5000,
                    "business_name_tr": "Müşteriler",
                    "admin_label_tr": "Müşteri Kartları",
                    "category": "crm",
                    "description_tr": "Tüm müşteri kayıtları",
                },
            ]
        return {
            "tables": tables,
            "relationships": [],
            "dialect": "postgresql",
            "source_name": "Test DB",
        }

    def test_technical_name_still_works(self):
        """Teknik tablo adı (invoices) hâlâ eşleşir."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        result = match_template_query("invoices tablosunda kaç kayıt var?", ctx)
        assert result is not None
        assert result["table"] == "invoices"

    def test_turkish_business_name_matches(self):
        """Türkçe iş adı (faturalar) ile tablo eşleşir."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        result = match_template_query("faturalarda kaç kayıt var?", ctx)
        assert result is not None
        assert result["table"] == "invoices"

    def test_turkish_business_name_exact(self):
        """Tam Türkçe iş adı (Faturalar) ile eşleşir."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        result = match_template_query("Faturalar tablosundaki toplam sayısı", ctx)
        assert result is not None
        assert result["table"] == "invoices"

    def test_admin_label_matches(self):
        """Admin etiketi (Müşteri Kartları) ile eşleşir."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        result = match_template_query("müşteri kartlarında kaç kayıt var?", ctx)
        assert result is not None
        assert result["table"] == "customers"

    def test_turkish_suffix_lar(self):
        """Türkçe çoğul eki (-lar/-ler) eşleşir."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        result = match_template_query("müşterilerde kaç kayıt var?", ctx)
        assert result is not None
        assert result["table"] == "customers"

    def test_turkish_suffix_dan(self):
        """Türkçe ayrılma eki (-dan/-den) eşleşir."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        # "müşteriler" + "den" → müşterilerden, template "kaç kayıt" ile eşleşir
        result = match_template_query("müşterilerden kaç kayıt var?", ctx)
        assert result is not None
        assert result["table"] == "customers"

    def test_no_match_returns_none(self):
        """Hiçbir tablo eşleşmezse None döner."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context()
        result = match_template_query("hava durumu nedir?", ctx)
        assert result is None

    def test_no_tables_returns_none(self):
        """Tablo listesi boşsa None döner."""
        from app.services.hybrid_router import match_template_query
        ctx = self._make_schema_context(tables=[])
        result = match_template_query("faturalarda kaç kayıt?", ctx)
        assert result is None


# =============================================================================
# TEST: format_schema_for_llm() — Enrichment Bilgisi LLM Context'e Dahil
# =============================================================================

class TestFormatSchemaForLLM:
    """LLM context formatında enrichment bilgisi testleri."""

    def test_includes_business_name(self):
        """LLM context'te business_name_tr görünür."""
        from app.services.hybrid_router import format_schema_for_llm
        ctx = TestEnrichmentTableMatching._make_schema_context()
        output = format_schema_for_llm(ctx)
        assert "[Faturalar]" in output

    def test_includes_admin_label(self):
        """Admin etiketi varsa business_name yerine kullanılır."""
        from app.services.hybrid_router import format_schema_for_llm
        ctx = TestEnrichmentTableMatching._make_schema_context()
        output = format_schema_for_llm(ctx)
        assert "[Müşteri Kartları]" in output

    def test_includes_description(self):
        """Açıklama LLM context'te görünür."""
        from app.services.hybrid_router import format_schema_for_llm
        ctx = TestEnrichmentTableMatching._make_schema_context()
        output = format_schema_for_llm(ctx)
        assert "Müşteri faturaları tablosu" in output

    def test_empty_enrichment_no_crash(self):
        """Enrichment yokken crash olmaz."""
        from app.services.hybrid_router import format_schema_for_llm
        tables = [{
            "schema": "public", "name": "test_table", "type": "table",
            "columns": [{"name": "id", "data_type": "integer", "is_pk": True}],
            "column_count": 1, "row_estimate": 100,
            "business_name_tr": "", "admin_label_tr": "",
            "category": "", "description_tr": "",
        }]
        ctx = {"tables": tables, "relationships": [], "dialect": "postgresql", "source_name": "X"}
        output = format_schema_for_llm(ctx)
        assert "test_table" in output

    def test_empty_context_returns_empty(self):
        """Boş context boş string döner."""
        from app.services.hybrid_router import format_schema_for_llm
        assert format_schema_for_llm({}) == ""
        assert format_schema_for_llm({"tables": []}) == ""


# =============================================================================
# TEST: _validate_synthesis() — Halüsinasyon Doğrulaması
# =============================================================================

class TestHallucinationGuard:
    """Sorgu zamanı halüsinasyon doğrulaması testleri."""

    @staticmethod
    def _make_service():
        from app.services.deep_think_service import DeepThinkService
        return DeepThinkService()

    def test_short_source_skips_validation(self):
        """Kısa kaynak metin (<500 char) doğrulamayı atlar."""
        service = self._make_service()
        rag_results = [{"content": "Kısa metin", "source_file": "test.txt"}]
        intent = MagicMock()

        result = service._validate_synthesis(
            "Bu bir uzun LLM cevabı " * 20,
            rag_results, "test sorusu", intent
        )
        # Kısa kaynak → doğrulama atlandı → orijinal cevap döner
        assert "LLM cevabı" in result

    def test_empty_synthesized_returns_as_is(self):
        """Boş cevap doğrulamadan geçer."""
        service = self._make_service()
        result = service._validate_synthesis("", [], "test", MagicMock())
        assert result == ""

    def test_none_results_returns_as_is(self):
        """None rag_results doğrulamadan geçer."""
        service = self._make_service()
        result = service._validate_synthesis("cevap", None, "test", MagicMock())
        assert result == "cevap"

    def test_validation_passes_returns_synthesized(self):
        """Doğrulama başarılı olunca orijinal cevap döner."""
        service = self._make_service()

        kaynak = "PostgreSQL veritabanı yönetimi hakkında detaylı bilgi. " * 30
        cevap = "PostgreSQL veritabanı yönetimi için şu adımları izleyin."

        rag_results = [{"content": kaynak, "source_file": "pg.txt"}]

        # validate_answer mock — passed=True
        mock_result = {"passed": True, "reason": "", "faithfulness": 0.8, "grounding": 0.5, "length_ratio": 1.0}

        with patch("app.services.learned_qa_service.get_learned_qa_service") as mock_svc:
            mock_qa = MagicMock()
            mock_qa._validate_answer.return_value = mock_result
            mock_qa.FAITHFULNESS_THRESHOLD = 0.45
            mock_qa.GROUNDING_THRESHOLD = 0.30
            mock_qa.MAX_LENGTH_RATIO = 8.0
            mock_svc.return_value = mock_qa

            result = service._validate_synthesis(cevap, rag_results, "pg nedir?", MagicMock())

        assert result == cevap

    def test_validation_fails_returns_fallback(self):
        """Doğrulama başarısız olunca fallback cevap döner."""
        service = self._make_service()

        # Kaynak metin 500+ char olmalı ki doğrulama çalışsın
        kaynak = "PostgreSQL veritabanı yönetimi hakkında detaylı bilgi ve uygulama adımları. " * 20
        cevap = "Bu tamamen uydurma bir bilgi ve kaynakta yok."

        rag_results = [
            {"content": kaynak, "source_file": "pg.txt", "score": 0.8},
            {"content": kaynak, "source_file": "pg2.txt", "score": 0.7},
        ]

        mock_result = {"passed": False, "reason": "low_grounding", "faithfulness": 0.1, "grounding": 0.05, "length_ratio": 2.0}

        with patch("app.services.learned_qa_service.get_learned_qa_service") as mock_svc:
            mock_qa = MagicMock()
            mock_qa._validate_answer.return_value = mock_result
            mock_qa.FAITHFULNESS_THRESHOLD = 0.45
            mock_qa.GROUNDING_THRESHOLD = 0.30
            mock_qa.MAX_LENGTH_RATIO = 8.0
            mock_svc.return_value = mock_qa

            result = service._validate_synthesis(cevap, rag_results, "pg nedir?", MagicMock())

        # Orijinal cevap DEĞİL, fallback dönmeli
        assert result != cevap

    def test_exception_fails_open(self):
        """Import hatası durumunda cevap engellenmez (fail-open)."""
        service = self._make_service()

        kaynak = "Uzun kaynak metin " * 50
        cevap = "Bu bir cevap"
        rag_results = [{"content": kaynak, "source_file": "test.txt"}]

        with patch("app.services.learned_qa_service.get_learned_qa_service",
                    side_effect=ImportError("Module yok")):
            result = service._validate_synthesis(cevap, rag_results, "test?", MagicMock())

        assert result == cevap  # Fail-open: hata olsa da cevap döner


# =============================================================================
# TEST: detect_db_intent() — Intent Analizi (değişmemiş olmalı)
# =============================================================================

class TestDetectDbIntent:
    """Intent analizi regresyon testleri."""

    def test_db_intent_detected(self):
        """DB kalıbı algılanır."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType
        result = detect_db_intent("müşteri sayısı kaç")
        assert result == IntentType.DATABASE_QUERY

    def test_no_db_intent_returns_none(self):
        """DB kalıbı yoksa None döner."""
        from app.services.hybrid_router import detect_db_intent
        result = detect_db_intent("VPN nasıl kurulur?")
        assert result is None

    def test_hybrid_intent_detected(self):
        """Hybrid kalıbı algılanır."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType
        result = detect_db_intent("fatura nedir ve toplam kaç tane var")
        assert result == IntentType.HYBRID
"""
v3.1.0: Enrichment-Aware Routing & Hallucination Guard Tests
"""
