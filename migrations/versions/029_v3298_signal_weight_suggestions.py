"""v3.29.8 L2: signal_weight_suggestions — admin-gated tuner suggestions

Revision ID: 029_v3298_signal_weight_suggestions
Revises: 028_v3290_query_failure_log
Create Date: 2026-05-19

v3.29.8 — Signal Weight Tuner Layer 2 (offline analyzer + suggestions)
----------------------------------------------------------------------
Plan: .agents/plans/v3.29.8_signal_weight_tuner.md

multi_signal_rank 7 sinyalle (semantic, name_fuzzy, column_match,
fk_centrality, recency, usage_freq, glossary_match) tablo seçimi yapar.
Layer 1 (v3.29.8) pipeline_events.signal_breakdown event'i ile sinyal
skorlarını + outcome'ı kaydeder. Bu migration, offline analyzer'ın
ürettiği ağırlık önerilerini saklayan tabloyu kurar.

Tablo: signal_weight_suggestions
    - id BIGSERIAL PK
    - company_id INTEGER (RLS scope) — NULL = global öneri
    - signal_name VARCHAR(32) — semantic/name_fuzzy/column_match/...
    - current_weight REAL — analiz anındaki yürürlükteki ağırlık
    - suggested_weight REAL — analyzer'ın önerdiği yeni ağırlık
    - confidence REAL — 0..1 (Bayesian shrinkage uygulanmış |r|)
    - correlation_pearson REAL — ham Pearson r ([-1, 1])
    - sample_size INTEGER — analiz penceresindeki run sayısı
    - window_days SMALLINT — analiz penceresi (default 7)
    - computed_at TIMESTAMPTZ — üretim zamanı
    - admin_verified BOOLEAN DEFAULT FALSE — admin onayı
    - applied_at TIMESTAMPTZ NULL — uygulandıysa ne zaman
    - applied_by INTEGER NULL — kim uyguladı (user_id)
    - audit_note TEXT NULL — uygulayan kişinin notu

RLS PERMISSIVE — company_id current_setting('app.current_company_id') match.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "029_v3298_signal_weight_suggestions"
down_revision: Union[str, None] = "028_v3290_query_failure_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VALID_SIGNALS = (
    "semantic", "name_fuzzy", "column_match",
    "fk_centrality", "recency", "usage_freq", "glossary_match",
)


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS signal_weight_suggestions (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        signal_name VARCHAR(32) NOT NULL,
        current_weight REAL NOT NULL,
        suggested_weight REAL NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.0,
        correlation_pearson REAL NOT NULL DEFAULT 0.0,
        sample_size INTEGER NOT NULL DEFAULT 0,
        window_days SMALLINT NOT NULL DEFAULT 7,
        computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        admin_verified BOOLEAN NOT NULL DEFAULT FALSE,
        applied_at TIMESTAMPTZ,
        applied_by INTEGER,
        audit_note TEXT,
        CONSTRAINT ck_sws_signal CHECK (signal_name IN (
            'semantic','name_fuzzy','column_match','fk_centrality',
            'recency','usage_freq','glossary_match'
        )),
        CONSTRAINT ck_sws_weight_range CHECK (
            suggested_weight >= 0.0 AND suggested_weight <= 1.0
        ),
        CONSTRAINT ck_sws_confidence_range CHECK (
            confidence >= 0.0 AND confidence <= 1.0
        )
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sws_company ON signal_weight_suggestions(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sws_signal ON signal_weight_suggestions(signal_name);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sws_computed ON signal_weight_suggestions(computed_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sws_verified ON signal_weight_suggestions(admin_verified) WHERE admin_verified = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sws_applied ON signal_weight_suggestions(applied_at DESC) WHERE applied_at IS NOT NULL;")

    # RLS — PERMISSIVE pattern, NULL company_id = global öneri (tüm şirketler okur)
    op.execute("ALTER TABLE signal_weight_suggestions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE signal_weight_suggestions FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY signal_weight_suggestions_company_scope ON signal_weight_suggestions
        AS PERMISSIVE
        FOR ALL
        USING (
            company_id IS NULL OR company_id = COALESCE(
                NULLIF(current_setting('app.current_company_id', TRUE), '')::INTEGER,
                company_id
            )
        )
        WITH CHECK (
            company_id IS NULL OR company_id = COALESCE(
                NULLIF(current_setting('app.current_company_id', TRUE), '')::INTEGER,
                company_id
            )
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS signal_weight_suggestions_company_scope ON signal_weight_suggestions;")
    op.execute("ALTER TABLE IF EXISTS signal_weight_suggestions DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS idx_sws_applied;")
    op.execute("DROP INDEX IF EXISTS idx_sws_verified;")
    op.execute("DROP INDEX IF EXISTS idx_sws_computed;")
    op.execute("DROP INDEX IF EXISTS idx_sws_signal;")
    op.execute("DROP INDEX IF EXISTS idx_sws_company;")
    op.execute("DROP TABLE IF EXISTS signal_weight_suggestions CASCADE;")
