"""Yeni data_sources tablosu

Revision ID: 002_data_sources
Revises: 001_baseline
Create Date: 2026-03-23
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "002_data_sources"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """data_sources tablosunu oluşturur."""
    op.execute("""
    CREATE TABLE IF NOT EXISTS data_sources (
        id SERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        name VARCHAR(200) NOT NULL,
        source_type VARCHAR(50) NOT NULL,
        db_type VARCHAR(50),
        host VARCHAR(500),
        port INTEGER,
        db_name VARCHAR(200),
        db_user VARCHAR(200),
        db_password_encrypted VARCHAR(500),
        file_server_path VARCHAR(1000),
        description TEXT,
        is_active BOOLEAN DEFAULT true,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        created_by INTEGER REFERENCES users(id)
    );

    CREATE INDEX IF NOT EXISTS idx_data_sources_company ON data_sources(company_id);
    CREATE INDEX IF NOT EXISTS idx_data_sources_type ON data_sources(source_type);
    CREATE INDEX IF NOT EXISTS idx_data_sources_active ON data_sources(is_active);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_sources CASCADE")
