"""v3.43.0 — ds_discovery_jobs satır-bazlı ilerleme alanları (P1-D)

Revision ID: 050_v3430_ds_jobs_progress
Revises: 049_v3383_system_logs_request_id
Create Date: 2026-06-01

DB keşif/enrichment işlerinde "X/N tablo işlendi" canlı ilerleme göstergesi için:
- progress_current / progress_total: işlenen / toplam birim
- progress_stage: hangi adım ('samples', 'enrichment', ...)
- progress_updated_at: son ilerleme zamanı (UI "takıldı mı" tespiti)

Idempotent: ADD COLUMN IF NOT EXISTS. SCHEMA_SQL (app/core/schema.py) startup'ta da
aynı kolonları garanti eder; bu migration Alembic-yönetilen ortamlar için.
Downgrade: kolonlar düşürülür.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "050_v3430_ds_jobs_progress"
down_revision: Union[str, None] = "049_v3383_system_logs_request_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = text(
    """
    ALTER TABLE ds_discovery_jobs ADD COLUMN IF NOT EXISTS progress_current INTEGER DEFAULT 0;
    ALTER TABLE ds_discovery_jobs ADD COLUMN IF NOT EXISTS progress_total INTEGER DEFAULT 0;
    ALTER TABLE ds_discovery_jobs ADD COLUMN IF NOT EXISTS progress_stage VARCHAR(40);
    ALTER TABLE ds_discovery_jobs ADD COLUMN IF NOT EXISTS progress_updated_at TIMESTAMP;
    """
)

_DOWNGRADE_SQL = text(
    """
    ALTER TABLE ds_discovery_jobs DROP COLUMN IF EXISTS progress_updated_at;
    ALTER TABLE ds_discovery_jobs DROP COLUMN IF EXISTS progress_stage;
    ALTER TABLE ds_discovery_jobs DROP COLUMN IF EXISTS progress_total;
    ALTER TABLE ds_discovery_jobs DROP COLUMN IF EXISTS progress_current;
    """
)


def upgrade() -> None:
    op.get_bind().execute(_UPGRADE_SQL)
    print("[mig 050_v3430] ds_discovery_jobs progress columns ready")


def downgrade() -> None:
    op.get_bind().execute(_DOWNGRADE_SQL)
