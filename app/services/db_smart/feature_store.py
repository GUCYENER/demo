"""Feature Store — CatBoost wizard ranker eğitimi için feature aggregator
(v3.30.0 FAZ 4 P22).

Plan: .agents/in_flight/2026-05-21_p22_feature-store.md
Tüketici: P23-P27 CatBoost wizard ranker eğitim/predict job'ları.

Modül kapsamı:
    - get_user_features(cur, user_id, company_id)             -> per-user vektör
    - get_table_features(cur, table_id, company_id, source_id) -> per-table vektör
    - get_query_features(cur, session_uid)                    -> per-query vektör
    - get_recommendation_features(cur, recommendation_id, ...) -> per-reco vektör
    - to_vector(feature_dict, feature_order, default=0.0)     -> List[float]

Tasarım notları:
    1) Senkron psycopg2 cursor stili — sibling `learning_recorder.py` ve
       `metric_engine.py` ile birebir uyumlu. Brief'in "async" ifadesi mevcut
       db_smart altyapısıyla çelişiyor; project convention'a uyduk (cursor).
    2) Hiçbir yeni dependency YOK — pure SQL aggregate + dict.
    3) PII guard: `_load_pii_columns` (learning_recorder'dan reuse) ile
       is_pii=TRUE kolonlar feature sayımlarından dışlanır. Hiçbir RAW kolon
       değeri feature içine girmez; yalnızca count/oran/bucket üretiriz.
    4) RLS: bu modül asla `apply_vyra_user_context` çağırmaz — caller
       endpoint katmanında zaten SET LOCAL ile context'i kurmuş olmalıdır.
       Tüm sorgular RLS predicate'inden geçer. Materialized view'ler RLS
       desteklemediği için `company_id` kolonu MV'de saklanır ve sorgu
       sırasında WHERE company_id = … filtresi UYGULANIR (fail-closed).
    5) MV yok ya da stale ise canlı sorguya fallback (>24h gecikme veya
       `mv_dbsmart_*` tablosu yoksa). MV'ler 037 migration'da CREATE edilir.
    6) Sıfır-baseline davranış: hiçbir interaction yok / cross-tenant ise
       tüm sayılar 0.0/0 dönülür (None KESİNLİKLE dönülmez — vektörleştirme
       deterministik kalsın diye).
    7) to_vector stable order'lı — train/predict feature index drift'i
       engellenir. Unknown key → default; bool → 0.0/1.0; string → hash bucket
       (mod 100). CatBoost native categorical handling ranker'ın kendi
       konfig'i; bu modül sadece sayısal vektör üretir.

NOTE: FAZ 2 P30 (034_dbsmart_interactions_partitioning) ileride merge
edilebilir; bu modül `dbsmart_interactions` tablosundan agg'lar yapar ve
partitioning sonrası query planner'ı aynı SQL'i partition pruning ile
sürdürür — değişiklik gerekmez.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Set

from app.services.db_smart.learning_recorder import _load_pii_columns

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────

# Materialized view stale eşiği — bu saatten eski refreshed_at varsa
# canlı sorguya fallback yapılır.
_MV_STALE_HOURS = 24

# Hash bucket modulo — string categorical'ı 0..N-1 aralığına sıkıştırır.
_HASH_BUCKETS = 100

# Row-count bucket eşikleri (log-scale)
_ROW_BUCKETS = (
    (0, 0),
    (100, 1),
    (1_000, 2),
    (10_000, 3),
    (100_000, 4),
    (1_000_000, 5),
    (10_000_000, 6),
)

# Estimated cost bucket (join + filter heuristik)
_COST_BUCKETS = (
    (1, 0),
    (3, 1),
    (6, 2),
    (10, 3),
)

# Sıfır-baseline user feature dict (vektör shape stabilitesi).
_USER_ZERO_BASELINE: Dict[str, Any] = {
    "total_queries_30d": 0,
    "avg_session_duration_sec": 0.0,
    "domain_diversity": 0,
    "table_coverage": 0,
    "recommendation_acceptance_rate": 0.0,
    "top_metric_categories": [],
    "last_active_ts": None,
}

_TABLE_ZERO_BASELINE: Dict[str, Any] = {
    "row_count_bucket": 0,
    "column_count": 0,
    "fk_centrality": 0.0,
    "pii_column_ratio": 0.0,
    "business_glossary_term_count": 0,
    "select_frequency_30d": 0,
    "distinct_user_count_30d": 0,
    "avg_query_complexity": 0.0,
}

_QUERY_ZERO_BASELINE: Dict[str, Any] = {
    "table_count": 0,
    "join_count": 0,
    "filter_count": 0,
    "group_count": 0,
    "order_count": 0,
    "has_limit": False,
    "distinct_columns": 0,
    "distinct_metric_categories": 0,
    "cross_domain": False,
    "dialect": "",
    "estimated_cost_bucket": 0,
}

_RECO_ZERO_BASELINE: Dict[str, Any] = {
    "chart_type": "",
    "insight_count": 0,
    "severity_max": 0,
    "table_count_in_recommendation": 0,
    "position_in_list": 0,
    "freshness_age_minutes": 0,
    "user_acceptance_rate_for_chart_type": 0.0,
}


# ─────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────

def _row_count_bucket(n: Optional[int]) -> int:
    """Satır sayısını log-scale bucket'a indirir (0..6)."""
    if not n or n <= 0:
        return 0
    last_bucket = 0
    for threshold, bucket in _ROW_BUCKETS:
        if n >= threshold:
            last_bucket = bucket
    return last_bucket


