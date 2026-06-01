"""v3.46.0 P3 — ds_synthetic_query_runs.error_kind (sentetik hata sınıflandırma)

Revision ID: 052_v3460_synthetic_error_kind
Revises: 051_v3440_few_shot_origin
Create Date: 2026-06-01

FK Loop'un başarısız sentetik denemelerini ops panelinde SINIF bazında görebilmek için:
- error_kind VARCHAR(24)  → permission | not_found | type_mismatch | syntax | timeout |
  infra | empty | unknown (synthetic_errors.classify_synthetic_error üretir)

Idempotent: ADD COLUMN IF NOT EXISTS. Mevcut satırlar NULL (geriye dönük sınıflama yapılmaz;
yeni denemeler doldurur). Kısmi index yalnız sınıflı satırlar için (dağılım sorgusu hızlı).
Downgrade: kolon + index düşürülür.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "052_v3460_synthetic_error_kind"
down_revision: Union[str, None] = "051_v3440_few_shot_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = text(
    """
    ALTER TABLE ds_synthetic_query_runs ADD COLUMN IF NOT EXISTS error_kind VARCHAR(24);
    CREATE INDEX IF NOT EXISTS idx_synth_runs_error_kind
        ON ds_synthetic_query_runs(source_id, error_kind)
        WHERE error_kind IS NOT NULL;
    """
)

_DOWNGRADE_SQL = text(
    """
    DROP INDEX IF EXISTS idx_synth_runs_error_kind;
    ALTER TABLE ds_synthetic_query_runs DROP COLUMN IF EXISTS error_kind;
    """
)


def upgrade() -> None:
    op.get_bind().execute(_UPGRADE_SQL)
    print("[mig 052_v3460] ds_synthetic_query_runs.error_kind ready")


def downgrade() -> None:
    op.get_bind().execute(_DOWNGRADE_SQL)
