"""v3.14.0: Golden SQL, Business Process Templates, Pending DB Queries, FK unique index

Revision ID: 006_v3140_async_golden_sql
Revises: 005_v344_rag_pipeline_optimization
Create Date: 2026-05-14
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "006_v3140_async_golden_sql"
down_revision: Union[str, None] = "005_v344_rag_pipeline_optimization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """v3.14.0 yeni tablolar ve index'ler."""

    # 1. Golden SQL Store
    op.execute("""
    CREATE TABLE IF NOT EXISTS golden_sql (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        question_text TEXT NOT NULL,
        question_embedding FLOAT[],
        sql_query TEXT NOT NULL,
        tables_used TEXT[],
        dialect VARCHAR(20) DEFAULT 'postgresql',
        verified BOOLEAN DEFAULT FALSE,
        usage_count INTEGER DEFAULT 0,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_golden_sql_source ON golden_sql(source_id);
    CREATE INDEX IF NOT EXISTS idx_golden_sql_company ON golden_sql(company_id);
    CREATE INDEX IF NOT EXISTS idx_golden_sql_verified ON golden_sql(verified);
    """)

    # 2. İş Süreci Şablonları
    op.execute("""
    CREATE TABLE IF NOT EXISTS business_process_templates (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        process_name VARCHAR(200) NOT NULL,
        process_name_tr VARCHAR(200),
        description_tr TEXT,
        tables_used TEXT[] NOT NULL,
        typical_queries JSONB,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_bpt_source ON business_process_templates(source_id);
    """)

    # 3. Asenkron DB Sorgu Takibi
    op.execute("""
    CREATE TABLE IF NOT EXISTS pending_db_queries (
        id SERIAL PRIMARY KEY,
        dialog_id INTEGER NOT NULL REFERENCES dialogs(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id),
        company_id INTEGER NOT NULL,
        query_text TEXT NOT NULL,
        query_text_short VARCHAR(80) NOT NULL,
        status VARCHAR(20) DEFAULT 'queued',
        source_id INTEGER REFERENCES data_sources(id),
        source_name VARCHAR(200),
        sql_generated TEXT,
        result_message_id INTEGER REFERENCES dialog_messages(id) ON DELETE SET NULL,
        result_summary VARCHAR(200),
        error_message TEXT,
        started_at TIMESTAMP DEFAULT NOW(),
        completed_at TIMESTAMP,
        elapsed_ms INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_pending_dbq_user ON pending_db_queries(user_id, status);
    CREATE INDEX IF NOT EXISTS idx_pending_dbq_dialog ON pending_db_queries(dialog_id);
    """)

    # 4. FK unique index (ON CONFLICT desteği)
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ds_db_rels_unique
        ON ds_db_relationships(source_id, COALESCE(from_schema,''), from_table, from_column,
                               COALESCE(to_schema,''), to_table, to_column);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pending_db_queries CASCADE")
    op.execute("DROP TABLE IF EXISTS business_process_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS golden_sql CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_ds_db_rels_unique")
