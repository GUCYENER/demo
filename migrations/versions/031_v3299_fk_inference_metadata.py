"""v3.29.9: FK Inference Metadata — ds_db_relationships extension

Revision ID: 031_v3299_fk_inference_metadata
Revises: 030_v3298_signal_weight_overrides
Create Date: 2026-05-19

v3.29.9 — FK Inference Layer (declared + inferred birleşik graph)
==================================================================
Plan: .agents/plans/v3.29.9_fk_inference.md

Mevcut FK keşfi sadece DB'nin DECLARE ettiği FK'ları okuyor
(pg_constraint contype='f'). Enterprise sistemler (OnedeskTest gibi)
ORM/app-layer FK enforcement kullandığı için DB'de FK declare etmiyor
→ multi_signal_rank.fk_centrality, fk_graph_resolver, Query Builder v2
hepsi zayıf graph üzerinde çalışıyor.

Bu migration ds_db_relationships'i inferred FK metadata ile genişletir:
    - is_inferred BOOL — declared vs inferred ayrımı
    - inference_method VARCHAR(32) — 'naming' | 'naming+type' | 'naming+type+sample'
    - evidence_json JSONB — {naming_pattern, type_match, sample_coverage, sample_size, ...}
    - admin_verified BOOL — admin onayı (declared FK'lar default TRUE)
    - verified_by, verified_at — onay audit
    - rejected_at TIMESTAMPTZ — admin "yanlış" derse soft-delete (NULL = aktif)

NOT: confidence_score zaten v3.29.0 migration 023'te eklendi (Faz 6 G1
cardinality_analyzer için), reuse edilir. Yeni kolon eklenmez.

Backfill:
    Tüm mevcut satırlar declared FK olarak işaretlenir:
        is_inferred = FALSE
        admin_verified = TRUE  (DB declare etti, zaten doğrulanmış)
        inference_method = NULL

System settings:
    FK_INFERENCE_DEPLOY_TS — deploy zamanı; signal_weight_analyzer
    bunu okuyarak fk_centrality Pearson'unu deploy öncesi event'lerden
    izole eder (v3.29.8 senkron).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "031_v3299_fk_inference_metadata"
down_revision: Union[str, None] = "030_v3298_signal_weight_overrides"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE ds_db_relationships
        ADD COLUMN IF NOT EXISTS is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS inference_method VARCHAR(32),
        ADD COLUMN IF NOT EXISTS evidence_json JSONB,
        ADD COLUMN IF NOT EXISTS admin_verified BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS verified_by INTEGER
            REFERENCES users(id) ON DELETE SET NULL,
        ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ;
    """)

    # CHECK constraints (idempotent — DROP+ADD pattern)
    op.execute("""
    ALTER TABLE ds_db_relationships
        DROP CONSTRAINT IF EXISTS ck_dsdrel_inference_method;
    """)
    op.execute("""
    ALTER TABLE ds_db_relationships
        ADD CONSTRAINT ck_dsdrel_inference_method
        CHECK (inference_method IS NULL OR inference_method IN (
            'naming', 'naming+type', 'naming+type+sample', 'manual', 'llm'
        ));
    """)

    # Backfill: tüm mevcut satırlar declared FK → admin_verified=TRUE
    # is_inferred default FALSE zaten, admin_verified default FALSE'tu →
    # mevcut satırların admin_verified'ını TRUE yap (DB declare etmiş = onaylı)
    op.execute("""
    UPDATE ds_db_relationships
       SET admin_verified = TRUE
     WHERE admin_verified = FALSE
       AND is_inferred = FALSE
       AND verified_at IS NULL;
    """)

    # Indexler
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dsdrel_inferred_pending
        ON ds_db_relationships(source_id)
        WHERE is_inferred = TRUE AND admin_verified = FALSE AND rejected_at IS NULL;
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dsdrel_active
        ON ds_db_relationships(source_id)
        WHERE rejected_at IS NULL;
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_dsdrel_method
        ON ds_db_relationships(inference_method)
        WHERE inference_method IS NOT NULL;
    """)

    # Deploy timestamp (v3.29.8 signal_weight_analyzer Pearson window filter için)
    op.execute("""
    INSERT INTO system_settings (setting_key, setting_value, description)
    VALUES (
        'fk_inference_deploy_ts',
        NOW()::TEXT,
        'v3.29.9 FK inference deploy zamanı — signal_weight_analyzer fk_centrality semantik değişiminden önceki event''leri filtreler'
    )
    ON CONFLICT (setting_key) DO UPDATE
        SET setting_value = EXCLUDED.setting_value,
            description = EXCLUDED.description,
            updated_at = CURRENT_TIMESTAMP;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE setting_key = 'fk_inference_deploy_ts';")
    op.execute("DROP INDEX IF EXISTS idx_dsdrel_method;")
    op.execute("DROP INDEX IF EXISTS idx_dsdrel_active;")
    op.execute("DROP INDEX IF EXISTS idx_dsdrel_inferred_pending;")
    op.execute("ALTER TABLE ds_db_relationships DROP CONSTRAINT IF EXISTS ck_dsdrel_inference_method;")
    op.execute("""
    ALTER TABLE ds_db_relationships
        DROP COLUMN IF EXISTS rejected_at,
        DROP COLUMN IF EXISTS verified_at,
        DROP COLUMN IF EXISTS verified_by,
        DROP COLUMN IF EXISTS admin_verified,
        DROP COLUMN IF EXISTS evidence_json,
        DROP COLUMN IF EXISTS inference_method,
        DROP COLUMN IF EXISTS is_inferred;
    """)
