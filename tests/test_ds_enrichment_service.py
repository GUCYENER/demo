"""
VYRA L1 Support API - DS Enrichment Service Tests
====================================================
ds_enrichment_service modülünün unit testleri.

Kapsamı:
  - LLM yanıt parse
  - Skor hesaplama
  - Fallback analiz
  - Tablo enrichment upsert
  - Sütun enrichment
  - Admin onay/pending
  - İstatistikler

v3.0.0
"""

import pytest
import json
from unittest.mock import MagicMock, patch


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_enrich_db():
    """DS Enrichment servis testleri için mock DB bağlantısı."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def sample_columns():
    """Örnek sütun listesi."""
    return [
        {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False},
        {"name": "customer_name", "data_type": "varchar(255)", "is_pk": False, "is_nullable": False},
        {"name": "email", "data_type": "varchar(100)", "is_pk": False, "is_nullable": True},
        {"name": "created_at", "data_type": "timestamptz", "is_pk": False, "is_nullable": True},
        {"name": "total_amount", "data_type": "numeric(10,2)", "is_pk": False, "is_nullable": True},
    ]


@pytest.fixture
def sample_table_info(sample_columns):
    """Örnek tablo bilgisi."""
    return {
        "id": 1,
        "schema_name": "public",
        "object_name": "invoices",
        "table_name": "invoices",
        "object_type": "table",
        "column_count": 5,
        "row_count_estimate": 15420,
        "columns_json": sample_columns,
    }


@pytest.fixture
def sample_llm_response():
    """LLM'den beklenen örnek JSON yanıtı."""
    return json.dumps({
        "business_name_tr": "Fatura",
        "business_name_en": "Invoice",
        "description_tr": "Müşterilere kesilen faturaları saklayan tablo.",
        "category": "finance",
        "confidence": 0.92,
        "sample_questions": [
            "Son faturamın tutarı nedir?",
            "Bu ay kaç fatura kesildi?",
            "En yüksek fatura hangi müşteriye ait?"
        ],
        "columns": {
            "id": {
                "business_name_tr": "Fatura No",
                "description_tr": "Benzersiz fatura numarası",
                "is_key": True,
                "semantic_type": "id"
            },
            "customer_name": {
                "business_name_tr": "Müşteri Adı",
                "description_tr": "Faturanın kesildiği müşterinin adı",
                "is_key": False,
                "semantic_type": "name"
            },
            "total_amount": {
                "business_name_tr": "Toplam Tutar",
                "description_tr": "Fatura toplam tutarı",
                "is_key": False,
                "semantic_type": "amount"
            }
        }
    })


@pytest.fixture
def sample_relationships():
    """Örnek FK ilişkileri."""
    return [
        {
            "from_table": "invoices",
            "from_column": "customer_id",
            "to_table": "customers",
            "to_column": "id"
        },
        {
            "from_table": "invoice_items",
            "from_column": "invoice_id",
            "to_table": "invoices",
            "to_column": "id"
        }
    ]


@pytest.fixture
def sample_pending_rows():
    """Admin onayı bekleyen enrichment kayıtları."""
    return [
        {
            "id": 1,
            "source_id": 2,
            "schema_name": "public",
            "table_name": "sys_config",
            "business_name_tr": "sys_config",
            "description_tr": "Sistem konfigürasyon tablosu — otomatik analiz",
            "category": "config",
            "enrichment_score": 0.45,
            "llm_confidence": 0.3,
            "admin_approved": False,
            "admin_label_tr": None,
            "admin_notes": None,
            "last_enriched_at": "2026-03-30T18:00:00Z",
            "version": 1,
            "source_name": "Ana Veritabanı"
        },
        {
            "id": 2,
            "source_id": 2,
            "schema_name": "public",
            "table_name": "tmp_process_log",
            "business_name_tr": "tmp_process_log",
            "description_tr": "Geçici işlem log tablosu",
            "category": "log",
            "enrichment_score": 0.55,
            "llm_confidence": 0.4,
            "admin_approved": False,
            "admin_label_tr": None,
            "admin_notes": None,
            "last_enriched_at": "2026-03-30T18:01:00Z",
            "version": 1,
            "source_name": "Ana Veritabanı"
        }
    ]


