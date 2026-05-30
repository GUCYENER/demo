"""v3.38.3 — system_logs.request_id + hata sorgu indeksleri (Merkezi Hata Gözlemi)

Revision ID: 049_v3383_system_logs_request_id
Revises: 048_v3380_table_level_permissions
Create Date: 2026-05-30

Merkezi hata gözlemi (errors.jsonl + admin "Hata İzleme" UI) için:
- request_id kolonu: kullanıcının gördüğü 500 (X-Request-ID) ↔ log kaydı eşleşir.
- (level, created_at) indeksi: hata listesi sorgusu hızlı.
- request_id kismi indeksi: request_id ile tek kayda gitme hızlı.

Idempotent: IF NOT EXISTS. Downgrade: kolon + indeksler düşürülür.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "049_v3383_system_logs_request_id"
down_revision: Union[str, None] = "048_v3380_table_level_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = text(
    """
    ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(32);
    CREATE INDEX IF NOT EXISTS idx_system_logs_level_created
        ON system_logs(level, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_system_logs_request_id
        ON system_logs(request_id) WHERE request_id IS NOT NULL;
    """
)

_DOWNGRADE_SQL = text(
    """
    DROP INDEX IF EXISTS idx_system_logs_request_id;
    DROP INDEX IF EXISTS idx_system_logs_level_created;
    ALTER TABLE system_logs DROP COLUMN IF EXISTS request_id;
    """
)


def upgrade() -> None:
    op.get_bind().execute(_UPGRADE_SQL)
    print("[mig 049_v3383] system_logs.request_id + error indexes ready")


def downgrade() -> None:
    op.get_bind().execute(_DOWNGRADE_SQL)
