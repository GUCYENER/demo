"""v3.32.0 — merge: error_pattern_review + fernet_key_version

Revision ID: 042_v3320_merge_error_review_fernet
Revises: 040_v3320_error_pattern_review, 041_v3320_fernet_key_version
Create Date: 2026-05-23

Ajan-I (040) ve Ajan-J (041) disjoint paralel dispatch sırasında ikisi de
`down_revision = "038_v3320_fk_position"` ile dallandı. Bu boş merge migration
iki head'i tek başa birleştirir; herhangi bir DDL içermez.

NOT: Mevcut migrations/versions/042_v3300_query_examples.py dosyasının
revision id'si farklı (`042_v3300_query_examples`), aynı sayıyla
çakışmaz çünkü alembic revision string'ler.
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "042_v3320_merge_error_review_fernet"
down_revision: Union[str, Sequence[str], None] = (
    "040_v3320_error_pattern_review",
    "041_v3320_fernet_key_version",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge: branched heads (040 + 041) → tek linear head."""
    pass


def downgrade() -> None:
    """No-op merge downgrade — alembic ikiye böler."""
    pass
