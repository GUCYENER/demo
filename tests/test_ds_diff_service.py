"""
VYRA L1 Support API - DS Diff Service Tests
=============================================
ds_diff_service modülünün unit testleri.

Kapsamı:
  - Snapshot oluşturma
  - Hash hesaplama
  - Diff algoritması (eklenen/silinen/değişen tablolar)
  - Sütun düzeyi diff (tip değişikliği, PK değişikliği)
  - Tablo key üretimi
  - Snapshot geçmişi

v3.0.0
"""

import pytest
import json
from unittest.mock import MagicMock


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_diff_db():
    """DS Diff servis testleri için mock DB bağlantısı."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def sample_objects_v1():
    """Versiyon 1: başlangıç objeleri."""
    return [
        {
            "schema_name": "public",
            "object_name": "users",
            "object_type": "table",
            "row_count_estimate": 100,
            "columns_json": [
                {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False},
                {"name": "username", "data_type": "varchar(50)", "is_pk": False, "is_nullable": False},
                {"name": "email", "data_type": "varchar(100)", "is_pk": False, "is_nullable": True},
            ]
        },
        {
            "schema_name": "public",
            "object_name": "orders",
            "object_type": "table",
            "row_count_estimate": 5000,
            "columns_json": [
                {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False},
                {"name": "user_id", "data_type": "integer", "is_pk": False, "is_nullable": False},
                {"name": "total", "data_type": "numeric(10,2)", "is_pk": False, "is_nullable": True},
            ]
        }
    ]


@pytest.fixture
def sample_objects_v2():
    """Versiyon 2: users değişti, orders aynı, products eklendi."""
    return [
        {
            "schema_name": "public",
            "object_name": "users",
            "object_type": "table",
            "row_count_estimate": 150,
            "columns_json": [
                {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False},
                {"name": "username", "data_type": "varchar(100)", "is_pk": False, "is_nullable": False},  # tip değişti
                {"name": "email", "data_type": "varchar(100)", "is_pk": False, "is_nullable": True},
                {"name": "phone", "data_type": "varchar(20)", "is_pk": False, "is_nullable": True},  # yeni sütun
            ]
        },
        {
            "schema_name": "public",
            "object_name": "orders",
            "object_type": "table",
            "row_count_estimate": 6000,  # satır sayısı değişti ama yapı aynı
            "columns_json": [
                {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False},
                {"name": "user_id", "data_type": "integer", "is_pk": False, "is_nullable": False},
                {"name": "total", "data_type": "numeric(10,2)", "is_pk": False, "is_nullable": True},
            ]
        },
        {
            "schema_name": "public",
            "object_name": "products",
            "object_type": "table",
            "row_count_estimate": 200,
            "columns_json": [
                {"name": "id", "data_type": "integer", "is_pk": True, "is_nullable": False},
                {"name": "name", "data_type": "varchar(255)", "is_pk": False, "is_nullable": False},
            ]
        }
    ]


@pytest.fixture
def sample_rels():
    """Örnek ilişkiler."""
    return [
        {
            "from_schema": "public",
            "from_table": "orders",
            "from_column": "user_id",
            "to_schema": "public",
            "to_table": "users",
            "to_column": "id",
            "constraint_name": "fk_orders_user"
        }
    ]


# =============================================================================
# TEST: _build_snapshot_data
# =============================================================================

class TestBuildSnapshotData:
    """Snapshot verisi oluşturma testleri."""

    def test_builds_correct_structure(self, sample_objects_v1, sample_rels):
        """Doğru yapıda snapshot verisi oluşturulmalı."""
        from app.services.ds_diff_service import _build_snapshot_data
        data = _build_snapshot_data(sample_objects_v1, sample_rels)

        assert "tables" in data
        assert "relationships" in data
        assert len(data["tables"]) == 2
        assert len(data["relationships"]) == 1

    def test_table_has_required_fields(self, sample_objects_v1, sample_rels):
        """Her tablo gerekli alanları içermeli."""
        from app.services.ds_diff_service import _build_snapshot_data
        data = _build_snapshot_data(sample_objects_v1, sample_rels)

        table = data["tables"][0]
        assert "schema" in table
        assert "name" in table
        assert "type" in table
        assert "columns" in table
        assert isinstance(table["columns"], list)

    def test_handles_string_columns_json(self):
        """columns_json string olarak gelirse parse etmeli."""
        from app.services.ds_diff_service import _build_snapshot_data

        objects = [{
            "schema_name": "public",
            "object_name": "test",
            "object_type": "table",
            "columns_json": json.dumps([{"name": "id", "data_type": "int", "is_pk": True, "is_nullable": False}]),
            "row_count_estimate": 10
        }]
        data = _build_snapshot_data(objects, [])
        assert len(data["tables"][0]["columns"]) == 1
        assert data["tables"][0]["columns"][0]["name"] == "id"

    def test_handles_empty_lists(self):
        """Boş listelerle çalışmalı."""
        from app.services.ds_diff_service import _build_snapshot_data
        data = _build_snapshot_data([], [])

        assert data["tables"] == []
        assert data["relationships"] == []


# =============================================================================
# TEST: _compute_snapshot_hash
# =============================================================================

class TestComputeSnapshotHash:
    """Snapshot hash hesaplama testleri."""

    def test_same_data_same_hash(self, sample_objects_v1, sample_rels):
        """Aynı veri her zaman aynı hash üretmeli."""
        from app.services.ds_diff_service import _build_snapshot_data, _compute_snapshot_hash

        data = _build_snapshot_data(sample_objects_v1, sample_rels)
        h1 = _compute_snapshot_hash(data)
        h2 = _compute_snapshot_hash(data)

        assert h1 == h2

    def test_different_data_different_hash(self, sample_objects_v1, sample_objects_v2, sample_rels):
        """Farklı veri farklı hash üretmeli (yapı değiştiğinde)."""
        from app.services.ds_diff_service import _build_snapshot_data, _compute_snapshot_hash

        d1 = _build_snapshot_data(sample_objects_v1, sample_rels)
        d2 = _build_snapshot_data(sample_objects_v2, sample_rels)

        h1 = _compute_snapshot_hash(d1)
        h2 = _compute_snapshot_hash(d2)

        assert h1 != h2

    def test_row_count_does_not_affect_hash(self, sample_rels):
        """Satır sayısı değişikliği hash'i etkilememeli."""
        from app.services.ds_diff_service import _build_snapshot_data, _compute_snapshot_hash

        obj_100 = [{
            "schema_name": "public", "object_name": "test", "object_type": "table",
            "row_count_estimate": 100,
            "columns_json": [{"name": "id", "data_type": "int", "is_pk": True, "is_nullable": False}]
        }]
        obj_999 = [{
            "schema_name": "public", "object_name": "test", "object_type": "table",
            "row_count_estimate": 99999,
            "columns_json": [{"name": "id", "data_type": "int", "is_pk": True, "is_nullable": False}]
        }]

        h1 = _compute_snapshot_hash(_build_snapshot_data(obj_100, []))
        h2 = _compute_snapshot_hash(_build_snapshot_data(obj_999, []))

        assert h1 == h2  # Yapı aynı, sadece row_estimate farklı


