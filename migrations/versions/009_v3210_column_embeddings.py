"""v3.21.0: ds_column_embeddings tablosu + RLS + HNSW index (Faz 2a)

Revision ID: 009_v3210_column_embeddings
Revises: 008_v3200_rls_remove_legacy
Create Date: 2026-05-17

Faz 2 — Column-Level Embedding + Hybrid Search
----------------------------------------------
Aynı isimde tablo/kolon ayrımı için kolon-bazlı embedding tablosu eklenir.

ds_column_embeddings:
    - source_id (RLS scope)
    - schema/table/column triplet (UNIQUE)
    - data_type, nullable, pk/fk flag
    - business_name_tr, synonyms[] (TR business glossary)
    - semantic_type (email/phone/id/datetime/money/name vs.)
    - sample_values JSONB (preview)
    - description (LLM ile sentetik)
    - embedding VECTOR(384) → HNSW index (cosine)  [pgvector varsa]
    - tsv TSVECTOR (Türkçe full-text)  → GIN index

Hybrid retrieval (Faz 2d):
    hybrid_score = 0.65 * (1 - cosine_dist) + 0.35 * ts_rank

RLS politikası 007/008'deki strict form ile aynı (legacy passthrough YOK).

pgvector yoksa: embedding kolonu FLOAT[] olarak oluşturulur; vector index'i
schema.py'deki v3.3.0 [A8] pattern'i ile gelecekte upgrade edilir.
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "009_v3210_column_embeddings"
down_revision: Union[str, None] = "008_v3200_rls_remove_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY_STRICT = """(
    current_setting('app.bypass_rls', true) = 'on'
    OR source_id::text = current_setting('app.current_source_id', true)
)"""


def upgrade() -> None:
    # pgvector — best-effort (schema.py [A8] paterni)
    op.execute("""
    DO $$
    BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
        RAISE NOTICE 'pgvector aktif (009)';
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'pgvector yok, FLOAT[] fallback ile devam: %', SQLERRM;
    END $$;
    """)

    # Tablo — embedding kolonu için pgvector varsa vector(384), yoksa FLOAT[]
    op.execute("""
    DO $$
    DECLARE
        v_has_vector BOOLEAN;
        v_embedding_type TEXT;
    BEGIN
        SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')
            INTO v_has_vector;
        v_embedding_type := CASE WHEN v_has_vector THEN 'vector(384)' ELSE 'FLOAT[]' END;

        EXECUTE format($f$
            CREATE TABLE IF NOT EXISTS ds_column_embeddings (
                id BIGSERIAL PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
                schema_name VARCHAR(128),
                table_name  VARCHAR(256) NOT NULL,
                column_name VARCHAR(256) NOT NULL,
                data_type   VARCHAR(64),
                is_nullable BOOLEAN DEFAULT TRUE,
                is_pk BOOLEAN DEFAULT FALSE,
                is_fk BOOLEAN DEFAULT FALSE,
                business_name_tr VARCHAR(256),
                synonyms TEXT[] DEFAULT ARRAY[]::TEXT[],
                semantic_type VARCHAR(32),
                sample_values JSONB,
                description TEXT,
                embedding %s,
                tsv TSVECTOR,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_ds_col_emb UNIQUE (source_id, schema_name, table_name, column_name)
            )
        $f$, v_embedding_type);
    END $$;
    """)

    # tsv otomatik dolum — BEFORE INSERT/UPDATE trigger
    op.execute("""
    CREATE OR REPLACE FUNCTION ds_col_emb_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.tsv := to_tsvector('pg_catalog.simple',
            coalesce(NEW.business_name_tr,'') || ' ' ||
            coalesce(NEW.description,'')      || ' ' ||
            coalesce(array_to_string(NEW.synonyms,' '), '') || ' ' ||
            coalesce(NEW.column_name,'')      || ' ' ||
            coalesce(NEW.table_name,'')
        );
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    DROP TRIGGER IF EXISTS trg_ds_col_emb_tsv ON ds_column_embeddings;
    CREATE TRIGGER trg_ds_col_emb_tsv
        BEFORE INSERT OR UPDATE ON ds_column_embeddings
        FOR EACH ROW EXECUTE FUNCTION ds_col_emb_tsv_update();
    """)

    # Standard indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_col_emb_source ON ds_column_embeddings(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_col_emb_tbl ON ds_column_embeddings(source_id, schema_name, table_name);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_col_emb_tsv ON ds_column_embeddings USING gin(tsv);")

    # Vector index — sadece pgvector varsa; HNSW dene, olmazsa ivfflat
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ds_col_emb_hnsw '
                        'ON ds_column_embeddings USING hnsw (embedding vector_cosine_ops) '
                        'WITH (m = 16, ef_construction = 64)';
                RAISE NOTICE 'HNSW index olusturuldu (ds_column_embeddings)';
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'HNSW basarisiz, ivfflat fallback: %', SQLERRM;
                BEGIN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ds_col_emb_ivfflat '
                            'ON ds_column_embeddings USING ivfflat (embedding vector_cosine_ops) '
                            'WITH (lists = 100)';
                EXCEPTION WHEN OTHERS THEN
                    RAISE NOTICE 'ivfflat de basarisiz: %', SQLERRM;
                END;
            END;
        ELSE
            RAISE NOTICE 'pgvector yok, vector index atlandi (FLOAT[] fallback)';
        END IF;
    END $$;
    """)

    # RLS
    op.execute("ALTER TABLE ds_column_embeddings ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE ds_column_embeddings FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
    CREATE POLICY rls_source_scoped ON ds_column_embeddings
        FOR ALL
        USING {_POLICY_STRICT}
        WITH CHECK {_POLICY_STRICT};
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rls_source_scoped ON ds_column_embeddings;")
    op.execute("DROP TRIGGER IF EXISTS trg_ds_col_emb_tsv ON ds_column_embeddings;")
    op.execute("DROP TABLE IF EXISTS ds_column_embeddings CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS ds_col_emb_tsv_update();")
