"""v3.27.0 C.G5 — synonym_suggestions (admin onay kuyruğu)

Revision ID: 022_v3270_synonym_suggestions
Revises: 021_v3270_db_learning_loop
Create Date: 2026-05-18

Synonym Auto-Learner çıktıları için onay kuyruğu. Kullanıcı sorularındaki
terimler ile veritabanı kolon adları arasındaki cosine benzerliği orta
seviyede (0.65 ≤ x < 0.85) olan adayları LLM doğrulaması sonrası buraya
kaydeder. Admin onaylarsa kalıcı eşanlam sözlüğüne (ds_column_synonyms /
business_glossary) taşınır.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "022_v3270_synonym_suggestions"
down_revision: Union[str, None] = "021_v3270_db_learning_loop"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""

_POLICY_CHECK_PERMISSIVE = """(
    company_id IS NULL
    OR current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS synonym_suggestions (
        id BIGSERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        user_term TEXT NOT NULL,            -- soru içinde geçen kullanıcı terimi
        schema_name VARCHAR(128),
        table_name VARCHAR(128) NOT NULL,
        column_name VARCHAR(128) NOT NULL,
        similarity REAL,                    -- cosine similarity (0..1)
        llm_verdict VARCHAR(16),            -- 'match' | 'no_match' | 'uncertain'
        llm_rationale TEXT,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
        reviewer_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        reviewed_at TIMESTAMPTZ,
        observed_count INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        CONSTRAINT uniq_syn_sugg UNIQUE (source_id, user_term, schema_name, table_name, column_name)
    );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_syn_status ON synonym_suggestions(status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_syn_source ON synonym_suggestions(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_syn_company ON synonym_suggestions(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_syn_term ON synonym_suggestions(LOWER(user_term));")

    op.execute("ALTER TABLE synonym_suggestions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON synonym_suggestions;")
    op.execute(f"""
    CREATE POLICY rls_company_scoped ON synonym_suggestions
        FOR ALL
        USING {_POLICY_USING_PERMISSIVE}
        WITH CHECK {_POLICY_CHECK_PERMISSIVE};
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON synonym_suggestions;")
    op.execute("DROP TABLE IF EXISTS synonym_suggestions CASCADE;")