# =============================================================================
# TEST: compute_diff
# =============================================================================

class TestComputeDiff:
    """İki snapshot arasındaki diff hesaplama testleri."""

    def test_detects_added_tables(self, sample_objects_v1, sample_objects_v2, sample_rels):
        """Yeni eklenen tablolar tespit edilmeli."""
        from app.services.ds_diff_service import _build_snapshot_data, compute_diff

        old = _build_snapshot_data(sample_objects_v1, sample_rels)
        new = _build_snapshot_data(sample_objects_v2, sample_rels)

        diff = compute_diff(old, new)

        assert "public.products" in diff["added_tables"]

    def test_detects_removed_tables(self, sample_objects_v1, sample_rels):
        """Silinen tablolar tespit edilmeli."""
        from app.services.ds_diff_service import _build_snapshot_data, compute_diff

        old = _build_snapshot_data(sample_objects_v1, sample_rels)
        # orders tablosu yok
        new_objs = [sample_objects_v1[0]]  # sadece users
        new = _build_snapshot_data(new_objs, [])

        diff = compute_diff(old, new)

        assert "public.orders" in diff["removed_tables"]

    def test_detects_modified_tables(self, sample_objects_v1, sample_objects_v2, sample_rels):
        """Değişen tablolar tespit edilmeli."""
        from app.services.ds_diff_service import _build_snapshot_data, compute_diff

        old = _build_snapshot_data(sample_objects_v1, sample_rels)
        new = _build_snapshot_data(sample_objects_v2, sample_rels)

        diff = compute_diff(old, new)

        modified_names = [m["table"] for m in diff["modified_tables"]]
        assert "public.users" in modified_names

    def test_unchanged_tables_detected(self, sample_objects_v1, sample_objects_v2, sample_rels):
        """Değişmeyen tablolar tespit edilmeli."""
        from app.services.ds_diff_service import _build_snapshot_data, compute_diff

        old = _build_snapshot_data(sample_objects_v1, sample_rels)
        new = _build_snapshot_data(sample_objects_v2, sample_rels)

        diff = compute_diff(old, new)

        # orders'ın yapısı değişmedi (sadece row_count)
        assert "public.orders" in diff["unchanged_tables"]

    def test_identical_snapshots_no_changes(self, sample_objects_v1, sample_rels):
        """Aynı snapshot'lar arasında fark olmamalı."""
        from app.services.ds_diff_service import _build_snapshot_data, compute_diff

        data = _build_snapshot_data(sample_objects_v1, sample_rels)
        diff = compute_diff(data, data)

        assert len(diff["added_tables"]) == 0
        assert len(diff["removed_tables"]) == 0
        assert len(diff["modified_tables"]) == 0
        assert len(diff["unchanged_tables"]) == 2

    def test_summary_string_generated(self, sample_objects_v1, sample_objects_v2, sample_rels):
        """Özet metin üretilmeli."""
        from app.services.ds_diff_service import _build_snapshot_data, compute_diff

        old = _build_snapshot_data(sample_objects_v1, sample_rels)
        new = _build_snapshot_data(sample_objects_v2, sample_rels)

        diff = compute_diff(old, new)

        assert "summary" in diff
        assert isinstance(diff["summary"], str)
        assert len(diff["summary"]) > 0


