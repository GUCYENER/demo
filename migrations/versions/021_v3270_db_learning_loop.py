"""v3.27.0: DB Learning Loop — learned_db_queries + ds_synthetic_query_runs + pipeline_traces

Revision ID: 021_v3270_db_learning_loop
Revises: 020_v3260_query_decisions
Create Date: 2026-05-18

v3.27.0 — Veritabanında Ara Öğrenme Döngüsü
============================================
Plan: .agents/plans/v3.27_db_learning_loop.md

FAZ A — Çekirdek Öğrenme Döngüsü (G1 + G3 + G4)
-----------------------------------------------
Üç yeni tablo:

1. **learned_db_queries** (G3 — DB LLM bypass cache)
   - Başarılı (soru,SQL) çiftleri saklar; benzer soru gelince LLM bypass
   - 3 katmanlı dedupe: SHA256(canonical_sql) UNIQUE + cosine 0.92 + Jaccard 0.85

2. **ds_synthetic_query_runs** (G1 — FK synthetic execution audit)
   - Her FK için üretilen template sorgunun çalıştırma kaydı
   - Per (relationship_id, template_kind) tek satır → tekrar üretim yok

3. **pipeline_traces** (G9 — reasoning trace storage)
   - Her sorgu için pipeline state snapshot (candidates, scores, few-shots used)
   - Admin debug + ML training feature kaynağı

Kural: Tüm tablolar RLS PERMISSIVE (017 pattern). Embedding kolonları pgvector varsa
vector(384), yoksa float[] (graceful fallback — 014/009 pattern).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "021_v3270_db_learning_loop"
down_revision: Union[str, None] = "020_v3260_query_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY_USING_PERMISSIVE = """(
    current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""

_POLICY_CHECK_PERMISSIVE = """(
    company_id IS NULL
    OR current_setting('app.current_company_id', true) IS NULL
    OR current_setting('app.current_company_id', true) = ''
    OR current_setting('app.bypass_rls', true) = 'on'
    OR company_id::text = current_setting('app.current_company_id', true)
)"""


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"DROP POLICY IF EXISTS rls_company_scoped ON {table};")
    op.execute(f"""
    CREATE POLICY rls_company_scoped ON {table}
        FOR ALL
        USING {_POLICY_USING_PERMISSIVE}
        WITH CHECK {_POLICY_CHECK_PERMISSIVE};
    """)


