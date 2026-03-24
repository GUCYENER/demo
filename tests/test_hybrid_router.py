"""
VYRA - Hybrid Router & Intent Router Tests
============================================
Intent Router (DB intent tespiti), Hybrid Router, SQL Dialect Adapter
ve Template SQL eşleştirme unit testleri.

Test Sayısı: ~15 test
"""

import pytest
import re
from unittest.mock import MagicMock, patch


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def schema_context():
    """Örnek schema context (ds_learning keşfinden)."""
    return {
        "tables": [
            {
                "schema": "public",
                "name": "users",
                "type": "table",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False, "default_val": None},
                    {"name": "username", "data_type": "varchar", "is_pk": False, "is_nullable": False, "default_val": None},
                    {"name": "email", "data_type": "varchar", "is_pk": False, "is_nullable": True, "default_val": None},
                    {"name": "salary", "data_type": "numeric", "is_pk": False, "is_nullable": True, "default_val": None},
                    {"name": "created_at", "data_type": "timestamp", "is_pk": False, "is_nullable": True, "default_val": None},
                ],
                "column_count": 5,
                "row_estimate": 1500,
            },
            {
                "schema": "public",
                "name": "orders",
                "type": "table",
                "columns": [
                    {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False, "default_val": None},
                    {"name": "user_id", "data_type": "integer", "is_pk": False, "is_nullable": False, "default_val": None},
                    {"name": "amount", "data_type": "numeric", "is_pk": False, "is_nullable": True, "default_val": None},
                    {"name": "status", "data_type": "varchar", "is_pk": False, "is_nullable": True, "default_val": None},
                    {"name": "order_date", "data_type": "timestamp", "is_pk": False, "is_nullable": True, "default_val": None},
                ],
                "column_count": 5,
                "row_estimate": 50000,
            },
        ],
        "relationships": [
            {
                "from": "public.orders.user_id",
                "to": "public.users.id",
                "constraint": "fk_orders_user",
            }
        ],
        "dialect": "postgresql",
        "source_name": "TestDB",
        "source_id": 1,
    }


# =============================================================================
# TEST: Intent Router — DB Intent Detection
# =============================================================================

