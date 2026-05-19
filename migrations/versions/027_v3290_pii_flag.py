"""v3.29.3: PII flag on ds_column_enrichments — disambiguation kartı + sample-data prompt için

Revision ID: 027_v3290_pii_flag
Revises: 026_v3290_template_versioning
Create Date: 2026-05-19

v3.29.3 — Faz 6 G4: Disambiguation Cards + Sample-Data Prompt
-------------------------------------------------------------
Plan: C:/Users/EXT02D059293/.claude/plans/binary-hugging-bengio.md

ds_column_enrichments tablosuna PII (kişisel veri) bayrağı ekler:
    - is_pii            BOOLEAN DEFAULT FALSE
        LLM auto-detect veya admin işareti. TRUE ise sample data
        prompt'a girmeden önce maskelenir (örn. "ahmet@x.com" → "a***@x.com").

    - pii_mask_strategy VARCHAR(32) DEFAULT 'redact'
        'redact' | 'hash' | 'partial' | 'none'

Admin onaylı (admin_approved=TRUE) kolonlardan is_pii=TRUE olanlar G4
sample-data injection sırasında zorunlu mask altında prompt'a verilir.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "027_v3290_pii_flag"
down_revision: Union[str, None] = "026_v3290_template_versioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE ds_column_enrichments
        ADD COLUMN IF NOT EXISTS is_pii BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS pii_mask_strategy VARCHAR(32) NOT NULL DEFAULT 'redact'
            CHECK (pii_mask_strategy IN ('redact','hash','partial','none'));
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_col_enrich_pii ON ds_column_enrichments(is_pii) WHERE is_pii = TRUE;")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_col_enrich_pii;")
    op.execute("""
    ALTER TABLE ds_column_enrichments
        DROP COLUMN IF EXISTS pii_mask_strategy,
        DROP COLUMN IF EXISTS is_pii;
    """)
