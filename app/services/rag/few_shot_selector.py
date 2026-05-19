"""
few_shot_selector — Faz 4c
==========================
Validated NL→SQL example havuzundan (`few_shot_examples`) sql_generate node için
top-K en alakalı örnekleri seçer.

Seçim stratejisi (hybrid + priority):
    score = α * semantic_sim + β * lex_rank + γ * priority_boost

    semantic_sim: 1 - cosine_distance(query_emb, example_emb)  (pgvector varsa)
    lex_rank: ts_rank(tsv, plainto_tsquery(query))             (tsv ile)
    priority_boost: log1p(usage_count) * success_rate / 5      (saturated)

Filtreler:
    - company_id eşleşmeli (NULL → cross-company globaller)
    - source_id eşleşmeli VEYA NULL (NULL → kaynaktan bağımsız generic)
    - intent eşleşmesi varsa boost (intent_match=1.0, mismatch=0.7)
    - schema_signature overlap (Jaccard) → boost (uyumsuz = 0.5)

Çıktı:
    [{"id", "question", "sql_query", "intent", "schema_signature",
      "score", "usage_count", "success_rate"}, ...]

Kullanım (sql_generate node'da):
    examples = select_few_shots(cur, company_id, source_id,
                                question, q_emb, intent,
                                top_k=3)
    context_str += "\nÖrnekler:\n" + format_examples(examples)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
import logging
import math

logger = logging.getLogger(__name__)

# Hybrid weights (multi_signal_rank ile uyumlu pattern)
ALPHA_SEMANTIC = 0.55
BETA_LEXICAL = 0.25
GAMMA_PRIORITY = 0.20

# Intent/signature uyumsuzluk cezaları
INTENT_MISMATCH_PENALTY = 0.7
SIGNATURE_MISMATCH_PENALTY = 0.5


def _pgvector_available(cur) -> bool:
    """pgvector extension yüklü mü?"""
    try:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        return bool(cur.fetchone()[0])
    except Exception:
        return False


def _signature_jaccard(sig_a: str, sig_b: str) -> float:
    """İki schema_signature arasında Jaccard benzerliği (token bazlı)."""
    if not sig_a or not sig_b:
        return 0.0
    set_a = set(t.strip().lower() for t in sig_a.split(",") if t.strip())
    set_b = set(t.strip().lower() for t in sig_b.split(",") if t.strip())
    if not set_a or not set_b:
        return 0.0
    inter = set_a & set_b
    union = set_a | set_b
    return len(inter) / len(union) if union else 0.0


def _priority_boost(usage_count: int, success_rate: float) -> float:
    """log1p(usage)/log1p(50) ile saturated, success_rate çarpan."""
    sat = math.log1p(max(usage_count or 0, 0)) / math.log1p(50.0)
    sat = min(max(sat, 0.0), 1.0)
    return sat * (success_rate if success_rate is not None else 1.0)


def select_few_shots(
    cur,
    company_id: int,
    source_id: Optional[int],
    query_text: str,
    query_embedding: Optional[Sequence[float]] = None,
    intent: Optional[str] = None,
    candidate_signature: Optional[str] = None,
    top_k: int = 3,
    max_pool: int = 25,
) -> List[Dict[str, Any]]:
    """
    Few-shot örnek seçici.

    Args:
        cur: psycopg2 cursor (scoped — caller RLS bypass'i hallediyorsa kullanır)
        company_id: tenant
        source_id: data source (NULL → generic)
        query_text: kullanıcı sorusu (lexical match için)
        query_embedding: 384-d vektör (semantic match için; yoksa lex-only)
        intent: lookup/aggregate/report/follow_up (eşleşme boost)
        candidate_signature: "schema.tbl,schema.tbl" sıralı (Jaccard boost)
        top_k: dönecek örnek sayısı
        max_pool: candidate pool boyutu (DB tarafı)

    Returns:
        Top-K example list (score azalan)
    """
    if not query_text or not query_text.strip():
        return []

    has_pgvec = _pgvector_available(cur) and query_embedding is not None
    qt = query_text.strip()

    # Candidate pool çek (filtre: company + source/null)
    base_where = """
        company_id = %(company_id)s
        AND (source_id = %(source_id)s OR source_id IS NULL)
    """

    if has_pgvec:
        sql = f"""
        SELECT id, question, sql_query, intent, schema_signature,
               usage_count, success_rate,
               COALESCE(1 - (embedding <=> %(qe)s::vector), 0.0) AS sem_sim,
               COALESCE(ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %(qt)s)), 0.0) AS lex_rank
          FROM few_shot_examples
         WHERE {base_where}
         ORDER BY (
             0.55 * COALESCE(1 - (embedding <=> %(qe)s::vector), 0.0)
           + 0.25 * COALESCE(ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %(qt)s)), 0.0)
         ) DESC
         LIMIT %(max_pool)s
        """
        params = {
            "company_id": company_id,
            "source_id": source_id,
            "qe": list(query_embedding),
            "qt": qt,
            "max_pool": max_pool,
        }
    else:
        # Lex-only fallback
        sql = f"""
        SELECT id, question, sql_query, intent, schema_signature,
               usage_count, success_rate,
               0.0 AS sem_sim,
               COALESCE(ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %(qt)s)), 0.0) AS lex_rank
          FROM few_shot_examples
         WHERE {base_where}
         ORDER BY COALESCE(ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %(qt)s)), 0.0) DESC,
                  usage_count DESC
         LIMIT %(max_pool)s
        """
        params = {
            "company_id": company_id,
            "source_id": source_id,
            "qt": qt,
            "max_pool": max_pool,
        }

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("[few_shot_selector] DB hata: %s", e)
        return []

    # Score + post-process (intent + signature boost)
    results: List[Dict[str, Any]] = []
    for r in rows:
        rid, question, sql_query, ex_intent, ex_sig, usage, succ, sem, lex = r
        prio = _priority_boost(usage or 0, succ if succ is not None else 1.0)
        base = ALPHA_SEMANTIC * float(sem or 0.0) + BETA_LEXICAL * float(lex or 0.0) + GAMMA_PRIORITY * prio

        # Intent match factor
        intent_factor = 1.0
        if intent and ex_intent and intent != ex_intent:
            intent_factor = INTENT_MISMATCH_PENALTY

        # Signature overlap factor
        sig_factor = 1.0
        if candidate_signature and ex_sig:
            j = _signature_jaccard(candidate_signature, ex_sig)
            # Jaccard 0 → penalty, 1 → boost; 0.5 → nötr
            if j >= 0.5:
                sig_factor = 1.0 + 0.2 * (j - 0.5) * 2  # 1.0..1.2
            else:
                sig_factor = SIGNATURE_MISMATCH_PENALTY + (0.5 - SIGNATURE_MISMATCH_PENALTY) * (j / 0.5)
                # 0.5..1.0

        final_score = base * intent_factor * sig_factor

        results.append({
            "id": rid,
            "question": question,
            "sql_query": sql_query,
            "intent": ex_intent,
            "schema_signature": ex_sig,
            "score": float(final_score),
            "sem_sim": float(sem or 0.0),
            "lex_rank": float(lex or 0.0),
            "priority": float(prio),
            "usage_count": int(usage or 0),
            "success_rate": float(succ if succ is not None else 1.0),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def format_examples_for_prompt(examples: List[Dict[str, Any]]) -> str:
    """LLM prompt'una eklemek için örnekleri formatlar."""
    if not examples:
        return ""
    lines = ["Örnekler:"]
    for i, ex in enumerate(examples, 1):
        lines.append(f"\nÖrnek {i}:")
        lines.append(f"  Soru: {ex['question']}")
        lines.append(f"  SQL:  {ex['sql_query']}")
    return "\n".join(lines)


