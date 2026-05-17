"""
size_classifier — Faz 2 (v3.26.0 P1-a)
======================================
Result Size Predictor için CatBoost multiclass model + feature extractor.

Heuristik (result_size_predictor.predict_result_size) ne kalıyor:
    - Aggregate-only, PK eşitlik, explicit LIMIT → kesin etiket (model'siz)
    - EXPLAIN row estimate varsa → buna güveniyoruz (genelde doğru)
    - Tablo reltuples varsa → kullanıyoruz
    - Fallback "medium" → BURADA model devreye girer (eğitilmişse)

ML target: 4 sınıf (small=0, medium=1, large=2, huge=3) — multiclass.
Features (deterministic order, SIZE_FEATURE_ORDER):
    has_aggregate, has_group_by, has_pk_where, has_distinct,
    explicit_limit_n (0 if none), join_count,
    has_explain_estimate, explain_rows_log10,
    has_reltuples, reltuples_log10,
    where_clauses_count, dialect_pg, dialect_mysql, dialect_mssql, dialect_oracle

Training data source:
    agentic_size_observations.features + actual_bucket (label)
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    from catboost import CatBoostClassifier  # type: ignore
    _HAS_CATBOOST = True
except Exception:
    _HAS_CATBOOST = False


SIZE_FEATURE_ORDER: List[str] = [
    "has_aggregate",
    "has_group_by",
    "has_pk_where",
    "has_distinct",
    "explicit_limit_n",     # 0 if not present
    "join_count",
    "has_explain_estimate",
    "explain_rows_log10",   # 0 if missing
    "has_reltuples",
    "reltuples_log10",      # 0 if missing
    "where_clauses_count",  # WHERE içinde AND/OR sayısı + 1
    "dialect_pg",
    "dialect_mysql",
    "dialect_mssql",
    "dialect_oracle",
]


BUCKET_TO_LABEL: Dict[str, int] = {"small": 0, "medium": 1, "large": 2, "huge": 3}
LABEL_TO_BUCKET: Dict[int, str] = {v: k for k, v in BUCKET_TO_LABEL.items()}


_AGG_RE = re.compile(r"\b(count|sum|avg|min|max)\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)
_DISTINCT_RE = re.compile(r"\bselect\s+distinct\b", re.IGNORECASE)
_JOIN_RE = re.compile(r"\bjoin\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
_FETCH_RE = re.compile(r"\bfetch\s+(?:first|next)\s+(\d+)\s+rows?\s+only\b", re.IGNORECASE)
_TOP_RE = re.compile(r"\bselect\s+top\s+(\d+)\b", re.IGNORECASE)
_PK_WHERE_RE = re.compile(
    r"\bwhere\b[^;]*?\b(id|pk|primary_key)\s*=\s*(\d+|'[^']*'|\$\d+|\?|:\w+)",
    re.IGNORECASE,
)
_WHERE_RE = re.compile(r"\bwhere\b", re.IGNORECASE)
_AND_OR_RE = re.compile(r"\b(and|or)\b", re.IGNORECASE)


def _safe_log10(n: Optional[float]) -> float:
    if n is None or n <= 0:
        return 0.0
    try:
        return math.log10(float(n))
    except Exception:
        return 0.0


def extract_size_features(
    sql: str,
    *,
    explain_rows: Optional[int] = None,
    reltuples: Optional[int] = None,
    dialect: str = "postgresql",
) -> Dict[str, float]:
    """SQL + DB hint'leri → SIZE_FEATURE_ORDER dict (float değerler)."""
    if not sql:
        sql = ""
    explicit_limit = 0
    for rx in (_LIMIT_RE, _FETCH_RE, _TOP_RE):
        m = rx.search(sql)
        if m:
            try:
                explicit_limit = int(m.group(1))
                break
            except (TypeError, ValueError):
                continue

    where_count = 0
    if _WHERE_RE.search(sql):
        # WHERE ... — AND/OR sayısı + 1 ≈ predicate sayısı (kaba tahmin)
        wm = _WHERE_RE.search(sql)
        tail = sql[wm.end():] if wm else ""
        where_count = 1 + len(_AND_OR_RE.findall(tail))

    d = (dialect or "").lower()
    return {
        "has_aggregate": 1.0 if _AGG_RE.search(sql) else 0.0,
        "has_group_by": 1.0 if _GROUP_BY_RE.search(sql) else 0.0,
        "has_pk_where": 1.0 if _PK_WHERE_RE.search(sql) else 0.0,
        "has_distinct": 1.0 if _DISTINCT_RE.search(sql) else 0.0,
        "explicit_limit_n": float(explicit_limit),
        "join_count": float(len(_JOIN_RE.findall(sql))),
        "has_explain_estimate": 1.0 if explain_rows is not None else 0.0,
        "explain_rows_log10": _safe_log10(explain_rows),
        "has_reltuples": 1.0 if reltuples is not None else 0.0,
        "reltuples_log10": _safe_log10(reltuples),
        "where_clauses_count": float(where_count),
        "dialect_pg": 1.0 if d in ("postgresql", "postgres", "pg") else 0.0,
        "dialect_mysql": 1.0 if d == "mysql" else 0.0,
        "dialect_mssql": 1.0 if d in ("mssql", "sqlserver") else 0.0,
        "dialect_oracle": 1.0 if d == "oracle" else 0.0,
    }


def features_to_vector(features: Dict[str, float]) -> List[float]:
    return [float(features.get(k, 0.0)) for k in SIZE_FEATURE_ORDER]


def rows_to_bucket(n: int) -> str:
    """result_size_predictor ile aynı eşikler."""
    if n <= 50:
        return "small"
    if n <= 1_000:
        return "medium"
    if n <= 50_000:
        return "large"
    return "huge"


def predict_with_model(model: Any, features: Dict[str, float]) -> Optional[Tuple[str, float]]:
    """
    Yüklü model üzerinde predict_proba → (bucket, confidence) döner.

    Confidence < 0.4 ise None (heuristik fallback caller tarafında uygulanır).
    """
    if model is None:
        return None
    try:
        x = features_to_vector(features)
        probs = model.predict_proba([x])[0]
        # En yüksek olasılıklı sınıf
        idx = int(max(range(len(probs)), key=lambda i: probs[i]))
        conf = float(probs[idx])
        bucket = LABEL_TO_BUCKET.get(idx, "medium")
        if conf < 0.4:
            return None
        return bucket, conf
    except Exception as e:
        logger.debug("[size_classifier] predict hata: %s", e)
        return None