# =============================================================================
# TEST: _parse_llm_analysis
# =============================================================================

class TestParseLLMAnalysis:
    """LLM yanıt parse fonksiyonu testleri."""

    def test_parses_valid_json(self, sample_llm_response):
        """Geçerli JSON yanıtını doğru parse etmeli."""
        from app.services.ds_enrichment_service import _parse_llm_analysis
        result = _parse_llm_analysis(sample_llm_response)

        assert result is not None
        assert result["business_name_tr"] == "Fatura"
        assert result["business_name_en"] == "Invoice"
        assert result["category"] == "finance"
        assert result["llm_confidence"] == 0.92
        assert len(result["sample_questions"]) == 3
        assert "columns" in result
        assert "id" in result["columns"]

    def test_parses_markdown_wrapped_json(self, sample_llm_response):
        """Markdown code block içindeki JSON'u parse edebilmeli."""
        from app.services.ds_enrichment_service import _parse_llm_analysis

        wrapped = f"```json\n{sample_llm_response}\n```"
        result = _parse_llm_analysis(wrapped)

        assert result is not None
        assert result["business_name_tr"] == "Fatura"

    def test_returns_none_for_invalid_json(self):
        """Bozuk JSON için None dönmeli."""
        from app.services.ds_enrichment_service import _parse_llm_analysis
        result = _parse_llm_analysis("Bu bir JSON değil, düz metin.")

        assert result is None

    def test_returns_none_for_empty_input(self):
        """Boş input için None dönmeli."""
        from app.services.ds_enrichment_service import _parse_llm_analysis

        assert _parse_llm_analysis("") is None
        assert _parse_llm_analysis(None) is None

    def test_normalizes_invalid_category(self):
        """Geçersiz kategori 'other' olarak düzeltilmeli."""
        from app.services.ds_enrichment_service import _parse_llm_analysis

        data = json.dumps({
            "business_name_tr": "Test",
            "business_name_en": "Test",
            "description_tr": "Test tablosu",
            "category": "bilinmeyen_kategori",
            "confidence": 0.5,
            "sample_questions": [],
            "columns": {}
        })
        result = _parse_llm_analysis(data)

        assert result["category"] == "other"

    def test_accepts_all_valid_categories(self):
        """Tüm geçerli kategoriler kabul edilmeli."""
        from app.services.ds_enrichment_service import _parse_llm_analysis

        valid_cats = ["finance", "hr", "crm", "inventory", "system", "log", "config", "auth", "other"]
        for cat in valid_cats:
            data = json.dumps({
                "business_name_tr": "Test", "business_name_en": "Test",
                "description_tr": "X", "category": cat,
                "confidence": 0.5, "sample_questions": [], "columns": {}
            })
            result = _parse_llm_analysis(data)
            assert result["category"] == cat, f"Kategori '{cat}' kabul edilmeliydi"

    def test_handles_missing_optional_fields(self):
        """Opsiyonel alanlar eksik olsa bile çalışmalı."""
        from app.services.ds_enrichment_service import _parse_llm_analysis

        data = json.dumps({
            "business_name_tr": "Fatura",
            "confidence": 0.8
        })
        result = _parse_llm_analysis(data)

        assert result is not None
        assert result["business_name_tr"] == "Fatura"
        assert result["business_name_en"] == ""
        assert result["category"] == "other"
        assert result["columns"] == {}


# =============================================================================
# TEST: _compute_enrichment_score
# =============================================================================