# =============================================================================
# TEST: _compute_column_diff
# =============================================================================

class TestColumnDiff:
    """Sütun düzeyi diff testleri."""

    def test_detects_added_columns(self):
        """Yeni eklenen sütunlar tespit edilmeli."""
        from app.services.ds_diff_service import _compute_column_diff

        old = {
            "columns": [
                {"name": "id", "data_type": "int"},
                {"name": "name", "data_type": "varchar"}
            ]
        }
        new = {
            "columns": [
                {"name": "id", "data_type": "int"},
                {"name": "name", "data_type": "varchar"},
                {"name": "phone", "data_type": "varchar"}
            ]
        }
        diff = _compute_column_diff(old, new)
        assert "phone" in diff["added_columns"]

    def test_detects_removed_columns(self):
        """Silinen sütunlar tespit edilmeli."""
        from app.services.ds_diff_service import _compute_column_diff

        old = {
            "columns": [
                {"name": "id", "data_type": "int"},
                {"name": "legacy_field", "data_type": "text"}
            ]
        }
        new = {
            "columns": [
                {"name": "id", "data_type": "int"}
            ]
        }
        diff = _compute_column_diff(old, new)
        assert "legacy_field" in diff["removed_columns"]

    def test_detects_type_changes(self):
        """Veri tipi değişiklikleri tespit edilmeli."""
        from app.services.ds_diff_service import _compute_column_diff

        old = {
            "columns": [
                {"name": "username", "data_type": "varchar(50)"}
            ]
        }
        new = {
            "columns": [
                {"name": "username", "data_type": "varchar(100)"}
            ]
        }
        diff = _compute_column_diff(old, new)

        assert len(diff["type_changes"]) == 1
        change = diff["type_changes"][0]
        assert change["column"] == "username"
        assert change["old_type"] == "varchar(50)"
        assert change["new_type"] == "varchar(100)"

    def test_detects_pk_changes(self):
        """PK değişiklikleri tespit edilmeli."""
        from app.services.ds_diff_service import _compute_column_diff

        old = {
            "columns": [
                {"name": "id", "data_type": "int", "is_pk": False}
            ]
        }
        new = {
            "columns": [
                {"name": "id", "data_type": "int", "is_pk": True}
            ]
        }
        diff = _compute_column_diff(old, new)

        assert len(diff["pk_changes"]) == 1
        assert diff["pk_changes"][0]["is_pk"] is True

    def test_no_changes_detected(self):
        """Değişiklik yoksa boş listeler dönmeli."""
        from app.services.ds_diff_service import _compute_column_diff

        table = {
            "columns": [
                {"name": "id", "data_type": "int", "is_pk": True},
                {"name": "name", "data_type": "varchar", "is_pk": False}
            ]
        }
        diff = _compute_column_diff(table, table)

        assert diff["added_columns"] == []
        assert diff["removed_columns"] == []
        assert diff["type_changes"] == []
        assert diff["pk_changes"] == []