def upgrade() -> None:
    # ============================================================
    # 1. learned_db_queries — DB LLM bypass cache
    # ============================================================
    op.execute("""
    DO $$
    DECLARE
        v_emb_type TEXT;
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            v_emb_type := 'vector(384)';
        ELSE
            v_emb_type := 'float[]';
        END IF;

        EXECUTE format($f$
        CREATE TABLE IF NOT EXISTS learned_db_queries (
            id BIGSERIAL PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            question_normalized TEXT NOT NULL,
            question_embedding %s,
            sql_query TEXT NOT NULL,
            sql_hash CHAR(64) NOT NULL,                  -- SHA256(canonical_sql) hex
            intent VARCHAR(64),
            schema_signature TEXT,                       -- "schema.tableA,schema.tableB" sortlu
            columns_meta JSONB DEFAULT '[]'::jsonb,      -- [{name, type, business_name}]
            result_fingerprint CHAR(64),                 -- SHA256(sorted column types + row_count_bucket)
            source VARCHAR(32) NOT NULL DEFAULT 'user',  -- 'user' | 'synthetic' | 'manual'
            hit_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 1,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            tsv TSVECTOR,
            CONSTRAINT uniq_learned_sql_per_source UNIQUE (source_id, sql_hash)
        );
        $f$, v_emb_type);
    END $$;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_source ON learned_db_queries(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_company ON learned_db_queries(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_active ON learned_db_queries(is_active) WHERE is_active = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_intent ON learned_db_queries(intent);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_source_route ON learned_db_queries(source);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_hit ON learned_db_queries(hit_count DESC);")

    # tsv trigger (Türkçe FTS — pg_catalog.simple)
    op.execute("""
    CREATE OR REPLACE FUNCTION learned_db_tsv_update() RETURNS trigger AS $$
    BEGIN
        NEW.tsv := to_tsvector('pg_catalog.simple',
            coalesce(NEW.question, '') || ' ' ||
            coalesce(NEW.question_normalized, '') || ' ' ||
            coalesce(NEW.intent, '') || ' ' ||
            coalesce(NEW.schema_signature, '')
        );
        NEW.updated_at := NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    op.execute("""
    DROP TRIGGER IF EXISTS trg_learned_db_tsv ON learned_db_queries;
    CREATE TRIGGER trg_learned_db_tsv
        BEFORE INSERT OR UPDATE ON learned_db_queries
        FOR EACH ROW EXECUTE FUNCTION learned_db_tsv_update();
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_learned_db_tsv ON learned_db_queries USING gin(tsv);")

    # HNSW on embedding (pgvector varsa)
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_learned_db_emb_hnsw
                         ON learned_db_queries USING hnsw (question_embedding vector_cosine_ops)
                         WITH (m=16, ef_construction=64)
                         WHERE is_active = TRUE';
            EXCEPTION WHEN OTHERS THEN
                BEGIN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_learned_db_emb_ivf
                             ON learned_db_queries USING ivfflat (question_embedding vector_cosine_ops)
                             WITH (lists=100)';
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
            END;
        END IF;
    END $$;
    """)
    _enable_rls("learned_db_queries")

    # ============================================================
    # 2. ds_synthetic_query_runs — FK template execution audit
    # ============================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS ds_synthetic_query_runs (
        id BIGSERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        relationship_id BIGINT,                          -- ds_db_relationships.id (soft FK)
        from_schema VARCHAR(128),
        from_table VARCHAR(128),
        from_column VARCHAR(128),
        to_schema VARCHAR(128),
        to_table VARCHAR(128),
        to_column VARCHAR(128),
        template_kind VARCHAR(32) NOT NULL,              -- 'LOOKUP_JOIN' | 'AGGREGATE_COUNT'
        dialect VARCHAR(16) NOT NULL,                    -- postgresql | oracle | mssql | mysql
        rendered_sql TEXT NOT NULL,
        sql_hash CHAR(64) NOT NULL,                      -- SHA256 hex
        executed_at TIMESTAMPTZ DEFAULT NOW(),
        success BOOLEAN NOT NULL DEFAULT FALSE,
        row_count INTEGER,
        elapsed_ms INTEGER,
        error_message TEXT,
        learned_query_id BIGINT REFERENCES learned_db_queries(id) ON DELETE SET NULL,
        meta JSONB DEFAULT '{}'::jsonb,
        CONSTRAINT uniq_synth_per_rel_kind UNIQUE (source_id, relationship_id, template_kind)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_synth_source ON ds_synthetic_query_runs(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_synth_company ON ds_synthetic_query_runs(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_synth_executed ON ds_synthetic_query_runs(executed_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_synth_success ON ds_synthetic_query_runs(success);")
    _enable_rls("ds_synthetic_query_runs")

    # ============================================================
    # 3. pipeline_traces — reasoning trace storage (G9)
    # ============================================================
    op.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_traces (
        id BIGSERIAL PRIMARY KEY,
        run_id VARCHAR(64) NOT NULL,                     -- UUID per pipeline run
        dialog_id INTEGER REFERENCES dialogs(id) ON DELETE SET NULL,
        message_id INTEGER,                              -- dialog_messages.id (soft FK — assistant message)
        source_id INTEGER REFERENCES data_sources(id) ON DELETE CASCADE,
        company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        question TEXT NOT NULL,
        intent VARCHAR(64),
        intent_confidence REAL,
        cache_hit BOOLEAN DEFAULT FALSE,
        cache_hit_id BIGINT REFERENCES learned_db_queries(id) ON DELETE SET NULL,
        ast_shortcut_used BOOLEAN DEFAULT FALSE,
        candidates_json JSONB DEFAULT '[]'::jsonb,       -- ranked table candidates + scores
        selected_tables_json JSONB DEFAULT '[]'::jsonb,
        few_shot_ids BIGINT[],                           -- few_shot_examples.id referansları
        sql_generated TEXT,
        validation_errors JSONB DEFAULT '[]'::jsonb,
        self_heal_iterations SMALLINT DEFAULT 0,
        execute_success BOOLEAN,
        row_count INTEGER,
        elapsed_ms INTEGER,
        feedback_value SMALLINT,                         -- 1 helpful, 0 neutral, -1 negative
        feedback_id BIGINT,                              -- user_feedback.id soft FK
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_run ON pipeline_traces(run_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_source ON pipeline_traces(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_company ON pipeline_traces(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_user ON pipeline_traces(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_created ON pipeline_traces(created_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_cache_hit ON pipeline_traces(cache_hit) WHERE cache_hit = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trace_dialog ON pipeline_traces(dialog_id);")
    _enable_rls("pipeline_traces")


def downgrade() -> None:
    for tbl in ("pipeline_traces", "ds_synthetic_query_runs", "learned_db_queries"):
        op.execute(f"DROP POLICY IF EXISTS rls_company_scoped ON {tbl};")
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
    op.execute("DROP TRIGGER IF EXISTS trg_learned_db_tsv ON learned_db_queries;")
    op.execute("DROP FUNCTION IF EXISTS learned_db_tsv_update();")