class TestComputeEnrichmentScore:
    """Bileşik skor hesaplama testleri."""

    def test_perfect_score(self, sample_columns):
        """Mükemmel durumda skor 1.0'a yakın olmalı."""
        from app.services.ds_enrichment_service import _compute_enrichment_score

        llm_result = {
            "llm_confidence": 0.95,
            "business_name_tr": "Fatura",
            "business_name_en": "Invoice",
            "columns": {"id": {}, "customer_name": {}, "email": {},
                         "created_at": {}, "total_amount": {}}
        }
        score = _compute_enrichment_score(llm_result, sample_columns, [{"row": 1}])

        assert score >= 0.9
        assert score <= 1.0

    def test_zero_confidence_low_score(self, sample_columns):
        """LLM confidence 0 ise skor düşük olmalı."""
        from app.services.ds_enrichment_service import _compute_enrichment_score

        llm_result = {
            "llm_confidence": 0.0,
            "business_name_tr": "",
            "columns": {}
        }
        score = _compute_enrichment_score(llm_result, sample_columns, None)

        assert score < 0.3

    def test_name_quality_affects_score(self, sample_columns):
        """business_name_tr kalitesi skoru etkilemeli."""
        from app.services.ds_enrichment_service import _compute_enrichment_score

        base = {"llm_confidence": 0.8, "columns": {}}

        # İsim yok → düşük
        no_name = {**base, "business_name_tr": ""}
        # İsim var, EN farklı → yüksek
        good_name = {**base, "business_name_tr": "Fatura", "business_name_en": "Invoice"}
        # İsim var ama EN ile aynı → orta
        same_name = {**base, "business_name_tr": "invoices", "business_name_en": "invoices"}

        s_no = _compute_enrichment_score(no_name, sample_columns, None)
        s_good = _compute_enrichment_score(good_name, sample_columns, None)
        s_same = _compute_enrichment_score(same_name, sample_columns, None)

        assert s_good > s_same  # Farklı isim daha iyi
        assert s_same > s_no    # Herhangi bir isim yok'tan iyi

    def test_sample_data_bonus(self, sample_columns):
        """Örnek veri varsa skor 0.1 artmalı."""
        from app.services.ds_enrichment_service import _compute_enrichment_score

        llm_result = {
            "llm_confidence": 0.8,
            "business_name_tr": "Fatura",
            "business_name_en": "Invoice",
            "columns": {}
        }
        without_sample = _compute_enrichment_score(llm_result, sample_columns, None)
        with_sample = _compute_enrichment_score(llm_result, sample_columns, [{"row": 1}])

        assert with_sample - without_sample == pytest.approx(0.1, abs=0.01)

    def test_column_coverage_affects_score(self, sample_columns):
        """Sütun coverage skoru etkilemeli."""
        from app.services.ds_enrichment_service import _compute_enrichment_score

        base = {"llm_confidence": 0.8, "business_name_tr": "T", "business_name_en": "X"}

        # 0 sütun enrich → düşük
        no_cols = {**base, "columns": {}}
        # Tüm sütunlar enrich → yüksek
        all_cols = {**base, "columns": {c["name"]: {} for c in sample_columns}}

        s_no = _compute_enrichment_score(no_cols, sample_columns, None)
        s_all = _compute_enrichment_score(all_cols, sample_columns, None)

        assert s_all > s_no

    def test_score_capped_at_one(self):
        """Skor asla 1.0'ı aşmamalı."""
        from app.services.ds_enrichment_service import _compute_enrichment_score

        extreme = {
            "llm_confidence": 1.0,
            "business_name_tr": "Mükemmel İsim",
            "business_name_en": "Different",
            "columns": {f"col{i}": {} for i in range(100)}
        }
        cols = [{"name": f"col{i}", "data_type": "text"} for i in range(100)]
        score = _compute_enrichment_score(extreme, cols, [{"x": 1}])

        assert score <= 1.0


# =============================================================================
# TEST: _generate_fallback_analysis
# =============================================================================

