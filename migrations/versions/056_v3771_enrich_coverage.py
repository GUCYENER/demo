"""v3.77.1 (Tema-1 Residual-3) — ds_table_enrichments kolon-kapsama (kısmi/başarısız enrichment rozeti)

Revision ID: 056_v3771_enrich_coverage
Revises: 055_v3770_fk_diagnostics
Create Date: 2026-06-06

enrich_table 'columns_enriched' (GERÇEK etiketlenen kolon sayısı) hesaplıyor + Hata İzleme'ye loglyor
(v3.75.0) ama PERSIST etmiyordu → UI'de tablo başına "kısmi/başarısız → Yeniden Öğren" rozeti gösterilemiyordu
(kullanıcı bulgusu: '312 LLM BEKLEYEN'). Bu migration columns_enriched + columns_total alanlarını ekler.
Idempotent (ADD COLUMN IF NOT EXISTS). source_id-scoped tablo; RLS değişmez.

Downgrade: kolonlar düşürülür.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "056_v3771_enrich_coverage"
down_revision: Union[str, None] = "055_v3770_fk_diagnostics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE ds_table_enrichments ADD COLUMN IF NOT EXISTS columns_enriched INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE ds_table_enrichments ADD COLUMN IF NOT EXISTS columns_total INTEGER DEFAULT 0;")
    print("[mig 056_v3771] ds_table_enrichments columns_enriched/columns_total ready")


def downgrade() -> None:
    op.execute("ALTER TABLE ds_table_enrichments DROP COLUMN IF EXISTS columns_enriched;")
    op.execute("ALTER TABLE ds_table_enrichments DROP COLUMN IF EXISTS columns_total;")
