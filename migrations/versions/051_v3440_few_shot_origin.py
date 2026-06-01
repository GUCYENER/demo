"""v3.44.0 P1 — few_shot_examples.origin + is_active (sentetik few-shot terfi)

Revision ID: 051_v3440_few_shot_origin
Revises: 050_v3430_ds_jobs_progress
Create Date: 2026-06-01

FK Loop'un doğrulanmış sentetik sorgularını few_shot_examples'a terfi edebilmek için:
- origin VARCHAR(16) DEFAULT 'user'  → 'user' | 'synthetic_fk' | 'synthetic_llm' | 'manual'
  (selector sentetiği gerçeğe göre ağırlıklasın/cap'lesin; selektif invalidation)
- is_active BOOLEAN DEFAULT TRUE     → soft-delete / devre-dışı (drift veya admin)

Idempotent: ADD COLUMN IF NOT EXISTS. Mevcut kayıtlar DEFAULT 'user'/TRUE alır.
Downgrade: kolonlar düşürülür.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "051_v3440_few_shot_origin"
down_revision: Union[str, None] = "050_v3430_ds_jobs_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = text(
    """
    ALTER TABLE few_shot_examples ADD COLUMN IF NOT EXISTS origin VARCHAR(16) DEFAULT 'user';
    ALTER TABLE few_shot_examples ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
    CREATE INDEX IF NOT EXISTS idx_few_shot_origin ON few_shot_examples(origin);
    CREATE INDEX IF NOT EXISTS idx_few_shot_active ON few_shot_examples(is_active) WHERE is_active = TRUE;
    """
)

_DOWNGRADE_SQL = text(
    """
    DROP INDEX IF EXISTS idx_few_shot_active;
    DROP INDEX IF EXISTS idx_few_shot_origin;
    ALTER TABLE few_shot_examples DROP COLUMN IF EXISTS is_active;
    ALTER TABLE few_shot_examples DROP COLUMN IF EXISTS origin;
    """
)


def upgrade() -> None:
    op.get_bind().execute(_UPGRADE_SQL)
    print("[mig 051_v3440] few_shot_examples.origin + is_active ready")


def downgrade() -> None:
    op.get_bind().execute(_DOWNGRADE_SQL)
