"""v3.30.0: dbsmart_interactions partitioning + archive table

Revision ID: 034_v3300_dbsmart_interactions_partitioning
Revises: 033_v3300_metric_library_seed
Create Date: 2026-05-21

FAZ 2 P30 — Implicit Learning Closure
--------------------------------------
dbsmart_interactions tablosunu RANGE partition by created_at (monthly) olarak
dönüştürür. Archive tablosu + bandit/analytics index eklenir.

Strateji:
- Tablo 0 satır → basit DROP + CREATE PARTITION BY
- Tablo dolu → rename → yeni partitioned create → INSERT SELECT → drop old
- Idempotent: pg_class.relkind='p' kontrolü ile atlama

RLS:
- Her child partition'a RLS policy re-apply zorunlu (PostgreSQL constraint).
- dbsmart_interactions_archive kendi RLS policy'sine sahip.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '034_v3300_dbsmart_interactions_partitioning'
down_revision = '033_v3300_metric_library_seed'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # --- 1. Check if already partitioned ---
    already = conn.execute(sa.text("""
        SELECT c.relkind FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE c.relname = 'dbsmart_interactions' AND n.nspname = 'public'
    """)).scalar()

    if already == 'p':
        # Already partitioned — skip
        conn.execute(sa.text("SELECT 1"))  # noop
    else:
        # --- 2. Convert to partitioned table ---
        # Table may not exist yet (clean install) — check first
        table_exists = conn.execute(sa.text("""
            SELECT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE c.relname = 'dbsmart_interactions' AND n.nspname = 'public'
            )
        """)).scalar()

        row_count = 0
        if table_exists:
            row_count = conn.execute(sa.text(
                "SELECT COUNT(*) FROM dbsmart_interactions"
            )).scalar() or 0

        if row_count == 0:
            # Empty table — simple recreate
            conn.execute(sa.text("""
                DROP TABLE IF EXISTS dbsmart_interactions CASCADE
            """))
            conn.execute(sa.text("""
                CREATE TABLE dbsmart_interactions (
                    id BIGSERIAL,
                    session_id INT,
                    user_id INT NOT NULL,
                    company_id INT NOT NULL,
                    step SMALLINT,
                    action VARCHAR(60) NOT NULL,
                    suggestion_shown JSONB,
                    suggestion_accepted JSONB,
                    user_override JSONB,
                    satisfaction SMALLINT,
                    duration_ms INT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """))
        else:
            # Has data — rename + copy
            conn.execute(sa.text("""
                ALTER TABLE dbsmart_interactions RENAME TO dbsmart_interactions_old
            """))
            conn.execute(sa.text("""
                CREATE TABLE dbsmart_interactions (
                    id BIGSERIAL,
                    session_id INT,
                    user_id INT NOT NULL,
                    company_id INT NOT NULL,
                    step SMALLINT,
                    action VARCHAR(60) NOT NULL,
                    suggestion_shown JSONB,
                    suggestion_accepted JSONB,
                    user_override JSONB,
                    satisfaction SMALLINT,
                    duration_ms INT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (id, created_at)
                ) PARTITION BY RANGE (created_at)
            """))

        # Enable RLS on parent
        conn.execute(sa.text("""
            ALTER TABLE dbsmart_interactions ENABLE ROW LEVEL SECURITY
        """))
        conn.execute(sa.text("""
            ALTER TABLE dbsmart_interactions FORCE ROW LEVEL SECURITY
        """))

        # Create current + next month partitions
        conn.execute(sa.text("""
            DO $$
            DECLARE
                m_start DATE;
                m_end DATE;
                part_name TEXT;
            BEGIN
                FOR i IN 0..1 LOOP
                    m_start := date_trunc('month', NOW()) + (i || ' month')::interval;
                    m_end := m_start + '1 month'::interval;
                    part_name := 'dbsmart_interactions_' || to_char(m_start, 'YYYY_MM');

                    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part_name) THEN
                        EXECUTE format(
                            'CREATE TABLE %I PARTITION OF dbsmart_interactions FOR VALUES FROM (%L) TO (%L)',
                            part_name, m_start, m_end
                        );
                        -- RLS per partition
                        EXECUTE format(
                            'ALTER TABLE %I ENABLE ROW LEVEL SECURITY', part_name
                        );
                        EXECUTE format(
                            'CREATE POLICY pol_dbsmart_interactions_isolation ON %I '
                            'USING (user_id = NULLIF(current_setting(''vyra.user_id'', TRUE), '''')::int '
                            'OR current_setting(''vyra.is_admin'', TRUE) = ''true'')',
                            part_name
                        );
                    END IF;
                END LOOP;
            END $$
        """))

        # Copy old data (if rename path)
        if row_count > 0:
            conn.execute(sa.text("""
                INSERT INTO dbsmart_interactions
                    (session_id, user_id, company_id, step, action,
                     suggestion_shown, suggestion_accepted, user_override,
                     satisfaction, duration_ms, created_at)
                SELECT session_id, user_id, company_id, step, action,
                       suggestion_shown, suggestion_accepted, user_override,
                       satisfaction, duration_ms, created_at
                FROM dbsmart_interactions_old
            """))
            conn.execute(sa.text("""
                DROP TABLE IF EXISTS dbsmart_interactions_old CASCADE
            """))

    # --- 3. Archive table ---
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS dbsmart_interactions_archive (
            id BIGSERIAL PRIMARY KEY,
            original_id BIGINT,
            company_id INT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("""
        ALTER TABLE dbsmart_interactions_archive ENABLE ROW LEVEL SECURITY
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE POLICY pol_dbsmart_archive_isolation
            ON dbsmart_interactions_archive
            USING (
                company_id = NULLIF(current_setting('vyra.company_id', TRUE), '')::int
                OR current_setting('vyra.is_admin', TRUE) = 'true'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """))

    # --- 4. Bandit / analytics index ---
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_dbsmart_inter_user_action_ts
        ON dbsmart_interactions (user_id, action, created_at DESC)
    """))


def downgrade():
    conn = op.get_bind()

    # Drop archive table
    conn.execute(sa.text("""
        DROP TABLE IF EXISTS dbsmart_interactions_archive CASCADE
    """))

    # Drop index
    conn.execute(sa.text("""
        DROP INDEX IF EXISTS idx_dbsmart_inter_user_action_ts
    """))

    # Note: Converting back from partitioned to regular table is complex.
    # In production, a separate migration should handle this carefully.
    # For dev, we leave the partitioned table as-is (it's compatible).
