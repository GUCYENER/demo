"""v3.29.2: Template versioning — template_version + complexity_score + join_path

Revision ID: 026_v3290_template_versioning
Revises: 025_v3290_code_value_dictionary
Create Date: 2026-05-19

v3.29.2 — Faz 6 G3: Çoklu-Tablo Şablonları
------------------------------------------
Plan: C:/Users/EXT02D059293/.claude/plans/binary-hugging-bengio.md

learned_db_queries ve ds_synthetic_query_runs'a şu kolonları ekler:

    - template_version   SMALLINT DEFAULT 1
        1: v3.27 (LOOKUP_JOIN, AGGREGATE_COUNT)
        2: v3.29.2 (CHAIN_JOIN_*, CTE_*, LATERAL_TOP_K, STRING_AGG_*, JUNCTION_N2M,
           TIME_SERIES_GENERATE, WINDOW_RUNNING_TOTAL)

    - complexity_score   SMALLINT DEFAULT 1
        1: tek tablo
        2: 2-hop join
        3: 3-hop join veya basit CTE
        4: 4+ hop, window/LATERAL
        5: CTE chain + window + STRING_AGG

    - join_path          TEXT[]
        ['public.problem','public.party','public.party_relation'] sırasıyla.
        Debug + few-shot match için kullanılır.

ds_synthetic_query_runs'taki UNIQUE constraint genişletilmez — aynı
(relationship_id, template_kind) bir tek satıra mappinglenir (G3'te
template_kind'ın string adı tek başına yeterli ayrımı sağlar).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "026_v3290_template_versioning"
down_revision: Union[str, None] = "025_v3290_code_value_dictionary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # learned_db_queries
    op.execute("""
    ALTER TABLE learned_db_queries
        ADD COLUMN IF NOT EXISTS template_version SMALLINT NOT NULL DEFAULT 1
            CHECK (template_version BETWEEN 1 AND 9),
        ADD COLUMN IF NOT EXISTS complexity_score SMALLINT NOT NULL DEFAULT 1
            CHECK (complexity_score BETWEEN 1 AND 5),
        ADD COLUMN IF NOT EXISTS join_path TEXT[] DEFAULT ARRAY[]::TEXT[];
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_template_version ON learned_db_queries(template_version);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_complexity ON learned_db_queries(complexity_score);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_join_path ON learned_db_queries USING gin(join_path);")

    # ds_synthetic_query_runs
    op.execute("""
    ALTER TABLE ds_synthetic_query_runs
        ADD COLUMN IF NOT EXISTS template_version SMALLINT NOT NULL DEFAULT 1
            CHECK (template_version BETWEEN 1 AND 9),
        ADD COLUMN IF NOT EXISTS complexity_score SMALLINT NOT NULL DEFAULT 1
            CHECK (complexity_score BETWEEN 1 AND 5),
        ADD COLUMN IF NOT EXISTS join_path TEXT[] DEFAULT ARRAY[]::TEXT[];
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_synth_template_version ON ds_synthetic_query_runs(template_version);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_synth_complexity ON ds_synthetic_query_runs(complexity_score);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_synth_complexity;")
    op.execute("DROP INDEX IF EXISTS idx_synth_template_version;")
    op.execute("DROP INDEX IF EXISTS idx_learned_db_join_path;")
    op.execute("DROP INDEX IF EXISTS idx_learned_db_complexity;")
    op.execute("DROP INDEX IF EXISTS idx_learned_db_template_version;")
    op.execute("""
    ALTER TABLE ds_synthetic_query_runs
        DROP COLUMN IF EXISTS join_path,
        DROP COLUMN IF EXISTS complexity_score,
        DROP COLUMN IF EXISTS template_version;
    """)
    op.execute("""
    ALTER TABLE learned_db_queries
        DROP COLUMN IF EXISTS join_path,
        DROP COLUMN IF EXISTS complexity_score,
        DROP COLUMN IF EXISTS template_version;
    """)
