"""v3.34.1 audit hardening — schema_warn enrichment index + detail CHECK + index rename

Revision ID: 045_v3341_audit_index_cap_rename
Revises: 044_v3330_rls_canonical_with_check
Create Date: 2026-05-24

Refactor scope: R007 + R008 + R009 (mini refactor sprint, v3.34.1)
-------------------------------------------------------------------
Bkz: .agents/refactor/REFACTOR_BACKLOG.md

- R007: `ds_schema_record_warnings.enrichment_id` üzerinde index yoktu — admin
  warning panel endpoint'i per-enrichment filtre kullandığında seq-scan riskli.
  `CREATE INDEX IF NOT EXISTS idx_schema_warn_enrich` eklenir.

- R008: Mig 043'te oluşturulan `idx_ds_table_enrich_source_id_pk` index ismi,
  mig 004'ün koyduğu `idx_table_enrich_*` konvansiyonuyla uyumsuz. Ops grep
  / `pg_stat_user_indexes` patterns bu indexi atlıyordu. `ALTER INDEX RENAME`
  ile düzeltilir (non-breaking).

- R009: `ds_schema_record_warnings.detail` TEXT idi — app layer 500 cap dışında
  DB güvencesi yoktu. Yeni `CHECK (char_length(detail) <= 1000)` constraint
  ile 1000 char headroom verilir (app 500 cap altındadır → regresyon yok).

R010 NOT bir DOC-only madde, code değişikliği yok (bkz. data_sources_api.py
docstring + bu dosyanın bu açıklamasının altındaki "operational note").

Operational note (R010):
- FastAPI `BackgroundTasks` SIGTERM-safe değildir. uvicorn restart, bulk
  approve sonrası 30s içinde yapılırsa in-flight `_generate_schema_records_
  background` worker'ları yarıda kesilebilir. Approve UPDATE commit'lenmiş
  durumda → kullanıcı state'i güvende; eksik kalan `ds_schema_record_warnings`
  satırları ve embedding'leri admin warning panelinde "beklenenden az" olarak
  görülür. Manuel re-index endpoint'i ileride eklenecek (R010 takip).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "045_v3341_audit_index_cap_rename"
down_revision: Union[str, Sequence[str], None] = "044_v3330_rls_canonical_with_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # R007 — index on enrichment_id
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_schema_warn_enrich "
        "ON ds_schema_record_warnings(enrichment_id);"
    )

    # R008 — non-breaking index rename
    # Eğer hedef isim zaten varsa (örn: bu migration kısmen uygulandıysa) atla.
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'idx_ds_table_enrich_source_id_pk' AND c.relkind = 'i'
        ) AND NOT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'idx_table_enrich_source_id_pk' AND c.relkind = 'i'
        ) THEN
            EXECUTE 'ALTER INDEX idx_ds_table_enrich_source_id_pk '
                    'RENAME TO idx_table_enrich_source_id_pk';
        END IF;
    END$$;
    """)

    # R009 — detail length CHECK constraint
    # IF NOT EXISTS Postgres'te constraint için yok → guard ile DO $$ bloğu.
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ds_schema_warn_detail_max_len'
        ) THEN
            ALTER TABLE ds_schema_record_warnings
                ADD CONSTRAINT ds_schema_warn_detail_max_len
                CHECK (detail IS NULL OR char_length(detail) <= 1000);
        END IF;
    END$$;
    """)


def downgrade() -> None:
    # R009 — drop CHECK constraint
    op.execute(
        "ALTER TABLE ds_schema_record_warnings "
        "DROP CONSTRAINT IF EXISTS ds_schema_warn_detail_max_len;"
    )

    # R008 — revert rename (only if currently the canonical name)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'idx_table_enrich_source_id_pk' AND c.relkind = 'i'
        ) AND NOT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'idx_ds_table_enrich_source_id_pk' AND c.relkind = 'i'
        ) THEN
            EXECUTE 'ALTER INDEX idx_table_enrich_source_id_pk '
                    'RENAME TO idx_ds_table_enrich_source_id_pk';
        END IF;
    END$$;
    """)

    # R007 — drop index
    op.execute("DROP INDEX IF EXISTS idx_schema_warn_enrich;")