def _cost_bucket(complexity: float) -> int:
    """Heuristik query maliyet bucket'ı."""
    last = 0
    for threshold, bucket in _COST_BUCKETS:
        if complexity >= threshold:
            last = bucket
    return last


def _mv_is_fresh(cur: Any, mv_name: str) -> bool:
    """MV'nin son refreshed_at değeri _MV_STALE_HOURS saatten yeni mi?

    MV tablosu/kolonu yoksa False döner — caller canlı sorguya düşer.
    Hata sessiz: feature_store flow-critical değil.
    """
    try:
        cur.execute(
            f"""
            SELECT EXTRACT(EPOCH FROM (NOW() - MAX(refreshed_at)))/3600.0
              FROM {mv_name}
            """
        )
        row = cur.fetchone()
    except Exception as e:
        logger.debug("[feature_store] MV freshness check failed (%s): %s", mv_name, e)
        return False
    if not row or row[0] is None:
        return False
    try:
        return float(row[0]) <= float(_MV_STALE_HOURS)
    except (TypeError, ValueError):
        return False


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────
# 1) USER FEATURES
# ─────────────────────────────────────────────────────────────

def get_user_features(
    cur: Any,
    user_id: int,
    company_id: int,
) -> Dict[str, Any]:
    """Per-user feature vector (30g moving window).

    Returns:
        dict with keys:
            total_queries_30d        — QueryExecuted action count
            avg_session_duration_sec — avg(NOW()-created_at) per session
            domain_diversity         — distinct metric category count
            table_coverage           — distinct table id count
            recommendation_acceptance_rate — Accepted / (Accepted+Rejected+Shown)
            top_metric_categories    — top 5 category strings (most used)
            last_active_ts           — max(created_at) across interactions

    Cross-tenant veya boş sonuç → _USER_ZERO_BASELINE (no leakage).
    """
    if not user_id or not company_id:
        return dict(_USER_ZERO_BASELINE)

    # 1) MV fresh ise hızlı yol
    if _mv_is_fresh(cur, "mv_dbsmart_user_features"):
        try:
            cur.execute(
                """
                SELECT total_queries_30d, avg_session_duration_sec,
                       domain_diversity, table_coverage,
                       recommendation_acceptance_rate, top_metric_categories,
                       last_active_ts
                  FROM mv_dbsmart_user_features
                 WHERE user_id = %s AND company_id = %s
                 LIMIT 1
                """,
                (int(user_id), int(company_id)),
            )
            row = cur.fetchone()
            if row:
                return {
                    "total_queries_30d": _safe_int(row[0]),
                    "avg_session_duration_sec": _safe_float(row[1]),
                    "domain_diversity": _safe_int(row[2]),
                    "table_coverage": _safe_int(row[3]),
                    "recommendation_acceptance_rate": _safe_float(row[4]),
                    "top_metric_categories": list(row[5]) if row[5] else [],
                    "last_active_ts": row[6],
                }
        except Exception as e:
            logger.debug("[feature_store] MV user read failed, fallback live: %s", e)

    # 2) Canlı agg fallback
    out: Dict[str, Any] = dict(_USER_ZERO_BASELINE)
    try:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE action = 'QueryExecuted')                       AS total_q,
                COUNT(DISTINCT (suggestion_accepted->>'category'))                     AS domains,
                COUNT(DISTINCT (suggestion_accepted->>'table_id'))                     AS tables,
                COUNT(*) FILTER (WHERE action = 'ReportRecommendationAccepted')        AS accepted,
                COUNT(*) FILTER (WHERE action = 'ReportRecommendationRejected')        AS rejected,
                COUNT(*) FILTER (WHERE action = 'ReportRecommendationShown')           AS shown,
                MAX(created_at)                                                        AS last_ts
              FROM dbsmart_interactions
             WHERE user_id = %s
               AND company_id = %s
               AND created_at >= NOW() - INTERVAL '30 days'
            """,
            (int(user_id), int(company_id)),
        )
        row = cur.fetchone()
        if row:
            total_q, domains, tables, acc, rej, shown, last_ts = row
            denom = _safe_int(acc) + _safe_int(rej) + _safe_int(shown)
            rate = (_safe_int(acc) / denom) if denom > 0 else 0.0
            out.update({
                "total_queries_30d": _safe_int(total_q),
                "domain_diversity": _safe_int(domains),
                "table_coverage": _safe_int(tables),
                "recommendation_acceptance_rate": round(rate, 4),
                "last_active_ts": last_ts,
            })
    except Exception as e:
        logger.warning("[feature_store] user agg failed uid=%s: %s", user_id, e)
        return dict(_USER_ZERO_BASELINE)

    # 3) Session duration ortalaması
    try:
        cur.execute(
            """
            SELECT AVG(EXTRACT(EPOCH FROM (COALESCE(completed_at, last_activity_at) - created_at)))::float
              FROM dbsmart_sessions
             WHERE user_id = %s
               AND company_id = %s
               AND created_at >= NOW() - INTERVAL '30 days'
            """,
            (int(user_id), int(company_id)),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            out["avg_session_duration_sec"] = round(_safe_float(row[0]), 2)
    except Exception as e:
        logger.debug("[feature_store] session duration agg skipped: %s", e)

    # 4) Top-5 metric categories (chosen)
    try:
        cur.execute(
            """
            SELECT (suggestion_accepted->>'category') AS category, COUNT(*) AS n
              FROM dbsmart_interactions
             WHERE user_id = %s
               AND company_id = %s
               AND action IN ('MetricChosen','CustomMetricWritten')
               AND suggestion_accepted ? 'category'
               AND created_at >= NOW() - INTERVAL '30 days'
             GROUP BY 1
             ORDER BY n DESC
             LIMIT 5
            """,
            (int(user_id), int(company_id)),
        )
        rows = cur.fetchall() or []
        out["top_metric_categories"] = [r[0] for r in rows if r and r[0]]
    except Exception as e:
        logger.debug("[feature_store] top metric categories skipped: %s", e)

    return out


# ─────────────────────────────────────────────────────────────
# 2) TABLE FEATURES
# ─────────────────────────────────────────────────────────────

def get_table_features(
    cur: Any,
    table_id: int,
    company_id: int,
    source_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Per-table feature vector.

    PII: `_load_pii_columns(cur, source_id)` ile is_pii=TRUE kolonlar
    sayılır → `pii_column_ratio` üretilir; RAW kolon adı veya değer asla
    feature dict'e yazılmaz.
    """
    if not table_id or not company_id:
        return dict(_TABLE_ZERO_BASELINE)

    # 1) MV fresh ise hızlı yol
    if _mv_is_fresh(cur, "mv_dbsmart_table_features"):
        try:
            cur.execute(
                """
                SELECT row_count_bucket, column_count, fk_centrality,
                       pii_column_ratio, business_glossary_term_count,
                       select_frequency_30d, distinct_user_count_30d,
                       avg_query_complexity
                  FROM mv_dbsmart_table_features
                 WHERE table_id = %s AND company_id = %s
                 LIMIT 1
                """,
                (int(table_id), int(company_id)),
            )
            row = cur.fetchone()
            if row:
                return {
                    "row_count_bucket": _safe_int(row[0]),
                    "column_count": _safe_int(row[1]),
                    "fk_centrality": _safe_float(row[2]),
                    "pii_column_ratio": _safe_float(row[3]),
                    "business_glossary_term_count": _safe_int(row[4]),
                    "select_frequency_30d": _safe_int(row[5]),
                    "distinct_user_count_30d": _safe_int(row[6]),
                    "avg_query_complexity": _safe_float(row[7]),
                }
        except Exception as e:
            logger.debug("[feature_store] MV table read failed, fallback live: %s", e)

    # 2) Canlı agg
    out: Dict[str, Any] = dict(_TABLE_ZERO_BASELINE)
    schema_name: Optional[str] = None
    object_name: Optional[str] = None
    row_count: Optional[int] = None

    try:
        cur.execute(
            """
            SELECT schema_name, object_name, row_count_estimate, columns_json, source_id
              FROM ds_db_objects
             WHERE id = %s
             LIMIT 1
            """,
            (int(table_id),),
        )
        r = cur.fetchone()
        if r:
            schema_name, object_name, row_count, columns_json, src_id = r
            if source_id is None and src_id is not None:
                source_id = int(src_id)
            col_count = 0
            if isinstance(columns_json, list):
                col_count = len(columns_json)
            out["row_count_bucket"] = _row_count_bucket(_safe_int(row_count))
            out["column_count"] = col_count
    except Exception as e:
        logger.debug("[feature_store] ds_db_objects lookup skipped: %s", e)

    # PII ratio (column_count > 0 ise)
    if source_id is not None and out["column_count"] > 0:
        try:
            pii_cols: Set[str] = _load_pii_columns(cur, int(source_id))
            if pii_cols:
                # Bu kolon adlarından bu tabloya ait olanları say.
                try:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                          FROM ds_column_enrichments ce
                          JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
                         WHERE ce.is_pii = TRUE
                           AND te.source_id = %s
                           AND te.schema_name = %s
                           AND te.object_name = %s
                        """,
                        (int(source_id), schema_name, object_name),
                    )
                    cnt_row = cur.fetchone()
                    pii_n = _safe_int(cnt_row[0]) if cnt_row else 0
                    out["pii_column_ratio"] = round(pii_n / max(out["column_count"], 1), 4)
                except Exception as e:
                    logger.debug("[feature_store] pii count skipped: %s", e)
        except Exception as e:
            logger.debug("[feature_store] _load_pii_columns failed: %s", e)

    # FK centrality
    try:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM ds_relationships WHERE from_table_id = %s) +
                (SELECT COUNT(*) FROM ds_relationships WHERE to_table_id   = %s)
            """,
            (int(table_id), int(table_id)),
        )
        r = cur.fetchone()
        if r and r[0] is not None:
            # Normalize edilmesi için /10 ile clamp
            raw = _safe_int(r[0])
            out["fk_centrality"] = round(min(raw / 10.0, 1.0), 4)
    except Exception as e:
        logger.debug("[feature_store] fk_centrality skipped: %s", e)

    # Business glossary term count
    if object_name is not None:
        try:
            cur.execute(
                """
                SELECT COUNT(*)
                  FROM business_glossary
                 WHERE company_id = %s
                   AND (mapped_table = %s OR mapped_table = %s)
                """,
                (int(company_id), object_name, f"{schema_name}.{object_name}" if schema_name else object_name),
            )
            r = cur.fetchone()
            out["business_glossary_term_count"] = _safe_int(r[0]) if r else 0
        except Exception as e:
            logger.debug("[feature_store] glossary count skipped: %s", e)

    # Select frequency + distinct user count (last 30d)
    try:
        cur.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT user_id)
              FROM dbsmart_interactions
             WHERE company_id = %s
               AND action = 'TableSelected'
               AND (suggestion_accepted->>'table_id')::int = %s
               AND created_at >= NOW() - INTERVAL '30 days'
            """,
            (int(company_id), int(table_id)),
        )
        r = cur.fetchone()
        if r:
            out["select_frequency_30d"] = _safe_int(r[0])
            out["distinct_user_count_30d"] = _safe_int(r[1])
    except Exception as e:
        logger.debug("[feature_store] select freq skipped: %s", e)

    return out


# ─────────────────────────────────────────────────────────────
# 3) QUERY FEATURES
# ─────────────────────────────────────────────────────────────

def get_query_features(cur: Any, session_uid: str) -> Dict[str, Any]:
    """Per-query feature vector — dbsmart_sessions.context JSONB'den çıkarır.

    AST snapshot (context) yapı:
        {
          "tables": [...],
          "joins":  [...],
          "filters":[...],
          "groups": [...],
          "orders": [...],
          "limit":  int|null,
          "columns":[...],
          "metric_categories": [...],
          "domains": [...],
          "dialect": "postgresql"
        }
    Bu fonksiyon yapıya tolerant — eksik alanlar 0/False/empty döner.
    """
    out: Dict[str, Any] = dict(_QUERY_ZERO_BASELINE)
    if not session_uid:
        return out

    try:
        cur.execute(
            """
            SELECT context, dialect
              FROM dbsmart_sessions
             WHERE session_uid = %s
             LIMIT 1
            """,
            (str(session_uid),),
        )
        row = cur.fetchone()
    except Exception as e:
        logger.warning("[feature_store] query feature lookup failed: %s", e)
        return out
    if not row:
        return out

    ctx, dialect = row
    if not isinstance(ctx, dict):
        # JSON string olarak gelmişse parse et
        try:
            import json as _json
            ctx = _json.loads(ctx) if isinstance(ctx, str) else {}
        except Exception:
            ctx = {}

    if not isinstance(ctx, dict):
        ctx = {}

    def _len(key: str) -> int:
        v = ctx.get(key)
        return len(v) if isinstance(v, (list, tuple)) else 0

    table_count = _len("tables")
    join_count = _len("joins")
    filter_count = _len("filters")
    group_count = _len("groups")
    order_count = _len("orders")
    columns = ctx.get("columns") if isinstance(ctx.get("columns"), list) else []
    distinct_cols = len({c for c in columns if isinstance(c, str)})
    metric_cats = ctx.get("metric_categories") if isinstance(ctx.get("metric_categories"), list) else []
    distinct_metric_cats = len({m for m in metric_cats if isinstance(m, str)})
    domains = ctx.get("domains") if isinstance(ctx.get("domains"), list) else []
    cross_domain = len({d for d in domains if isinstance(d, str)}) > 1
    has_limit = ctx.get("limit") is not None
    complexity = table_count + join_count * 2 + filter_count + group_count + order_count

    out.update({
        "table_count": table_count,
        "join_count": join_count,
        "filter_count": filter_count,
        "group_count": group_count,
        "order_count": order_count,
        "has_limit": bool(has_limit),
        "distinct_columns": distinct_cols,
        "distinct_metric_categories": distinct_metric_cats,
        "cross_domain": cross_domain,
        "dialect": dialect or "",
        "estimated_cost_bucket": _cost_bucket(float(complexity)),
    })
    return out


# ─────────────────────────────────────────────────────────────
# 4) RECOMMENDATION FEATURES
# ─────────────────────────────────────────────────────────────

def get_recommendation_features(
    cur: Any,
    recommendation_id: int,
    user_id: int,
    company_id: int,
) -> Dict[str, Any]:
    """Per-recommendation feature vector + user-historical acceptance.

    severity_max → trigger_pattern JSONB içinden okunur (örn. {"severity": "high"}).
    user_acceptance_rate_for_chart_type → user'ın bu chart_type için tarihsel
    accepted/(accepted+rejected+shown) oranı.
    """
    out: Dict[str, Any] = dict(_RECO_ZERO_BASELINE)
    if not recommendation_id or not user_id or not company_id:
        return out

    chart_type = ""
    insight_count = 0
    severity_max = 0
    try:
        cur.execute(
            """
            SELECT recommendation_key, recommended_viz, trigger_pattern
              FROM dbsmart_report_recommendations
             WHERE id = %s
             LIMIT 1
            """,
            (int(recommendation_id),),
        )
        r = cur.fetchone()
        if r:
            _, recommended_viz, trigger_pattern = r
            chart_type = recommended_viz or ""
            if isinstance(trigger_pattern, dict):
                tp = trigger_pattern
                # insight_count: trigger_pattern.insights listesi varsa onun len'i
                insights = tp.get("insights")
                if isinstance(insights, list):
                    insight_count = len(insights)
                # severity ordinal map
                sev = (tp.get("severity") or "").lower()
                severity_max = {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(sev, 0)
                # table_count_in_recommendation
                tables_in = tp.get("tables")
                if isinstance(tables_in, list):
                    out["table_count_in_recommendation"] = len(tables_in)
    except Exception as e:
        logger.debug("[feature_store] reco lookup skipped: %s", e)

    out["chart_type"] = chart_type
    out["insight_count"] = insight_count
    out["severity_max"] = severity_max

    # User-historical acceptance for this chart_type
    if chart_type:
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE action = 'ReportRecommendationAccepted') AS acc,
                    COUNT(*) FILTER (WHERE action = 'ReportRecommendationRejected') AS rej,
                    COUNT(*) FILTER (WHERE action = 'ReportRecommendationShown')    AS shown
                  FROM dbsmart_interactions
                 WHERE user_id = %s
                   AND company_id = %s
                   AND created_at >= NOW() - INTERVAL '90 days'
                   AND COALESCE(suggestion_shown->>'chart_type',
                                suggestion_accepted->>'chart_type') = %s
                """,
                (int(user_id), int(company_id), chart_type),
            )
            r = cur.fetchone()
            if r:
                acc = _safe_int(r[0])
                rej = _safe_int(r[1])
                shown = _safe_int(r[2])
                denom = acc + rej + shown
                rate = (acc / denom) if denom > 0 else 0.0
                out["user_acceptance_rate_for_chart_type"] = round(rate, 4)
        except Exception as e:
            logger.debug("[feature_store] reco historical rate skipped: %s", e)

    # Position-in-list + freshness — caller'dan gelmeyince 0/0 kalır.
    # (Caller endpoint context bunları enjekte etmek isterse ekleyebilir.)
    return out


