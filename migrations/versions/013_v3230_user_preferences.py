"""v3.23.0: user_preferences tablosu (Faz 4a)

Revision ID: 013_v3230_user_preferences
Revises: 012_v3220_business_glossary
Create Date: 2026-05-17

Faz 4 — User Preferences
------------------------
ARTEMIS-ML + APOLLO + METIS plan: per-user kişiselleştirme katmanı.

Kullanım:
- multi_signal_rank: weight_overrides JSONB → default ağırlıkları override
- retrieve: preferred_tables[] → boost; blacklisted_tables[] → filter
- intent_extract: frequent_patterns JSONB (örn. en sık sorulan kalıplar) → confidence boost

CREATE TABLE user_preferences (
    id BIGSERIAL PK,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    weight_overrides JSONB    -- {"semantic":0.30, "name_fuzzy":0.25, ...}
    preferred_tables TEXT[]   -- ["sales.orders", "sales.customers"]
    blacklisted_tables TEXT[] -- soft black-list (rank=0)
    frequent_patterns JSONB   -- en sık kullanılan intent / soru kalıpları
    settings JSONB            -- extensible (UI prefs, locale, etc.)
    created_at, updated_at
);

İndexler:
    - UNIQUE (user_id) — tek satır per user
    - idx_company — company-level analytics

RLS yok — user_id sahipliği application'da enforce edilir (auth middleware).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "013_v3230_user_preferences"
down_revision: Union[str, None] = "012_v3220_business_glossary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS user_preferences (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        weight_overrides JSONB DEFAULT '{}'::jsonb,
        preferred_tables TEXT[] DEFAULT ARRAY[]::TEXT[],
        blacklisted_tables TEXT[] DEFAULT ARRAY[]::TEXT[],
        frequent_patterns JSONB DEFAULT '{}'::jsonb,
        settings JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        CONSTRAINT uq_user_preferences_user UNIQUE (user_id)
    );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_user_preferences_company ON user_preferences(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_preferences_pref_tables ON user_preferences USING gin(preferred_tables);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_preferences_blk_tables ON user_preferences USING gin(blacklisted_tables);")

    # updated_at trigger (Faz 2/3 pattern)
    op.execute("""
    CREATE OR REPLACE FUNCTION user_preferences_touch() RETURNS trigger AS $$
    BEGIN
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    DROP TRIGGER IF EXISTS trg_user_preferences_touch ON user_preferences;
    CREATE TRIGGER trg_user_preferences_touch
        BEFORE UPDATE ON user_preferences
        FOR EACH ROW EXECUTE FUNCTION user_preferences_touch();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_user_preferences_touch ON user_preferences;")
    op.execute("DROP FUNCTION IF EXISTS user_preferences_touch();")
    op.execute("DROP TABLE IF EXISTS user_preferences CASCADE;")
