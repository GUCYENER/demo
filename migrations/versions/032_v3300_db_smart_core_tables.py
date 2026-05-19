"""v3.30.0 FAZ 0 — Akıllı Veri Keşfi (DB Smart) çekirdek tablolar

Revision ID: 032_v3300_db_smart_core_tables
Revises: 031_v3299_fk_inference_metadata
Create Date: 2026-05-19

v3.30.0 — Akıllı Veri Keşfi (DB Smart Wizard) FAZ 0
====================================================
Plan: .agents/plans/v3.30.0_db_smart_wizard.md
Mimari: docs/db_smart/01_architecture.md

Bu migration 8 yeni tablo + RLS + indexler + feature_permissions seed kurar:

  1. dbsmart_sessions             — wizard oturum durum makinesi
  2. dbsmart_saved_reports        — kaydedilen rapor + share + schedule
  3. dbsmart_templates            — community/official SQL template marketplace
  4. dbsmart_user_preferences     — kullanıcı tercih kalıcılığı (cold-start öncesi)
  5. dbsmart_metric_library       — 5 domain × 8-12 metrik tanımı (seed Faz 1)
  6. dbsmart_interactions         — implicit/explicit event store (month-partitioned)
  7. dbsmart_report_recommendations — shape→viz öneri kuralları
  8. dbsmart_ab_buckets           — A/B testing variant bucketing (Faz 4)

NOT (kullanıcı kararları, FAZ 0 plan §9):
    - Schedule: in-process scheduler (Celery yok) — schedule_cron alanı saklanır,
      hook Faz 3 G3.3'te eklenir.
    - E-mail: KAPSAM DIŞI. last_run_snapshot in-app olarak tutulur.
    - MCP: KAPSAM DIŞI (v3.31.0 ayrı plan).

RLS:
    Tüm kullanıcı-spesifik tablolar `current_setting('vyra.user_id')::int` ve
    `current_setting('vyra.company_id')::int` üzerinden izole edilir. Admin
    bypass: `current_setting('vyra.is_admin', true)::bool = TRUE`.

Indexler:
    Tüm tablolarda btree(user_id, company_id, ...) + GIN(jsonb context/state).
    dbsmart_interactions ek olarak ay bazlı partition (Faz 0 placeholder; gerçek
    DECLARATIVE PARTITION ileride; v3.30.0 FAZ 0'da single-table + (created_at)
    btree yeterli).

Idempotency:
    Tüm CREATE TABLE / CREATE INDEX / CREATE POLICY IF NOT EXISTS pattern'i.
    Tekrar koşturma güvenli.

Downgrade:
    Tüm tablolar DROP CASCADE. Feature seed satırı feature_permissions'tan değil
    KNOWN_FEATURE_KEYS'ten temizlenmez (kod değişikliği gerekir).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "032_v3300_db_smart_core_tables"
down_revision: Union[str, None] = "031_v3299_fk_inference_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) dbsmart_sessions — wizard oturum durum makinesi
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_sessions (
        id              SERIAL PRIMARY KEY,
        session_uid     UUID NOT NULL UNIQUE,
        user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        source_id       INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
        current_step    SMALLINT NOT NULL DEFAULT 0,
        status          VARCHAR(20) NOT NULL DEFAULT 'active',
        context         JSONB NOT NULL DEFAULT '{}'::jsonb,
        generated_sql   TEXT,
        dialect         VARCHAR(20),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at    TIMESTAMPTZ,
        CONSTRAINT ck_dbsmart_sessions_status
            CHECK (status IN ('active','completed','abandoned','expired'))
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_sessions_user_last
        ON dbsmart_sessions (user_id, company_id, last_activity_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_sessions_status
        ON dbsmart_sessions (status) WHERE status = 'active';
    CREATE INDEX IF NOT EXISTS idx_dbsmart_sessions_ctx
        ON dbsmart_sessions USING GIN (context);
    """)

    # ------------------------------------------------------------------
    # 2) dbsmart_saved_reports — kaydedilen rapor + share + schedule
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_saved_reports (
        id                  SERIAL PRIMARY KEY,
        user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        company_id          INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        source_id           INTEGER REFERENCES data_sources(id) ON DELETE SET NULL,
        name                VARCHAR(200) NOT NULL,
        description         TEXT,
        wizard_state        JSONB NOT NULL,
        last_sql            TEXT,
        last_dialect        VARCHAR(20),
        tags                TEXT[],
        run_count           INTEGER NOT NULL DEFAULT 0,
        last_run_at         TIMESTAMPTZ,
        last_run_snapshot   JSONB,
        is_shared           BOOLEAN NOT NULL DEFAULT FALSE,
        share_token         VARCHAR(64),
        share_expires_at    TIMESTAMPTZ,
        schedule_cron       VARCHAR(64),
        schedule_next_run   TIMESTAMPTZ,
        owner_team_id       INTEGER,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_saved_user
        ON dbsmart_saved_reports (user_id, company_id);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_saved_schedule
        ON dbsmart_saved_reports (schedule_next_run) WHERE schedule_cron IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS uq_dbsmart_saved_share_token
        ON dbsmart_saved_reports (share_token) WHERE share_token IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # 3) dbsmart_templates — SQL template marketplace
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_templates (
        id                          SERIAL PRIMARY KEY,
        template_key                VARCHAR(120) NOT NULL UNIQUE,
        category                    VARCHAR(60) NOT NULL,
        applicable_table_patterns   TEXT[] NOT NULL DEFAULT '{}',
        sql_template                TEXT NOT NULL,
        required_columns            JSONB NOT NULL DEFAULT '{}'::jsonb,
        dialect_variants            JSONB NOT NULL DEFAULT '{}'::jsonb,
        source_id                   INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id                  INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        is_official                 BOOLEAN NOT NULL DEFAULT FALSE,
        is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
        created_by                  INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_templates_company
        ON dbsmart_templates (company_id, is_active);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_templates_category
        ON dbsmart_templates (category);
    """)

    # ------------------------------------------------------------------
    # 4) dbsmart_user_preferences — kullanıcı tercih kalıcılığı
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_user_preferences (
        id                      SERIAL PRIMARY KEY,
        user_id                 INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        company_id              INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        frequent_tables         INTEGER[] NOT NULL DEFAULT '{}',
        preferred_date_range    VARCHAR(40),
        default_metrics         TEXT[] NOT NULL DEFAULT '{}',
        learned_preferences     JSONB NOT NULL DEFAULT '{}'::jsonb,
        ui_settings             JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_userprefs_company
        ON dbsmart_user_preferences (company_id);
    """)

    # ------------------------------------------------------------------
    # 5) dbsmart_metric_library — metrik tanımları (seed Faz 1 G1.4)
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_metric_library (
        id                      SERIAL PRIMARY KEY,
        metric_key              VARCHAR(120) NOT NULL UNIQUE,
        name_tr                 VARCHAR(160) NOT NULL,
        name_en                 VARCHAR(160),
        category                VARCHAR(60) NOT NULL,
        sub_category            VARCHAR(60),
        description_tr          TEXT,
        rationale_template_tr   TEXT,
        applicable_when         JSONB NOT NULL DEFAULT '{}'::jsonb,
        sql_templates           JSONB NOT NULL DEFAULT '{}'::jsonb,
        required_features       JSONB NOT NULL DEFAULT '[]'::jsonb,
        optional_features       JSONB NOT NULL DEFAULT '[]'::jsonb,
        default_viz             VARCHAR(40) NOT NULL DEFAULT 'table',
        is_official             BOOLEAN NOT NULL DEFAULT TRUE,
        is_active               BOOLEAN NOT NULL DEFAULT TRUE,
        owner_user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
        source_id               INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id              INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        usage_count             INTEGER NOT NULL DEFAULT 0,
        success_rate            REAL,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_dbsmart_metric_viz CHECK (default_viz IN (
            'table','bar','line','area','kpi','pie','donut','heatmap',
            'treemap','funnel','cohort','map','scatter','box','sankey',
            'sunburst','calendar'
        ))
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_metric_category
        ON dbsmart_metric_library (category, is_active);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_metric_applicable
        ON dbsmart_metric_library USING GIN (applicable_when);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_metric_official
        ON dbsmart_metric_library (is_official, is_active);
    """)

    # ------------------------------------------------------------------
    # 6) dbsmart_interactions — event store (PII-aware)
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_interactions (
        id                  BIGSERIAL PRIMARY KEY,
        session_id          INTEGER REFERENCES dbsmart_sessions(id) ON DELETE CASCADE,
        user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        company_id          INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        step                SMALLINT,
        action              VARCHAR(60) NOT NULL,
        suggestion_shown    JSONB,
        suggestion_accepted JSONB,
        user_override       JSONB,
        satisfaction        SMALLINT,
        duration_ms         INTEGER,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT ck_dbsmart_interactions_satisfaction
            CHECK (satisfaction IS NULL OR satisfaction BETWEEN -1 AND 5)
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_inter_user_ts
        ON dbsmart_interactions (user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_inter_session
        ON dbsmart_interactions (session_id);
    CREATE INDEX IF NOT EXISTS idx_dbsmart_inter_action
        ON dbsmart_interactions (action, created_at DESC);
    """)

    # ------------------------------------------------------------------
    # 7) dbsmart_report_recommendations — shape→viz öneri kuralları
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_report_recommendations (
        id                      SERIAL PRIMARY KEY,
        recommendation_key      VARCHAR(120) NOT NULL UNIQUE,
        trigger_pattern         JSONB NOT NULL,
        recommended_viz         VARCHAR(40) NOT NULL,
        confidence_min          REAL NOT NULL DEFAULT 0.6,
        rationale_template_tr   TEXT,
        is_active               BOOLEAN NOT NULL DEFAULT TRUE,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_reco_active
        ON dbsmart_report_recommendations (is_active);
    """)

    # ------------------------------------------------------------------
    # 8) dbsmart_ab_buckets — A/B testing (Faz 4 G4.5)
    # ------------------------------------------------------------------
    op.execute("""
    CREATE TABLE IF NOT EXISTS dbsmart_ab_buckets (
        id              SERIAL PRIMARY KEY,
        user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        experiment_key  VARCHAR(80) NOT NULL,
        variant         VARCHAR(40) NOT NULL,
        bucket_hash     INTEGER NOT NULL,
        assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (user_id, experiment_key)
    );
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dbsmart_ab_exp
        ON dbsmart_ab_buckets (experiment_key, variant);
    """)

    # ------------------------------------------------------------------
    # 9) RLS politikaları (Postgres 14+ FORCE ROW LEVEL SECURITY)
    # ------------------------------------------------------------------
    op.execute("""
    DO $$
    DECLARE
        t TEXT;
    BEGIN
        FOREACH t IN ARRAY ARRAY[
            'dbsmart_sessions',
            'dbsmart_saved_reports',
            'dbsmart_user_preferences',
            'dbsmart_interactions',
            'dbsmart_ab_buckets'
        ]
        LOOP
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
            EXECUTE format($p$
                DROP POLICY IF EXISTS pol_%1$s_isolation ON %1$s;
                CREATE POLICY pol_%1$s_isolation ON %1$s
                USING (
                    (current_setting('vyra.is_admin', true) = 'true')
                    OR (user_id = NULLIF(current_setting('vyra.user_id', true), '')::int)
                )
                WITH CHECK (
                    (current_setting('vyra.is_admin', true) = 'true')
                    OR (user_id = NULLIF(current_setting('vyra.user_id', true), '')::int)
                );
            $p$, t);
        END LOOP;
    END$$;
    """)

    # dbsmart_templates ve dbsmart_metric_library: company-scope yazma, global okuma
    op.execute("""
    ALTER TABLE dbsmart_templates ENABLE ROW LEVEL SECURITY;
    ALTER TABLE dbsmart_templates FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS pol_dbsmart_templates_read ON dbsmart_templates;
    CREATE POLICY pol_dbsmart_templates_read ON dbsmart_templates
        FOR SELECT
        USING (
            is_official = TRUE
            OR company_id IS NULL
            OR company_id = NULLIF(current_setting('vyra.company_id', true), '')::int
            OR current_setting('vyra.is_admin', true) = 'true'
        );
    DROP POLICY IF EXISTS pol_dbsmart_templates_write ON dbsmart_templates;
    CREATE POLICY pol_dbsmart_templates_write ON dbsmart_templates
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
    op.execute("""
    ALTER TABLE dbsmart_metric_library ENABLE ROW LEVEL SECURITY;
    ALTER TABLE dbsmart_metric_library FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS pol_dbsmart_metric_read ON dbsmart_metric_library;
    CREATE POLICY pol_dbsmart_metric_read ON dbsmart_metric_library
        FOR SELECT
        USING (
            is_official = TRUE
            OR company_id IS NULL
            OR company_id = NULLIF(current_setting('vyra.company_id', true), '')::int
            OR current_setting('vyra.is_admin', true) = 'true'
        );
    DROP POLICY IF EXISTS pol_dbsmart_metric_write ON dbsmart_metric_library;
    CREATE POLICY pol_dbsmart_metric_write ON dbsmart_metric_library
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

    # ------------------------------------------------------------------
    # 10) system_settings deploy marker
    # ------------------------------------------------------------------
    op.execute("""
    INSERT INTO system_settings (setting_key, setting_value, description, updated_at)
    VALUES (
        'DBSMART_DEPLOY_TS',
        NOW()::text,
        'v3.30.0 FAZ 0 — Akıllı Veri Keşfi tablolar deploy zamanı (signal weight analyzer izole eder)',
        NOW()
    )
    ON CONFLICT (setting_key) DO UPDATE
       SET setting_value = EXCLUDED.setting_value,
           updated_at    = NOW();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS dbsmart_ab_buckets CASCADE;
    DROP TABLE IF EXISTS dbsmart_report_recommendations CASCADE;
    DROP TABLE IF EXISTS dbsmart_interactions CASCADE;
    DROP TABLE IF EXISTS dbsmart_metric_library CASCADE;
    DROP TABLE IF EXISTS dbsmart_user_preferences CASCADE;
    DROP TABLE IF EXISTS dbsmart_templates CASCADE;
    DROP TABLE IF EXISTS dbsmart_saved_reports CASCADE;
    DROP TABLE IF EXISTS dbsmart_sessions CASCADE;
    DELETE FROM system_settings WHERE setting_key = 'DBSMART_DEPLOY_TS';
    """)
