"""v3.32.0 — data_sources.key_version (Fernet key rotation tracking)

Revision ID: 041_v3320_fernet_key_version
Revises: 038_v3320_fk_position
Create Date: 2026-05-23

Plan: .agents/in_flight/2026-05-23_smart-J_fernet-rotation-mvp.md

Ajan-J MVP — Fernet Credential Rotation Infrastructure
------------------------------------------------------
`data_sources.db_password_encrypted` Fernet ile şifreli olarak saklanıyor;
ancak master key compromise olursa tüm DS şifrelerinin hangi key ile
şifrelendiği bilgisi yok. Bu migration:

1) `key_version INTEGER NOT NULL DEFAULT 1` kolonu ekler. Mevcut tüm
   satırlar varsayılan olarak v1 ile etiketlenir (geriye uyum).
2) `idx_data_sources_key_version` partial-olmayan index — rotation script
   ileride "WHERE key_version < <current>" sorgusu yaparken kullanır.

Auto-scheduler v3.33'e ertelendi → bu MVP sadece kolon + script altyapısıdır.

NOT: down_revision alembic head'i `038_v3320_fk_position` olarak doğrulandı
(038 zinciri: 043 → 038 → 041).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "041_v3320_fernet_key_version"
down_revision: Union[str, None] = "038_v3320_fk_position"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) key_version kolonu — default 1 (geriye uyum: mevcut DS'ler v1 sayılır)
    op.execute("""
        ALTER TABLE data_sources
        ADD COLUMN IF NOT EXISTS key_version INTEGER NOT NULL DEFAULT 1;
    """)

    # 2) Rotation script "henüz rotate edilmemiş" sorgusunu hızlandırmak için
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_data_sources_key_version
        ON data_sources(key_version);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_data_sources_key_version;")
    op.execute("ALTER TABLE data_sources DROP COLUMN IF EXISTS key_version;")
