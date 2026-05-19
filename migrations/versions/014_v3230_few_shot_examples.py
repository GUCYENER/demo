"""v3.23.0: few_shot_examples tablosu (Faz 4b)

Revision ID: 014_v3230_few_shot_examples
Revises: 013_v3230_user_preferences
Create Date: 2026-05-17

Faz 4 — Few-shot Store
----------------------
METIS + ORACLE + PROMETHEUS plan: validated NL→SQL örnek havuzu.

Pipeline'da sql_generate node few-shot retrieval ile bağlamı zenginleştirir:
- Soru embedding hesaplanır
- Top-K benzer örnek seçilir (hybrid: semantic + intent + schema_signature match)
- LLM prompt'una "Örnekler:" bloğu enjekte edilir → SQL kalitesi artar

Beslenme:
- execute_node başarıyla dönen sorgular (success_rate=1.0)
- Kullanıcı manuel olarak işaretlerse (UI'da "Bunu örnek olarak sakla")
- Synthetic Q generator (K8) onaylanmış sorgular

CREATE TABLE few_shot_examples (
    id BIGSERIAL PK,
    company_id INT NOT NULL,
    source_id INT (NULL → global),
    question TEXT NOT NULL,
    sql_query TEXT NOT NULL,
    intent VARCHAR(64)              -- lookup/aggregate/report/follow_up
    schema_signature VARCHAR(512)   -- "schema.tableA,schema.tableB" (alfabetik)
    embedding VECTOR(384) (graceful fallback)
    tsv TSVECTOR (trigger)
    usage_count INT DEFAULT 0
    success_rate REAL DEFAULT 1.0   -- moving average (basit)
    last_used_at TIMESTAMP
    created_by INT REFERENCES users(id)
    created_at, updated_at
);

RLS: yok — company_id ve source_id application'da filtrelenir.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "014_v3230_few_shot_examples"
down_revision: Union[str, None] = "013_v3230_user_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector availability check (Faz 2 pattern)
    has_pgvector = """
    SELECT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'vector'
    );
    """

    op.execute("""
    DO $$
    DECLARE
        v_has_vector BOOLEAN;
        v_emb_type TEXT;
    BEGIN
        SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO v_has_vector;
        IF v_has_vector THEN
            v_emb_type := 'vector(384)';
        ELSE
            v_emb_type := 'float[]';
        END IF;

        EXECUTE format($f$
        CREATE TABLE IF NOT EXISTS few_shot_examples (
            id BIGSERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            source_id INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            sql_query TEXT NOT NULL,
            intent VARCHAR(64),
            schema_signature VARCHAR(512),
            embedding %s,
            tsv TSVECTOR,
            usage_count INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 1.0,
            last_used_at TIMESTAMP,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        $f$, v_emb_type);
    END $$;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_few_shot_company ON few_shot_examples(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_few_shot_source ON few_shot_examples(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_few_shot_intent ON few_shot_examples(intent);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_few_shot_signature ON few_shot_examples(schema_signature);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_few_shot_usage ON few_shot_examples(usage_count DESC);")

    # tsv trigger
    op.execute("""
    CREATE OR REPLACE FUNCTION few_shot_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.tsv := to_tsvector('pg_catalog.simple',
            coalesce(NEW.question, '') || ' ' ||
            coalesce(NEW.intent, '') || ' ' ||
            coalesce(NEW.schema_signature, '')
        );
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    DROP TRIGGER IF EXISTS trg_few_shot_tsv ON few_shot_examples;
    CREATE TRIGGER trg_few_shot_tsv
        BEFORE INSERT OR UPDATE ON few_shot_examples
        FOR EACH ROW EXECUTE FUNCTION few_shot_tsv_update();
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_few_shot_tsv ON few_shot_examples USING gin(tsv);")

    # HNSW index on embedding (pgvector varsa)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_few_shot_emb_hnsw
                         ON few_shot_examples USING hnsw (embedding vector_cosine_ops)
                         WITH (m=16, ef_construction=64)';
            EXCEPTION WHEN OTHERS THEN
                -- HNSW yoksa ivfflat dene
                BEGIN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_few_shot_emb_ivf
                             ON few_shot_examples USING ivfflat (embedding vector_cosine_ops)
                             WITH (lists=100)';
                EXCEPTION WHEN OTHERS THEN
                    -- index oluşturulamadıysa devam et
                    NULL;
                END;
            END;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_few_shot_tsv ON few_shot_examples;")
    op.execute("DROP FUNCTION IF EXISTS few_shot_tsv_update();")
    op.execute("DROP TABLE IF EXISTS few_shot_examples CASCADE;")
