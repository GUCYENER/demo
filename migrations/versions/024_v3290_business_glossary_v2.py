"""v3.29.1: Business Glossary v2 — term_type + expansion_tr + mapped_* + embedding

Revision ID: 024_v3290_business_glossary_v2
Revises: 023_v3290_relationship_cardinality
Create Date: 2026-05-19

v3.29.1 — Faz 6 G2 (1/2): Glossary genişletmesi
-----------------------------------------------
Plan: C:/Users/EXT02D059293/.claude/plans/binary-hugging-bengio.md

Mevcut business_glossary tablosuna eklenir:
    - term_type        VARCHAR(32)     'acronym'|'synonym'|'jargon'|'metric'|'process'
    - expansion_tr     TEXT             "L1" → "Level 1 Destek Ekibi"
    - mapped_table     VARCHAR(256)     query expansion sonrası tablo hint
    - mapped_columns   TEXT[]           ilgili kolonlar
    - embedding        vector(384)|float[]   intent_extract için cosine
    - admin_verified   BOOLEAN          LLM-otomatik aday vs admin-onaylı
    - usage_count      INTEGER          kullanım sıklığı (sıralama için)
    - last_used_at     TIMESTAMPTZ

Mevcut sütunlar (term, synonyms, canonical_*) korunur.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "024_v3290_business_glossary_v2"
down_revision: Union[str, None] = "023_v3290_relationship_cardinality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Skaler yeni alanlar
    op.execute("""
    ALTER TABLE business_glossary
        ADD COLUMN IF NOT EXISTS term_type VARCHAR(32)
            CHECK (term_type IS NULL OR term_type IN ('acronym','synonym','jargon','metric','process')),
        ADD COLUMN IF NOT EXISTS expansion_tr TEXT,
        ADD COLUMN IF NOT EXISTS mapped_table VARCHAR(256),
        ADD COLUMN IF NOT EXISTS mapped_columns TEXT[] DEFAULT ARRAY[]::TEXT[],
        ADD COLUMN IF NOT EXISTS admin_verified BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS usage_count INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;
    """)

    # 2. Embedding (pgvector varsa vector(384), yoksa float[])
    op.execute("""
    DO $$
    DECLARE
        v_emb_type TEXT;
        v_exists   BOOLEAN;
    BEGIN
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='business_glossary' AND column_name='embedding'
        ) INTO v_exists;
        IF NOT v_exists THEN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                v_emb_type := 'vector(384)';
            ELSE
                v_emb_type := 'float[]';
            END IF;
            EXECUTE format('ALTER TABLE business_glossary ADD COLUMN embedding %s', v_emb_type);
        END IF;
    END $$;
    """)

    # 3. İndeksler
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_term_type ON business_glossary(term_type) WHERE term_type IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_admin_verified ON business_glossary(admin_verified, company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_mapped_table ON business_glossary(mapped_table) WHERE mapped_table IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_glossary_usage ON business_glossary(usage_count DESC) WHERE admin_verified = TRUE;")

    # 4. HNSW on embedding (pgvector varsa; fallback ivfflat)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_business_glossary_emb_hnsw
                         ON business_glossary USING hnsw (embedding vector_cosine_ops)
                         WITH (m=16, ef_construction=64)';
            EXCEPTION WHEN OTHERS THEN
                BEGIN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_business_glossary_emb_ivf
                             ON business_glossary USING ivfflat (embedding vector_cosine_ops)
                             WITH (lists=100)';
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
            END;
        END IF;
    END $$;
    """)

    # 5. tsv trigger'ı expansion_tr + mapped_table'ı içerecek şekilde güncelle
    op.execute("""
    CREATE OR REPLACE FUNCTION business_glossary_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.tsv := to_tsvector('pg_catalog.simple',
            coalesce(NEW.term, '') || ' ' ||
            coalesce(array_to_string(NEW.synonyms, ' '), '') || ' ' ||
            coalesce(NEW.description, '') || ' ' ||
            coalesce(NEW.expansion_tr, '') || ' ' ||
            coalesce(NEW.mapped_table, '')
        );
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # tsv trigger'ı eski haline döndür
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

    op.execute("DROP INDEX IF EXISTS idx_business_glossary_emb_hnsw;")
    op.execute("DROP INDEX IF EXISTS idx_business_glossary_emb_ivf;")
    op.execute("DROP INDEX IF EXISTS idx_business_glossary_usage;")
    op.execute("DROP INDEX IF EXISTS idx_business_glossary_mapped_table;")
    op.execute("DROP INDEX IF EXISTS idx_business_glossary_admin_verified;")
    op.execute("DROP INDEX IF EXISTS idx_business_glossary_term_type;")
    op.execute("""
    ALTER TABLE business_glossary
        DROP COLUMN IF EXISTS embedding,
        DROP COLUMN IF EXISTS last_used_at,
        DROP COLUMN IF EXISTS usage_count,
        DROP COLUMN IF EXISTS admin_verified,
        DROP COLUMN IF EXISTS mapped_columns,
        DROP COLUMN IF EXISTS mapped_table,
        DROP COLUMN IF EXISTS expansion_tr,
        DROP COLUMN IF EXISTS term_type;
    """)
