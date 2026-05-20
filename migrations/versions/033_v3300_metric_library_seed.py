"""v3.30.0 FAZ 1 G1.4 — Metric Library Seed (3 domain × 24+ metrik)

Revision ID: 033_v3300_metric_library_seed
Revises: 032_v3300_db_smart_core_tables
Create Date: 2026-05-19

Plan: .agents/plans/v3.30.0_db_smart_wizard.md §G1.4
Mimari: docs/db_smart/01_architecture.md

3 Domain × 30 metrik (target: 24+):
    - generic   (8) — top_n_by, time_series_count, distinct_distribution, null_ratio,
                       sum, avg, count_distinct, group_by_category
    - helpdesk (12) — oldest_open, sla_critical_top10, avg_resolution_hours,
                       daily_open_trend, reopen_ratio, backlog_aging,
                       team_distribution, first_response_time, p1_p2_count,
                       weekend_load, ticket_lifecycle_funnel, sla_breach_count
    - sales    (10) — top_customer_revenue, monthly_trend, avg_basket,
                       repeat_purchase_ratio, conversion_funnel, rfm_segment,
                       daily_revenue, top_product, geographic_distribution,
                       churn_risk_cohort

Her metrik 4 dialect SQL template (postgresql, oracle, mssql, mysql) içerir.
Parametre placeholder formatı: :limit, :date_from, :date_to, :status_open_values vb.

İdempotent: ON CONFLICT (metric_key) DO NOTHING.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "033_v3300_metric_library_seed"
down_revision: str = "032_v3300_db_smart_core_tables"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Metrik tanımları — bilinçli olarak ayrı liste/sözlüklerle (review-kolay)
# Her metrik: metric_key, name_tr, category, description_tr,
#            applicable_when (JSONB), sql_templates (4 dialect), default_viz
# ---------------------------------------------------------------------------

# GENERIC (8) — domain-agnostic metrikler
GENERIC_METRICS: List[Dict[str, Any]] = [
    {
        "metric_key": "generic.top_n_by",
        "name_tr": "Bir alana göre Top-N",
        "category": "generic",
        "sub_category": "ranking",
        "description_tr": "Seçilen ölçü kolonuna göre azalan sıralı ilk N satır.",
        "applicable_when": {
            "requires_columns": ["measure_numeric", "dimension_any"],
            "min_rows": 10,
        },
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT {dimension} AS label, SUM({measure}) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {dimension} AS label, SUM({measure}) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {dimension} AS label, SUM({measure}) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC",
            "mysql":      "SELECT {dimension} AS label, SUM({measure}) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "generic.time_series_count",
        "name_tr": "Zaman serisi sayım",
        "category": "generic",
        "sub_category": "trend",
        "description_tr": "Gün/hafta/ay bazında satır sayısı trendi.",
        "applicable_when": {"requires_columns": ["date_column"], "min_rows": 30},
        "default_viz": "line",
        "sql_templates": {
            "postgresql": "SELECT DATE_TRUNC(:granularity, {date_col}) AS bucket, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
            "oracle":     "SELECT TRUNC({date_col}, :oracle_fmt) AS bucket, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY TRUNC({date_col}, :oracle_fmt) ORDER BY 1",
            "mssql":      "SELECT DATEFROMPARTS(YEAR({date_col}), MONTH({date_col}), 1) AS bucket, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY DATEFROMPARTS(YEAR({date_col}), MONTH({date_col}), 1) ORDER BY 1",
            "mysql":      "SELECT DATE_FORMAT({date_col}, :mysql_fmt) AS bucket, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
        },
    },
    {
        "metric_key": "generic.distinct_distribution",
        "name_tr": "Kategori dağılımı",
        "category": "generic",
        "sub_category": "distribution",
        "description_tr": "Bir kategorik alandaki benzersiz değerlerin frekans dağılımı.",
        "applicable_when": {"requires_columns": ["dimension_categorical"], "cardinality_max": 50},
        "default_viz": "pie",
        "sql_templates": {
            "postgresql": "SELECT {dimension} AS label, COUNT(*) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {dimension} AS label, COUNT(*) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {dimension} AS label, COUNT(*) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC",
            "mysql":      "SELECT {dimension} AS label, COUNT(*) AS value FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "generic.null_ratio",
        "name_tr": "NULL oranı",
        "category": "generic",
        "sub_category": "quality",
        "description_tr": "Seçilen kolondaki NULL/boş değer yüzdesi (veri kalitesi).",
        "applicable_when": {"requires_columns": ["any"], "min_rows": 100},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT (COUNT(*) FILTER (WHERE {col} IS NULL))::float / NULLIF(COUNT(*),0) AS null_ratio FROM {table} {where}",
            "oracle":     "SELECT SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0) AS null_ratio FROM {table} {where}",
            "mssql":      "SELECT CAST(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS FLOAT) / NULLIF(COUNT(*),0) AS null_ratio FROM {table} {where}",
            "mysql":      "SELECT SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0) AS null_ratio FROM {table} {where}",
        },
    },
    {
        "metric_key": "generic.sum",
        "name_tr": "Toplam",
        "category": "generic",
        "sub_category": "aggregate",
        "description_tr": "Sayısal kolonun toplamı (opsiyonel kategoriye göre).",
        "applicable_when": {"requires_columns": ["measure_numeric"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT SUM({measure}) AS total FROM {table} {where}",
            "oracle":     "SELECT SUM({measure}) AS total FROM {table} {where}",
            "mssql":      "SELECT SUM({measure}) AS total FROM {table} {where}",
            "mysql":      "SELECT SUM({measure}) AS total FROM {table} {where}",
        },
    },
    {
        "metric_key": "generic.avg",
        "name_tr": "Ortalama",
        "category": "generic",
        "sub_category": "aggregate",
        "description_tr": "Sayısal kolonun aritmetik ortalaması.",
        "applicable_when": {"requires_columns": ["measure_numeric"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT AVG({measure})::numeric(18,2) AS avg_value FROM {table} {where}",
            "oracle":     "SELECT ROUND(AVG({measure}), 2) AS avg_value FROM {table} {where}",
            "mssql":      "SELECT CAST(AVG({measure}) AS DECIMAL(18,2)) AS avg_value FROM {table} {where}",
            "mysql":      "SELECT ROUND(AVG({measure}), 2) AS avg_value FROM {table} {where}",
        },
    },
    {
        "metric_key": "generic.count_distinct",
        "name_tr": "Benzersiz sayım",
        "category": "generic",
        "sub_category": "aggregate",
        "description_tr": "Bir alandaki benzersiz değer sayısı.",
        "applicable_when": {"requires_columns": ["dimension_any"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT COUNT(DISTINCT {col}) AS distinct_count FROM {table} {where}",
            "oracle":     "SELECT COUNT(DISTINCT {col}) AS distinct_count FROM {table} {where}",
            "mssql":      "SELECT COUNT(DISTINCT {col}) AS distinct_count FROM {table} {where}",
            "mysql":      "SELECT COUNT(DISTINCT {col}) AS distinct_count FROM {table} {where}",
        },
    },
    {
        "metric_key": "generic.group_by_category",
        "name_tr": "Kategoriye göre grupla",
        "category": "generic",
        "sub_category": "groupby",
        "description_tr": "Kategori × ölçü ızgarası (cross-tab başlangıcı).",
        "applicable_when": {"requires_columns": ["dimension_categorical", "measure_numeric"]},
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT {dimension} AS label, SUM({measure}) AS value, COUNT(*) AS cnt FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {dimension} AS label, SUM({measure}) AS value, COUNT(*) AS cnt FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {dimension} AS label, SUM({measure}) AS value, COUNT(*) AS cnt FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC",
            "mysql":      "SELECT {dimension} AS label, SUM({measure}) AS value, COUNT(*) AS cnt FROM {table} {where} GROUP BY {dimension} ORDER BY value DESC LIMIT :limit",
        },
    },
]


# HELPDESK (12) — ticket/destek domain metrikleri
HELPDESK_METRICS: List[Dict[str, Any]] = [
    {
        "metric_key": "helpdesk.oldest_open",
        "name_tr": "En eski açık talepler",
        "category": "helpdesk",
        "sub_category": "aging",
        "description_tr": "Hâlâ açık olan ve oluşturulma tarihi en eski talepler.",
        "applicable_when": {
            "requires_columns": ["created_at", "status"],
            "table_hints": ["ticket", "talep", "destek", "issue"],
        },
        "default_viz": "table",
        "sql_templates": {
            "postgresql": "SELECT * FROM {table} WHERE {status_col} IN (:status_open_values) {extra_where} ORDER BY {created_col} ASC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT t.* FROM {table} t WHERE {status_col} IN (:status_open_values) {extra_where} ORDER BY {created_col} ASC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) * FROM {table} WHERE {status_col} IN (:status_open_values) {extra_where} ORDER BY {created_col} ASC",
            "mysql":      "SELECT * FROM {table} WHERE {status_col} IN (:status_open_values) {extra_where} ORDER BY {created_col} ASC LIMIT :limit",
        },
    },
    {
        "metric_key": "helpdesk.sla_critical_top10",
        "name_tr": "SLA kritik Top-10",
        "category": "helpdesk",
        "sub_category": "sla",
        "description_tr": "SLA ihlali yakın/aşılmış kritik öncelikli talepler.",
        "applicable_when": {"requires_columns": ["priority", "sla_deadline"], "table_hints": ["ticket"]},
        "default_viz": "table",
        "sql_templates": {
            "postgresql": "SELECT * FROM {table} WHERE {priority_col} IN (:priority_critical) AND {sla_col} <= NOW() + INTERVAL '4 hours' ORDER BY {sla_col} ASC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT t.* FROM {table} t WHERE {priority_col} IN (:priority_critical) AND {sla_col} <= SYSDATE + 4/24 ORDER BY {sla_col}) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) * FROM {table} WHERE {priority_col} IN (:priority_critical) AND {sla_col} <= DATEADD(hour, 4, GETDATE()) ORDER BY {sla_col} ASC",
            "mysql":      "SELECT * FROM {table} WHERE {priority_col} IN (:priority_critical) AND {sla_col} <= NOW() + INTERVAL 4 HOUR ORDER BY {sla_col} ASC LIMIT :limit",
        },
    },
    {
        "metric_key": "helpdesk.avg_resolution_hours",
        "name_tr": "Ortalama çözüm süresi (saat)",
        "category": "helpdesk",
        "sub_category": "performance",
        "description_tr": "Kapalı taleplerin oluşturma→kapatma süresi ortalaması (saat).",
        "applicable_when": {"requires_columns": ["created_at", "closed_at"], "table_hints": ["ticket"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT AVG(EXTRACT(EPOCH FROM ({closed_col} - {created_col}))/3600.0)::numeric(10,2) AS avg_hours FROM {table} WHERE {closed_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
            "oracle":     "SELECT ROUND(AVG(({closed_col} - {created_col}) * 24), 2) AS avg_hours FROM {table} WHERE {closed_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
            "mssql":      "SELECT AVG(CAST(DATEDIFF(MINUTE, {created_col}, {closed_col}) AS FLOAT)/60.0) AS avg_hours FROM {table} WHERE {closed_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
            "mysql":      "SELECT ROUND(AVG(TIMESTAMPDIFF(MINUTE, {created_col}, {closed_col})/60.0), 2) AS avg_hours FROM {table} WHERE {closed_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
        },
    },
    {
        "metric_key": "helpdesk.daily_open_trend",
        "name_tr": "Günlük açılan talep trendi",
        "category": "helpdesk",
        "sub_category": "trend",
        "description_tr": "Günlük yeni açılan talep sayısı zaman serisi.",
        "applicable_when": {"requires_columns": ["created_at"], "table_hints": ["ticket"]},
        "default_viz": "line",
        "sql_templates": {
            "postgresql": "SELECT DATE_TRUNC('day', {created_col}) AS day, COUNT(*) AS opened FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
            "oracle":     "SELECT TRUNC({created_col}) AS day, COUNT(*) AS opened FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY TRUNC({created_col}) ORDER BY 1",
            "mssql":      "SELECT CAST({created_col} AS DATE) AS day, COUNT(*) AS opened FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY CAST({created_col} AS DATE) ORDER BY 1",
            "mysql":      "SELECT DATE({created_col}) AS day, COUNT(*) AS opened FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
        },
    },
    {
        "metric_key": "helpdesk.reopen_ratio",
        "name_tr": "Yeniden açılma oranı",
        "category": "helpdesk",
        "sub_category": "quality",
        "description_tr": "Kapatılan ve sonra yeniden açılan talep yüzdesi.",
        "applicable_when": {"requires_columns": ["status_history"], "table_hints": ["ticket"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT (SUM(CASE WHEN {reopened_col} = TRUE THEN 1 ELSE 0 END))::float / NULLIF(COUNT(*),0) AS reopen_ratio FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to",
            "oracle":     "SELECT SUM(CASE WHEN {reopened_col} = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0) AS reopen_ratio FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to",
            "mssql":      "SELECT CAST(SUM(CASE WHEN {reopened_col} = 1 THEN 1 ELSE 0 END) AS FLOAT)/NULLIF(COUNT(*),0) AS reopen_ratio FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to",
            "mysql":      "SELECT SUM(CASE WHEN {reopened_col} = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0) AS reopen_ratio FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to",
        },
    },
    {
        "metric_key": "helpdesk.backlog_aging",
        "name_tr": "Backlog yaşlandırma",
        "category": "helpdesk",
        "sub_category": "aging",
        "description_tr": "Açık taleplerin yaş bantlarına göre dağılımı (<24h, 1-3g, 3-7g, >7g).",
        "applicable_when": {"requires_columns": ["created_at", "status"], "table_hints": ["ticket"]},
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT CASE WHEN NOW() - {created_col} < INTERVAL '24 hours' THEN '<24h' WHEN NOW() - {created_col} < INTERVAL '3 days' THEN '1-3g' WHEN NOW() - {created_col} < INTERVAL '7 days' THEN '3-7g' ELSE '>7g' END AS age_band, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY 1 ORDER BY 1",
            "oracle":     "SELECT CASE WHEN SYSDATE - {created_col} < 1 THEN '<24h' WHEN SYSDATE - {created_col} < 3 THEN '1-3g' WHEN SYSDATE - {created_col} < 7 THEN '3-7g' ELSE '>7g' END AS age_band, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY CASE WHEN SYSDATE - {created_col} < 1 THEN '<24h' WHEN SYSDATE - {created_col} < 3 THEN '1-3g' WHEN SYSDATE - {created_col} < 7 THEN '3-7g' ELSE '>7g' END",
            "mssql":      "SELECT CASE WHEN DATEDIFF(HOUR, {created_col}, GETDATE()) < 24 THEN '<24h' WHEN DATEDIFF(DAY, {created_col}, GETDATE()) < 3 THEN '1-3g' WHEN DATEDIFF(DAY, {created_col}, GETDATE()) < 7 THEN '3-7g' ELSE '>7g' END AS age_band, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY 1",
            "mysql":      "SELECT CASE WHEN TIMESTAMPDIFF(HOUR, {created_col}, NOW()) < 24 THEN '<24h' WHEN TIMESTAMPDIFF(DAY, {created_col}, NOW()) < 3 THEN '1-3g' WHEN TIMESTAMPDIFF(DAY, {created_col}, NOW()) < 7 THEN '3-7g' ELSE '>7g' END AS age_band, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY 1",
        },
    },
    {
        "metric_key": "helpdesk.team_distribution",
        "name_tr": "Takım dağılımı",
        "category": "helpdesk",
        "sub_category": "distribution",
        "description_tr": "Takım/atanan grup bazında açık talep sayısı.",
        "applicable_when": {"requires_columns": ["team_or_assignee"], "table_hints": ["ticket"]},
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT {team_col} AS team, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY {team_col} ORDER BY cnt DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {team_col} AS team, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY {team_col} ORDER BY cnt DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {team_col} AS team, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY {team_col} ORDER BY cnt DESC",
            "mysql":      "SELECT {team_col} AS team, COUNT(*) AS cnt FROM {table} WHERE {status_col} IN (:status_open_values) GROUP BY {team_col} ORDER BY cnt DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "helpdesk.first_response_time",
        "name_tr": "İlk yanıt süresi (saat)",
        "category": "helpdesk",
        "sub_category": "performance",
        "description_tr": "Talep oluşturma → ilk yanıt arasındaki ortalama süre (saat).",
        "applicable_when": {"requires_columns": ["created_at", "first_response_at"], "table_hints": ["ticket"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT AVG(EXTRACT(EPOCH FROM ({first_resp_col} - {created_col}))/3600.0)::numeric(10,2) AS frt_hours FROM {table} WHERE {first_resp_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
            "oracle":     "SELECT ROUND(AVG(({first_resp_col} - {created_col}) * 24), 2) AS frt_hours FROM {table} WHERE {first_resp_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
            "mssql":      "SELECT AVG(CAST(DATEDIFF(MINUTE, {created_col}, {first_resp_col}) AS FLOAT)/60.0) AS frt_hours FROM {table} WHERE {first_resp_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
            "mysql":      "SELECT ROUND(AVG(TIMESTAMPDIFF(MINUTE, {created_col}, {first_resp_col})/60.0), 2) AS frt_hours FROM {table} WHERE {first_resp_col} IS NOT NULL AND {created_col} BETWEEN :date_from AND :date_to",
        },
    },
    {
        "metric_key": "helpdesk.p1_p2_count",
        "name_tr": "P1/P2 öncelikli sayım",
        "category": "helpdesk",
        "sub_category": "priority",
        "description_tr": "Yüksek öncelikli (P1/P2) açık talep sayısı.",
        "applicable_when": {"requires_columns": ["priority", "status"], "table_hints": ["ticket"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT {priority_col} AS priority, COUNT(*) AS cnt FROM {table} WHERE {priority_col} IN (:priority_high) AND {status_col} IN (:status_open_values) GROUP BY {priority_col}",
            "oracle":     "SELECT {priority_col} AS priority, COUNT(*) AS cnt FROM {table} WHERE {priority_col} IN (:priority_high) AND {status_col} IN (:status_open_values) GROUP BY {priority_col}",
            "mssql":      "SELECT {priority_col} AS priority, COUNT(*) AS cnt FROM {table} WHERE {priority_col} IN (:priority_high) AND {status_col} IN (:status_open_values) GROUP BY {priority_col}",
            "mysql":      "SELECT {priority_col} AS priority, COUNT(*) AS cnt FROM {table} WHERE {priority_col} IN (:priority_high) AND {status_col} IN (:status_open_values) GROUP BY {priority_col}",
        },
    },
    {
        "metric_key": "helpdesk.weekend_load",
        "name_tr": "Hafta sonu yükü",
        "category": "helpdesk",
        "sub_category": "load",
        "description_tr": "Hafta sonu açılan talep sayısı (yedek hatlar için).",
        "applicable_when": {"requires_columns": ["created_at"], "table_hints": ["ticket"]},
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT EXTRACT(DOW FROM {created_col}) AS dow, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to AND EXTRACT(DOW FROM {created_col}) IN (0,6) GROUP BY 1 ORDER BY 1",
            "oracle":     "SELECT TO_CHAR({created_col}, 'D') AS dow, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to AND TO_CHAR({created_col}, 'D') IN ('1','7') GROUP BY TO_CHAR({created_col}, 'D') ORDER BY 1",
            "mssql":      "SELECT DATEPART(WEEKDAY, {created_col}) AS dow, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to AND DATEPART(WEEKDAY, {created_col}) IN (1,7) GROUP BY DATEPART(WEEKDAY, {created_col}) ORDER BY 1",
            "mysql":      "SELECT DAYOFWEEK({created_col}) AS dow, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to AND DAYOFWEEK({created_col}) IN (1,7) GROUP BY 1 ORDER BY 1",
        },
    },
    {
        "metric_key": "helpdesk.ticket_lifecycle_funnel",
        "name_tr": "Talep yaşam döngüsü hunisi",
        "category": "helpdesk",
        "sub_category": "funnel",
        "description_tr": "Open → In Progress → Resolved → Closed huni dönüşümü.",
        "applicable_when": {"requires_columns": ["status"], "table_hints": ["ticket"]},
        "default_viz": "funnel",
        "sql_templates": {
            "postgresql": "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
            "oracle":     "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
            "mssql":      "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
            "mysql":      "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {created_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
        },
    },
    {
        "metric_key": "helpdesk.sla_breach_count",
        "name_tr": "SLA ihlali sayısı",
        "category": "helpdesk",
        "sub_category": "sla",
        "description_tr": "Belirtilen dönemde SLA süresini aşan talep sayısı.",
        "applicable_when": {"requires_columns": ["sla_deadline", "closed_at"], "table_hints": ["ticket"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT COUNT(*) AS breach_cnt FROM {table} WHERE {closed_col} > {sla_col} AND {created_col} BETWEEN :date_from AND :date_to",
            "oracle":     "SELECT COUNT(*) AS breach_cnt FROM {table} WHERE {closed_col} > {sla_col} AND {created_col} BETWEEN :date_from AND :date_to",
            "mssql":      "SELECT COUNT(*) AS breach_cnt FROM {table} WHERE {closed_col} > {sla_col} AND {created_col} BETWEEN :date_from AND :date_to",
            "mysql":      "SELECT COUNT(*) AS breach_cnt FROM {table} WHERE {closed_col} > {sla_col} AND {created_col} BETWEEN :date_from AND :date_to",
        },
    },
]


# SALES (10) — satış domain metrikleri
SALES_METRICS: List[Dict[str, Any]] = [
    {
        "metric_key": "sales.top_customer_revenue",
        "name_tr": "Top müşteri (gelire göre)",
        "category": "sales",
        "sub_category": "ranking",
        "description_tr": "Toplam gelir bazında en yüksek N müşteri.",
        "applicable_when": {"requires_columns": ["customer_id", "amount"], "table_hints": ["order", "invoice", "satis"]},
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT {customer_col} AS customer, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY revenue DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {customer_col} AS customer, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY revenue DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {customer_col} AS customer, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY revenue DESC",
            "mysql":      "SELECT {customer_col} AS customer, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY revenue DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "sales.monthly_trend",
        "name_tr": "Aylık satış trendi",
        "category": "sales",
        "sub_category": "trend",
        "description_tr": "Aylık toplam satış geliri zaman serisi.",
        "applicable_when": {"requires_columns": ["date", "amount"], "table_hints": ["order", "invoice", "satis"]},
        "default_viz": "line",
        "sql_templates": {
            "postgresql": "SELECT DATE_TRUNC('month', {date_col}) AS month, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
            "oracle":     "SELECT TRUNC({date_col}, 'MM') AS month, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY TRUNC({date_col}, 'MM') ORDER BY 1",
            "mssql":      "SELECT DATEFROMPARTS(YEAR({date_col}), MONTH({date_col}), 1) AS month, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY DATEFROMPARTS(YEAR({date_col}), MONTH({date_col}), 1) ORDER BY 1",
            "mysql":      "SELECT DATE_FORMAT({date_col}, '%Y-%m-01') AS month, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
        },
    },
    {
        "metric_key": "sales.avg_basket",
        "name_tr": "Ortalama sepet tutarı",
        "category": "sales",
        "sub_category": "performance",
        "description_tr": "Sipariş başına ortalama tutar.",
        "applicable_when": {"requires_columns": ["amount"], "table_hints": ["order", "invoice"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "SELECT AVG({amount_col})::numeric(18,2) AS avg_basket FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to",
            "oracle":     "SELECT ROUND(AVG({amount_col}), 2) AS avg_basket FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to",
            "mssql":      "SELECT CAST(AVG({amount_col}) AS DECIMAL(18,2)) AS avg_basket FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to",
            "mysql":      "SELECT ROUND(AVG({amount_col}), 2) AS avg_basket FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to",
        },
    },
    {
        "metric_key": "sales.repeat_purchase_ratio",
        "name_tr": "Tekrar satın alma oranı",
        "category": "sales",
        "sub_category": "loyalty",
        "description_tr": "Birden fazla sipariş veren müşteri yüzdesi.",
        "applicable_when": {"requires_columns": ["customer_id"], "table_hints": ["order"]},
        "default_viz": "kpi",
        "sql_templates": {
            "postgresql": "WITH c AS (SELECT {customer_col}, COUNT(*) AS n FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col}) SELECT (SUM(CASE WHEN n>1 THEN 1 ELSE 0 END))::float/NULLIF(COUNT(*),0) AS repeat_ratio FROM c",
            "oracle":     "WITH c AS (SELECT {customer_col}, COUNT(*) AS n FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col}) SELECT SUM(CASE WHEN n>1 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0) AS repeat_ratio FROM c",
            "mssql":      "WITH c AS (SELECT {customer_col}, COUNT(*) AS n FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col}) SELECT CAST(SUM(CASE WHEN n>1 THEN 1 ELSE 0 END) AS FLOAT)/NULLIF(COUNT(*),0) AS repeat_ratio FROM c",
            "mysql":      "WITH c AS (SELECT {customer_col}, COUNT(*) AS n FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col}) SELECT SUM(CASE WHEN n>1 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0) AS repeat_ratio FROM c",
        },
    },
    {
        "metric_key": "sales.conversion_funnel",
        "name_tr": "Dönüşüm hunisi",
        "category": "sales",
        "sub_category": "funnel",
        "description_tr": "Sepet → Sipariş → Ödeme aşama dönüşümü.",
        "applicable_when": {"requires_columns": ["status"], "table_hints": ["order"]},
        "default_viz": "funnel",
        "sql_templates": {
            "postgresql": "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
            "oracle":     "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
            "mssql":      "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
            "mysql":      "SELECT {status_col} AS stage, COUNT(*) AS cnt FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {status_col} ORDER BY cnt DESC",
        },
    },
    {
        "metric_key": "sales.rfm_segment",
        "name_tr": "RFM segmentasyonu",
        "category": "sales",
        "sub_category": "segmentation",
        "description_tr": "Recency-Frequency-Monetary tabanlı müşteri segment dağılımı.",
        "applicable_when": {"requires_columns": ["customer_id", "date", "amount"], "table_hints": ["order"]},
        "default_viz": "heatmap",
        "sql_templates": {
            "postgresql": "SELECT {customer_col} AS customer, MAX({date_col}) AS recency, COUNT(*) AS frequency, SUM({amount_col}) AS monetary FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY monetary DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {customer_col} AS customer, MAX({date_col}) AS recency, COUNT(*) AS frequency, SUM({amount_col}) AS monetary FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY monetary DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {customer_col} AS customer, MAX({date_col}) AS recency, COUNT(*) AS frequency, SUM({amount_col}) AS monetary FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY monetary DESC",
            "mysql":      "SELECT {customer_col} AS customer, MAX({date_col}) AS recency, COUNT(*) AS frequency, SUM({amount_col}) AS monetary FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {customer_col} ORDER BY monetary DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "sales.daily_revenue",
        "name_tr": "Günlük gelir",
        "category": "sales",
        "sub_category": "trend",
        "description_tr": "Günlük toplam satış geliri.",
        "applicable_when": {"requires_columns": ["date", "amount"], "table_hints": ["order", "invoice"]},
        "default_viz": "line",
        "sql_templates": {
            "postgresql": "SELECT DATE_TRUNC('day', {date_col}) AS day, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
            "oracle":     "SELECT TRUNC({date_col}) AS day, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY TRUNC({date_col}) ORDER BY 1",
            "mssql":      "SELECT CAST({date_col} AS DATE) AS day, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY CAST({date_col} AS DATE) ORDER BY 1",
            "mysql":      "SELECT DATE({date_col}) AS day, SUM({amount_col}) AS revenue FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY 1 ORDER BY 1",
        },
    },
    {
        "metric_key": "sales.top_product",
        "name_tr": "Top ürün",
        "category": "sales",
        "sub_category": "ranking",
        "description_tr": "Adet veya gelir bazında en çok satılan ürünler.",
        "applicable_when": {"requires_columns": ["product_id", "amount"], "table_hints": ["order_item", "satis"]},
        "default_viz": "bar",
        "sql_templates": {
            "postgresql": "SELECT {product_col} AS product, SUM({amount_col}) AS revenue, COUNT(*) AS units FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {product_col} ORDER BY revenue DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {product_col} AS product, SUM({amount_col}) AS revenue, COUNT(*) AS units FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {product_col} ORDER BY revenue DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {product_col} AS product, SUM({amount_col}) AS revenue, COUNT(*) AS units FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {product_col} ORDER BY revenue DESC",
            "mysql":      "SELECT {product_col} AS product, SUM({amount_col}) AS revenue, COUNT(*) AS units FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {product_col} ORDER BY revenue DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "sales.geographic_distribution",
        "name_tr": "Coğrafi dağılım",
        "category": "sales",
        "sub_category": "geography",
        "description_tr": "Şehir/bölge bazında satış dağılımı.",
        "applicable_when": {"requires_columns": ["city_or_region", "amount"], "table_hints": ["order"]},
        "default_viz": "map",
        "sql_templates": {
            "postgresql": "SELECT {geo_col} AS region, SUM({amount_col}) AS revenue, COUNT(*) AS orders FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {geo_col} ORDER BY revenue DESC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {geo_col} AS region, SUM({amount_col}) AS revenue, COUNT(*) AS orders FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {geo_col} ORDER BY revenue DESC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {geo_col} AS region, SUM({amount_col}) AS revenue, COUNT(*) AS orders FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {geo_col} ORDER BY revenue DESC",
            "mysql":      "SELECT {geo_col} AS region, SUM({amount_col}) AS revenue, COUNT(*) AS orders FROM {table} WHERE {date_col} BETWEEN :date_from AND :date_to GROUP BY {geo_col} ORDER BY revenue DESC LIMIT :limit",
        },
    },
    {
        "metric_key": "sales.churn_risk_cohort",
        "name_tr": "Churn riski kohortu",
        "category": "sales",
        "sub_category": "retention",
        "description_tr": "Son N gündür alışveriş yapmayan eski müşteriler (churn riski).",
        "applicable_when": {"requires_columns": ["customer_id", "date"], "table_hints": ["order"]},
        "default_viz": "table",
        "sql_templates": {
            "postgresql": "SELECT {customer_col} AS customer, MAX({date_col}) AS last_order, NOW() - MAX({date_col}) AS days_since FROM {table} GROUP BY {customer_col} HAVING NOW() - MAX({date_col}) > (:churn_days || ' days')::interval ORDER BY last_order ASC LIMIT :limit",
            "oracle":     "SELECT * FROM (SELECT {customer_col} AS customer, MAX({date_col}) AS last_order FROM {table} GROUP BY {customer_col} HAVING SYSDATE - MAX({date_col}) > :churn_days ORDER BY last_order ASC) WHERE ROWNUM <= :limit",
            "mssql":      "SELECT TOP (:limit) {customer_col} AS customer, MAX({date_col}) AS last_order, DATEDIFF(DAY, MAX({date_col}), GETDATE()) AS days_since FROM {table} GROUP BY {customer_col} HAVING DATEDIFF(DAY, MAX({date_col}), GETDATE()) > :churn_days ORDER BY last_order ASC",
            "mysql":      "SELECT {customer_col} AS customer, MAX({date_col}) AS last_order, DATEDIFF(NOW(), MAX({date_col})) AS days_since FROM {table} GROUP BY {customer_col} HAVING DATEDIFF(NOW(), MAX({date_col})) > :churn_days ORDER BY last_order ASC LIMIT :limit",
        },
    },
]


ALL_METRICS: List[Dict[str, Any]] = GENERIC_METRICS + HELPDESK_METRICS + SALES_METRICS


def upgrade() -> None:
    """30 metrik tanımını dbsmart_metric_library'ye seed et (idempotent)."""
    assert len(ALL_METRICS) >= 24, f"Plan §G1.4 hedef: 24+ metrik, mevcut: {len(ALL_METRICS)}"

    insert_sql = """
        INSERT INTO dbsmart_metric_library (
            metric_key, name_tr, category, sub_category, description_tr,
            applicable_when, sql_templates, default_viz,
            is_official, is_active
        ) VALUES (
            :metric_key, :name_tr, :category, :sub_category, :description_tr,
            CAST(:applicable_when AS JSONB), CAST(:sql_templates AS JSONB),
            :default_viz, TRUE, TRUE
        )
        ON CONFLICT (metric_key) DO NOTHING
    """

    conn = op.get_bind()
    from sqlalchemy import text
    stmt = text(insert_sql)

    for m in ALL_METRICS:
        conn.execute(stmt, {
            "metric_key": m["metric_key"],
            "name_tr": m["name_tr"],
            "category": m["category"],
            "sub_category": m.get("sub_category"),
            "description_tr": m.get("description_tr"),
            "applicable_when": json.dumps(m.get("applicable_when") or {}),
            "sql_templates": json.dumps(m.get("sql_templates") or {}),
            "default_viz": m.get("default_viz", "table"),
        })

    # Versiyon marker — system_settings (setting_key, setting_value) gerçek şemaya uyumlu
    op.execute("""
        INSERT INTO system_settings (setting_key, setting_value, description)
        VALUES ('DBSMART_METRIC_SEED_TS', NOW()::text,
                'v3.30.0 FAZ 1 G1.4 — metric library seed timestamp')
        ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value, updated_at = NOW()
    """)


def downgrade() -> None:
    """Yalnızca official seed satırları sil (kullanıcı override'larına dokunma)."""
    keys = [m["metric_key"] for m in ALL_METRICS]
    from sqlalchemy import text
    conn = op.get_bind()
    stmt = text("DELETE FROM dbsmart_metric_library WHERE metric_key = ANY(:keys) AND is_official = TRUE")
    conn.execute(stmt, {"keys": keys})
    op.execute("DELETE FROM system_settings WHERE key = 'DBSMART_METRIC_SEED_TS'")
