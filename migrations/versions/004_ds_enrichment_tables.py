"""DS Enrichment tabloları (v3.0.0)

Revision ID: 004_ds_enrichment_tables
Revises: 003_ds_discovery_tables
Create Date: 2026-03-30
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "004_ds_enrichment_tables"
down_revision: Union[str, None] = "003_ds_discovery_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """DS enrichment (LLM zenginleştirme) ve schema snapshot tablolarını oluşturur."""
    op.execute("""
    -- Schema Snapshot (diff tespiti için)
    CREATE TABLE IF NOT EXISTS ds_schema_snapshots (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        snapshot_hash VARCHAR(64) NOT NULL,
        snapshot_data JSONB NOT NULL,
        diff_summary JSONB,
        table_count INTEGER DEFAULT 0,
        column_count INTEGER DEFAULT 0,
        relationship_count INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_schema_snap_source ON ds_schema_snapshots(source_id);
    CREATE INDEX IF NOT EXISTS idx_schema_snap_created ON ds_schema_snapshots(created_at DESC);

    -- Tablo Zenginleştirme (LLM + Admin)
    CREATE TABLE IF NOT EXISTS ds_table_enrichments (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL,
        schema_name VARCHAR(128),
        table_name VARCHAR(256) NOT NULL,
        object_type VARCHAR(20) DEFAULT 'table',

        -- LLM üretimi
        business_name_tr VARCHAR(256),
        business_name_en VARCHAR(256),
        description_tr TEXT,
        category VARCHAR(64),
        sample_questions JSONB,
        llm_confidence FLOAT DEFAULT 0,

        -- Bileşik skor
        enrichment_score FLOAT DEFAULT 0,

        -- Admin düzeltmesi
        admin_approved BOOLEAN DEFAULT FALSE,
        admin_label_tr VARCHAR(256),
        admin_notes TEXT,
        approved_by INTEGER,
        approved_at TIMESTAMPTZ,

        -- İzleme
        schema_hash VARCHAR(64),
        last_enriched_at TIMESTAMPTZ,
        version INTEGER DEFAULT 1,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),

        UNIQUE(source_id, schema_name, table_name)
    );
    CREATE INDEX IF NOT EXISTS idx_table_enrich_source ON ds_table_enrichments(source_id);
    CREATE INDEX IF NOT EXISTS idx_table_enrich_score ON ds_table_enrichments(enrichment_score);
    CREATE INDEX IF NOT EXISTS idx_table_enrich_approved ON ds_table_enrichments(admin_approved);
    CREATE INDEX IF NOT EXISTS idx_table_enrich_active ON ds_table_enrichments(is_active);

    -- Sütun Zenginleştirme (LLM + Admin)
    CREATE TABLE IF NOT EXISTS ds_column_enrichments (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        table_enrichment_id INTEGER REFERENCES ds_table_enrichments(id) ON DELETE CASCADE,
        column_name VARCHAR(256) NOT NULL,
        data_type VARCHAR(128),

        -- LLM üretimi
        business_name_tr VARCHAR(256),
        description_tr TEXT,
        is_key_column BOOLEAN DEFAULT FALSE,
        semantic_type VARCHAR(64),

        -- Admin düzeltmesi
        admin_label_tr VARCHAR(256),
        admin_approved BOOLEAN DEFAULT FALSE,

        -- İzleme
        column_hash VARCHAR(64),
        version INTEGER DEFAULT 1,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),

        UNIQUE(table_enrichment_id, column_name)
    );
    CREATE INDEX IF NOT EXISTS idx_col_enrich_table ON ds_column_enrichments(table_enrichment_id);
    CREATE INDEX IF NOT EXISTS idx_col_enrich_source ON ds_column_enrichments(source_id);

    -- ds_learning_results genişletme (versiyon + geçerlilik)
    ALTER TABLE ds_learning_results ADD COLUMN IF NOT EXISTS is_valid BOOLEAN DEFAULT TRUE;
    ALTER TABLE ds_learning_results ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ;
    ALTER TABLE ds_learning_results ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
    ALTER TABLE ds_learning_results ADD COLUMN IF NOT EXISTS enrichment_id INTEGER;

    CREATE INDEX IF NOT EXISTS idx_ds_learn_results_valid ON ds_learning_results(is_valid);
    CREATE INDEX IF NOT EXISTS idx_ds_learn_results_enrich ON ds_learning_results(enrichment_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ds_column_enrichments CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_table_enrichments CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_schema_snapshots CASCADE")
    op.execute("""
    ALTER TABLE ds_learning_results DROP COLUMN IF EXISTS is_valid;
    ALTER TABLE ds_learning_results DROP COLUMN IF EXISTS invalidated_at;
    ALTER TABLE ds_learning_results DROP COLUMN IF EXISTS version;
    ALTER TABLE ds_learning_results DROP COLUMN IF EXISTS enrichment_id;
    """)
