"""v3.38.0 — Tablo bazli yetkilendirme (DB + schema + tablo)

Revision ID: 048_v3380_table_level_permissions
Revises: 047_v3371_saved_reports_source_id_backfill
Create Date: 2026-05-29

Kaynak (data source) yetkilendirmesini DB seviyesinden tablo seviyesine indirir.

1. data_source_permissions.scope_mode kolonu eklenir:
   - 'all'        : kaynaktaki TUM tablolar (geriye uyumlu varsayilan — mevcut
                    tum satirlar bu degeri alir, davranis aynen korunur)
   - 'restricted' : yalniz data_source_table_permissions allowlist'i
   restricted + 0 tablo => hicbir tablo okunamaz (dokuman geregi).

2. data_source_table_permissions tablosu olusturulur — (schema, tablo) allowlist.
   Bir kullanicinin nihai erisimi = direkt + org grant birlesimi; herhangi bir
   grant 'all' ise TUM tablolar erisilebilir (bkz. app/services/data_source_access).

Idempotent: kolon/tablo IF NOT EXISTS ile eklenir.
Downgrade: tablo + kolon dusurulur (allowlist verisi kaybolur).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "048_v3380_table_level_permissions"
down_revision: Union[str, None] = "047_v3371_saved_reports_source_id_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = text(
    """
    -- 1) scope_mode kolonu (mevcut satirlar 'all' = mevcut davranis)
    ALTER TABLE data_source_permissions
        ADD COLUMN IF NOT EXISTS scope_mode VARCHAR(16) NOT NULL DEFAULT 'all';

    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'data_source_permissions_scope_mode_chk'
        ) THEN
            ALTER TABLE data_source_permissions
                ADD CONSTRAINT data_source_permissions_scope_mode_chk
                CHECK (scope_mode IN ('all','restricted'));
        END IF;
    END $$;

    -- 2) tablo bazli allowlist
    CREATE TABLE IF NOT EXISTS data_source_table_permissions (
        id SERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        subject_type VARCHAR(10) NOT NULL CHECK (subject_type IN ('user','org')),
        subject_id INTEGER NOT NULL,
        schema_name VARCHAR(255) NOT NULL,
        table_name VARCHAR(255) NOT NULL,
        granted_at TIMESTAMP DEFAULT NOW(),
        granted_by INTEGER REFERENCES users(id),
        UNIQUE(source_id, subject_type, subject_id, schema_name, table_name)
    );
    CREATE INDEX IF NOT EXISTS idx_ds_table_perm_subject
        ON data_source_table_permissions(source_id, subject_type, subject_id);
    CREATE INDEX IF NOT EXISTS idx_ds_table_perm_lookup
        ON data_source_table_permissions(source_id, schema_name, table_name);
    """
)

_DOWNGRADE_SQL = text(
    """
    DROP TABLE IF EXISTS data_source_table_permissions;
    ALTER TABLE data_source_permissions
        DROP CONSTRAINT IF EXISTS data_source_permissions_scope_mode_chk;
    ALTER TABLE data_source_permissions
        DROP COLUMN IF EXISTS scope_mode;
    """
)


def upgrade() -> None:
    op.get_bind().execute(_UPGRADE_SQL)
    print("[mig 048_v3380] scope_mode + data_source_table_permissions ready")


def downgrade() -> None:
    op.get_bind().execute(_DOWNGRADE_SQL)
