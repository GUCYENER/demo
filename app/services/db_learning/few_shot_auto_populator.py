"""VYRA v3.27.0 — Few-Shot Auto Populator (G4).

Kullanıcı sorgusu pipeline'ı başarıyla tamamladığında, kalite eşiklerini
geçen örnekler few_shot_examples tablosuna otomatik eklenir.

Quality gate (TÜM şartlar gerekli):
  * sql ve question dolu
  * row_count > 0 (sıfır sonuç öğretici değil)
  * elapsed_ms < FEW_SHOT_MAX_LATENCY_MS (default 2000ms)
  * user feedback NEGATIF değil (state.get('user_feedback') == 'negative' atla)
  * cache_hit DEĞIL (zaten öğrenilmiş)

Dedupe (2 katman):
  * Layer 1 — (source_id, company_id, intent, normalized_question) exact match
  * Layer 2 — cosine(embedding) ≥ COSINE_DUP_THRESHOLD (0.92)
  Match → usage_count++, last_used_at=NOW()
  Match yok → INSERT

Tüm yazımlar SAVEPOINT içinde best-effort; pipeline'ı asla durdurmaz.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.db_learning.dedupe_service import (
    COSINE_DUP_MAX_DISTANCE,
    build_schema_signature,
)
from app.services.db_learning.learned_queries_service import (
    _embed_question,
    _vector_literal,
    normalize_question,
)

logger = logging.getLogger(__name__)

TABLE_NAME = "few_shot_examples"
FEW_SHOT_MAX_LATENCY_MS = 2000


# ─────────────────────────────────────────────────────────────
# Embedding kolonu (vector vs float[])
# ─────────────────────────────────────────────────────────────

def _detect_fs_embedding_type(cur) -> str:
    """few_shot_examples.embedding kolonu vector mi float[] mi?"""
    try:
        cur.execute(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = 'embedding'
            """,
            (TABLE_NAME,),
        )
        row = cur.fetchone()
        if row:
            udt = row.get("udt_name") if hasattr(row, "get") else row[0]
            return "vector" if udt == "vector" else "array"
    except Exception:
        pass
    return "vector"


# ─────────────────────────────────────────────────────────────
# Quality gate
# ─────────────────────────────────────────────────────────────

def _passes_quality_gate(state: Dict[str, Any]) -> bool:
    sql = state.get("sql")
    question = state.get("question")
    if not sql or not question:
        return False
    if state.get("_cache_hit"):
        return False
    if state.get("errors"):
        return False
    row_count = int(state.get("row_count") or 0)
    if row_count <= 0:
        return False
    elapsed = int(state.get("execute_elapsed_ms") or state.get("elapsed_ms") or 0)
    if elapsed > FEW_SHOT_MAX_LATENCY_MS:
        return False
    feedback = (state.get("user_feedback") or "").lower()
    if feedback == "negative":
        return False
    return True


# ─────────────────────────────────────────────────────────────
# Dedupe (Layer 1 + 2)
# ─────────────────────────────────────────────────────────────

def _find_duplicate(
    cur,
    *,
    company_id: int,
    source_id: Optional[int],
    intent: Optional[str],
    question: str,
    embedding: Optional[List[float]],
) -> Optional[int]:
    """Var olan few_shot_examples kaydını bul (yoksa None).

    Layer 1: normalize(question) exact.
    Layer 2: cosine(embedding) >= 0.92 (vector ise DB-side).
    """
    q_norm = normalize_question(question)

    # ─── Layer 1 ──────────────────────────────────────
    try:
        if source_id is not None:
            cur.execute(
                f"""
                SELECT id FROM {TABLE_NAME}
                WHERE company_id = %s AND source_id = %s
                  AND COALESCE(intent, '') = COALESCE(%s, '')
                  AND lower(regexp_replace(question, '\\s+', ' ', 'g')) = %s
                LIMIT 1
                """,
                (company_id, source_id, intent, q_norm),
            )
        else:
            cur.execute(
                f"""
                SELECT id FROM {TABLE_NAME}
                WHERE company_id = %s AND source_id IS NULL
                  AND COALESCE(intent, '') = COALESCE(%s, '')
                  AND lower(regexp_replace(question, '\\s+', ' ', 'g')) = %s
                LIMIT 1
                """,
                (company_id, intent, q_norm),
            )
        row = cur.fetchone()
        if row:
            return int(row.get("id") if hasattr(row, "get") else row[0])
    except Exception as e:
        logger.debug("[few_shot.dup.L1] %s", e)

    # ─── Layer 2 ──────────────────────────────────────
    if embedding is None or len(embedding) == 0:
        return None
    emb_type = _detect_fs_embedding_type(cur)
    if emb_type != "vector":
        return None
    try:
        lit = _vector_literal(embedding)
        if source_id is not None:
            cur.execute(
                f"""
                SELECT id, (embedding <=> %s::vector) AS dist
                FROM {TABLE_NAME}
                WHERE company_id = %s AND source_id = %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                (lit, company_id, source_id, lit),
            )
        else:
            cur.execute(
                f"""
                SELECT id, (embedding <=> %s::vector) AS dist
                FROM {TABLE_NAME}
                WHERE company_id = %s AND source_id IS NULL
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                (lit, company_id, lit),
            )
        row = cur.fetchone()
        if row:
            rid = row.get("id") if hasattr(row, "get") else row[0]
            dist = row.get("dist") if hasattr(row, "get") else row[1]
            if dist is not None and float(dist) <= COSINE_DUP_MAX_DISTANCE:
                return int(rid)
    except Exception as e:
        logger.debug("[few_shot.dup.L2] %s", e)

    return None


