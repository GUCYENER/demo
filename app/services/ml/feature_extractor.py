"""
feature_extractor — Faz 5a
==========================
Pipeline state'inden CatBoost training/inference için feature matrix oluşturur.

İki kullanım:
    1) Training: pipeline run sonrası → DB'ye satırlar atılır (agentic_query_feedback)
    2) Inference: multi_signal_rank içinde her aday için feature vector → model.predict()

Feature listesi (FEATURE_ORDER): model deterministic input için sabit sıralı.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
import logging

logger = logging.getLogger(__name__)


# Model input sırasını sabitler — CatBoost feature_names ile birebir uyumlu
FEATURE_ORDER: List[str] = [
    "feat_semantic",
    "feat_name_fuzzy",
    "feat_column_match",
    "feat_fk_centrality",
    "feat_recency",
    "feat_usage_freq",
    "intent_confidence",
    "candidate_rank",   # candidate'ın listede kaçıncı sırada olduğu (sürekli sayı)
]


def extract_candidate_features(
    candidate: Dict[str, Any],
    state: Dict[str, Any],
    rank: int = 0,
) -> Dict[str, float]:
    """
    Tek aday için feature dict (FEATURE_ORDER key'leri).

    Ranked candidate'taki sinyaller multi_signal_rank tarafından zaten doldurulmuş:
        candidate.semantic_score, .name_fuzzy_score, .column_match_score,
        .fk_centrality_score, .recency_score, .usage_freq_score
    """
    return {
        "feat_semantic": float(candidate.get("semantic_score") or candidate.get("hybrid_score") or 0.0),
        "feat_name_fuzzy": float(candidate.get("name_fuzzy_score") or 0.0),
        "feat_column_match": float(candidate.get("column_match_score") or 0.0),
        "feat_fk_centrality": float(candidate.get("fk_centrality_score") or 0.0),
        "feat_recency": float(candidate.get("recency_score") or 0.0),
        "feat_usage_freq": float(candidate.get("usage_freq_score") or 0.0),
        "intent_confidence": float(state.get("intent_confidence") or 0.0),
        "candidate_rank": float(rank),
    }


def features_to_vector(features: Dict[str, float]) -> List[float]:
    """Feature dict → FEATURE_ORDER sırasına göre vector."""
    return [float(features.get(k, 0.0)) for k in FEATURE_ORDER]


def extract_batch(state: Dict[str, Any]) -> Tuple[List[List[float]], List[Dict[str, Any]]]:
    """
    Tüm ranked candidates için (feature matrix, candidate list) döner.
    Inference için pratik form.

    Returns:
        X: [[feat...], ...] shape (n_candidates, n_features)
        candidates: ranked_candidates listesi (aynı sırada)
    """
    candidates = state.get("ranked_candidates") or []
    X: List[List[float]] = []
    for i, cand in enumerate(candidates):
        feats = extract_candidate_features(cand, state, rank=i)
        X.append(features_to_vector(feats))
    return X, candidates


def collect_feedback_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pipeline çalıştıktan sonra DB'ye yazılacak satırları üretir.
    Her ranked candidate için 1 satır; selected/clarified/success bilgisi state'ten gelir.

    State'ten beklenenler:
        question, intent, intent_confidence, company_id, source_id, user_id,
        ranked_candidates (multi_signal_rank sonrası),
        selected_tables (clarification veya auto),
        validation_passed, row_count, elapsed_ms, retry_count,
        ambiguity (dict, reason field), error_category, user_feedback (opsiyonel int)
    """
    candidates = state.get("ranked_candidates") or []
    if not candidates:
        return []

    selected = state.get("selected_tables") or []
    selected_keys = set()
    for s in selected:
        sch = (s.get("schema_name") or "").lower()
        tbl = (s.get("table_name") or "").lower()
        selected_keys.add(f"{sch}.{tbl}")

    ambiguity = state.get("ambiguity") or {}
    was_clarified = bool(ambiguity.get("needs_clarification") or state.get("clarification_payload"))
    execution_success = bool(state.get("validation_passed")) and not (state.get("errors") or [])

    rows: List[Dict[str, Any]] = []
    for i, cand in enumerate(candidates):
        sch = (cand.get("schema_name") or "").lower()
        tbl = (cand.get("table_name") or "").lower()
        full = f"{sch}.{tbl}"
        was_selected = full in selected_keys

        feats = extract_candidate_features(cand, state, rank=i)
        rows.append({
            "company_id": state.get("company_id"),
            "source_id": state.get("source_id"),
            "user_id": state.get("user_id"),
            "question": state.get("question") or "",
            "intent": state.get("intent"),
            "intent_confidence": state.get("intent_confidence"),
            "candidate_rank": i,
            "candidate_schema": cand.get("schema_name"),
            "candidate_table": cand.get("table_name"),
            "feat_semantic": feats["feat_semantic"],
            "feat_name_fuzzy": feats["feat_name_fuzzy"],
            "feat_column_match": feats["feat_column_match"],
            "feat_fk_centrality": feats["feat_fk_centrality"],
            "feat_recency": feats["feat_recency"],
            "feat_usage_freq": feats["feat_usage_freq"],
            "final_score": float(cand.get("final_score") or 0.0),
            "was_selected": was_selected,
            "was_clarified": was_clarified,
            "execution_success": execution_success,
            "user_feedback": state.get("user_feedback"),
            "row_count": state.get("row_count"),
            "elapsed_ms": state.get("elapsed_ms"),
            "ambiguity_reason": ambiguity.get("reason"),
            "retry_count": int(state.get("retry_count") or 0),
            "error_category": state.get("error_category"),
        })
    return rows


def persist_feedback(cur, rows: List[Dict[str, Any]]) -> int:
    """
    agentic_query_feedback tablosuna batch insert.
    Returns: insert edilen satır sayısı.
    """
    if not rows:
        return 0
    cols = [
        "company_id", "source_id", "user_id", "question", "intent", "intent_confidence",
        "candidate_rank", "candidate_schema", "candidate_table",
        "feat_semantic", "feat_name_fuzzy", "feat_column_match",
        "feat_fk_centrality", "feat_recency", "feat_usage_freq",
        "final_score", "was_selected", "was_clarified",
        "execution_success", "user_feedback", "row_count", "elapsed_ms",
        "ambiguity_reason", "retry_count", "error_category",
    ]
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"""
        INSERT INTO agentic_query_feedback ({', '.join(cols)})
        VALUES ({placeholders})
    """
    n = 0
    for r in rows:
        try:
            values = tuple(r.get(c) for c in cols)
            cur.execute(sql, values)
            n += 1
        except Exception as e:
            logger.debug("[feature_extractor] feedback insert skipped: %s", e)
    return n
