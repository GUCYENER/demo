"""v3.32.0 — ds_db_relationships.fk_position (composite FK ordering)

Revision ID: 038_v3320_fk_position
Revises: 043_v3320_bulk_phase2
Create Date: 2026-05-23

Plan: .agents/plans/2026-05-23_1645_fk_loop_v3320_improvements_v1.md

Composite FK ilişkilerinin (constraint_name aynı, fk_position 1..N farklı)
deterministik olarak gruplandırılabilmesi için ``fk_position`` kolonu eklenir.

Kullanım:
    - ``ds_learning_service`` 4 dialect FK keşfinde ``cc.position``,
      ``fkc.constraint_column_id``, ``idx``, ``kcu.ORDINAL_POSITION``
      değerlerini bu kolona INSERT eder.
    - ``fk_synthetic_generator._fetch_relationships`` ``(source_id,
      constraint_name)`` ile groupBy, ``fk_position`` ile order yaparak
      composite FK'leri tek ``Relationship`` olarak döndürür.

Geriye uyum:
    - Default 1 → mevcut tek-column FK'lerin davranışı değişmez.
    - Composite (multi-column) FK'ler için backfill ROW_NUMBER ile yapılır.

NOT: numara sırası tarihsel nedenle 038 olarak verilmiştir (brief gereği);
gerçek alembic head son release'lere göre değişebilir → down_revision o head'e
bağlanır. Migration çalıştırılmadan önce alembic chain'i doğrulanmalıdır.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "038_v3320_fk_position"
down_revision: Union[str, None] = "043_v3320_bulk_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) fk_position kolonu ekle (default 1 → tek-column FK uyumu)
    op.execute(
        "ALTER TABLE ds_db_relationships "
        "ADD COLUMN IF NOT EXISTS fk_position INTEGER NOT NULL DEFAULT 1;"
    )

    # 2) Backfill: aynı (source_id, constraint_name) altındaki satırlara
    #    id sırasına göre 1..N pozisyonu ata. constraint_name NULL ise
    #    tek-column FK olarak kabul edilir (default 1 zaten yeterli).
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_id, constraint_name
                       ORDER BY id
                   ) AS pos
            FROM ds_db_relationships
            WHERE constraint_name IS NOT NULL
              AND constraint_name <> ''
        )
        UPDATE ds_db_relationships r
        SET fk_position = ranked.pos
        FROM ranked
        WHERE r.id = ranked.id;
    """)

    # 3) Composite FK groupBy + order için partial index
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ds_db_rels_constraint "
        "ON ds_db_relationships(source_id, constraint_name, fk_position) "
        "WHERE constraint_name IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ds_db_rels_constraint;")
    op.execute(
        "ALTER TABLE ds_db_relationships DROP COLUMN IF EXISTS fk_position;"
    )
