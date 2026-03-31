"""DS Discovery & Learning tabloları (v2.56.0)

Revision ID: 003_ds_discovery_tables
Revises: 002_data_sources
Create Date: 2026-03-30
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "003_ds_discovery_tables"
down_revision: Union[str, None] = "002_data_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """DS keşif ve öğrenme tablolarını oluşturur."""
    op.execute("""
    -- Keşif İş Takibi
    CREATE TABLE IF NOT EXISTS ds_discovery_jobs (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        job_type VARCHAR(50) NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        result_summary JSONB,
        error_message TEXT,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        duration_ms INTEGER,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_source ON ds_discovery_jobs(source_id);
    CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_company ON ds_discovery_jobs(company_id);
    CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_type ON ds_discovery_jobs(job_type);
    CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_status ON ds_discovery_jobs(status);
    CREATE INDEX IF NOT EXISTS idx_ds_disc_jobs_created ON ds_discovery_jobs(created_at DESC);

    -- Keşfedilen DB Objeleri
    CREATE TABLE IF NOT EXISTS ds_db_objects (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        schema_name VARCHAR(100),
        object_name VARCHAR(200) NOT NULL,
        object_type VARCHAR(50) NOT NULL,
        column_count INTEGER DEFAULT 0,
        row_count_estimate BIGINT DEFAULT 0,
        columns_json JSONB,
        discovered_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ds_db_objects_source ON ds_db_objects(source_id);
    CREATE INDEX IF NOT EXISTS idx_ds_db_objects_type ON ds_db_objects(object_type);

    -- FK İlişkileri
    CREATE TABLE IF NOT EXISTS ds_db_relationships (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        from_schema VARCHAR(100),
        from_table VARCHAR(200) NOT NULL,
        from_column VARCHAR(200) NOT NULL,
        to_schema VARCHAR(100),
        to_table VARCHAR(200) NOT NULL,
        to_column VARCHAR(200) NOT NULL,
        constraint_name VARCHAR(200),
        discovered_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ds_db_rels_source ON ds_db_relationships(source_id);

    -- Örnek Veriler
    CREATE TABLE IF NOT EXISTS ds_db_samples (
        id SERIAL PRIMARY KEY,
        object_id INTEGER NOT NULL REFERENCES ds_db_objects(id) ON DELETE CASCADE,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        sample_query TEXT NOT NULL,
        sample_data JSONB NOT NULL,
        row_count INTEGER DEFAULT 0,
        fetched_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ds_db_samples_obj ON ds_db_samples(object_id);
    CREATE INDEX IF NOT EXISTS idx_ds_db_samples_source ON ds_db_samples(source_id);

    -- Öğrenme Zamanlaması
    CREATE TABLE IF NOT EXISTS ds_learning_schedules (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE UNIQUE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        schedule_type VARCHAR(50) NOT NULL,
        interval_value INTEGER DEFAULT 24,
        is_active BOOLEAN DEFAULT TRUE,
        last_run_at TIMESTAMP,
        next_run_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ds_learn_sched_source ON ds_learning_schedules(source_id);
    CREATE INDEX IF NOT EXISTS idx_ds_learn_sched_active ON ds_learning_schedules(is_active);

    -- Öğrenme Sonuçları
    CREATE TABLE IF NOT EXISTS ds_learning_results (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        job_id INTEGER REFERENCES ds_discovery_jobs(id) ON DELETE SET NULL,
        content_type VARCHAR(50) NOT NULL,
        content_text TEXT NOT NULL,
        embedding FLOAT[],
        metadata JSONB,
        score FLOAT DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ds_learn_results_source ON ds_learning_results(source_id);
    CREATE INDEX IF NOT EXISTS idx_ds_learn_results_company ON ds_learning_results(company_id);
    CREATE INDEX IF NOT EXISTS idx_ds_learn_results_type ON ds_learning_results(content_type);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ds_learning_results CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_learning_schedules CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_db_samples CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_db_relationships CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_db_objects CASCADE")
    op.execute("DROP TABLE IF EXISTS ds_discovery_jobs CASCADE")
