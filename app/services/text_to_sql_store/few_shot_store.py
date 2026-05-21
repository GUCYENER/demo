"""query_examples accessors — few-shot retrieval store (v3.30.0 FAZ 4 P50).

Migration: ``migrations/versions/042_v3300_query_examples.py``
Embedding adapter: ``app.services.rag.embedding.EmbeddingManager``
    (ONNX-first, sentence-transformers fallback; 384-dim).

Public API (all synchronous — matches db_smart psycopg2 cursor style):

    record_example(cur, user_ctx, *, source_id, db_engine, question,
                   generated_sql, was_correct=True, user_feedback=None,
                   chosen_tables=None, chosen_columns=None) -> Optional[int]

    top_k_examples(cur, user_ctx, *, source_id, question, k=5,
                   include_company_baseline=True) -> List[dict]

    delete_example(cur, example_id, user_ctx) -> bool
        Soft-delete (was_correct=False) so the ivfflat index stays warm.

    _build_distance_query(*, scope, k) -> str
        Internal helper — returns the parameterised SELECT used by
        top_k_examples. Scope ∈ {'user', 'baseline'}.

RLS contract:
    All four functions assume ``apply_vyra_user_context(cur, user_ctx)`` was
    already invoked on the cursor by the caller (endpoint layer). The
    pol_query_examples_* policies enforce company_id isolation; cross-tenant
    leak is impossible at the DB layer. We never INSERT a row whose
    company_id differs from user_ctx['company_id'].

PII / TYCHE:
    ``question`` and ``generated_sql`` are user-authored — logged at INFO at
    record-time, never at DEBUG with payload. The embedding is a one-way
    transform (no inverse), safe to persist.

Embedding-service failure mode:
    top_k_examples returns [] (logged WARNING). record_example returns None
    (logged WARNING). The caller falls back to zero-shot prompting.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Public, also unit-test asserted.
EMBEDDING_DIM = 384
_MAX_K = 50
_MAX_QUESTION_LEN = 4000
_MAX_SQL_LEN = 16000
_VALID_FEEDBACK = {
    "manual_thumbs_up",
    "manual_thumbs_down",
    "auto_repaired",
    "synthetic",
}


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _require_user_ctx(user_ctx: Dict[str, Any]) -> Tuple[int, int]:
    uid = user_ctx.get("id") if user_ctx else None
    cid = user_ctx.get("company_id") if user_ctx else None
    if uid is None or cid is None:
        raise ValueError("user_ctx eksik (id, company_id zorunlu)")
    return int(uid), int(cid)


def _embed(question: str) -> Optional[List[float]]:
    """Return 384-dim embedding for `question` or None on failure.

    Lazy import keeps the EmbeddingManager (model loader) out of the
    import-time graph; tests can monkey-patch this symbol directly.
    """
    try:
        from app.services.rag.embedding import EmbeddingManager  # local import
        mgr = _get_embedding_manager()
        if mgr is None:
            mgr = EmbeddingManager()
            _cache_embedding_manager(mgr)
        return list(mgr.get_embedding(question))
    except Exception as e:  # noqa: BLE001 — broad: model load/inference paths
        logger.warning("[few_shot_store] embedding failed: %s", e)
        return None


# Module-level cache so we don't re-instantiate the manager on every call.
_EMB_MGR: Optional[Any] = None


def _get_embedding_manager() -> Optional[Any]:
    return _EMB_MGR


def _cache_embedding_manager(mgr: Any) -> None:
    global _EMB_MGR
    _EMB_MGR = mgr


def _vector_literal(emb: List[float]) -> str:
    """Render a Python list as a pgvector literal — e.g. '[0.1,0.2,...]'.

    Used as a bind parameter (NOT string-interpolated into the SQL body):
    psycopg2 sends it as a single TEXT value which pgvector casts via
    ``::vector``. Safe vs SQL injection.
    """
    return "[" + ",".join(f"{float(x):.6f}" for x in emb) + "]"


def _build_distance_query(*, scope: str, k: int) -> str:
    """Build a parameterised SELECT returning (id, question, generated_sql,
    distance, chosen_tables, chosen_columns, was_correct).

    Params bound by caller (positional %s):
        scope='user':     [vector_literal, user_id, source_id, k]
        scope='baseline': [vector_literal, company_id, source_id, k]
    """
    if scope == "user":
        where = "user_id = %s AND source_id = %s AND was_correct = TRUE"
    elif scope == "baseline":
        where = (
            "user_id IS NULL AND company_id = %s AND source_id = %s "
            "AND was_correct = TRUE"
        )
    else:  # pragma: no cover — defensive
        raise ValueError(f"unknown scope: {scope}")
    return f"""
        SELECT id, question, generated_sql,
               (embedding <=> %s::vector) AS distance,
               chosen_tables, chosen_columns, was_correct
        FROM query_examples
        WHERE {where}
          AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """


# ─────────────────────────────────────────────────────────────
# record_example
# ─────────────────────────────────────────────────────────────

def record_example(
    cur: Any,
    user_ctx: Dict[str, Any],
    *,
    source_id: int,
    db_engine: str,
    question: str,
    generated_sql: str,
    was_correct: bool = True,
    user_feedback: Optional[str] = None,
    chosen_tables: Optional[List[str]] = None,
    chosen_columns: Optional[List[str]] = None,
    as_company_baseline: bool = False,
) -> Optional[int]:
    """INSERT a query example. Returns inserted id or None on failure.

    ``as_company_baseline=True`` → user_id is set NULL (synthetic / P52
    baseline). The caller still must own a valid user_ctx for RLS.
    """
    user_id, company_id = _require_user_ctx(user_ctx)
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question boş olamaz")
    if not isinstance(generated_sql, str) or not generated_sql.strip():
        raise ValueError("generated_sql boş olamaz")
    if user_feedback is not None and user_feedback not in _VALID_FEEDBACK:
        raise ValueError(f"user_feedback geçersiz: {user_feedback!r}")

    q = question.strip()[:_MAX_QUESTION_LEN]
    sql = generated_sql.strip()[:_MAX_SQL_LEN]
    tables = list(chosen_tables or [])
    columns = list(chosen_columns or [])
    eff_user_id: Optional[int] = None if as_company_baseline else user_id

    emb = _embed(q)
    if emb is None:
        # Embedding service down → skip insertion; caller can retry later.
        logger.info(
            "[few_shot_store] skip record_example (no embedding) user=%s src=%s",
            user_id, source_id,
        )
        return None
    if len(emb) != EMBEDDING_DIM:
        logger.warning(
            "[few_shot_store] embedding dim mismatch: got %d expected %d",
            len(emb), EMBEDDING_DIM,
        )
        return None

    try:
        cur.execute(
            """
            INSERT INTO query_examples
                (user_id, company_id, source_id, db_engine, question,
                 generated_sql, was_correct, user_feedback, embedding,
                 chosen_tables, chosen_columns)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s)
            RETURNING id
            """,
            (
                eff_user_id, company_id, int(source_id), str(db_engine)[:20],
                q, sql, bool(was_correct), user_feedback,
                _vector_literal(emb), tables, columns,
            ),
        )
        row = cur.fetchone()
        if not row:
            logger.warning("[few_shot_store] INSERT RETURNING empty (RLS?)")
            return None
        rid = row[0] if not isinstance(row, dict) else row.get("id")
        logger.info(
            "[few_shot_store] recorded id=%s user=%s src=%s baseline=%s",
            rid, eff_user_id, source_id, as_company_baseline,
        )
        return int(rid)
    except Exception as e:  # noqa: BLE001
        logger.warning("[few_shot_store] record_example INSERT failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────
# top_k_examples
# ─────────────────────────────────────────────────────────────

def top_k_examples(
    cur: Any,
    user_ctx: Dict[str, Any],
    *,
    source_id: int,
    question: str,
    k: int = 5,
    include_company_baseline: bool = True,
) -> List[Dict[str, Any]]:
    """Top-k nearest examples (cosine distance) for (user, source).

    Strategy:
        1. Embed `question` (lazy ONNX/sentence-transformers).
        2. Run user-personal query (LIMIT k).
        3. If include_company_baseline: run baseline query (LIMIT k).
        4. Merge by distance ASC, return top-k.

    Returns [] on embedding-service failure (logged WARNING).
    Each row dict: {id, question, generated_sql, distance, chosen_tables,
                    chosen_columns, was_correct, source} where source ∈
                    {'user', 'baseline'}.
    """
    user_id, company_id = _require_user_ctx(user_ctx)
    if not isinstance(question, str) or not question.strip():
        return []
    k = max(1, min(int(k or 5), _MAX_K))

    emb = _embed(question.strip()[:_MAX_QUESTION_LEN])
    if emb is None:
        return []
    vec_lit = _vector_literal(emb)

    merged: List[Dict[str, Any]] = []

    # --- user-personal scope ---
    try:
        cur.execute(
            _build_distance_query(scope="user", k=k),
            (vec_lit, user_id, int(source_id), vec_lit, k),
        )
        for r in cur.fetchall() or []:
            merged.append(_row_to_dict(r, source="user"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[few_shot_store] user-scope query failed: %s", e)

    # --- company-baseline scope ---
    if include_company_baseline:
        try:
            cur.execute(
                _build_distance_query(scope="baseline", k=k),
                (vec_lit, company_id, int(source_id), vec_lit, k),
            )
            for r in cur.fetchall() or []:
                merged.append(_row_to_dict(r, source="baseline"))
        except Exception as e:  # noqa: BLE001
            logger.warning("[few_shot_store] baseline-scope query failed: %s", e)

    merged.sort(key=lambda d: (d["distance"] if d["distance"] is not None else 1e9))
    return merged[:k]


def _row_to_dict(r: Any, *, source: str) -> Dict[str, Any]:
    if isinstance(r, dict):
        out = dict(r)
        out["source"] = source
        return out
    return {
        "id": r[0],
        "question": r[1],
        "generated_sql": r[2],
        "distance": float(r[3]) if r[3] is not None else None,
        "chosen_tables": list(r[4] or []),
        "chosen_columns": list(r[5] or []),
        "was_correct": bool(r[6]),
        "source": source,
    }


# ─────────────────────────────────────────────────────────────
# delete_example
# ─────────────────────────────────────────────────────────────

def delete_example(
    cur: Any,
    example_id: int,
    user_ctx: Dict[str, Any],
) -> bool:
    """Soft-delete (was_correct=FALSE) the user's own example.

    The row + embedding stay so the ivfflat index doesn't degrade. Retrieval
    filters ``WHERE was_correct = TRUE`` so a soft-deleted row never surfaces.
    Returns True if a row was updated (RLS + user_id match), False otherwise.
    """
    user_id, _ = _require_user_ctx(user_ctx)
    try:
        cur.execute(
            """
            UPDATE query_examples
               SET was_correct = FALSE
             WHERE id = %s AND user_id = %s AND was_correct = TRUE
            """,
            (int(example_id), user_id),
        )
        rowcount = getattr(cur, "rowcount", 0) or 0
        return rowcount > 0
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[few_shot_store] delete_example %s failed: %s", example_id, e
        )
        return False