class TestDBIntentDetection:
    """DB intent pattern tespiti testleri."""

    def test_detect_row_count_query(self):
        """'kaç kayıt var' → DATABASE_QUERY olmalı."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType

        result = detect_db_intent("users tablosunda kaç kayıt var?")
        assert result == IntentType.DATABASE_QUERY

    def test_detect_total_amount_query(self):
        """'toplam tutar' → DATABASE_QUERY olmalı."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType

        result = detect_db_intent("bu aydaki toplam tutar nedir?")
        assert result == IntentType.DATABASE_QUERY

    def test_detect_latest_record_query(self):
        """'son fatura' → DATABASE_QUERY olmalı."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType

        result = detect_db_intent("son fatura bilgisi nedir?")
        assert result == IntentType.DATABASE_QUERY

    def test_detect_balance_query(self):
        """'bakiye' → DATABASE_QUERY olmalı."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType

        result = detect_db_intent("hesap bakiyem ne kadar?")
        assert result == IntentType.DATABASE_QUERY

    def test_detect_average_query(self):
        """'ortalama' → DATABASE_QUERY olmalı."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType

        result = detect_db_intent("ortalama sipariş tutarı nedir?")
        assert result == IntentType.DATABASE_QUERY

    def test_non_db_query_returns_none(self):
        """'VPN bağlantı sorunu' → None (doküman sorusu)."""
        from app.services.hybrid_router import detect_db_intent

        result = detect_db_intent("VPN bağlantı sorunu nasıl çözülür?")
        assert result is None

    def test_non_db_general_query_returns_none(self):
        """Genel bilgi sorusu → None."""
        from app.services.hybrid_router import detect_db_intent

        result = detect_db_intent("şirket politikası nedir?")
        assert result is None

    def test_customer_count_query(self):
        """'müşteri sayısı' → DATABASE_QUERY olmalı."""
        from app.services.hybrid_router import detect_db_intent
        from app.services.deep_think.types import IntentType

        result = detect_db_intent("müşteri sayısı kaç?")
        assert result == IntentType.DATABASE_QUERY


# =============================================================================
# TEST: analyze_intent — DB Intent Integration
# =============================================================================

class TestAnalyzeIntentDBIntegration:
    """analyze_intent'in DB intent'i doğru tanıyıp tanımadığını test eder."""

    def test_db_query_detected_by_analyze_intent(self):
        """analyze_intent() DB sorgusunu tanımalı."""
        from app.services.deep_think_service import DeepThinkService
        from app.services.deep_think.types import IntentType

        service = DeepThinkService()
        result = service.analyze_intent("users tablosunda kaç kayıt var?")

        assert result.intent_type == IntentType.DATABASE_QUERY

    def test_existing_intents_not_broken(self):
        """Mevcut intent tipleri bozulmamalı (regresyon)."""
        from app.services.deep_think_service import DeepThinkService
        from app.services.deep_think.types import IntentType

        service = DeepThinkService()

        # LIST_REQUEST
        assert service.analyze_intent("Cisco switch komutları nelerdir?").intent_type == IntentType.LIST_REQUEST

        # HOW_TO
        assert service.analyze_intent("VPN nasıl kurulur?").intent_type == IntentType.HOW_TO

        # TROUBLESHOOT
        assert service.analyze_intent("internet bağlantısı çalışmıyor").intent_type == IntentType.TROUBLESHOOT

        # SINGLE_ANSWER
        assert service.analyze_intent("VPN nedir?").intent_type == IntentType.SINGLE_ANSWER


# =============================================================================
# TEST: Template SQL Matching
# =============================================================================

class TestTemplateMatching:
    """Template SQL eşleştirme testleri."""

    def test_row_count_match(self, schema_context):
        """'users tablosunda kaç kayıt var' → row_count template."""
        from app.services.hybrid_router import match_template_query

        result = match_template_query("users tablosunda kaç kayıt var?", schema_context)

        assert result is not None
        assert result["template"] == "row_count"
        assert result["table"] == "users"

    def test_sum_match(self, schema_context):
        """'toplam salary' → sum_column template."""
        from app.services.hybrid_router import match_template_query

        result = match_template_query("users tablosundaki toplam salary nedir?", schema_context)

        assert result is not None
        assert result["template"] == "sum_column"
        assert result["col"] == "salary"

    def test_latest_records_match(self, schema_context):
        """'son orders' → latest_records template."""
        from app.services.hybrid_router import match_template_query

        result = match_template_query("son orders kayıtları neler?", schema_context)

        assert result is not None
        assert result["template"] == "latest_records"
        assert result["date_col"] == "order_date"

    def test_no_match_unknown_table(self, schema_context):
        """Bilinmeyen tablo → None."""
        from app.services.hybrid_router import match_template_query

        result = match_template_query("products tablosunda kaç ürün var?", schema_context)
        assert result is None

    def test_no_match_doc_query(self, schema_context):
        """Doküman sorusu → None."""
        from app.services.hybrid_router import match_template_query

        result = match_template_query("VPN bağlantısı nasıl kurulur?", schema_context)
        assert result is None


# =============================================================================
# TEST: Schema Context Formatting
# =============================================================================

class TestSchemaContextFormatting:
    """Schema context LLM formatı testleri."""

    def test_format_schema_for_llm(self, schema_context):
        """Schema context LLM'e uygun formatlanmalı."""
        from app.services.hybrid_router import format_schema_for_llm

        result = format_schema_for_llm(schema_context)

        assert "TestDB" in result
        assert "users" in result
        assert "orders" in result
        assert "Sütunlar:" in result

    def test_empty_context_returns_empty(self):
        """Boş context boş string dönmeli."""
        from app.services.hybrid_router import format_schema_for_llm

        assert format_schema_for_llm({}) == ""
        assert format_schema_for_llm({"tables": []}) == ""
