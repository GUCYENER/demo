"""v3.4.4 — RAG Pipeline Optimizasyonu: Versiyon güncelleme

Revision ID: 005_v344_rag_opt
Revises: 004_ds_enrichment_tables
Create Date: 2026-04-06
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers
revision: str = "005_v344_rag_opt"
down_revision: Union[str, None] = "004_ds_enrichment_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    v3.4.4 RAG Pipeline Optimizasyonu:
    - Bellek yönetimi (file_content DB'den lazy-load)
    - Threading → asyncio dönüşümü
    - Upload progress (XHR gerçek ölçüm)
    - Enhancement geçmişi widget
    - Word-level diff view
    - Polling optimizasyonu (status filtresi)
    - Enhancement timeout artırımı (300s)
    
    DB değişikliği: Sadece versiyon güncelleme (tablo değişikliği yok).
    """
    # system_settings tablosundaki app_version'ı güncelle
    op.execute("""
    UPDATE system_settings 
    SET setting_value = '3.4.4', 
        updated_at = NOW() 
    WHERE setting_key = 'app_version';
    """)


def downgrade() -> None:
    op.execute("""
    UPDATE system_settings 
    SET setting_value = '3.4.3', 
        updated_at = NOW() 
    WHERE setting_key = 'app_version';
    """)
