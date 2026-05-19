"""v3.21.0: ds_learning_results IVFFlat → HNSW migration (Faz 2e)

Revision ID: 011_v3210_ivfflat_to_hnsw
Revises: 010_v3210_lr_tsvector
Create Date: 2026-05-17

Faz 2e — Vector index hardening
-------------------------------
schema.py [A8] migration'da `idx_rag_chunks_embedding_ivfflat` IVFFlat ile
oluşturuluyordu. v3.21.0'da HNSW'ye geçiş yapılır:

    IVFFlat:
        - WITH (lists = 100) — küçük datasette aşırı liste sayısı recall düşürür
        - Build hızlı, query orta hızlı
        - Recall ~85-90%

    HNSW (pgvector 0.5.0+):
        - WITH (m = 16, ef_construction = 64)
        - Build daha yavaş ama query ~10x hızlı, recall ~95-98%

Etki:
    - ds_learning_results.embedding: HNSW (varsa)
    - rag_chunks.embedding: HNSW (opsiyonel — referans için aynı patern)

Fallback davranışı:
    - pgvector yoksa: hiçbir şey yapma
    - HNSW yoksa (eski pgvector): IVFFlat korunur
    - HNSW oluşturulursa: eski IVFFlat DROP edilir

Downgrade:
    HNSW DROP → IVFFlat yeniden oluştur (lists=100, schema.py [A8] paterni)
"""
from typing import Sequence, Union
from alembic import op

revision: str = "011_v3210_ivfflat_to_hnsw"
down_revision: Union[str, None] = "010_v3210_lr_tsvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TARGETS = (
    ("ds_learning_results", "idx_ds_lr_embedding_hnsw", "idx_ds_lr_embedding_ivfflat"),
    ("rag_chunks", "idx_rag_chunks_embedding_hnsw", "idx_rag_chunks_embedding_ivfflat"),
)


def upgrade() -> None:
    op.execute("""
    DO $$
    DECLARE
        has_vector BOOLEAN;
        has_hnsw   BOOLEAN;
    BEGIN
        SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_vector;
        IF NOT has_vector THEN
            RAISE NOTICE 'pgvector yok — IVFFlat/HNSW migration atlandi';
            RETURN;
        END IF;

        -- HNSW access method var mi?
        SELECT EXISTS(SELECT 1 FROM pg_am WHERE amname = 'hnsw') INTO has_hnsw;
        IF NOT has_hnsw THEN
            RAISE NOTICE 'HNSW access method yok (pgvector <0.5.0) — IVFFlat korunuyor';
            RETURN;
        END IF;

        -- ds_learning_results — embedding vector tipi mi? (FLOAT[] olmamali)
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'ds_learning_results'
              AND column_name = 'embedding'
              AND udt_name = 'vector'
        ) THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ds_lr_embedding_hnsw '
                        'ON ds_learning_results USING hnsw (embedding vector_cosine_ops) '
                        'WITH (m = 16, ef_construction = 64)';
                EXECUTE 'DROP INDEX IF EXISTS idx_ds_lr_embedding_ivfflat';
                RAISE NOTICE 'ds_learning_results HNSW olusturuldu, IVFFlat dropped';
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'ds_learning_results HNSW basarisiz: %', SQLERRM;
            END;
        ELSE
            RAISE NOTICE 'ds_learning_results.embedding vektor tipinde degil — atlandi';
        END IF;

        -- rag_chunks
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'rag_chunks'
              AND column_name = 'embedding'
              AND udt_name = 'vector'
        ) THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw '
                        'ON rag_chunks USING hnsw (embedding vector_cosine_ops) '
                        'WITH (m = 16, ef_construction = 64)';
                EXECUTE 'DROP INDEX IF EXISTS idx_rag_chunks_embedding_ivfflat';
                RAISE NOTICE 'rag_chunks HNSW olusturuldu, IVFFlat dropped';
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'rag_chunks HNSW basarisiz: %', SQLERRM;
            END;
        END IF;
    END $$;
    """)


def downgrade() -> None:
    """HNSW → IVFFlat geri al (pgvector varsa)."""
    op.execute("""
    DO $$
    DECLARE has_vector BOOLEAN;
    BEGIN
        SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector') INTO has_vector;
        IF NOT has_vector THEN RETURN; END IF;

        EXECUTE 'DROP INDEX IF EXISTS idx_ds_lr_embedding_hnsw';
        EXECUTE 'DROP INDEX IF EXISTS idx_rag_chunks_embedding_hnsw';

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'ds_learning_results'
              AND column_name = 'embedding' AND udt_name = 'vector'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ds_lr_embedding_ivfflat '
                    'ON ds_learning_results USING ivfflat (embedding vector_cosine_ops) '
                    'WITH (lists = 100)';
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'rag_chunks'
              AND column_name = 'embedding' AND udt_name = 'vector'
        ) THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_ivfflat '
                    'ON rag_chunks USING ivfflat (embedding vector_cosine_ops) '
                    'WITH (lists = 100)';
        END IF;
    END $$;
    """)