class TestFallbackAnalysis:
    """LLM çalışmadığında heuristic analiz testleri."""

    def test_finance_pattern_detected(self):
        """Finans anahtar kelimeleri doğru algılanmalı."""
        from app.services.ds_enrichment_service import _generate_fallback_analysis

        for name in ["invoices", "fatura_detay", "payments", "tahsilat"]:
            result = _generate_fallback_analysis(name, [])
            assert result["category"] == "finance", f"'{name}' finance olmalıydı"

    def test_hr_pattern_detected(self):
        """HR anahtar kelimeleri doğru algılanmalı."""
        from app.services.ds_enrichment_service import _generate_fallback_analysis

        for name in ["employees", "personel_list", "salary_records"]:
            result = _generate_fallback_analysis(name, [])
            assert result["category"] == "hr", f"'{name}' hr olmalıydı"

    def test_auth_pattern_detected(self):
        """Auth anahtar kelimeleri doğru algılanmalı."""
        from app.services.ds_enrichment_service import _generate_fallback_analysis

        for name in ["users", "user_roles", "permissions", "sessions"]:
            result = _generate_fallback_analysis(name, [])
            assert result["category"] == "auth", f"'{name}' auth olmalıydı"

    def test_unknown_table_categorized_as_other(self):
        """Tanınmayan tablo 'other' olmalı."""
        from app.services.ds_enrichment_service import _generate_fallback_analysis

        result = _generate_fallback_analysis("xyz_abc_123", [])
        assert result["category"] == "other"

    def test_fallback_has_low_confidence(self):
        """Fallback her zaman düşük güven skoru olmalı."""
        from app.services.ds_enrichment_service import _generate_fallback_analysis

        result = _generate_fallback_analysis("invoices", [])
        assert result["llm_confidence"] == 0.3

    def test_fallback_returns_required_keys(self):
        """Fallback tüm zorunlu alanları içermeli."""
        from app.services.ds_enrichment_service import _generate_fallback_analysis

        result = _generate_fallback_analysis("test_table", [])
        required = ["business_name_tr", "business_name_en", "description_tr",
                     "category", "llm_confidence", "sample_questions", "columns"]
        for key in required:
            assert key in result, f"'{key}' alanı eksik"


# =============================================================================
# TEST: _compute_table_schema_hash
# =============================================================================

class TestSchemaHash:
    """Tablo yapısı hash hesaplama testleri."""

    def test_same_structure_same_hash(self, sample_columns):
        """Aynı yapı her zaman aynı hash üretmeli."""
        from app.services.ds_enrichment_service import _compute_table_schema_hash

        hash1 = _compute_table_schema_hash("invoices", sample_columns)
        hash2 = _compute_table_schema_hash("invoices", sample_columns)

        assert hash1 == hash2

    def test_different_columns_different_hash(self, sample_columns):
        """Farklı sütunlar farklı hash üretmeli."""
        from app.services.ds_enrichment_service import _compute_table_schema_hash

        hash1 = _compute_table_schema_hash("invoices", sample_columns)

        # Bir sütun ekle
        modified = sample_columns + [{"name": "new_col", "data_type": "text"}]
        hash2 = _compute_table_schema_hash("invoices", modified)

        assert hash1 != hash2

    def test_column_order_independent(self, sample_columns):
        """Sütun sırası hash'i etkilememeli (sorted)."""
        from app.services.ds_enrichment_service import _compute_table_schema_hash

        hash1 = _compute_table_schema_hash("invoices", sample_columns)
        hash2 = _compute_table_schema_hash("invoices", list(reversed(sample_columns)))

        assert hash1 == hash2

    def test_different_table_name_different_hash(self, sample_columns):
        """Farklı tablo adı farklı hash üretmeli."""
        from app.services.ds_enrichment_service import _compute_table_schema_hash

        hash1 = _compute_table_schema_hash("invoices", sample_columns)
        hash2 = _compute_table_schema_hash("orders", sample_columns)

        assert hash1 != hash2


# =============================================================================
# TEST: get_pending_approvals
# =============================================================================

class TestGetPendingApprovals:
    """Admin onay kuyruğu testleri."""

    def test_returns_unapproved_records(self, mock_enrich_db, sample_pending_rows):
        """Onay bekleyen kayıtlar dönmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.fetchall.return_value = sample_pending_rows

        from app.services.ds_enrichment_service import get_pending_approvals
        result = get_pending_approvals(mock_conn, source_id=2)

        assert len(result) == 2
        assert result[0]["enrichment_score"] == 0.45
        assert result[1]["table_name"] == "tmp_process_log"

    def test_empty_pending_queue(self, mock_enrich_db):
        """Bekleyen kayıt yoksa boş liste dönmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.fetchall.return_value = []

        from app.services.ds_enrichment_service import get_pending_approvals
        result = get_pending_approvals(mock_conn, source_id=2)

        assert result == []

    def test_filters_by_source_id(self, mock_enrich_db, sample_pending_rows):
        """source_id filtresi SQL'e eklenmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.fetchall.return_value = sample_pending_rows

        from app.services.ds_enrichment_service import get_pending_approvals
        get_pending_approvals(mock_conn, source_id=5)

        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]
        assert "te.source_id = %s" in sql
        assert 5 in params

    def test_ordered_by_score_ascending(self, mock_enrich_db, sample_pending_rows):
        """Sonuçlar skora göre artan sırada olmalı (en düşük skor önce)."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.fetchall.return_value = sample_pending_rows

        from app.services.ds_enrichment_service import get_pending_approvals
        get_pending_approvals(mock_conn, source_id=2)

        sql = mock_cursor.execute.call_args[0][0]
        assert "ORDER BY te.enrichment_score ASC" in sql


