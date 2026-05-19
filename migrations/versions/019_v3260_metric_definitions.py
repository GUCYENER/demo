"""v3.26.0: metric_definitions — Semantic/Metric Layer (Faz 3 P1-b)

Revision ID: 019_v3260_metric_definitions
Revises: 018_v3260_size_observations
Create Date: 2026-05-17

Faz 3 — P1-b: Semantic Layer
----------------------------
Kullanıcı doğal dilinden → kanonik metrik tanımına geçişi sağlar.
Örnek: "aktif müşteri sayısı" → ``metric:active_customer_count`` →
SELECT COUNT(*) FROM customers WHERE status='active'

Tablo: metric_definitions
    name           — unique per (company_id) — örn. "monthly_revenue"
    display_name   — UI'da gösterilen ad — "Aylık Gelir"
    description    — Türkçe açıklama
    sql_expression — SELECT ifadesi (parameterless) veya CTE
    base_tables    — kullanılan tablo isimleri (schema.tablo) — RAG hint için
    dimensions     — ["region", "channel"] — gruplama boyutları
    filters        — JSONB default filter
    unit           — "TRY", "adet", "%"
    aggregation_type — "count" | "sum" | "avg" | "custom"

RLS: 017 pattern — company-level PERMISSIVE policy.

Pipeline entegrasyonu:
    - load_prefs_node available_metrics state'e enjekte eder.
    - sql_generate_node prompt'a "Tanımlı Metrikler" bloğu ekler.
    - sql_generate sonrası `metric_references` (kullanılan metric id'leri) loglanır.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "019_v3260_metric_definitions"
down_revision: Union[str, None] = "018_v3260_size_observations"
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
    CREATE TABLE IF NOT EXISTS metric_definitions (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        source_id INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        name VARCHAR(128) NOT NULL,                -- canonical identifier (snake_case)
        display_name VARCHAR(256) NOT NULL,
        description TEXT,
        sql_expression TEXT NOT NULL,              -- SELECT ifadesi (parameterless)
        base_tables TEXT[] DEFAULT '{}',           -- ['public.orders', 'public.customers']
        dimensions TEXT[] DEFAULT '{}',
        filters JSONB DEFAULT '{}'::jsonb,
        unit VARCHAR(32),
        aggregation_type VARCHAR(32),              -- count|sum|avg|custom
        synonyms TEXT[] DEFAULT '{}',              -- doğal dil eşleşmesi için
        is_active BOOLEAN DEFAULT TRUE,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        CONSTRAINT uq_metric_company_name UNIQUE (company_id, name)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_metric_company ON metric_definitions(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_metric_source ON metric_definitions(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_metric_active ON metric_definitions(is_active) WHERE is_active = TRUE;")

    # RLS — 017 pattern (PERMISSIVE)
    op.execute("ALTER TABLE metric_definitions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON metric_definitions;")
    op.execute(f"""
    CREATE POLICY rls_company_scoped ON metric_definitions
        FOR ALL
        USING {_POLICY_USING_PERMISSIVE}
        WITH CHECK {_POLICY_USING_PERMISSIVE};
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON metric_definitions;")
    op.execute("DROP TABLE IF EXISTS metric_definitions CASCADE;")
