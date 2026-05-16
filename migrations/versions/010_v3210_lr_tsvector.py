"""v3.21.0: ds_learning_results.tsv TSVECTOR + GIN index + backfill (Faz 2b)

Revision ID: 010_v3210_lr_tsvector
Revises: 009_v3210_column_embeddings
Create Date: 2026-05-17

Faz 2b — Hybrid Retrieval altyapısı
-----------------------------------
ds_learning_results tablosuna TSVECTOR kolonu eklenir:
    - tsv: content_text üzerinden Türkçe full-text search vektörü
    - BEFORE INSERT/UPDATE trigger ile otomatik dolum
    - GIN index → hızlı ts_rank/@@ sorguları
    - Mevcut satırlar için backfill

Hybrid retrieval Faz 2d:
    score = 0.65 * (1 - cosine_dist) + 0.35 * ts_rank(tsv, query)

config: 'pg_catalog.simple' kullanıyoruz — 'turkish' config olmayabilir;
       startup'ta CREATE TEXT SEARCH CONFIG ile geliştirilebilir.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "010_v3210_lr_tsvector"
down_revision: Union[str, None] = "009_v3210_column_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kolon — idempotent
    op.execute("ALTER TABLE ds_learning_results ADD COLUMN IF NOT EXISTS tsv TSVECTOR;")

    # Trigger function — content_text + metadata->>'table_name' + content_type
    op.execute("""
    CREATE OR REPLACE FUNCTION ds_lr_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.tsv := to_tsvector('pg_catalog.simple',
            coalesce(NEW.content_text, '') || ' ' ||
            coalesce(NEW.content_type, '') || ' ' ||
            coalesce(NEW.metadata->>'table_name', '') || ' ' ||
            coalesce(NEW.metadata->>'schema_name', '')
        );
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    DROP TRIGGER IF EXISTS trg_ds_lr_tsv ON ds_learning_results;
    CREATE TRIGGER trg_ds_lr_tsv
        BEFORE INSERT OR UPDATE ON ds_learning_results
        FOR EACH ROW EXECUTE FUNCTION ds_lr_tsv_update();
    """)

    # Backfill — RLS bypass ile (admin migration)
    op.execute("SELECT set_config('app.bypass_rls', 'on', false);")
    op.execute("""
    UPDATE ds_learning_results
       SET tsv = to_tsvector('pg_catalog.simple',
            coalesce(content_text, '') || ' ' ||
            coalesce(content_type, '') || ' ' ||
            coalesce(metadata->>'table_name', '') || ' ' ||
            coalesce(metadata->>'schema_name', '')
       )
     WHERE tsv IS NULL;
    """)
    op.execute("SELECT set_config('app.bypass_rls', '', false);")

    # GIN index
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_lr_tsv ON ds_learning_results USING gin(tsv);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ds_lr_tsv;")
    op.execute("DROP TRIGGER IF EXISTS trg_ds_lr_tsv ON ds_learning_results;")
    op.execute("DROP FUNCTION IF EXISTS ds_lr_tsv_update();")
    op.execute("ALTER TABLE ds_learning_results DROP COLUMN IF EXISTS tsv;")
