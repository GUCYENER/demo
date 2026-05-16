"""v3.25.0: pipeline_events tablosu (Faz 6c — observability)

Revision ID: 016_v3250_pipeline_events
Revises: 015_v3240_catboost_tables
Create Date: 2026-05-17

Faz 6c — Pipeline Observability
-------------------------------
Her node yürütülürken structured event yazılır. Amaç:
  - Node-bazında latency dağılımı (p50/p95)
  - Hata yoğunluğu (error_category × node)
  - Self-heal retry istatistikleri
  - Mode dağılımı (ast vs llm)

Tek tablo, append-only, partition-friendly (created_at index).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "016_v3250_pipeline_events"
down_revision: Union[str, None] = "015_v3240_catboost_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_events (
        id BIGSERIAL PRIMARY KEY,
        run_id UUID NOT NULL,
        company_id INTEGER,
        source_id INTEGER,
        user_id INTEGER,
        event_type TEXT NOT NULL,        -- 'node_start','node_end','pipeline_start',
                                          -- 'pipeline_end','interrupt','self_heal',
                                          -- 'stream_chunk','error'
        node_name TEXT,                   -- intent_extract / multi_signal_rank / ...
        duration_ms INTEGER,              -- node_end için süre
        status TEXT,                      -- 'ok' | 'error' | 'skipped'
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_pipeline_events_run
      ON pipeline_events(run_id, created_at);
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_pipeline_events_company_time
      ON pipeline_events(company_id, created_at DESC)
      WHERE company_id IS NOT NULL;
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_pipeline_events_type
      ON pipeline_events(event_type, created_at DESC);
    """)
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_pipeline_events_node_status
      ON pipeline_events(node_name, status)
      WHERE node_name IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pipeline_events CASCADE;")
