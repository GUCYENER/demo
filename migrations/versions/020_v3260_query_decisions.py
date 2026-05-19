"""v3.26.0: agentic_query_decisions — Column/Filter/Join predictor training data (Faz 4 P2-a)

Revision ID: 020_v3260_query_decisions
Revises: 019_v3260_metric_definitions
Create Date: 2026-05-17

Faz 4 — P2-a: Column / Filter / Join CatBoost predictors
---------------------------------------------------------
Pipeline her run sonrası 3 farklı tipte karar verir:
  - column : SQL SELECT listesine hangi kolonlar girdi?
  - filter : WHERE clause'da hangi kolonlar filtre olarak kullanıldı?
  - join   : Hangi (table_a, table_b) JOIN'leri kuruldu?

Bu kararlar +/- örnek olarak loglanır (was_used 0/1). Yeterli veri biriktiğinde
CatBoost multiclass/binary modeller eğitilir (model_type:
``column_predictor``/``filter_predictor``/``join_predictor``).

Tablo yapısı:
    decision_type  — 'column' | 'filter' | 'join'
    features       — JSONB feature vector (decision_type'a göre değişen şema)
    target_key     — örn. "schema.tabloA.col1" (column/filter) veya
                       "schema.tabloA::schema.tabloB" (join) — sortlu, deterministic
    was_used       — 0/1
    meta           — diagnostics JSONB

Tek tablo seçimi (3 ayrı tablo yerine) — yeni decision türü eklemek migration
gerektirmez, JSONB feature alanı forward-compatible.

RLS: 017 pattern — company-level PERMISSIVE policy.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "020_v3260_query_decisions"
down_revision: Union[str, None] = "019_v3260_metric_definitions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS agentic_query_decisions (
        id BIGSERIAL PRIMARY KEY,
        run_id VARCHAR(64),
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        decision_type VARCHAR(16) NOT NULL,         -- column | filter | join
        target_key TEXT NOT NULL,                   -- "schema.table.col" or "schema.a::schema.b"
        was_used SMALLINT NOT NULL DEFAULT 0,       -- 0/1
        features JSONB NOT NULL DEFAULT '{}'::jsonb,
        meta JSONB DEFAULT '{}'::jsonb,
        intent VARCHAR(64),
        sql_hash CHAR(40),                          -- SHA-1 hex
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_qdec_company ON agentic_query_decisions(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_qdec_type ON agentic_query_decisions(decision_type);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_qdec_created ON agentic_query_decisions(created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_qdec_company_type ON agentic_query_decisions(company_id, decision_type);")

    # RLS — 017 pattern (PERMISSIVE)
    op.execute("ALTER TABLE agentic_query_decisions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON agentic_query_decisions;")
    op.execute(f"""
    CREATE POLICY rls_company_scoped ON agentic_query_decisions
        FOR ALL
        USING {_POLICY_USING_PERMISSIVE}
        WITH CHECK (
            company_id IS NULL
            OR current_setting('app.current_company_id', true) IS NULL
            OR current_setting('app.current_company_id', true) = ''
            OR current_setting('app.bypass_rls', true) = 'on'
            OR company_id::text = current_setting('app.current_company_id', true)
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON agentic_query_decisions;")
    op.execute("DROP TABLE IF EXISTS agentic_query_decisions CASCADE;")
