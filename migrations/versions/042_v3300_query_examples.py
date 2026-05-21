"""v3.30.0: query_examples table + ivfflat embedding index (FAZ 4 P50)

Revision ID: 042_v3300_query_examples
Revises: 033_v3300_metric_library_seed
Create Date: 2026-05-21

v3.30.0 — FAZ 4 P50 (Master-Plan Gap Addendum)
================================================
Plan: .agents/in_flight/2026-05-20_plan-FAZ4_learning-loop.md
Brief: .agents/in_flight/2026-05-21_p50_query-examples-fewshot.md

Text-to-SQL few-shot retrieval store. Per (user_id, source_id) the top-K
nearest examples (by embedding cosine distance) are pulled at SQL generation
time and inserted into the LLM prompt as in-context examples.

Why this revision number:
    FAZ 2/3/4 plans reserve 034..041 across the wizard, feature_store,
    telemetry, i18n and ranker branches. P50 sits outside those branches and
    uses 042 to avoid collision. down_revision is the last *committed* head
    (033) — branch-merge ordering handled by Alembic at deploy time.

Schema:
    user_id NULL  → company baseline (P52 synthetic Q/SQL pairs).
    user_id NOT NULL → personal-history example (real query + thumbs-up or
                       auto-repair signal).

pgvector:
    Migration 024 (business_glossary_v2) already installs the vector
    extension when available. We CREATE EXTENSION IF NOT EXISTS defensively
    and only create the ivfflat index when the extension is present.

RLS:
    company_id-scoped tenant isolation (matches dbsmart_templates style in
    migration 032 — read-side filter, no FORCE; the writer flow goes through
    record_example() which always carries user_ctx).

Idempotent: CREATE ... IF NOT EXISTS throughout. Downgrade DROPs table +
indexes only — extension stays (other tables depend on it).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "042_v3300_query_examples"
down_revision: Union[str, None] = "033_v3300_metric_library_seed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) pgvector extension (defensive — 024 should have created it).
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ------------------------------------------------------------------
    # 2) query_examples table — embedding column type depends on whether
    #    pgvector is present. Mirror migration 024 pattern.
    # ------------------------------------------------------------------
    op.execute("""
    DO $$
    DECLARE
        v_emb_type TEXT;
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            v_emb_type := 'vector(384)';
        ELSE
            v_emb_type := 'float[]';
        END IF;

        EXECUTE format($ct$
            CREATE TABLE IF NOT EXISTS query_examples (
                id              BIGSERIAL PRIMARY KEY,
                user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                source_id       INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
                db_engine       VARCHAR(20) NOT NULL,
                question        TEXT NOT NULL,
                generated_sql   TEXT NOT NULL,
                was_correct     BOOLEAN NOT NULL DEFAULT TRUE,
                user_feedback   VARCHAR(32),
                embedding       %s,
                chosen_tables   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                chosen_columns  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT ck_query_examples_feedback CHECK (
                    user_feedback IS NULL OR user_feedback IN (
                        'manual_thumbs_up','auto_repaired','synthetic','manual_thumbs_down'
                    )
                )
            );
        $ct$, v_emb_type);
    END $$;
    """)

    # ------------------------------------------------------------------
    # 3) Lookup indexes (partial — user-personal vs company-baseline).
    # ------------------------------------------------------------------
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_query_examples_user_source
        ON query_examples (user_id, source_id, created_at DESC)
        WHERE user_id IS NOT NULL;
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_query_examples_company_baseline
        ON query_examples (company_id, source_id, created_at DESC)
        WHERE user_id IS NULL;
    """)

    # ------------------------------------------------------------------
    # 4) ivfflat cosine index (only if pgvector available).
    # ------------------------------------------------------------------
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_query_examples_embedding_cosine
                         ON query_examples USING ivfflat (embedding vector_cosine_ops)
                         WITH (lists = 100)';
            EXCEPTION WHEN OTHERS THEN
                -- ivfflat unavailable on this pgvector build — skip silently.
                NULL;
            END;
        END IF;
    END $$;
    """)

    # ------------------------------------------------------------------
    # 5) RLS — company-scoped read + write (style: dbsmart_templates / 032).
    # ------------------------------------------------------------------
    op.execute("""
    ALTER TABLE query_examples ENABLE ROW LEVEL SECURITY;
    ALTER TABLE query_examples FORCE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS pol_query_examples_read ON query_examples;
    CREATE POLICY pol_query_examples_read ON query_examples
        FOR SELECT
        USING (
            current_setting('vyra.is_admin', true) = 'true'
            OR company_id = NULLIF(current_setting('vyra.company_id', true), '')::int
        );

    DROP POLICY IF EXISTS pol_query_examples_write ON query_examples;
    CREATE POLICY pol_query_examples_write ON query_examples
        FOR ALL
        USING (
            current_setting('vyra.is_admin', true) = 'true'
            OR company_id = NULLIF(current_setting('vyra.company_id', true), '')::int
        )
        WITH CHECK (
            current_setting('vyra.is_admin', true) = 'true'
            OR company_id = NULLIF(current_setting('vyra.company_id', true), '')::int
        );
    """)


def downgrade() -> None:
    # Drop indexes + table only. Keep vector extension (shared with
    # business_glossary and any future embedding-backed tables).
    op.execute("DROP INDEX IF EXISTS idx_query_examples_embedding_cosine;")
    op.execute("DROP INDEX IF EXISTS idx_query_examples_company_baseline;")
    op.execute("DROP INDEX IF EXISTS idx_query_examples_user_source;")
    op.execute("DROP POLICY IF EXISTS pol_query_examples_read ON query_examples;")
    op.execute("DROP POLICY IF EXISTS pol_query_examples_write ON query_examples;")
    op.execute("DROP TABLE IF EXISTS query_examples CASCADE;")
