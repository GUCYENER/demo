"""v3.26.0: agentic_size_observations — Result Size Predictor training data (Faz 2)

Revision ID: 018_v3260_size_observations
Revises: 017_v3260_rls_tenant_tables
Create Date: 2026-05-17

Faz 2 — P1-a: Result Size Predictor CatBoost
--------------------------------------------
predict_result_size() heuristic + EXPLAIN + reltuples kullanıyor. Bu migration
ML training/observability tablosu ekler:

    agentic_size_observations (
        run_id, company_id, source_id,
        sql_hash, sql_text_short,
        features JSONB,                -- has_agg, has_pk_where, explicit_limit, join_count, ...
        predicted_bucket,              -- heuristik tahminin sonucu
        predicted_rows,
        actual_rows,                   -- execute_node sonrası gerçek
        actual_bucket,                 -- actual_rows → bucket
        dialect,
        created_at
    )

Trainer (catboost_trainer.train_size_classifier) bu tablodan multiclass
classifier eğitir (4 sınıf: small/medium/large/huge).

RLS: 017 pattern — company-level PERMISSIVE policy.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "018_v3260_size_observations"
down_revision: Union[str, None] = "017_v3260_rls_tenant_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""

_POLICY_CHECK_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id IS NULL
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS agentic_size_observations (
        id BIGSERIAL PRIMARY KEY,
        run_id UUID,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        sql_hash VARCHAR(64),                -- SHA1 of normalized SQL (dedupe)
        sql_text_short TEXT,                 -- first 500 chars
        features JSONB DEFAULT '{}'::jsonb,
        predicted_bucket VARCHAR(16),         -- small/medium/large/huge
        predicted_rows INTEGER,
        predicted_reason VARCHAR(32),
        actual_rows INTEGER,
        actual_bucket VARCHAR(16),
        dialect VARCHAR(16),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_aso_company ON agentic_size_observations(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aso_run ON agentic_size_observations(run_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aso_actual_bucket ON agentic_size_observations(actual_bucket);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aso_created ON agentic_size_observations(created_at DESC);")

    # RLS — 017 pattern
    op.execute("ALTER TABLE agentic_size_observations ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON agentic_size_observations;")
    op.execute(f"""
    CREATE POLICY rls_company_scoped ON agentic_size_observations
        FOR ALL
        USING {_POLICY_USING_PERMISSIVE}
        WITH CHECK {_POLICY_CHECK_PERMISSIVE};
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON agentic_size_observations;")
    op.execute("DROP TABLE IF EXISTS agentic_size_observations CASCADE;")
