"""v3.29.4: learned_query_failures — retry/error pattern learning

Revision ID: 028_v3290_query_failure_log
Revises: 027_v3290_pii_flag
Create Date: 2026-05-19

v3.29.4 — Faz 6 G5: Retry/Error Pattern Learning
------------------------------------------------
Plan: C:/Users/EXT02D059293/.claude/plans/binary-hugging-bengio.md

self_heal node'unda yakalanan SQL hataları sistematik olarak loglanır;
benzer sorularda LLM'e "geçen sefer aynı hata almıştın, şu düzeltmeyi yap"
ipucu sunulur. Aynı imzayla 3+ kez tekrarlanan hata admin review queue'ya
yükselir.

Tablo: learned_query_failures
    - id BIGSERIAL PK
    - source_id, company_id (RLS scope)
    - question TEXT, question_normalized TEXT
    - failed_sql TEXT NOT NULL
    - error_class VARCHAR(32) — syntax|missing_table|amb_column|timeout|empty|semantic|permission|unknown
    - error_message TEXT (kısa)
    - corrected_sql TEXT NULL — başarılı düzeltme (admin onayı olmadan few-shot'a girMEZ)
    - corrected_at TIMESTAMPTZ NULL
    - failure_signature CHAR(40) NOT NULL — SHA1(question_norm + error_class)
    - recurrence_count INTEGER NOT NULL DEFAULT 1
    - pattern_hint TEXT NULL — admin/LLM not (retry prompt'una verilir)
    - admin_approved BOOLEAN NOT NULL DEFAULT FALSE
    - last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    - created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    - UNIQUE (source_id, failure_signature)

RLS PERMISSIVE — company_id current_setting('app.current_company_id') match.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "028_v3290_query_failure_log"
down_revision: Union[str, None] = "027_v3290_pii_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS learned_query_failures (
        id BIGSERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        question TEXT NOT NULL,
        question_normalized TEXT,
        failed_sql TEXT NOT NULL,
        error_class VARCHAR(32) NOT NULL DEFAULT 'unknown',
        error_message TEXT,
        corrected_sql TEXT,
        corrected_at TIMESTAMPTZ,
        failure_signature CHAR(40) NOT NULL,
        recurrence_count INTEGER NOT NULL DEFAULT 1,
        pattern_hint TEXT,
        admin_approved BOOLEAN NOT NULL DEFAULT FALSE,
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_lqf_source_sig UNIQUE (source_id, failure_signature),
        CONSTRAINT ck_lqf_error_class CHECK (error_class IN (
            'syntax','missing_table','amb_column','timeout',
            'empty','semantic','permission','unknown'
        ))
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_lqf_source ON learned_query_failures(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lqf_company ON learned_query_failures(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lqf_class ON learned_query_failures(error_class);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lqf_recurrence ON learned_query_failures(recurrence_count DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lqf_last_seen ON learned_query_failures(last_seen_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lqf_approved ON learned_query_failures(admin_approved) WHERE admin_approved = TRUE;")

    # RLS — PERMISSIVE pattern, current_setting bazlı (v3.27.0 migration 021 ile uyumlu)
    op.execute("ALTER TABLE learned_query_failures ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE learned_query_failures FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY learned_query_failures_company_scope ON learned_query_failures
        AS PERMISSIVE
        FOR ALL
        USING (
            company_id = COALESCE(
                NULLIF(current_setting('app.current_company_id', TRUE), '')::INTEGER,
                company_id
            )
        )
        WITH CHECK (
            company_id = COALESCE(
                NULLIF(current_setting('app.current_company_id', TRUE), '')::INTEGER,
                company_id
            )
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS learned_query_failures_company_scope ON learned_query_failures;")
    op.execute("ALTER TABLE IF EXISTS learned_query_failures DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS idx_lqf_approved;")
    op.execute("DROP INDEX IF EXISTS idx_lqf_last_seen;")
    op.execute("DROP INDEX IF EXISTS idx_lqf_recurrence;")
    op.execute("DROP INDEX IF EXISTS idx_lqf_class;")
    op.execute("DROP INDEX IF EXISTS idx_lqf_company;")
    op.execute("DROP INDEX IF EXISTS idx_lqf_source;")
    op.execute("DROP TABLE IF EXISTS learned_query_failures CASCADE;")
