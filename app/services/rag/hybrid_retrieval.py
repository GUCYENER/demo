"""
VYRA — Hybrid Retrieval (Faz 2d, v3.21.0)
==========================================
Anlamsal (cosine) + leksik (ts_rank) skor harmanı.

Hedef: Aynı kelimeyi içeren tablo/kolonu vurgulamak (ts_rank) +
       anlam yakınlığını korumak (cosine). Saf semantic'in
       yakaladığı eşanlamlı arama korunur; literal isim eşleşmelerinde
       leksik bileşen avantaj sağlar.

Formül:
    hybrid_score = α * (1 - cosine_dist) + β * ts_rank
    Default: α=0.65, β=0.35  (master plan K-değerleri)

Kapsam:
    - ds_column_embeddings → kolon ataması (Faz 2c'den)
    - ds_learning_results  → tablo/şema bağlamı (Faz 2b TSVECTOR)

RLS:
    Tüm sorgular caller'ın scoped DB context'inden geçer. Bu modül
    DB bağlantısı açmaz; çağrı zinciri `get_db_context_scoped(source_id)`
    altında çalışmalı (Faz 1c sözleşmesi).

Embedding fallback:
    pgvector yoksa `embedding` kolonu FLOAT[] — semantic kısım atlanır,
    yalnız ts_rank sıralaması kullanılır.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Master plan ağırlıkları — ileride system_settings'ten okunabilir
ALPHA_SEMANTIC = 0.65
BETA_LEXICAL = 0.35


def _detect_pgvector(cur) -> bool:
    """pgvector extension yüklü mü?"""
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
        return cur.fetchone() is not None
    except Exception:
        return False


def _clean_query(text: str) -> str:
    """plainto_tsquery için temizlik — boş ise '' döner."""
    return (text or "").strip()


def search_columns(
    cur,
    source_id: int,
    query_text: str,
    query_embedding: Optional[List[float]] = None,
    limit: int = 20,
    alpha: float = ALPHA_SEMANTIC,
    beta: float = BETA_LEXICAL,
) -> List[Dict[str, Any]]:
    """
    ds_column_embeddings'te hibrit arama.

    Args:
        cur: scoped psycopg2 cursor (RLS aktif)
        source_id: explicit filter (RLS dışı planner için faydalı)
        query_text: kullanıcı sorgusu (TR)
        query_embedding: 384-d vektör; None ise semantic skip
        limit: max sonuç

    Returns:
        [{schema_name, table_name, column_name, ..., hybrid_score}, ...]
    """
    has_vector = _detect_pgvector(cur)
    use_semantic = has_vector and query_embedding is not None
    tsq = _clean_query(query_text)
    has_lex = bool(tsq)

    params: List[Any] = []

    if use_semantic:
        sem_select = "(1 - (embedding <=> %s::vector))"
        params.append(query_embedding)
    else:
        sem_select = "0.0::float"

    if has_lex:
        lex_select = "COALESCE(ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %s)), 0)"
        params.append(tsq)
    else:
        lex_select = "0.0::float"

    where = ["source_id = %s"]
    params.append(source_id)
    if has_lex:
        # Lexical filtreyi gevşek tutuyoruz: ya TSV match ya da semantic skor varsa kabul
        where.append("tsv @@ plainto_tsquery('pg_catalog.simple', %s)")
        params.append(tsq)

    sql = f"""
        WITH scored AS (
            SELECT
                id, schema_name, table_name, column_name,
                data_type, is_pk, is_fk, is_nullable,
                business_name_tr, synonyms, semantic_type,
                sample_values, description,
                {sem_select} AS semantic_score,
                {lex_select} AS lexical_score
            FROM ds_column_embeddings
            WHERE {' AND '.join(where)}
        )
        SELECT *,
               ({alpha} * semantic_score + {beta} * lexical_score) AS hybrid_score
          FROM scored
         ORDER BY hybrid_score DESC
         LIMIT %s
    """
    params.append(limit)

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        logger.error("[Hybrid] search_columns hata: %s", e)
        return []

    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "schema_name": r["schema_name"],
            "table_name": r["table_name"],
            "column_name": r["column_name"],
            "data_type": r["data_type"],
            "is_pk": r["is_pk"],
            "is_fk": r["is_fk"],
            "is_nullable": r["is_nullable"],
            "business_name_tr": r["business_name_tr"],
            "synonyms": list(r["synonyms"] or []),
            "semantic_type": r["semantic_type"],
            "sample_values": r["sample_values"],
            "description": r["description"],
            "semantic_score": float(r["semantic_score"] or 0.0),
            "lexical_score": float(r["lexical_score"] or 0.0),
            "hybrid_score": float(r["hybrid_score"] or 0.0),
        })
    return out


def search_learning_results(
    cur,
    source_id: int,
    query_text: str,
    query_embedding: Optional[List[float]] = None,
    limit: int = 10,
    alpha: float = ALPHA_SEMANTIC,
    beta: float = BETA_LEXICAL,
    content_types: Optional[Tuple[str, ...]] = None,
) -> List[Dict[str, Any]]:
    """
    ds_learning_results'ta hibrit arama (tablo/şema bağlamı).
    Sadece is_valid = TRUE kayıtlar.
    """
    has_vector = _detect_pgvector(cur)
    use_semantic = has_vector and query_embedding is not None
    tsq = _clean_query(query_text)
    has_lex = bool(tsq)

    params: List[Any] = []

    if use_semantic:
        sem_select = "(1 - (embedding <=> %s::vector))"
        params.append(query_embedding)
    else:
        sem_select = "0.0::float"

    if has_lex:
        lex_select = "COALESCE(ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %s)), 0)"
        params.append(tsq)
    else:
        lex_select = "0.0::float"

    where = ["source_id = %s", "is_valid = TRUE"]
    params.append(source_id)
    if content_types:
        where.append("content_type = ANY(%s)")
        params.append(list(content_types))
    if has_lex:
        where.append("tsv @@ plainto_tsquery('pg_catalog.simple', %s)")
        params.append(tsq)

    sql = f"""
        WITH scored AS (
            SELECT
                id, content_type, content_text, metadata, score,
                {sem_select} AS semantic_score,
                {lex_select} AS lexical_score
            FROM ds_learning_results
            WHERE {' AND '.join(where)}
        )
        SELECT *,
               ({alpha} * semantic_score + {beta} * lexical_score) AS hybrid_score
          FROM scored
         ORDER BY hybrid_score DESC
         LIMIT %s
    """
    params.append(limit)

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        logger.error("[Hybrid] search_learning_results hata: %s", e)
        return []

    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "content_type": r["content_type"],
            "content_text": r["content_text"],
            "metadata": r["metadata"],
            "stored_score": float(r["score"] or 0.0),
            "semantic_score": float(r["semantic_score"] or 0.0),
            "lexical_score": float(r["lexical_score"] or 0.0),
            "hybrid_score": float(r["hybrid_score"] or 0.0),
        })
    return out


def search_combined(
    cur,
    source_id: int,
    query_text: str,
    query_embedding: Optional[List[float]] = None,
    table_limit: int = 5,
    column_limit: int = 15,
    alpha: float = ALPHA_SEMANTIC,
    beta: float = BETA_LEXICAL,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Tek çağrıda tablo + kolon hibrit ataması.

    Returns:
        {"tables": [...], "columns": [...]}
    """
    tables = search_learning_results(
        cur, source_id, query_text, query_embedding,
        limit=table_limit, alpha=alpha, beta=beta,
        content_types=("schema_record",),
    )
    columns = search_columns(
        cur, source_id, query_text, query_embedding,
        limit=column_limit, alpha=alpha, beta=beta,
    )
    return {"tables": tables, "columns": columns}
