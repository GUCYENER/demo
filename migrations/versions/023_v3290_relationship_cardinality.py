"""v3.29.0: Relationship Cardinality & Junction Metadata

Revision ID: 023_v3290_relationship_cardinality
Revises: 022_v3270_synonym_suggestions
Create Date: 2026-05-19

v3.29.0 — Faz 6 G1: Derin DB Anlama
====================================
Plan: C:/Users/EXT02D059293/.claude/plans/binary-hugging-bengio.md

ds_db_relationships tablosuna cardinality + junction metadata ekler.
Path resolver (G3) bu alanları FK graph üzerinde yön ağırlığı ve
N:M köprü tespit için kullanır.

Yeni kolonlar:
    - cardinality_from CHAR(1)  ('1' | 'N')          — child taraf
    - cardinality_to   CHAR(1)  ('1' | 'N')          — parent taraf
    - is_junction      BOOLEAN  DEFAULT FALSE        — N:M köprü tablosu mu
    - path_weight      SMALLINT DEFAULT 100          — yön tercih ağırlığı (düşük=tercih)
    - inverse_relationship_id  INTEGER NULL          — ters yön self FK
    - confidence_score FLOAT    DEFAULT 0.0          — analiz güveni 0..1
    - last_analyzed_at TIMESTAMPTZ NULL
"""
from typing import Sequence, Union
from alembic import op

revision: str = "023_v3290_relationship_cardinality"
down_revision: Union[str, None] = "022_v3270_synonym_suggestions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE ds_db_relationships
        ADD COLUMN IF NOT EXISTS cardinality_from CHAR(1)
            CHECK (cardinality_from IS NULL OR cardinality_from IN ('1','N')),
        ADD COLUMN IF NOT EXISTS cardinality_to CHAR(1)
            CHECK (cardinality_to IS NULL OR cardinality_to IN ('1','N')),
        ADD COLUMN IF NOT EXISTS is_junction BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS path_weight SMALLINT NOT NULL DEFAULT 100,
        ADD COLUMN IF NOT EXISTS inverse_relationship_id INTEGER
            REFERENCES ds_db_relationships(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS confidence_score REAL NOT NULL DEFAULT 0.0
            CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
        ADD COLUMN IF NOT EXISTS last_analyzed_at TIMESTAMPTZ;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_db_rels_junction ON ds_db_relationships(source_id) WHERE is_junction = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_db_rels_confidence ON ds_db_relationships(source_id, confidence_score);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_db_rels_inverse ON ds_db_relationships(inverse_relationship_id) WHERE inverse_relationship_id IS NOT NULL;")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ds_db_rels_inverse;")
    op.execute("DROP INDEX IF EXISTS idx_ds_db_rels_confidence;")
    op.execute("DROP INDEX IF EXISTS idx_ds_db_rels_junction;")
    op.execute("""
    ALTER TABLE ds_db_relationships
        DROP COLUMN IF EXISTS last_analyzed_at,
        DROP COLUMN IF EXISTS confidence_score,
        DROP COLUMN IF EXISTS inverse_relationship_id,
        DROP COLUMN IF EXISTS path_weight,
        DROP COLUMN IF EXISTS is_junction,
        DROP COLUMN IF EXISTS cardinality_to,
        DROP COLUMN IF EXISTS cardinality_from;
    """)