def record_example_usage(cur, example_id: int, success: bool = True) -> None:
    """
    Bir örnek pipeline'da kullanıldığında usage_count + success_rate günceller.
    success_rate basit moving average: (old_rate * old_count + new_signal) / new_count
    """
    try:
        cur.execute("""
            UPDATE few_shot_examples
               SET usage_count = usage_count + 1,
                   success_rate = (
                       (COALESCE(success_rate, 1.0) * usage_count + %s::real) /
                       (usage_count + 1)
                   ),
                   last_used_at = NOW()
             WHERE id = %s
        """, (1.0 if success else 0.0, example_id))
    except Exception as e:
        logger.warning("[few_shot_selector] usage update hata id=%s: %s", example_id, e)


def upsert_example(
    cur,
    company_id: int,
    source_id: Optional[int],
    question: str,
    sql_query: str,
    intent: Optional[str] = None,
    schema_signature: Optional[str] = None,
    embedding: Optional[Sequence[float]] = None,
    created_by: Optional[int] = None,
) -> Optional[int]:
    """Yeni örnek ekle (duplicate question için INSERT-ON-CONFLICT yok — uniqueness kontrolünü caller yapar)."""
    try:
        if embedding is not None and _pgvector_available(cur):
            cur.execute("""
                INSERT INTO few_shot_examples
                    (company_id, source_id, question, sql_query, intent,
                     schema_signature, embedding, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s)
                RETURNING id
            """, (company_id, source_id, question, sql_query, intent,
                  schema_signature, list(embedding), created_by))
        else:
            cur.execute("""
                INSERT INTO few_shot_examples
                    (company_id, source_id, question, sql_query, intent,
                     schema_signature, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (company_id, source_id, question, sql_query, intent,
                  schema_signature, created_by))
        return cur.fetchone()[0]
    except Exception as e:
        logger.warning("[few_shot_selector] upsert hata: %s", e)
        return None
