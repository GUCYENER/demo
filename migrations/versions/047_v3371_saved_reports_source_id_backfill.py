"""v3.37.1 — dbsmart_saved_reports.source_id + last_dialect backfill

Revision ID: 047_v3371_saved_reports_source_id_backfill
Revises: 046_v3350_dbsmart_interactions_company_id_index
Create Date: 2026-05-26

Brief A (v3.37.1) — saved-report rerun port/dialect re-resolve.

dbsmart_saved_reports satirlarinda source_id NULL + wizard_state ? 'source_id'
oldugunda data_sources.db_type ile join edip source_id ve last_dialect
alanlarini doldurur. Bu sayede rerun yolu (_load_source) wizard_state
literal'larina degil canli data_sources kaydina basvurabilir.

Idempotent: ikinci kosumda source_id IS NULL filtresi 0 satir doner.
Downgrade: no-op (geri alma backfill semantik olarak anlamli degil).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "047_v3371_saved_reports_source_id_backfill"
down_revision: Union[str, None] = "046_v3350_dbsmart_interactions_company_id_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_SQL = text(
    """
    WITH targets AS (
        SELECT r.id,
               (r.wizard_state->>'source_id')::int AS sid,
               ds.db_type AS dialect
        FROM dbsmart_saved_reports r
        JOIN data_sources ds
          ON ds.id = (r.wizard_state->>'source_id')::int
        WHERE r.source_id IS NULL
          AND r.wizard_state ? 'source_id'
    )
    UPDATE dbsmart_saved_reports r
    SET source_id    = t.sid,
        last_dialect = t.dialect,
        updated_at   = NOW()
    FROM targets t
    WHERE r.id = t.id
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(_BACKFILL_SQL)
    try:
        rowcount = result.rowcount
    except Exception:
        rowcount = -1
    print(f"[mig 047_v3371] backfilled {rowcount} saved-report rows")


def downgrade() -> None:
    # Backfill geri alinmaz — eldeki source_id/last_dialect degerleri korunur.
    pass
