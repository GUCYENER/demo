"""VYRA v3.27.0 — Learned DB Queries Service (G3).

Public API:

  - lookup_cached_sql(source_id, question, ...) → CachedQuery | None
        Pipeline'in en başında çağrılır. Benzer soru (cosine ≥ threshold)
        varsa cached SQL döner → LLM bypass.

  - record_successful_query(source_id, question, sql, ...) → row_id
        Pipeline başarıyla execute olunca çağrılır. Dedupe yapar:
        eşleşme varsa hit_count++; yoksa yeni INSERT.

  - invalidate_by_table(source_id, table_name) → invalidated_count
        Schema drift detector çağırır. İlgili tabloyu kullanan tüm
        learned query'leri is_active=FALSE yapar (G6 ile entegre).

Tüm fonksiyonlar RLS uyumlu — caller mutlaka `get_db_context_scoped_company`
ile company_id set'li bir context açmış olmalı.

Embedding: app.services.rag.service.get_rag_service()._get_embedding(text)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.db_learning.dedupe_service import (
    COSINE_DUP_THRESHOLD,
    DuplicateMatch,
    build_schema_signature,
    bump_hit_count,
    check_duplicate,
    normalize_question,
    sql_hash,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Eşikler
# ─────────────────────────────────────────────────────────────
LOOKUP_COSINE_THRESHOLD = 0.85   # lookup'ta dedupe (0.92) eşiğinden daha gevşek
LOOKUP_TOPK = 5                   # tarama derinliği
TABLE_NAME = "learned_db_queries"


# ─────────────────────────────────────────────────────────────
# DTO
# ─────────────────────────────────────────────────────────────

@dataclass
class CachedQuery:
    """lookup_cached_sql döner — pipeline buradan SQL'i alıp execute eder."""
    id: int
    sql: str
    sql_hash: str
    question: str
    intent: Optional[str]
    schema_signature: Optional[str]
    columns_meta: List[Dict[str, Any]] = field(default_factory=list)
    similarity: float = 0.0
    hit_count: int = 0
    source: str = "user"  # 'user' | 'synthetic' | 'manual'


# ─────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────

def _embed_question(question: str) -> Optional[List[float]]:
    """RAG servisten embedding al. Servis yoksa None döner."""
    try:
        from app.services.rag.service import get_rag_service
        svc = get_rag_service()
        emb = svc._get_embedding(question)
        if emb and len(emb) > 0:
            return list(emb)
    except Exception as e:
        logger.debug("[learned_queries.embed] embedding failed: %s", e)
    return None


def _row_get(row, key: str, default=None):
    """RealDictCursor/tuple agnostic erişim."""
    if hasattr(row, "get"):
        return row.get(key, default)
    return default


def _vector_literal(emb: List[float]) -> str:
    """pgvector vector(384) literal — '[0.12, 0.34, ...]' formatı."""
    return "[" + ",".join(f"{x:.6f}" for x in emb) + "]"


def _detect_embedding_column_type(cur) -> str:
    """question_embedding kolonu vector mi float[] mi? (migration 021 graceful)."""
    try:
        cur.execute("""
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_name = 'learned_db_queries'
              AND column_name = 'question_embedding'
        """)
        row = cur.fetchone()
        if row:
            udt = _row_get(row, "udt_name") or (row[0] if isinstance(row, (list, tuple)) else None)
            return "vector" if udt == "vector" else "array"
    except Exception:
        pass
    return "vector"


# ─────────────────────────────────────────────────────────────
# Public — Lookup
# ─────────────────────────────────────────────────────────────

