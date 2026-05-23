"""v3.32.0 Faz 2 — Bulk approve perf: composite index + schema_record warnings

Revision ID: 043_v3320_bulk_phase2
Revises: 042_v3300_query_examples
Create Date: 2026-05-23

Faz 2 — BackgroundTasks + scale infra
-------------------------------------
Plan: .agents/plans/2026-05-23_1454_bulk_phase2_backgroundtasks_v1.md

Bu migration iki şey ekler:

1) `ds_table_enrichments` üzerinde composite index `(source_id, id)`.
   Bulk approve ARES validation sorgusu (`WHERE source_id=%s AND id=ANY(%s)`)
   şu an PK bitmap + filter scan kullanır; composite index ile 10k+ enrichment
   row + 100-item ANY senaryosunda index-only scan'e geçer.

   CONCURRENTLY: production'da downtime'sız oluşturulabilsin diye. Alembic
   default'ta her migration'ı tek transaction içinde çalıştırır; CREATE INDEX
   CONCURRENTLY transaction-block içinde çalışamaz, bu yüzden
   `op.get_context().autocommit_block()` kullanılır.

2) `ds_schema_record_warnings` tablosu — bulk approve'da BackgroundTasks olarak
   arka planda çalışan schema_record/embedding üretiminde hata oluşursa
   buraya INSERT edilir. Response zaten gönderilmiş olduğundan client'a
   raise edilemez; admin warning panel'inden takip edilir.

   RLS: mig 017 stilinde PERMISSIVE company-RLS policy.
   `reason` = type(e).__name__ (sanitized, client-safe).
   `detail` = str(e)[:500] (server-side log için; admin endpoint'ten görünür).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "043_v3320_bulk_phase2"
down_revision: Union[str, None] = "042_v3300_query_examples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Composite index — CONCURRENTLY (production-safe)
    # ------------------------------------------------------------------
    # autocommit_block: alembic'in default transaction'ından çık; PG
    # CREATE INDEX CONCURRENTLY transaction içinde çalışmaz.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "idx_ds_table_enrich_source_id_pk "
            "ON ds_table_enrichments (source_id, id);"
        )

    # ------------------------------------------------------------------
    # 2) ds_schema_record_warnings — async BG task hata kaydı
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS ds_schema_record_warnings (
        id BIGSERIAL PRIMARY KEY,
        enrichment_id INTEGER NOT NULL,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        detail TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        acknowledged_at TIMESTAMP
    );
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_schema_warn_source
        ON ds_schema_record_warnings(source_id);
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_schema_warn_company
        ON ds_schema_record_warnings(company_id);
    """)

    # RLS — PERMISSIVE company isolation (mig 017 stili)
    op.execute("ALTER TABLE ds_schema_record_warnings ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS ds_schema_warn_company_isolation ON ds_schema_record_warnings;")
    op.execute("""
    CREATE POLICY ds_schema_warn_company_isolation ON ds_schema_record_warnings
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (
            current_setting('app.bypass_rls', true) = 'on'
            OR company_id::text = current_setting('app.current_company_id', true)
            OR current_setting('app.current_company_id', true) = ''
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS ds_schema_warn_company_isolation ON ds_schema_record_warnings;")
    op.execute("DROP TABLE IF EXISTS ds_schema_record_warnings;")

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_ds_table_enrich_source_id_pk;")
