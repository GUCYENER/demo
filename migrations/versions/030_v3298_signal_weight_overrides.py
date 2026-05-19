"""v3.29.8 L3: signal_weight_overrides — DB-driven per-company weights

Revision ID: 030_v3298_signal_weight_overrides
Revises: 029_v3298_signal_weight_suggestions
Create Date: 2026-05-19

v3.29.8 — Signal Weight Tuner Layer 3 (admin-applied overrides)
---------------------------------------------------------------
Plan: .agents/plans/v3.29.8_signal_weight_tuner.md

multi_signal_rank ağırlıkları artık veritabanından şirket-bazlı
override edilebilir. Layer 2 önerilerinden admin onayıyla uygulananlar
buraya yazılır. UNIQUE(company_id, signal_name) ile her sinyal için
şirket başına tek değer tutulur.

Tablo: signal_weight_overrides
    - id BIGSERIAL PK
    - company_id INTEGER NOT NULL (RLS scope)
    - signal_name VARCHAR(32) — 7 sinyalden biri
    - weight REAL — yeni ağırlık değeri
    - updated_at TIMESTAMPTZ
    - updated_by INTEGER — apply eden user_id
    - source_suggestion_id BIGINT NULL — kaynak suggestion (audit trail)
    - audit_note TEXT NULL — apply eden kişinin notu
    - UNIQUE(company_id, signal_name)

RLS PERMISSIVE — company_id current_setting('app.current_company_id') match.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "030_v3298_signal_weight_overrides"
down_revision: Union[str, None] = "029_v3298_signal_weight_suggestions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS signal_weight_overrides (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        signal_name VARCHAR(32) NOT NULL,
        weight REAL NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        source_suggestion_id BIGINT REFERENCES signal_weight_suggestions(id) ON DELETE SET NULL,
        audit_note TEXT,
        CONSTRAINT ck_swo_signal CHECK (signal_name IN (
            'semantic','name_fuzzy','column_match','fk_centrality',
            'recency','usage_freq','glossary_match'
        )),
        CONSTRAINT ck_swo_weight_range CHECK (weight >= 0.0 AND weight <= 1.0),
        CONSTRAINT uq_swo_company_signal UNIQUE (company_id, signal_name)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_swo_company ON signal_weight_overrides(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_swo_updated ON signal_weight_overrides(updated_at DESC);")

    # RLS PERMISSIVE
    op.execute("ALTER TABLE signal_weight_overrides ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE signal_weight_overrides FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY signal_weight_overrides_company_scope ON signal_weight_overrides
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

    # Audit log tablosu (history — her apply yeni satır)
    op.execute("""
    CREATE TABLE IF NOT EXISTS signal_weight_audit_log (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        signal_name VARCHAR(32) NOT NULL,
        old_weight REAL,
        new_weight REAL NOT NULL,
        changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        changed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        action VARCHAR(16) NOT NULL DEFAULT 'apply',  -- apply|revert|manual
        source_suggestion_id BIGINT,
        audit_note TEXT,
        CONSTRAINT ck_swal_action CHECK (action IN ('apply','revert','manual','reset'))
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_swal_company ON signal_weight_audit_log(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_swal_changed ON signal_weight_audit_log(changed_at DESC);")

    op.execute("ALTER TABLE signal_weight_audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE signal_weight_audit_log FORCE ROW LEVEL SECURITY;")
    op.execute("""
    CREATE POLICY signal_weight_audit_log_company_scope ON signal_weight_audit_log
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
    op.execute("DROP POLICY IF EXISTS signal_weight_audit_log_company_scope ON signal_weight_audit_log;")
    op.execute("ALTER TABLE IF EXISTS signal_weight_audit_log DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS idx_swal_changed;")
    op.execute("DROP INDEX IF EXISTS idx_swal_company;")
    op.execute("DROP TABLE IF EXISTS signal_weight_audit_log CASCADE;")

    op.execute("DROP POLICY IF EXISTS signal_weight_overrides_company_scope ON signal_weight_overrides;")
    op.execute("ALTER TABLE IF EXISTS signal_weight_overrides DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP INDEX IF EXISTS idx_swo_updated;")
    op.execute("DROP INDEX IF EXISTS idx_swo_company;")
    op.execute("DROP TABLE IF EXISTS signal_weight_overrides CASCADE;")