def lookup_cached_sql(
    cur,
    source_id: int,
    question: str,
    *,
    threshold: float = LOOKUP_COSINE_THRESHOLD,
    intent: Optional[str] = None,
) -> Optional[CachedQuery]:
    """Soruya benzer cached SQL var mı?

    Sıralı kontrol:
      1) Tam soru hash (question_normalized eşitliği — sub-ms)
      2) pgvector cosine search (vector kolonu varsa)
      3) Fallback: question_normalized substring (en zayıf)

    Args:
        cur: psycopg2 DictCursor (RLS scoped — caller'dan)
        source_id: data_sources.id
        question: kullanıcı sorusu
        threshold: cosine eşik (default 0.85 — dedupe 0.92'den daha gevşek)
        intent: opsiyonel intent filtresi (eşleşme şartı değil; sadece tie-break)

    Returns:
        En yüksek skorlu CachedQuery veya None.
    """
    if not question or not question.strip():
        return None

    q_norm = normalize_question(question)

    # ─── 1) Tam normalize match (cosine'a gerek yok) ──────
    try:
        cur.execute(
            f"""
            SELECT id, sql_query, sql_hash, question, intent,
                   schema_signature, columns_meta, hit_count, source
            FROM {TABLE_NAME}
            WHERE source_id = %s
              AND is_active = TRUE
              AND question_normalized = %s
            ORDER BY hit_count DESC, last_used_at DESC NULLS LAST
            LIMIT 1
            """,
            (source_id, q_norm),
        )
        row = cur.fetchone()
        if row:
            return _row_to_cached(row, similarity=1.0)
    except Exception as e:
        logger.warning("[learned_queries.lookup.exact] %s", e)

    # ─── 2) pgvector cosine search ────────────────────────
    emb = _embed_question(question)
    if emb is not None:
        emb_col_type = _detect_embedding_column_type(cur)
        try:
            if emb_col_type == "vector":
                lit = _vector_literal(emb)
                cur.execute(
                    f"""
                    SELECT id, sql_query, sql_hash, question, intent,
                           schema_signature, columns_meta, hit_count, source,
                           (question_embedding <=> %s::vector) AS dist
                    FROM {TABLE_NAME}
                    WHERE source_id = %s
                      AND is_active = TRUE
                      AND question_embedding IS NOT NULL
                    ORDER BY question_embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (lit, source_id, lit, LOOKUP_TOPK),
                )
                rows = cur.fetchall() or []
                best = None
                best_sim = 0.0
                for r in rows:
                    dist = _row_get(r, "dist")
                    if dist is None:
                        continue
                    sim = 1.0 - float(dist)
                    if sim < threshold:
                        continue
                    # intent tie-break — eşitse aynı intent'i tercih et
                    if best is None or sim > best_sim or (
                        intent and _row_get(r, "intent") == intent and sim >= best_sim - 0.02
                    ):
                        best = r
                        best_sim = sim
                if best is not None:
                    return _row_to_cached(best, similarity=best_sim)
            else:
                # float[] fallback — küçük tablo varsayımı, Python cosine
                cur.execute(
                    f"""
                    SELECT id, sql_query, sql_hash, question, intent,
                           schema_signature, columns_meta, hit_count, source,
                           question_embedding
                    FROM {TABLE_NAME}
                    WHERE source_id = %s
                      AND is_active = TRUE
                      AND question_embedding IS NOT NULL
                    LIMIT 500
                    """,
                    (source_id,),
                )
                rows = cur.fetchall() or []
                best = None
                best_sim = 0.0
                for r in rows:
                    cand = _row_get(r, "question_embedding") or []
                    if not cand:
                        continue
                    sim = _cosine(emb, list(cand))
                    if sim >= threshold and sim > best_sim:
                        best = r
                        best_sim = sim
                if best is not None:
                    return _row_to_cached(best, similarity=best_sim)
        except Exception as e:
            logger.debug("[learned_queries.lookup.vector] %s", e)

    # ─── 3) Fallback: FTS prefix (tsv) ────────────────────
    try:
        cur.execute(
            f"""
            SELECT id, sql_query, sql_hash, question, intent,
                   schema_signature, columns_meta, hit_count, source,
                   ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %s)) AS rk
            FROM {TABLE_NAME}
            WHERE source_id = %s
              AND is_active = TRUE
              AND tsv @@ plainto_tsquery('pg_catalog.simple', %s)
            ORDER BY rk DESC, hit_count DESC
            LIMIT 1
            """,
            (q_norm, source_id, q_norm),
        )
        row = cur.fetchone()
        if row:
            rk = _row_get(row, "rk") or 0.0
            # ts_rank tipik [0..1] aralığında — eşik düşük tutuldu
            if float(rk) >= 0.05:
                # FTS'den benzerlik çıkarımı yapma; similarity=0.0 ver,
                # caller bunu zayıf hit kabul edip kullanabilir veya atlayabilir
                return _row_to_cached(row, similarity=float(rk))
    except Exception as e:
        logger.debug("[learned_queries.lookup.fts] %s", e)

    return None


def _cosine(a: List[float], b: List[float]) -> float:
    """Saf-Python cosine (numpy yok). Boş veya boyut uyumsuzsa 0.0."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        xf = float(x)
        yf = float(y)
        dot += xf * yf
        na += xf * xf
        nb += yf * yf
    if na <= 0 or nb <= 0:
        return 0.0
    import math
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _row_to_cached(row, similarity: float) -> CachedQuery:
    """psycopg2 row → CachedQuery."""
    columns_meta = _row_get(row, "columns_meta") or []
    if isinstance(columns_meta, str):
        # JSONB bazen string olarak gelebilir (autoreg yoksa)
        import json
        try:
            columns_meta = json.loads(columns_meta)
        except Exception:
            columns_meta = []
    return CachedQuery(
        id=int(_row_get(row, "id")),
        sql=_row_get(row, "sql_query") or "",
        sql_hash=_row_get(row, "sql_hash") or "",
        question=_row_get(row, "question") or "",
        intent=_row_get(row, "intent"),
        schema_signature=_row_get(row, "schema_signature"),
        columns_meta=columns_meta if isinstance(columns_meta, list) else [],
        similarity=float(similarity),
        hit_count=int(_row_get(row, "hit_count") or 0),
        source=_row_get(row, "source") or "user",
    )


