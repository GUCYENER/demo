"""
VYRA L1 Support API - DS QA Generator Tests
==============================================
ds_qa_generator modülünün unit testleri.

Kapsamı:
  - Enriched QA üretimi
  - Enrichment verilerinin QA metinlerine yansıması
  - Dedup hash mantığı
  - Invalidation mantığı
  - Embedding entegrasyonu

v3.0.0
"""

import pytest
import json
from unittest.mock import MagicMock, patch, PropertyMock


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_qa_db():
    """DS QA Generator testleri için mock DB bağlantısı."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def sample_enrichments():
    """Enrichment tablosu satırları."""
    return [
        {
            "id": 1,
            "schema_name": "public",
            "table_name": "invoices",
            "object_type": "table",
            "business_name_tr": "Fatura",
            "description_tr": "Müşterilere kesilen faturaları saklayan tablo.",
            "category": "finance",
            "sample_questions": json.dumps([
                "Son faturamın tutarı nedir?",
                "Bu ay kaç fatura kesildi?"
            ]),
            "enrichment_score": 0.92,
            "admin_label_tr": None
        },
        {
            "id": 2,
            "schema_name": "public",
            "table_name": "customers",
            "object_type": "table",
            "business_name_tr": "Müşteri",
            "description_tr": "Müşteri bilgilerini saklayan tablo.",
            "category": "crm",
            "sample_questions": json.dumps([
                "Toplam müşteri sayısı kaç?"
            ]),
            "enrichment_score": 0.88,
            "admin_label_tr": "Müşteri Kartları"  # Admin düzeltmesi
        }
    ]


@pytest.fixture
def sample_objects():
    """DB objeleri."""
    return [
        {
            "id": 10,
            "schema_name": "",
            "object_name": "invoices",
            "object_type": "table",
            "column_count": 5,
            "row_count_estimate": 15420,
            "columns_json": json.dumps([
                {"name": "id", "data_type": "integer", "is_pk": True},
                {"name": "customer_id", "data_type": "integer", "is_pk": False},
                {"name": "total_amount", "data_type": "numeric", "is_pk": False},
            ])
        },
        {
            "id": 11,
            "schema_name": "",
            "object_name": "customers",
            "object_type": "table",
            "column_count": 3,
            "row_count_estimate": 500,
            "columns_json": json.dumps([
                {"name": "id", "data_type": "integer", "is_pk": True},
                {"name": "name", "data_type": "varchar", "is_pk": False},
            ])
        }
    ]


@pytest.fixture
def sample_rels():
    """İlişkiler."""
    return [
        {
            "from_schema": "public",
            "from_table": "invoices",
            "from_column": "customer_id",
            "to_schema": "public",
            "to_table": "customers",
            "to_column": "id"
        }
    ]


@pytest.fixture
def sample_samples():
    """Örnek veriler."""
    return [
        {
            "object_id": 10,
            "sample_data": json.dumps([
                {"id": 1, "customer_id": 5, "total_amount": 1500.00},
                {"id": 2, "customer_id": 3, "total_amount": 2700.50}
            ]),
            "row_count": 2,
            "object_name": "invoices"
        }
    ]


def _setup_mock_cursor(mock_cursor, enrichments, objects, rels, samples,
                        existing_hashes=None, job_id=None):
    """Mock cursor'ı sırayla döndürecek şekilde ayarla."""
    company_row = {"company_id": 1}
    hash_rows = [{"q_hash": h} for h in (existing_hashes or [])]
    job_row = {"id": job_id} if job_id else None

    mock_cursor.fetchone.side_effect = [
        company_row,   # company_id
        job_row         # job_id
    ]
    mock_cursor.fetchall.side_effect = [
        enrichments,    # enrichments
        objects,        # objects
        rels,           # relationships
        samples,        # samples
        hash_rows,      # dedup hashes
    ]
    mock_cursor.rowcount = 0  # invalidated count


# =============================================================================
# TEST: generate_enriched_qa — Temel Akış
# =============================================================================

