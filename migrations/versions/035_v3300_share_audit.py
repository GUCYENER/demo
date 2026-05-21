"""v3.30.0: share audience + audit log columns

Revision ID: 035_v3300_share_audit
Revises: 033_v3300_metric_library_seed
Create Date: 2026-05-21

FAZ 3 P38 — Share auth-bound viewer + audit log
-------------------------------------------------
dbsmart_saved_reports tablosuna 3 yeni kolon ekler:
- share_audience: 'public' | 'tenant' | 'users' (default 'public')
- share_allowed_user_ids: INT[] (NULL allowed)
- share_audit: JSONB (default '[]', max 20 entry head-append)

Idempotent: column existence check ile IF NOT EXISTS pattern.
"""
from alembic import op
import sqlalchemy as sa


revision = '035_v3300_share_audit'
down_revision = '033_v3300_metric_library_seed'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Add share_audience column
    conn.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE dbsmart_saved_reports
            ADD COLUMN share_audience VARCHAR(16) DEFAULT 'public';
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$
    """))

    # Add share_allowed_user_ids column
    conn.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE dbsmart_saved_reports
            ADD COLUMN share_allowed_user_ids INT[];
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$
    """))

    # Add share_audit JSONB column
    conn.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE dbsmart_saved_reports
            ADD COLUMN share_audit JSONB DEFAULT '[]'::jsonb;
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$
    """))

    # Add CHECK constraint for audience values
    conn.execute(sa.text("""
        DO $$ BEGIN
            ALTER TABLE dbsmart_saved_reports
            ADD CONSTRAINT chk_share_audience
            CHECK (share_audience IN ('public', 'tenant', 'users'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """))


def downgrade():
    conn = op.get_bind()

    conn.execute(sa.text("""
        ALTER TABLE dbsmart_saved_reports
        DROP CONSTRAINT IF EXISTS chk_share_audience
    """))
    conn.execute(sa.text("""
        ALTER TABLE dbsmart_saved_reports
        DROP COLUMN IF EXISTS share_audit
    """))
    conn.execute(sa.text("""
        ALTER TABLE dbsmart_saved_reports
        DROP COLUMN IF EXISTS share_allowed_user_ids
    """))
    conn.execute(sa.text("""
        ALTER TABLE dbsmart_saved_reports
        DROP COLUMN IF EXISTS share_audience
    """))