# ─────────────────────────────────────────────────────────────
# Public — Record
# ─────────────────────────────────────────────────────────────

def record_successful_query(
    cur,
    *,
    source_id: int,
    company_id: Optional[int],
    question: str,
    sql: str,
    intent: Optional[str] = None,
    tables: Optional[List[str]] = None,
    columns_meta: Optional[List[Dict[str, Any]]] = None,
    result_fingerprint: Optional[str] = None,
    source: str = "user",
    created_by_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Başarılı (soru, SQL) çiftini öğren — dedupe ile.

    Return:
        {"status": "duplicate"|"inserted",
         "id": <row_id>,
         "layer": 1|2|3|None,
         "similarity": float}

    Raises:
        Asla — DB hatası loglanır ve {"status": "error", ...} döner.
    """
    if not question or not sql:
        return {"status": "skipped", "reason": "empty_input"}

    q_norm = normalize_question(question)
    schema_sig = build_schema_signature(tables or [])
    sh = sql_hash(sql)

    emb = _embed_question(question)

    # ─── Dedupe ─────────────────────────────────────────
    try:
        match = check_duplicate(
            cur,
            source_id=source_id,
            sql=sql,
            question=question,
            schema_signature=schema_sig or None,
            question_embedding=emb,
            table=TABLE_NAME,
        )
    except Exception as e:
        logger.warning("[learned_queries.record.dedupe] failed: %s", e)
        match = None

    if isinstance(match, DuplicateMatch):
        # Mevcut kayıt — hit_count++
        try:
            bump_hit_count(cur, TABLE_NAME, match.existing_id)
        except Exception as e:
            logger.warning("[learned_queries.record.bump] %s", e)
        return {
            "status": "duplicate",
            "id": match.existing_id,
            "layer": match.layer,
            "similarity": match.similarity,
            "reason": match.reason,
        }

    # ─── INSERT ─────────────────────────────────────────
    try:
        emb_lit = None
        emb_col_type = _detect_embedding_column_type(cur)
        if emb is not None:
            if emb_col_type == "vector":
                emb_lit = _vector_literal(emb)
            else:
                emb_lit = list(emb)  # float[] direct

        import json as _json
        cols_json = _json.dumps(columns_meta or [], ensure_ascii=False)

        if emb_lit is not None and emb_col_type == "vector":
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME}
                  (source_id, company_id, question, question_normalized,
                   question_embedding, sql_query, sql_hash, intent,
                   schema_signature, columns_meta, result_fingerprint,
                   source, hit_count, success_count, failure_count,
                   last_used_at, is_active, created_by_user_id)
                VALUES (%s, %s, %s, %s,
                        %s::vector, %s, %s, %s,
                        %s, %s::jsonb, %s,
                        %s, 0, 1, 0,
                        NOW(), TRUE, %s)
                ON CONFLICT (source_id, sql_hash)
                  DO UPDATE SET hit_count = {TABLE_NAME}.hit_count + 1,
                                last_used_at = NOW()
                RETURNING id
                """,
                (source_id, company_id, question, q_norm,
                 emb_lit, sql, sh, intent,
                 schema_sig or None, cols_json, result_fingerprint,
                 source, created_by_user_id),
            )
        else:
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME}
                  (source_id, company_id, question, question_normalized,
                   question_embedding, sql_query, sql_hash, intent,
                   schema_signature, columns_meta, result_fingerprint,
                   source, hit_count, success_count, failure_count,
                   last_used_at, is_active, created_by_user_id)
                VALUES (%s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s::jsonb, %s,
                        %s, 0, 1, 0,
                        NOW(), TRUE, %s)
                ON CONFLICT (source_id, sql_hash)
                  DO UPDATE SET hit_count = {TABLE_NAME}.hit_count + 1,
                                last_used_at = NOW()
                RETURNING id
                """,
                (source_id, company_id, question, q_norm,
                 emb_lit, sql, sh, intent,
                 schema_sig or None, cols_json, result_fingerprint,
                 source, created_by_user_id),
            )
        row = cur.fetchone()
        rid = _row_get(row, "id") if row else None
        if rid is None and row and isinstance(row, (list, tuple)):
            rid = row[0]
        return {"status": "inserted", "id": int(rid) if rid else None,
                "layer": None, "similarity": 1.0}
    except Exception as e:
        logger.warning("[learned_queries.record.insert] %s", e)
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Public — Failure record (caller learns from misses too)
# ─────────────────────────────────────────────────────────────

def record_failure(cur, row_id: int) -> None:
    """Cached SQL execute edildi ama hatalı sonuç döndü — failure_count++.

    Üst üste failure (örn. 3+) → is_active=FALSE yapmak caller sorumluluğunda,
    veya schema drift detector tarafından invalidate edilir.
    """
    try:
        cur.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET failure_count = failure_count + 1,
                updated_at = NOW(),
                is_active = CASE
                    WHEN failure_count + 1 >= 3 THEN FALSE
                    ELSE is_active
                END
            WHERE id = %s
            """,
            (row_id,),
        )
    except Exception as e:
        logger.warning("[learned_queries.record_failure] %s", e)