# ─────────────────────────────────────────────────────────────
# UPSERT
# ─────────────────────────────────────────────────────────────

def _bump_existing(cur, fs_id: int) -> None:
    try:
        cur.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET usage_count = usage_count + 1,
                last_used_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            (fs_id,),
        )
    except Exception as e:
        logger.debug("[few_shot.bump] %s", e)


def _insert_new(
    cur,
    *,
    company_id: int,
    source_id: Optional[int],
    question: str,
    sql: str,
    intent: Optional[str],
    schema_signature: Optional[str],
    embedding: Optional[List[float]],
    created_by: Optional[int],
) -> Optional[int]:
    emb_type = _detect_fs_embedding_type(cur)
    if embedding and emb_type == "vector":
        lit = _vector_literal(embedding)
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME}
                (company_id, source_id, question, sql_query, intent,
                 schema_signature, embedding, usage_count, success_rate,
                 last_used_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, 1, 1.0, NOW(), %s)
            RETURNING id
            """,
            (company_id, source_id, question, sql, intent,
             schema_signature, lit, created_by),
        )
    elif embedding and emb_type == "array":
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME}
                (company_id, source_id, question, sql_query, intent,
                 schema_signature, embedding, usage_count, success_rate,
                 last_used_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1.0, NOW(), %s)
            RETURNING id
            """,
            (company_id, source_id, question, sql, intent,
             schema_signature, list(embedding), created_by),
        )
    else:
        cur.execute(
            f"""
            INSERT INTO {TABLE_NAME}
                (company_id, source_id, question, sql_query, intent,
                 schema_signature, usage_count, success_rate,
                 last_used_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 1, 1.0, NOW(), %s)
            RETURNING id
            """,
            (company_id, source_id, question, sql, intent,
             schema_signature, created_by),
        )
    row = cur.fetchone()
    if row is None:
        return None
    return int(row.get("id") if hasattr(row, "get") else row[0])


# ─────────────────────────────────────────────────────────────
# Public — pipeline'dan çağrılır
# ─────────────────────────────────────────────────────────────

def populate_from_pipeline_state(cur, state: Dict[str, Any]) -> Dict[str, Any]:
    """Pipeline state'inden few_shot örneği ekle/güncelle.

    Returns:
      {'status': 'skipped'|'inserted'|'bumped'|'error', 'id': int|None, 'reason': str}
    """
    if not _passes_quality_gate(state):
        return {"status": "skipped", "id": None, "reason": "quality_gate"}

    company_id = state.get("company_id")
    if company_id is None:
        return {"status": "skipped", "id": None, "reason": "no_company"}

    source_id = state.get("source_id")
    question = str(state.get("question") or "").strip()
    sql = str(state.get("sql") or "").strip()
    intent = state.get("intent")
    user_id = state.get("user_id")

    # schema_signature için tables topla
    tables: List[str] = []
    for tc in (state.get("selected_tables") or []):
        if isinstance(tc, dict):
            sch = tc.get("schema_name")
            tbl = tc.get("table_name")
            if tbl:
                tables.append(f"{sch}.{tbl}" if sch else tbl)
    schema_signature = build_schema_signature(tables) if tables else None

    # embedding (best-effort)
    embedding = _embed_question(question)

    try:
        dup_id = _find_duplicate(
            cur,
            company_id=int(company_id),
            source_id=int(source_id) if source_id is not None else None,
            intent=intent,
            question=question,
            embedding=embedding,
        )
        if dup_id:
            _bump_existing(cur, dup_id)
            return {"status": "bumped", "id": dup_id, "reason": "duplicate"}

        new_id = _insert_new(
            cur,
            company_id=int(company_id),
            source_id=int(source_id) if source_id is not None else None,
            question=question,
            sql=sql,
            intent=intent,
            schema_signature=schema_signature,
            embedding=embedding,
            created_by=int(user_id) if user_id else None,
        )
        return {"status": "inserted", "id": new_id, "reason": "new"}
    except Exception as e:
        logger.warning("[few_shot.populate] error: %s", e)
        return {"status": "error", "id": None, "reason": str(e)[:200]}