# ─────────────────────────────────────────────────────────────
# 5) VECTORIZATION
# ─────────────────────────────────────────────────────────────

def _coerce_scalar(v: Any, default: float) -> float:
    """Bool/int/float/str/None → float (CatBoost ranker numeric input).

    - None → default
    - bool → 0.0/1.0
    - int/float → float(v)
    - str → sha1(v) mod _HASH_BUCKETS (kategorik hash bucket)
    - list/tuple → len() (kardinaliteyi proxy olarak kullan)
    - dict → default (modülün üreteceği şekil değil)
    """
    if v is None:
        return default
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return default
        # NaN/Inf guard
        if f != f or f == float("inf") or f == float("-inf"):
            return default
        return f
    if isinstance(v, str):
        if not v:
            return 0.0
        h = hashlib.sha1(v.encode("utf-8", errors="replace")).hexdigest()
        return float(int(h[:8], 16) % _HASH_BUCKETS)
    if isinstance(v, (list, tuple)):
        return float(len(v))
    return default


def to_vector(
    feature_dict: Dict[str, Any],
    feature_order: Sequence[str],
    default: float = 0.0,
) -> List[float]:
    """Stable-order vectorization for CatBoost ranker train/predict.

    Args:
        feature_dict: get_*_features() output (dict).
        feature_order: kanonik anahtar sırası — train ve predict aynı listeyi
                       paylaşmalı (drift'i bu eşitlik engeller).
        default: bilinmeyen/None anahtar için default float değer.

    Returns:
        len(feature_order) uzunluğunda List[float].
    """
    if not isinstance(feature_dict, dict):
        feature_dict = {}
    if not feature_order:
        return []
    out: List[float] = []
    for key in feature_order:
        if not isinstance(key, str):
            out.append(default)
            continue
        if key not in feature_dict:
            out.append(default)
            continue
        out.append(_coerce_scalar(feature_dict[key], default))
    return out


__all__ = [
    "get_user_features",
    "get_table_features",
    "get_query_features",
    "get_recommendation_features",
    "to_vector",
]
