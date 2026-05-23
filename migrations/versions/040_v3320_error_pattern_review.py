"""v3.32.0 — learned_query_failures.review_status (Error Pattern Approval UI)

Revision ID: 040_v3320_error_pattern_review
Revises: 038_v3320_fk_position
Create Date: 2026-05-23

Plan: .agents/in_flight/2026-05-23_smart-I_error-pattern-review.md

Ajan-I MVP — self_heal rewrite kararlarının audit edilebilir admin onay
akışı için ``learned_query_failures`` tablosuna yeni kolonlar eklenir:

    review_status   TEXT NOT NULL DEFAULT 'pending'
                    -- 'pending' | 'approved' | 'rejected'
    reviewed_by     INTEGER NULL REFERENCES users(id)
    reviewed_at     TIMESTAMPTZ NULL
    review_note     TEXT NULL

Bu kolonlar mevcut ``admin_approved`` BOOLEAN alanına ek olarak gelir.
``admin_approved`` mevcut few-shot pool kontrolü için korunur; yeni
``review_status`` ise admin'in açık karar/etiket tarihçesini taşır
(approve/reject + not + kim/ne zaman).

Geriye uyum:
    - Mevcut tüm satırlar `review_status='pending'` ile dolar.
    - Mevcut `admin_approved=TRUE` satırları için backfill: `review_status='approved'`.
    - Eski endpoint'ler etkilenmez (yeni kolonlar opsiyonel).

Index:
    - idx_lqf_review_status (partial — pending olanlar için, admin queue okumalarını hızlandırır).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "040_v3320_error_pattern_review"
down_revision: Union[str, None] = "038_v3320_fk_position"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Kolonları ekle (idempotent — IF NOT EXISTS)
    op.execute("""
        ALTER TABLE learned_query_failures
            ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS reviewed_by INTEGER NULL REFERENCES users(id),
            ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS review_note TEXT NULL;
    """)

    # 2) CHECK constraint — review_status enum benzeri kısıt
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_lqf_review_status'
            ) THEN
                ALTER TABLE learned_query_failures
                    ADD CONSTRAINT ck_lqf_review_status
                    CHECK (review_status IN ('pending','approved','rejected'));
            END IF;
        END $$;
    """)

    # 3) Backfill — mevcut admin_approved=TRUE satırları 'approved' olarak işaretle
    op.execute("""
        UPDATE learned_query_failures
        SET review_status = 'approved',
            reviewed_at = COALESCE(reviewed_at, last_seen_at, NOW())
        WHERE admin_approved = TRUE
          AND review_status = 'pending';
    """)

    # 4) Partial index — admin queue pending listesini hızlandır
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_lqf_review_status
            ON learned_query_failures(review_status, last_seen_at DESC)
            WHERE review_status = 'pending';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lqf_review_status;")
    op.execute("""
        ALTER TABLE learned_query_failures
            DROP CONSTRAINT IF EXISTS ck_lqf_review_status;
    """)
    op.execute("""
        ALTER TABLE learned_query_failures
            DROP COLUMN IF EXISTS review_note,
            DROP COLUMN IF EXISTS reviewed_at,
            DROP COLUMN IF EXISTS reviewed_by,
            DROP COLUMN IF EXISTS review_status;
    """)