# ─────────────────────────────────────────────────────────────
# v3.44.0 P1 — Sentetik (FK Loop) terfi
# ─────────────────────────────────────────────────────────────

def _set_origin(cur, fs_id: int, origin: str) -> None:
    """origin kolonu (mig 051) varsa kaydın kaynağını işaretle — yoksa sessiz atla.

    Kolon varlığı önce kontrol edilir (cache'li) → UPDATE yalnız kolon mevcutsa koşar, bu yüzden
    'column does not exist' ile transaction poison'lanmaz."""
    try:
        from app.services.rag.few_shot_selector import _has_origin_columns
        if not _has_origin_columns(cur):
            return
        cur.execute(
            f"UPDATE {TABLE_NAME} SET origin = %s WHERE id = %s",
            (origin, fs_id),
        )
    except Exception as e:
        logger.debug("[few_shot.set_origin] %s", e)


def promote_synthetic(
    cur,
    *,
    company_id: int,
    source_id: Optional[int],
    question: str,
    sql: str,
    tables: Optional[List[str]] = None,
    origin: str = "synthetic_fk",
    intent: Optional[str] = None,
    created_by: Optional[int] = None,
) -> Dict[str, Any]:
    """FK Loop'un doğrulanmış sentetik sorgusunu few_shot_examples'a terfi et.

    Mevcut auto-populator altyapısını YENİDEN KULLANIR: dedup (L1 normalize + L2 cosine≥0.92),
    canonical embedding (_embed_question), schema_signature (build_schema_signature), vector/array
    insert (_insert_new). Bu sayede sentetik örnekler gerçek pipeline örnekleriyle AYNI havuzda,
    AYNI dedup ve embedding sözleşmesiyle yaşar (çift insert yolu / drift yok).

    intent=None bilinçli: sentetik intent ('synthetic_lookup_join' gibi) gerçek kullanıcı niyetiyle
    asla eşleşmez → selector'da yapay INTENT_MISMATCH_PENALTY (0.7) oluşurdu. None ile sentetik
    yalnız SYNTHETIC_WEIGHT (0.85) ile ağırlıklanır (tasarlanan tek-ceza).

    origin='synthetic_fk' insert SONRASI işaretlenir (kolon mig 051 ile geldiyse).

    Returns: {'status': 'inserted'|'bumped'|'skipped'|'error', 'id': int|None, 'reason': str}.
    Best-effort: caller SAVEPOINT'i sağlamalı (poison'da rollback caller'ın sorumluluğu)."""
    if company_id is None:
        return {"status": "skipped", "id": None, "reason": "no_company"}
    q = (question or "").strip()
    s = (sql or "").strip()
    if not q or not s:
        return {"status": "skipped", "id": None, "reason": "empty"}

    schema_signature = build_schema_signature(tables) if tables else None
    embedding = _embed_question(q)  # best-effort; None ise lex-only few-shot yine seçilebilir

    try:
        dup_id = _find_duplicate(
            cur,
            company_id=int(company_id),
            source_id=int(source_id) if source_id is not None else None,
            intent=intent,
            question=q,
            embedding=embedding,
        )
        if dup_id:
            _bump_existing(cur, dup_id)
            return {"status": "bumped", "id": dup_id, "reason": "duplicate"}

        new_id = _insert_new(
            cur,
            company_id=int(company_id),
            source_id=int(source_id) if source_id is not None else None,
            question=q,
            sql=s,
            intent=intent,
            schema_signature=schema_signature,
            embedding=embedding,
            created_by=created_by,
        )
        if new_id and origin and origin != "user":
            _set_origin(cur, new_id, origin)
        return {"status": "inserted", "id": new_id, "reason": "new"}
    except Exception as e:
        logger.warning("[few_shot.promote_synthetic] error: %s", e)
        return {"status": "error", "id": None, "reason": str(e)[:200]}


__all__ = [
    "populate_from_pipeline_state",
    "promote_synthetic",
    "FEW_SHOT_MAX_LATENCY_MS",
]
