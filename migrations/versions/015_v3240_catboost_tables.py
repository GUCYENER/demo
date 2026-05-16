"""v3.24.0: agentic_query_feedback + catboost_models tabloları (Faz 5a)

Revision ID: 015_v3240_catboost_tables
Revises: 014_v3230_few_shot_examples
Create Date: 2026-05-17

Faz 5 — CatBoost Eğitim Verisi + Model Versiyonlama
---------------------------------------------------
ARTEMIS-ML plan: heuristik multi_signal_rank ağırlıklarını öğrenen CatBoost
classifier/ranker için iki tablo:

1) agentic_query_feedback — eğitim verisi
   Pipeline her çalıştığında snapshot atılır:
   - state, ranked candidates, feature vector, seçilen tablo, success label
   - Implicit feedback (execute başarısı) + explicit (user thumb up/down)

2) catboost_models — model versiyonlama
   - model_type (ranking/clarification_gate/intent_classifier)
   - version, file_path, metrics, training_size, is_active
   - active model load-time'da read edilir

RLS yok — company_id application'da enforce.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "015_v3240_catboost_tables"
down_revision: Union[str, None] = "014_v3230_few_shot_examples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) agentic_query_feedback
    op.execute("""
    CREATE TABLE IF NOT EXISTS agentic_query_feedback (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,

        question TEXT NOT NULL,
        intent VARCHAR(64),
        intent_confidence REAL,

        -- Candidate-level rows (her aday için 1 satır)
        candidate_rank INTEGER,
        candidate_schema VARCHAR(128),
        candidate_table VARCHAR(256),

        -- Features (multi_signal_rank sinyalleri)
        feat_semantic REAL,
        feat_name_fuzzy REAL,
        feat_column_match REAL,
        feat_fk_centrality REAL,
        feat_recency REAL,
        feat_usage_freq REAL,
        final_score REAL,

        -- Labels
        was_selected BOOLEAN DEFAULT FALSE,        -- bu aday seçildi mi
        was_clarified BOOLEAN DEFAULT FALSE,       -- clarification gerekti mi
        execution_success BOOLEAN,                 -- SQL çalıştı mı
        user_feedback SMALLINT,                    -- -1 (negatif), 0 (nötr), 1 (pozitif)
        row_count INTEGER,
        elapsed_ms INTEGER,

        -- Context snapshot
        ambiguity_reason VARCHAR(64),
        retry_count SMALLINT DEFAULT 0,
        error_category VARCHAR(32),

        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_aqf_company ON agentic_query_feedback(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aqf_source ON agentic_query_feedback(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aqf_user ON agentic_query_feedback(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aqf_selected ON agentic_query_feedback(was_selected);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aqf_created ON agentic_query_feedback(created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_aqf_intent ON agentic_query_feedback(intent);")

    # 2) catboost_models
    op.execute("""
    CREATE TABLE IF NOT EXISTS catboost_models (
        id BIGSERIAL PRIMARY KEY,
        model_type VARCHAR(64) NOT NULL,        -- 'ranking' | 'clarification_gate' | 'intent_classifier'
        version VARCHAR(32) NOT NULL,
        file_path TEXT NOT NULL,
        feature_names TEXT[],
        training_size INTEGER,
        train_metrics JSONB DEFAULT '{}'::jsonb, -- {auc, accuracy, ndcg, ...}
        validation_metrics JSONB DEFAULT '{}'::jsonb,
        hyperparameters JSONB DEFAULT '{}'::jsonb,
        is_active BOOLEAN DEFAULT FALSE,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,  -- NULL = global
        trained_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        CONSTRAINT uq_catboost_active UNIQUE (model_type, company_id, is_active)
            DEFERRABLE INITIALLY DEFERRED
    );
    """)
    # Not: aynı (model_type, company_id) için yalnız 1 active olabilmesi UNIQUE üzerine.
    # PostgreSQL'de partial unique daha iyi — onu kullanalım:
    op.execute("ALTER TABLE catboost_models DROP CONSTRAINT IF EXISTS uq_catboost_active;")
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_catboost_active_partial
        ON catboost_models (model_type, COALESCE(company_id, 0))
        WHERE is_active = TRUE;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_catboost_type_company ON catboost_models(model_type, company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_catboost_active ON catboost_models(is_active) WHERE is_active = TRUE;")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_catboost_active_partial;")
    op.execute("DROP TABLE IF EXISTS catboost_models CASCADE;")
    op.execute("DROP TABLE IF EXISTS agentic_query_feedback CASCADE;")