# ─────────────────────────────────────────────────────────────
# Public — Invalidation (schema drift)
# ─────────────────────────────────────────────────────────────

def invalidate_by_table(
    cur,
    source_id: int,
    table_name: str,
    schema_name: Optional[str] = None,
) -> int:
    """Schema'da değişen tabloyu kullanan tüm learned query'leri pasifle.

    Eşleşme stratejisi: schema_signature LIKE '%table%' (basit; tokenize'a
    güvenmek için Python tarafında doğrulayabiliriz ama 'invalidation safe-side'
    kuralı gereği yanlış pozitif kabul edilir — kullanıcı sorgusu tekrar
    çalışınca normalize edilip yeniden öğrenilir).

    Args:
        source_id: data_sources.id
        table_name: değişen tablo
        schema_name: opsiyonel — verilirse 'schema.table' tam eşleşme yapılır

    Returns:
        invalidate edilen satır sayısı
    """
    if not table_name:
        return 0
    needle = f"{schema_name.lower()}.{table_name.lower()}" if schema_name else table_name.lower()
    try:
        cur.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET is_active = FALSE,
                updated_at = NOW()
            WHERE source_id = %s
              AND is_active = TRUE
              AND schema_signature IS NOT NULL
              AND lower(schema_signature) LIKE %s
            """,
            (source_id, f"%{needle}%"),
        )
        # rowcount psycopg2'de mevcut
        return int(getattr(cur, "rowcount", 0) or 0)
    except Exception as e:
        logger.warning("[learned_queries.invalidate] %s", e)
        return 0


# ─────────────────────────────────────────────────────────────
# Public — Listing / Admin
# ─────────────────────────────────────────────────────────────

def list_learned_queries(
    cur,
    source_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    only_active: bool = True,
    source_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Admin sayfası için listele — newest first, hit_count azalan."""
    where = ["source_id = %s"]
    params: List[Any] = [source_id]
    if only_active:
        where.append("is_active = TRUE")
    if source_filter:
        where.append("source = %s")
        params.append(source_filter)
    where_sql = " AND ".join(where)
    params.extend([limit, offset])
    try:
        cur.execute(
            f"""
            SELECT id, question, sql_query, intent, schema_signature,
                   source, hit_count, success_count, failure_count,
                   last_used_at, created_at, is_active
            FROM {TABLE_NAME}
            WHERE {where_sql}
            ORDER BY hit_count DESC, last_used_at DESC NULLS LAST, created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        rows = cur.fetchall() or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "id": _row_get(r, "id"),
                "question": _row_get(r, "question"),
                "sql_query": _row_get(r, "sql_query"),
                "intent": _row_get(r, "intent"),
                "schema_signature": _row_get(r, "schema_signature"),
                "source": _row_get(r, "source"),
                "hit_count": _row_get(r, "hit_count"),
                "success_count": _row_get(r, "success_count"),
                "failure_count": _row_get(r, "failure_count"),
                "last_used_at": _row_get(r, "last_used_at"),
                "created_at": _row_get(r, "created_at"),
                "is_active": _row_get(r, "is_active"),
            })
        return out
    except Exception as e:
        logger.warning("[learned_queries.list] %s", e)
        return []


def deactivate(cur, row_id: int) -> bool:
    """Tek bir öğrenilmiş sorguyu pasifleştir (admin button)."""
    try:
        cur.execute(
            f"UPDATE {TABLE_NAME} SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
            (row_id,),
        )
        return int(getattr(cur, "rowcount", 0) or 0) > 0
    except Exception as e:
        logger.warning("[learned_queries.deactivate] %s", e)
        return False


__all__ = [
    "LOOKUP_COSINE_THRESHOLD",
    "TABLE_NAME",
    "CachedQuery",
    "lookup_cached_sql",
    "record_successful_query",
    "record_failure",
    "invalidate_by_table",
    "list_learned_queries",
    "deactivate",
]
