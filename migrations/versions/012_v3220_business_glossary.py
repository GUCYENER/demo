"""v3.22.0: business_glossary tablosu (Faz 3a)

Revision ID: 012_v3220_business_glossary
Revises: 011_v3210_ivfflat_to_hnsw
Create Date: 2026-05-17

Faz 3 — Business Glossary
-------------------------
APOLLO master plan: kullanıcı domain dilini canonical tablo/kolona eşler.

CREATE TABLE business_glossary (
    id BIGSERIAL PK,
    company_id INT FK (NULL → genel sözlük),
    term VARCHAR,
    synonyms TEXT[],
    canonical_schema VARCHAR,
    canonical_table VARCHAR,
    canonical_column VARCHAR,     -- NULL → tablo seviyesi map
    description TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

İndexler:
    - (company_id, term) — lookup
    - GIN(synonyms) — synonym arama
    - tsv (içerik) — TSV match

RLS yok — bu metadata company seviyesinde (RLS source_id'ye bağlı).
Filtreleme application'da: WHERE company_id IS NULL OR company_id = $current.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "012_v3220_business_glossary"
down_revision: Union[str, None] = "011_v3210_ivfflat_to_hnsw"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS business_glossary (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        term VARCHAR(256) NOT NULL,
        synonyms TEXT[] DEFAULT ARRAY[]::TEXT[],
        canonical_schema VARCHAR(128),
        canonical_table VARCHAR(256),
        canonical_column VARCHAR(256),
        description TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        CONSTRAINT uq_business_glossary_company_term UNIQUE (company_id, term)
    );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_company ON business_glossary(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_term ON business_glossary(term);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_syn ON business_glossary USING gin(synonyms);")

    # tsv kolonu + trigger (Faz 2 pattern — IMMUTABLE problemi nedeniyle GENERATED yerine trigger)
    op.execute("ALTER TABLE business_glossary ADD COLUMN IF NOT EXISTS tsv TSVECTOR;")
    op.execute("""
    CREATE OR REPLACE FUNCTION business_glossary_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.tsv := to_tsvector('pg_catalog.simple',
            coalesce(NEW.term, '') || ' ' ||
            coalesce(array_to_string(NEW.synonyms, ' '), '') || ' ' ||
            coalesce(NEW.description, '')
        );
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    DROP TRIGGER IF EXISTS trg_business_glossary_tsv ON business_glossary;
    CREATE TRIGGER trg_business_glossary_tsv
        BEFORE INSERT OR UPDATE ON business_glossary
        FOR EACH ROW EXECUTE FUNCTION business_glossary_tsv_update();
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_tsv ON business_glossary USING gin(tsv);")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_business_glossary_tsv ON business_glossary;")
    op.execute("DROP FUNCTION IF EXISTS business_glossary_tsv_update();")
    op.execute("DROP TABLE IF EXISTS business_glossary CASCADE;")
