"""v3.30.0 FAZ 4 P22 — Feature Store materialized views

Revision ID: 037_v3300_feature_store_mvs
Revises: 033_v3300_metric_library_seed
Create Date: 2026-05-21

FAZ 4 P22 — Feature Store base. İki materialized view CatBoost wizard
ranker'ları (P23-P27) tarafından eğitim/predict pipeline'larında
kullanılır. Refresh planı (scheduler hook'u ileride):
    - mv_dbsmart_user_features : haftalık (Pzt 02:00 ART)
    - mv_dbsmart_table_features: gecelik (03:30 ART)

REFRESH MATERIALIZED VIEW CONCURRENTLY gereksinimi → her MV için
UNIQUE INDEX şart. Hem (user_id) hem (table_id, company_id) tekil bir
satır garanti ediyor; aksi halde CONCURRENTLY REFRESH PG tarafında
ERROR ile reddedilir.

RLS:
    Materialized view'ler Postgres'te native olarak RLS desteklemez.
    Bu yüzden her MV `company_id` (ve gerekli yerlerde `source_id`)
    kolonlarını içerir ve downstream `feature_store.py` sorguları
    daima `WHERE company_id = …` filtresi UYGULAR. Cross-tenant
    sızıntı için ek defans bu uygulama-katmanı guard'ıdır.

NOTE: FAZ 2 P30 (034_dbsmart_interactions_partitioning) ileride
ayrı merge edilebilir; bu revision bağımsızdır ve yalnızca MV ekler.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "037_v3300_feature_store_mvs"
down_revision: Union[str, None] = "035_v3300_share_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) mv_dbsmart_user_features — per-user 30g moving window
    # ------------------------------------------------------------------
    # CREATE MATERIALIZED VIEW IF NOT EXISTS — PG 9.5+ destekli.
    # WITH NO DATA: ilk REFRESH komutu kayıtları üretir (deploy sırasında
    # boş tablodayken sorgu maliyeti olmasın).
    op.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_dbsmart_user_features AS
    WITH
    inter_agg AS (
        SELECT
            i.user_id,
            i.company_id,
            COUNT(*) FILTER (WHERE i.action = 'QueryExecuted')                  AS total_queries_30d,
            COUNT(DISTINCT (i.suggestion_accepted->>'category'))                AS domain_diversity,
            COUNT(DISTINCT (i.suggestion_accepted->>'table_id'))                AS table_coverage,
            COUNT(*) FILTER (WHERE i.action = 'ReportRecommendationAccepted')   AS rec_acc,
            COUNT(*) FILTER (WHERE i.action = 'ReportRecommendationRejected')   AS rec_rej,
            COUNT(*) FILTER (WHERE i.action = 'ReportRecommendationShown')      AS rec_shown,
            MAX(i.created_at)                                                   AS last_active_ts
        FROM dbsmart_interactions i
        WHERE i.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY i.user_id, i.company_id
    ),
    sess_agg AS (
        SELECT
            s.user_id,
            s.company_id,
            AVG(EXTRACT(EPOCH FROM (COALESCE(s.completed_at, s.last_activity_at) - s.created_at)))::numeric(10,2) AS avg_session_duration_sec
        FROM dbsmart_sessions s
        WHERE s.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY s.user_id, s.company_id
    ),
    top_cats AS (
        SELECT
            user_id,
            company_id,
            ARRAY_AGG(category ORDER BY n DESC) FILTER (WHERE category IS NOT NULL) AS top_metric_categories
        FROM (
            SELECT
                i.user_id,
                i.company_id,
                (i.suggestion_accepted->>'category') AS category,
                COUNT(*) AS n,
                ROW_NUMBER() OVER (
                    PARTITION BY i.user_id, i.company_id
                    ORDER BY COUNT(*) DESC
                ) AS rn
            FROM dbsmart_interactions i
            WHERE i.action IN ('MetricChosen','CustomMetricWritten')
              AND i.suggestion_accepted ? 'category'
              AND i.created_at >= NOW() - INTERVAL '30 days'
            GROUP BY i.user_id, i.company_id, (i.suggestion_accepted->>'category')
        ) ranked
        WHERE rn <= 5
        GROUP BY user_id, company_id
    )
    SELECT
        ia.user_id                                                            AS user_id,
        ia.company_id                                                         AS company_id,
        COALESCE(ia.total_queries_30d, 0)                                     AS total_queries_30d,
        COALESCE(sa.avg_session_duration_sec, 0)::numeric(10,2)               AS avg_session_duration_sec,
        COALESCE(ia.domain_diversity, 0)                                      AS domain_diversity,
        COALESCE(ia.table_coverage, 0)                                        AS table_coverage,
        CASE
            WHEN COALESCE(ia.rec_acc,0) + COALESCE(ia.rec_rej,0) + COALESCE(ia.rec_shown,0) = 0
                THEN 0::numeric(5,4)
            ELSE (COALESCE(ia.rec_acc,0)::numeric
                  / (COALESCE(ia.rec_acc,0) + COALESCE(ia.rec_rej,0) + COALESCE(ia.rec_shown,0)))::numeric(5,4)
        END                                                                   AS recommendation_acceptance_rate,
        COALESCE(tc.top_metric_categories, ARRAY[]::text[])                   AS top_metric_categories,
        ia.last_active_ts                                                     AS last_active_ts,
        NOW()                                                                 AS refreshed_at
      FROM inter_agg ia
      LEFT JOIN sess_agg sa ON sa.user_id = ia.user_id AND sa.company_id = ia.company_id
      LEFT JOIN top_cats tc ON tc.user_id = ia.user_id AND tc.company_id = ia.company_id
    WITH NO DATA;
    """)

    # UNIQUE INDEX (user_id) — CONCURRENTLY REFRESH için ZORUNLU.
    # NOT: bir kullanıcı tek company'ye ait (RLS) — user_id tekil yeterli.
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_dbsmart_user_features_user
        ON mv_dbsmart_user_features (user_id);
    """)
    # Helper: şirket-bazlı analitik için son aktiflik DESC
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_mv_dbsmart_user_features_company_last
        ON mv_dbsmart_user_features (company_id, last_active_ts DESC);
    """)

    # ------------------------------------------------------------------
    # 2) mv_dbsmart_table_features — per-table 30g moving window
    # ------------------------------------------------------------------
    op.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_dbsmart_table_features AS
    WITH
    tbl_base AS (
        SELECT
            d.id                          AS table_id,
            d.source_id                   AS source_id,
            d.schema_name                 AS schema_name,
            d.object_name                 AS object_name,
            COALESCE(d.row_count_estimate, 0) AS row_count_est,
            CASE
                WHEN d.row_count_estimate IS NULL OR d.row_count_estimate <= 0       THEN 0
                WHEN d.row_count_estimate < 100                                       THEN 1
                WHEN d.row_count_estimate < 1000                                      THEN 2
                WHEN d.row_count_estimate < 10000                                     THEN 3
                WHEN d.row_count_estimate < 100000                                    THEN 4
                WHEN d.row_count_estimate < 1000000                                   THEN 5
                ELSE                                                                       6
            END::smallint                 AS row_count_bucket,
            CASE
                WHEN jsonb_typeof(to_jsonb(d.columns_json)) = 'array'
                    THEN jsonb_array_length(to_jsonb(d.columns_json))::smallint
                ELSE 0::smallint
            END                           AS column_count
        FROM ds_db_objects d
    ),
    fk_deg AS (
        SELECT
            t.id AS table_id,
            ((SELECT COUNT(*) FROM ds_db_relationships r WHERE r.source_id = t.source_id AND r.from_table = t.object_name) +
             (SELECT COUNT(*) FROM ds_db_relationships r WHERE r.source_id = t.source_id AND r.to_table   = t.object_name))::int AS deg
        FROM ds_db_objects t
    ),
    pii_cnt AS (
        SELECT
            te.source_id    AS source_id,
            te.schema_name  AS schema_name,
            te.table_name   AS object_name,
            COUNT(*) FILTER (WHERE ce.is_pii = TRUE) AS pii_n,
            COUNT(*)                                  AS col_n
        FROM ds_column_enrichments ce
        JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
        GROUP BY te.source_id, te.schema_name, te.table_name
    ),
    glossary_cnt AS (
        SELECT
            bg.company_id   AS company_id,
            bg.mapped_table AS mapped_table,
            COUNT(*)        AS term_n
        FROM business_glossary bg
        WHERE bg.mapped_table IS NOT NULL
        GROUP BY bg.company_id, bg.mapped_table
    ),
    sel_freq AS (
        SELECT
            i.company_id                                              AS company_id,
            ((i.suggestion_accepted->>'table_id')::int)               AS table_id,
            COUNT(*)                                                  AS select_freq,
            COUNT(DISTINCT i.user_id)                                 AS user_n
        FROM dbsmart_interactions i
        WHERE i.action = 'TableSelected'
          AND i.suggestion_accepted ? 'table_id'
          AND (i.suggestion_accepted->>'table_id') ~ '^[0-9]+$'
          AND i.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY i.company_id, ((i.suggestion_accepted->>'table_id')::int)
    ),
    -- Cartesian-ish: tablo × her şirket için satır üretmek yerine
    -- yalnızca interaction'ı olan veya glossary mapping'i olan
    -- (company_id, table_id) çiftlerini oluştur.
    ct_pairs AS (
        SELECT DISTINCT sf.table_id, sf.company_id
        FROM sel_freq sf
        WHERE sf.table_id IS NOT NULL
        UNION
        SELECT tb.table_id, gl.company_id
        FROM tbl_base tb
        JOIN glossary_cnt gl ON gl.mapped_table = tb.object_name
           OR gl.mapped_table = (tb.schema_name || '.' || tb.object_name)
    )
    SELECT
        cp.table_id                                                           AS table_id,
        cp.company_id                                                         AS company_id,
        tb.source_id                                                          AS source_id,
        COALESCE(tb.row_count_bucket, 0)::smallint                            AS row_count_bucket,
        COALESCE(tb.column_count, 0)::smallint                                AS column_count,
        LEAST(COALESCE(fd.deg, 0)::numeric / 10.0, 1.0)::numeric(6,4)         AS fk_centrality,
        CASE
            WHEN COALESCE(pc.col_n, 0) = 0 THEN 0::numeric(5,4)
            ELSE (COALESCE(pc.pii_n,0)::numeric
                  / COALESCE(pc.col_n,1))::numeric(5,4)
        END                                                                   AS pii_column_ratio,
        COALESCE(gl.term_n, 0)::smallint                                      AS business_glossary_term_count,
        COALESCE(sf.select_freq, 0)::int                                      AS select_frequency_30d,
        COALESCE(sf.user_n, 0)::int                                           AS distinct_user_count_30d,
        -- Heuristik: select_freq + glossary terms karışımı (placeholder).
        (COALESCE(sf.select_freq,0)::numeric * 0.1 + COALESCE(gl.term_n,0) * 0.5)::numeric(6,2)
                                                                              AS avg_query_complexity,
        NOW()                                                                 AS refreshed_at
      FROM ct_pairs cp
      JOIN tbl_base tb ON tb.table_id = cp.table_id
      LEFT JOIN fk_deg fd  ON fd.table_id = cp.table_id
      LEFT JOIN pii_cnt pc ON pc.source_id   = tb.source_id
                          AND pc.schema_name = tb.schema_name
                          AND pc.object_name = tb.object_name
      LEFT JOIN glossary_cnt gl ON gl.company_id   = cp.company_id
                               AND (gl.mapped_table = tb.object_name
                                    OR gl.mapped_table = (tb.schema_name || '.' || tb.object_name))
      LEFT JOIN sel_freq sf ON sf.company_id = cp.company_id
                           AND sf.table_id   = cp.table_id
    WITH NO DATA;
    """)

    # UNIQUE INDEX (table_id, company_id) — CONCURRENTLY REFRESH için ZORUNLU
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_dbsmart_table_features_tbl_co
        ON mv_dbsmart_table_features (table_id, company_id);
    """)
    # Helper: source bazlı sıklığa göre sıralı erişim
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_mv_dbsmart_table_features_source_freq
        ON mv_dbsmart_table_features (source_id, select_frequency_30d DESC);
    """)

    # ------------------------------------------------------------------
    # Deploy marker
    # ------------------------------------------------------------------
    op.execute("""
    INSERT INTO system_settings (setting_key, setting_value, description, updated_at)
    VALUES (
        'DBSMART_FEATURE_STORE_DEPLOY_TS',
        NOW()::text,
        'v3.30.0 FAZ 4 P22 — Feature Store materialized views deploy zamanı',
        NOW()
    )
    ON CONFLICT (setting_key) DO UPDATE
       SET setting_value = EXCLUDED.setting_value,
           updated_at    = NOW();
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dbsmart_table_features CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dbsmart_user_features CASCADE;")
    op.execute("DELETE FROM system_settings WHERE setting_key = 'DBSMART_FEATURE_STORE_DEPLOY_TS';")