# =============================================================================
# TEST: Table Key Generation
# =============================================================================

class TestTableKey:
    """Tablo key üretim testleri."""

    def test_with_schema(self):
        """Schema varsa 'schema.table' formatında olmalı."""
        from app.services.ds_diff_service import _table_key
        key = _table_key({"schema_name": "public", "object_name": "users"})
        assert key == "public.users"

    def test_without_schema(self):
        """Schema yoksa sadece tablo adı dönmeli."""
        from app.services.ds_diff_service import _table_key
        key = _table_key({"schema_name": "", "object_name": "users"})
        assert key == "users"

    def test_table_key_from_data(self):
        """Snapshot data formatından key üretilmeli."""
        from app.services.ds_diff_service import _table_key_from_data
        key = _table_key_from_data({"schema": "sales", "name": "invoices"})
        assert key == "sales.invoices"


# =============================================================================
# TEST: get_snapshot_history
# =============================================================================

class TestGetSnapshotHistory:
    """Snapshot geçmişi testleri."""

    def test_returns_history_list(self, mock_diff_db):
        """Geçmiş liste olarak dönmeli."""
        mock_conn, mock_cursor = mock_diff_db
        from datetime import datetime
        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "snapshot_hash": "abc123",
                "diff_summary": json.dumps({"summary": "İlk keşif"}),
                "table_count": 10,
                "column_count": 50,
                "relationship_count": 5,
                "created_at": datetime(2026, 3, 30, 18, 0, 0)
            }
        ]

        from app.services.ds_diff_service import get_snapshot_history
        history = get_snapshot_history(mock_conn, source_id=2)

        assert len(history) == 1
        assert history[0]["table_count"] == 10
        assert history[0]["snapshot_hash"] == "abc123"

    def test_empty_history(self, mock_diff_db):
        """Geçmiş yoksa boş liste dönmeli."""
        mock_conn, mock_cursor = mock_diff_db
        mock_cursor.fetchall.return_value = []

        from app.services.ds_diff_service import get_snapshot_history
        history = get_snapshot_history(mock_conn, source_id=999)

        assert history == []


# =============================================================================
# TEST: create_snapshot — İlk Çalıştırma
# =============================================================================

class TestCreateSnapshot:
    """Snapshot oluşturma testleri."""

    def test_first_run_detected(self, mock_diff_db, sample_objects_v1, sample_rels):
        """İlk çalıştırmada is_first_run=True olmalı."""
        mock_conn, mock_cursor = mock_diff_db
        # Önceki snapshot yok
        mock_cursor.fetchone.side_effect = [None, {"id": 1}]

        from app.services.ds_diff_service import create_snapshot
        result = create_snapshot(mock_conn, source_id=2,
                                 objects=sample_objects_v1,
                                 relationships=sample_rels)

        assert result["is_first_run"] is True
        assert len(result["diff"]["added_tables"]) == 2
