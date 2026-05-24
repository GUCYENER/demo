"""v3.35.0 — dbsmart_interactions company_id index (audit P1 S4 / FIX10)

Revision ID: 046_v3350_dbsmart_interactions_company_id_index
Revises: 045_v3341_audit_index_cap_rename
Create Date: 2026-05-24

FIX10 (NIKE+HEPHAESTUS+ARES) — Smart Discovery audit P1 S4:
Partitioned `dbsmart_interactions` tablosu büyüdükçe tenant-bazlı analitik
sorgular (company_id filtre + zaman aralığı) sequential scan riskine giriyor.

Çözüm: `(company_id, created_at DESC)` composite index — PG 11+ partitioned
tables üzerinde parent'a oluşturulduğunda tüm partition'lara otomatik propagate
edilir (mevcut + gelecek aylık partition'lar).

Index ismi `idx_dbsmart_interactions_company_id_created_at` — partition başına
PG otomatik suffix (`<partition>_<idx>_idx`) ekler.

Note: CONCURRENTLY partitioned table parent'ında desteklenmez. Migration
"IF NOT EXISTS" + parent-level index ile çalışır; partition'lar metadata-only
attach edilir (kısa lock; production'da maintenance window önerilir).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "046_v3350_dbsmart_interactions_company_id_index"
down_revision: Union[str, None] = "045_v3341_audit_index_cap_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Parent partitioned table → recurses to all partitions
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dbsmart_interactions_company_id_created_at "
        "ON dbsmart_interactions (company_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_dbsmart_interactions_company_id_created_at"
    )
