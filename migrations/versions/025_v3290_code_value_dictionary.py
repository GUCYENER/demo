"""v3.29.1: Code Value Dictionary — ds_code_values

Revision ID: 025_v3290_code_value_dictionary
Revises: 024_v3290_business_glossary_v2
Create Date: 2026-05-19

v3.29.1 — Faz 6 G2 (2/2): Code Value sözlüğü
--------------------------------------------
Plan: C:/Users/EXT02D059293/.claude/plans/binary-hugging-bengio.md

Kullanım amacı:
    DB'deki kodlu kolonlar (örn. ActionCd='StepUnderTook', PriorityLvl='H')
    Türkçe etiketlere ve açıklamalara eşlenir. Pipeline'da intent_extract
    ve sql_generate node'ları bu sözlüğü prompt'a "CODE VALUE HINTS" olarak
    enjekte eder; ranker ise eşleşen kodları semantik sinyale ekler.

CREATE TABLE ds_code_values (
    id BIGSERIAL PK,
    source_id   INT FK
    company_id  INT FK
    table_name  VARCHAR
    column_name VARCHAR
    code_value  VARCHAR        -- ham veritabanı değeri (örn 'StepUnderTook')
    label_tr    VARCHAR        -- "Üstlenen"
    label_en    VARCHAR        -- "Picked up"
    description_tr TEXT
    ordinal     SMALLINT       -- görsel sıralama
    is_active   BOOLEAN
    inferred_by VARCHAR(16)    -- 'llm' | 'admin' | 'sample_scan'
    confidence  REAL 0..1
    embedding   vector(384)|float[]
    usage_count INT
    last_used_at TIMESTAMPTZ
    created_at, updated_at TIMESTAMPTZ
    UNIQUE(source_id, table_name, column_name, code_value)
);

RLS PERMISSIVE (017 pattern) — company_id bazlı.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "025_v3290_code_value_dictionary"
down_revision: Union[str, None] = "024_v3290_business_glossary_v2"
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
        CREATE TABLE IF NOT EXISTS ds_code_values (
            id BIGSERIAL PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            table_name VARCHAR(256) NOT NULL,
            column_name VARCHAR(256) NOT NULL,
            code_value VARCHAR(256) NOT NULL,
            label_tr VARCHAR(256),
            label_en VARCHAR(256),
            description_tr TEXT,
            ordinal SMALLINT DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            inferred_by VARCHAR(16) NOT NULL DEFAULT 'sample_scan'
                CHECK (inferred_by IN ('llm','admin','sample_scan')),
            confidence REAL NOT NULL DEFAULT 0.0
                CHECK (confidence >= 0.0 AND confidence <= 1.0),
            embedding %s,
            usage_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_ds_code_values UNIQUE (source_id, table_name, column_name, code_value)
        );
        $f$, v_emb_type);
    END $$;
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_code_values_source ON ds_code_values(source_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_code_values_company ON ds_code_values(company_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_code_values_lookup ON ds_code_values(source_id, table_name, column_name, code_value);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_code_values_active ON ds_code_values(is_active) WHERE is_active = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ds_code_values_inferred ON ds_code_values(inferred_by);")

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
            BEGIN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ds_code_values_emb_hnsw
                         ON ds_code_values USING hnsw (embedding vector_cosine_ops)
                         WITH (m=16, ef_construction=64)
                         WHERE is_active = TRUE';
            EXCEPTION WHEN OTHERS THEN
                BEGIN
                    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_ds_code_values_emb_ivf
                             ON ds_code_values USING ivfflat (embedding vector_cosine_ops)
                             WITH (lists=100)';
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
            END;
        END IF;
    END $$;
    """)

    _enable_rls("ds_code_values")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rls_company_scoped ON ds_code_values;")
    op.execute("DROP TABLE IF EXISTS ds_code_values CASCADE;")