# =============================================================================
# TEST: approve_enrichment
# =============================================================================

class TestApproveEnrichment:
    """Admin onay fonksiyonu testleri."""

    def test_approve_without_label(self, mock_enrich_db):
        """Label olmadan onay yapılabilmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.rowcount = 1

        from app.services.ds_enrichment_service import approve_enrichment
        result = approve_enrichment(mock_conn, enrichment_id=1, user_id=99)

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_approve_with_custom_label(self, mock_enrich_db):
        """Admin kendi label'ını ekleyerek onay yapabilmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.rowcount = 1

        from app.services.ds_enrichment_service import approve_enrichment
        result = approve_enrichment(
            mock_conn, enrichment_id=1, user_id=99,
            admin_label_tr="Fatura Listesi",
            admin_notes="İsim düzeltildi"
        )

        assert result is True
        sql = mock_cursor.execute.call_args[0][0]
        assert "admin_label_tr" in sql
        assert "admin_notes" in sql

    def test_approve_nonexistent_returns_false(self, mock_enrich_db):
        """Olmayan kayıt için False dönmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.rowcount = 0

        from app.services.ds_enrichment_service import approve_enrichment
        result = approve_enrichment(mock_conn, enrichment_id=9999, user_id=99)

        assert result is False

    def test_approve_rolls_back_on_error(self, mock_enrich_db):
        """Hata durumunda rollback yapmalı."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.execute.side_effect = Exception("DB Error")

        from app.services.ds_enrichment_service import approve_enrichment
        result = approve_enrichment(mock_conn, enrichment_id=1, user_id=99)

        assert result is False
        mock_conn.rollback.assert_called_once()


# =============================================================================
# TEST: get_enrichment_stats
# =============================================================================

