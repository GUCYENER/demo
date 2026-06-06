"""v3.77.0 (Tema-1 kapalı-döngü) — ds_fk_diagnostics: FK çıkarımında çözülemeyen kolonlar

Revision ID: 055_v3770_fk_diagnostics
Revises: 054_v3530_sql_query_jobs
Create Date: 2026-06-06

infer-fks'in 'unresolved' listesi (no_pattern_match / no_target_table / target_pk_not_found) bugüne
kadar tek-atımlık dönüş-dict'te kalıyordu → admin "FK neden gelmedi"yi göremiyordu. Bu tablo onu KALICI
yapar (kök-neden görünürlüğü + trend). source_id-scoped (ds_db_relationships gibi; company_id/RLS YOK —
tenant gate'i endpoint'te _ensure_source_visible). Idempotent (IF NOT EXISTS) — startup SCHEMA_SQL ile
birebir aynı; çift-uygulama güvenli.

Downgrade: tablo düşürülür.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "055_v3770_fk_diagnostics"
down_revision: Union[str, None] = "054_v3530_sql_query_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ds_fk_diagnostics (
            id SERIAL PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            from_schema VARCHAR(100),
            from_table VARCHAR(200) NOT NULL,
            from_column VARCHAR(200) NOT NULL,
            reason VARCHAR(40) NOT NULL,
            root VARCHAR(200),
            head VARCHAR(200),
            evidence_json JSONB,
            is_fixed BOOLEAN NOT NULL DEFAULT FALSE,
            first_seen_at TIMESTAMP DEFAULT NOW(),
            last_seen_at TIMESTAMP DEFAULT NOW(),
            fixed_at TIMESTAMP
        );
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ds_fk_diag_unique
            ON ds_fk_diagnostics(source_id, COALESCE(from_schema,''), from_table, from_column);
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_fk_diag_open ON ds_fk_diagnostics(source_id, is_fixed);")
    print("[mig 055_v3770] ds_fk_diagnostics ready")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ds_fk_diagnostics;")