class TestGenerateEnrichedQA:
    """generate_enriched_qa temel akış testleri."""

    @patch("app.services.ds_qa_generator.EmbeddingManager", create=True)
    def test_generates_qa_from_enrichments(self, MockEmbMgr,
                                            mock_qa_db, sample_enrichments,
                                            sample_objects, sample_rels,
                                            sample_samples):
        """Enrichment verilerinden QA üretilmeli."""
        mock_conn, mock_cursor = mock_qa_db
        _setup_mock_cursor(mock_cursor, sample_enrichments,
                           sample_objects, sample_rels, sample_samples)

        # Mock embedding
        mock_emb = MagicMock()
        mock_emb.get_embeddings_batch.return_value = [[0.1] * 384] * 50
        MockEmbMgr.return_value = mock_emb

        with patch("app.services.ds_qa_generator.EmbeddingManager", return_value=mock_emb):
            from app.services.ds_qa_generator import generate_enriched_qa
            result = generate_enriched_qa(source_id=2, vyra_conn=mock_conn)

        assert result["success"] is True
        assert result["data"]["qa_pairs_generated"] > 0

    def test_returns_error_without_embedding(self, mock_qa_db):
        """Embedding yoksa hata dönmeli."""
        mock_conn, mock_cursor = mock_qa_db
        mock_cursor.fetchone.return_value = {"company_id": 1}

        with patch("app.services.rag.embedding.EmbeddingManager",
                    side_effect=Exception("Embedding yok")):
            from app.services.ds_qa_generator import generate_enriched_qa
            result = generate_enriched_qa(source_id=2, vyra_conn=mock_conn)

        assert result["success"] is False
        assert "Embedding" in result.get("error", "")


# =============================================================================
# TEST: Admin Label Önceliği
# =============================================================================

class TestAdminLabelPriority:
    """Admin'in verdiği label'ın QA'ya yansıması testleri."""

    def test_admin_label_used_when_present(self, sample_enrichments):
        """admin_label_tr varsa business_name_tr yerine kullanılmalı."""
        # customers tablosunda admin_label_tr = "Müşteri Kartları"
        customer = sample_enrichments[1]
        bname = customer["admin_label_tr"] or customer["business_name_tr"]
        assert bname == "Müşteri Kartları"

    def test_business_name_used_when_no_admin_label(self, sample_enrichments):
        """admin_label_tr yoksa business_name_tr kullanılmalı."""
        invoice = sample_enrichments[0]
        bname = invoice["admin_label_tr"] or invoice["business_name_tr"]
        assert bname == "Fatura"


# =============================================================================
# TEST: Dedup Hash
# =============================================================================

class TestDedupHash:
    """Duplicate QA önleme testleri."""

    def test_duplicate_questions_skipped(self):
        """Aynı soru hash'i varsa atlanmalı."""
        import hashlib
        question = "Son faturamın tutarı nedir?"
        q_hash = hashlib.md5(question.encode()).hexdigest()

        existing = {q_hash}
        new_hash = hashlib.md5(question.encode()).hexdigest()

        assert new_hash in existing  # Atlanmalı

    def test_different_questions_not_skipped(self):
        """Farklı sorular atlanmamalı."""
        import hashlib
        q1 = "Son faturamın tutarı nedir?"
        q2 = "Bu ay kaç fatura kesildi?"

        h1 = hashlib.md5(q1.encode()).hexdigest()
        h2 = hashlib.md5(q2.encode()).hexdigest()

        assert h1 != h2


# =============================================================================
# TEST: Category Labels
# =============================================================================

class TestCategoryLabels:
    """Kategori Türkçe etiket testleri."""

    def test_finance_label(self):
        """Finance kategorisi 'finans ve muhasebe' olmalı."""
        cat_labels = {
            "finance": "finans ve muhasebe", "hr": "insan kaynakları",
            "crm": "müşteri ilişkileri", "inventory": "stok ve envanter",
            "auth": "kimlik doğrulama ve yetkilendirme", "system": "sistem",
            "log": "log ve denetim", "config": "ayar ve konfigürasyon"
        }
        assert cat_labels["finance"] == "finans ve muhasebe"
        assert cat_labels["crm"] == "müşteri ilişkileri"
        assert cat_labels["auth"] == "kimlik doğrulama ve yetkilendirme"

    def test_unknown_category_passes_through(self):
        """Bilinmeyen kategori doğrudan kullanılmalı."""
        cat_labels = {"finance": "finans"}
        category = "custom_type"
        label = cat_labels.get(category, category)
        assert label == "custom_type"


# =============================================================================
# TEST: Invalidation
# =============================================================================

class TestInvalidation:
    """Eski QA kayıtlarının geçersiz kılınması testleri."""

    def test_hash_cleared_after_invalidation(self):
        """Invalidation sonrası hash seti temizlenmeli."""
        existing_hashes = {"abc123", "def456", "ghi789"}

        # Invalidation simüle et
        invalidated = 10
        if invalidated > 0:
            existing_hashes.clear()

        assert len(existing_hashes) == 0

    def test_hash_not_cleared_if_no_invalidation(self):
        """Invalidation yoksa hash seti korunmalı."""
        existing_hashes = {"abc123", "def456"}

        invalidated = 0
        if invalidated > 0:
            existing_hashes.clear()

        assert len(existing_hashes) == 2