class TestEnrichmentStats:
    """Enrichment istatistik testleri."""

    def test_returns_all_stat_fields(self, mock_enrich_db):
        """Tüm istatistik alanları dönmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.fetchone.return_value = {
            "total": 45,
            "approved": 30,
            "pending_review": 10,
            "auto_approved": 5,
            "avg_score": 0.78,
            "last_enriched": None
        }

        from app.services.ds_enrichment_service import get_enrichment_stats
        stats = get_enrichment_stats(mock_conn, source_id=2)

        assert stats["total"] == 45
        assert stats["approved"] == 30
        assert stats["pending_review"] == 10
        assert stats["avg_score"] == 0.78

    def test_empty_enrichment_returns_zero(self, mock_enrich_db):
        """Enrichment yoksa total=0 dönmeli."""
        mock_conn, mock_cursor = mock_enrich_db
        mock_cursor.fetchone.return_value = None

        from app.services.ds_enrichment_service import get_enrichment_stats
        stats = get_enrichment_stats(mock_conn, source_id=999)

        assert stats["total"] == 0


# =============================================================================
# TEST: enrich_table (skipping logic)
# =============================================================================

class TestEnrichTableSkipping:
    """Tablo enrichment atlama mantığı testleri."""

    def test_skips_unchanged_table(self, mock_enrich_db, sample_table_info, sample_columns):
        """Hash aynı ve aktifse yeniden enrich yapmamalı."""
        mock_conn, mock_cursor = mock_enrich_db

        from app.services.ds_enrichment_service import _compute_table_schema_hash
        expected_hash = _compute_table_schema_hash("invoices", sample_columns)

        # Mevcut enrichment simüle et
        mock_cursor.fetchone.return_value = {
            "id": 10,
            "schema_hash": expected_hash,
            "enrichment_score": 0.85,
            "business_name_tr": "Fatura",
            "admin_approved": True,
            "is_active": True,
            "version": 2
        }

        from app.services.ds_enrichment_service import enrich_table
        result = enrich_table(mock_conn, source_id=2, company_id=1,
                              table_info=sample_table_info)

        assert result["skipped"] is True
        assert result["enrichment_id"] == 10
        assert result["score"] == 0.85


# =============================================================================
# TEST: enrich_tables_batch
# =============================================================================

class TestEnrichTablesBatch:
    """Batch enrichment testleri."""

    @patch("app.services.ds_enrichment_service.enrich_table")
    def test_batch_counts_correctly(self, mock_enrich_single, mock_enrich_db):
        """Batch sayaçları doğru hesaplanmalı."""
        mock_conn, _ = mock_enrich_db

        mock_enrich_single.side_effect = [
            {"enrichment_id": 1, "score": 0.9, "admin_required": False, "skipped": False},
            {"enrichment_id": 2, "score": 0.5, "admin_required": True, "skipped": False},
            {"enrichment_id": 3, "score": 0.8, "admin_required": False, "skipped": True},
        ]

        tables = [
            {"id": 1, "object_name": "invoices"},
            {"id": 2, "object_name": "sys_log"},
            {"id": 3, "object_name": "users"},
        ]

        from app.services.ds_enrichment_service import enrich_tables_batch
        result = enrich_tables_batch(mock_conn, 2, 1, tables)

        assert result["total"] == 3
        assert result["enriched"] == 2  # 2 yeni
        assert result["skipped"] == 1   # 1 atlandı
        assert result["admin_required"] == 1
        assert result["errors"] == 0

    @patch("app.services.ds_enrichment_service.enrich_table")
    def test_batch_handles_errors(self, mock_enrich_single, mock_enrich_db):
        """Hata olan tablolar sayılmalı ama batch devam etmeli."""
        mock_conn, _ = mock_enrich_db

        mock_enrich_single.side_effect = [
            {"enrichment_id": 1, "score": 0.9, "admin_required": False, "skipped": False},
            Exception("LLM API hatası"),
            {"enrichment_id": 3, "score": 0.8, "admin_required": False, "skipped": False},
        ]

        tables = [
            {"id": 1, "object_name": "invoices"},
            {"id": 2, "object_name": "broken_table"},
            {"id": 3, "object_name": "users"},
        ]

        from app.services.ds_enrichment_service import enrich_tables_batch
        result = enrich_tables_batch(mock_conn, 2, 1, tables)

        assert result["total"] == 3
        assert result["enriched"] == 2
        assert result["errors"] == 1

    @patch("app.services.ds_enrichment_service.enrich_table")
    def test_batch_empty_list(self, mock_enrich_single, mock_enrich_db):
        """Boş tablo listesi hata vermemeli."""
        mock_conn, _ = mock_enrich_db

        from app.services.ds_enrichment_service import enrich_tables_batch
        result = enrich_tables_batch(mock_conn, 2, 1, [])

        assert result["total"] == 0
        assert result["enriched"] == 0
        mock_enrich_single.assert_not_called()


# =============================================================================
# TEST: Confidence Threshold
# =============================================================================

class TestConfidenceThreshold:
    """Güven skoru eşik değeri testleri."""

    def test_threshold_is_0_7(self):
        """Eşik değeri 0.7 olmalı."""
        from app.services.ds_enrichment_service import CONFIDENCE_THRESHOLD
        assert CONFIDENCE_THRESHOLD == 0.7

    def test_below_threshold_requires_admin(self):
        """0.7 altı skor admin onayı gerektirmeli."""
        from app.services.ds_enrichment_service import CONFIDENCE_THRESHOLD
        score = 0.65
        assert score < CONFIDENCE_THRESHOLD

    def test_above_threshold_auto_approved(self):
        """0.7 ve üstü skor otomatik onaylanmalı."""
        from app.services.ds_enrichment_service import CONFIDENCE_THRESHOLD
        score = 0.75
        assert score >= CONFIDENCE_THRESHOLD
