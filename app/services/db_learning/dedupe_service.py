"""VYRA v3.27.0 — Dedupe Service (G3 + G1 + G4 ortak).

3 katmanlı duplicate tespiti:

  Layer 1 — SHA256 canonical SQL exact match
            (DB UNIQUE constraint: learned_db_queries.sql_hash)
  Layer 2 — cosine(question_embedding) >= 0.92
            (anlamsal duplicate: aynı soru farklı kelimelerle)
  Layer 3 — Jaccard(schema_signature_tokens) >= 0.85
            (aynı tablolar/kolonlar üzerinde işlem)

Kural: Bir kayıt INSERT öncesi 3 katmanı sırayla kontrol et. Eşleşme bulursa
mevcut kaydı GERİ DÖN (yeni INSERT yapma); caller hit_count++ yapar.

DİKKAT: Layer 2 ve 3 SQL içinde değil Python tarafında hesaplanır (psycopg2
DictCursor üzerinden); pgvector cosine için DB-side karşılaştırma kullanılır.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

import logging

logger = logging.getLogger(__name__)

# ============================================================
# Eşikler — değiştirilirse plan dosyasında da güncelle
# ============================================================
COSINE_DUP_THRESHOLD = 0.92        # Layer 2 — anlamsal dup
JACCARD_DUP_THRESHOLD = 0.85       # Layer 3 — schema dup
# pgvector cosine distance ile karşılaştırma: distance = 1 - cosine_similarity
# similarity >= 0.92  ↔  distance <= 0.08
COSINE_DUP_MAX_DISTANCE = 1.0 - COSINE_DUP_THRESHOLD


# ============================================================
# Yardımcılar
# ============================================================

_WS_RE = re.compile(r"\s+")
_QUOTE_RE = re.compile(r'["`\[\]]')
_PARAM_RE = re.compile(r"%\([a-zA-Z_][a-zA-Z_0-9]*\)s|%s|\?|\$\d+")


def canonicalize_sql(sql: str) -> str:
    """SQL'i kanonik forma getir (whitespace + quoting + identifier normalize).

    Bu fonksiyon dialect-agnostic — string literal ve değer değişikliği
    sadece SQL_HASH eşitliğini bozmamalı. Yani 'WHERE id=1' ile 'WHERE id=2'
    AYNI hash döner (literal'ler maskelenir).
    """
    if not sql:
        return ""
    s = sql.strip().lower()
    # String literal'leri tek place-holder ile değiştir (basit; nested quote için sınırlı)
    s = re.sub(r"'([^']|'')*'", "'?'", s)
    # Sayı literal'leri
    s = re.sub(r"\b\d+(\.\d+)?\b", "?", s)
    # Parametre placeholder normalize
    s = _PARAM_RE.sub("?", s)
    # Quoting karakterleri kaldır
    s = _QUOTE_RE.sub("", s)
    # Whitespace tek boşluğa
    s = _WS_RE.sub(" ", s)
    # Trailing ; varsa kaldır
    s = s.rstrip(";").strip()
    return s


def sql_hash(sql: str) -> str:
    """Kanonik SQL'in SHA256 hex (64 char). DB UNIQUE constraint ile uyumlu."""
    canon = canonicalize_sql(sql)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def normalize_question(question: str) -> str:
    """Sorgu normalizasyonu — Türkçe lowercase + noktalama + whitespace temizliği."""
    if not question:
        return ""
    s = question.strip().lower()
    # Türkçe karakter koruması (İ, I farkı için manual)
    s = s.replace("İ", "i").replace("I", "ı")
    s = re.sub(r"[^\w\sçğıöşüâîû]", " ", s, flags=re.UNICODE)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _tokenize_signature(signature: Optional[str]) -> set:
    """schema_signature'i tokenize et — virgül + nokta + alt-çizgi ayrımı.

    Örnek: 'sales.orders,sales.customers' →
           {'sales', 'orders', 'customers'}
    """
    if not signature:
        return set()
    parts = re.split(r"[,.\s_]+", signature.lower())
    return {p for p in parts if p and len(p) > 1}


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard similarity — iki set arası kesişim/birleşim oranı."""
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union)


def build_schema_signature(tables: Iterable[str]) -> str:
    """Sorgu adaylarından alfabetik sıralı schema_signature üret.

    Input: ['sales.orders', 'public.customers']
    Output: 'public.customers,sales.orders'
    """
    cleaned = sorted({t.strip().lower() for t in tables if t and t.strip()})
    return ",".join(cleaned)


# ============================================================
# Ana dedupe API
# ============================================================

@dataclass
class DuplicateMatch:
    """Eşleşme bulundu — caller bunu kullanarak hit_count++ yapar."""
    existing_id: int
    layer: int           # 1, 2, 3
    similarity: float    # 1.0 (Layer 1) / cosine (L2) / jaccard (L3)
    reason: str          # 'sql_hash' / 'embedding_cosine' / 'schema_jaccard'


def check_duplicate(
    cur,
    source_id: int,
    sql: str,
    question: str,
    schema_signature: Optional[str] = None,
    question_embedding: Optional[List[float]] = None,
    table: str = "learned_db_queries",
) -> Optional[DuplicateMatch]:
    """3 katmanlı dedupe kontrolü.

    Args:
        cur: psycopg2 DictCursor (RLS context: app.current_company_id set olmalı)
        source_id: data_sources.id
        sql: Aday SQL (canonical değil; normalize edilecek)
        question: Aday soru metni
        schema_signature: 'schema.table' csv (build_schema_signature ile)
        question_embedding: 384-d float list (None ise Layer 2 atlanır)
        table: 'learned_db_queries' (default) veya başka dedupe edilen tablo

    Returns:
        DuplicateMatch (eşleşme varsa) veya None (yeni kayıt INSERT edilebilir)
    """
    # ─── Layer 1: SQL hash exact ───────────────────────────────
    h = sql_hash(sql)
    try:
        cur.execute(
            f"SELECT id FROM {table} WHERE source_id = %s AND sql_hash = %s AND is_active = TRUE LIMIT 1",
            (source_id, h),
        )
        row = cur.fetchone()
        if row:
            existing_id = row[0] if not hasattr(row, "get") else row.get("id", row[0])
            return DuplicateMatch(existing_id=existing_id, layer=1, similarity=1.0, reason="sql_hash")
    except Exception as e:
        logger.warning("[dedupe.L1] hash lookup failed: %s", e)

    # ─── Layer 2: embedding cosine (pgvector varsa DB-side) ───
    if question_embedding is not None and len(question_embedding) > 0:
        try:
            # pgvector operator <=> = cosine distance (0 = identical)
            # Eşik: distance <= COSINE_DUP_MAX_DISTANCE (0.08)
            emb_str = "[" + ",".join(f"{x:.6f}" for x in question_embedding) + "]"
            cur.execute(
                f"""
                SELECT id, (question_embedding <=> %s::vector) AS dist
                FROM {table}
                WHERE source_id = %s
                  AND is_active = TRUE
                  AND question_embedding IS NOT NULL
                ORDER BY question_embedding <=> %s::vector
                LIMIT 1
                """,
                (emb_str, source_id, emb_str),
            )
            row = cur.fetchone()
            if row:
                existing_id = row[0] if not hasattr(row, "get") else row.get("id", row[0])
                dist = row[1] if not hasattr(row, "get") else row.get("dist", row[1])
                if dist is not None and float(dist) <= COSINE_DUP_MAX_DISTANCE:
                    similarity = 1.0 - float(dist)
                    return DuplicateMatch(
                        existing_id=existing_id,
                        layer=2,
                        similarity=similarity,
                        reason="embedding_cosine",
                    )
        except Exception as e:
            # pgvector yoksa veya float[] tip uyumsuzluğu — sessizce geç
            logger.debug("[dedupe.L2] embedding lookup skipped: %s", e)

    # ─── Layer 3: Jaccard schema_signature ─────────────────────
    if schema_signature:
        try:
            sig_tokens = _tokenize_signature(schema_signature)
            if sig_tokens:
                # Aynı source'taki tüm aktif kayıtların signature'ını Python tarafında karşılaştır
                # (DB-side Jaccard için pg_trgm gerekir, opsiyonel — burada kompakt çözüm)
                cur.execute(
                    f"""
                    SELECT id, schema_signature
                    FROM {table}
                    WHERE source_id = %s
                      AND is_active = TRUE
                      AND schema_signature IS NOT NULL
                    LIMIT 500
                    """,
                    (source_id,),
                )
                rows = cur.fetchall() or []
                best_id = None
                best_score = 0.0
                for r in rows:
                    rid = r[0] if not hasattr(r, "get") else r.get("id", r[0])
                    rsig = r[1] if not hasattr(r, "get") else r.get("schema_signature", r[1])
                    score = jaccard(sig_tokens, _tokenize_signature(rsig))
                    if score >= JACCARD_DUP_THRESHOLD and score > best_score:
                        best_id = rid
                        best_score = score
                if best_id:
                    return DuplicateMatch(
                        existing_id=best_id,
                        layer=3,
                        similarity=best_score,
                        reason="schema_jaccard",
                    )
        except Exception as e:
            logger.debug("[dedupe.L3] jaccard lookup skipped: %s", e)

    return None


def bump_hit_count(cur, table: str, row_id: int) -> None:
    """Eşleşen mevcut kaydın hit_count'ını arttır + last_used_at güncelle.

    Caller sorumluluğu: commit yap (autocommit kapalıysa).
    """
    try:
        cur.execute(
            f"""
            UPDATE {table}
            SET hit_count = hit_count + 1,
                last_used_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            (row_id,),
        )
    except Exception as e:
        logger.warning("[dedupe.bump] update failed for id=%s: %s", row_id, e)


__all__ = [
    "COSINE_DUP_THRESHOLD",
    "JACCARD_DUP_THRESHOLD",
    "canonicalize_sql",
    "sql_hash",
    "normalize_question",
    "jaccard",
    "build_schema_signature",
    "DuplicateMatch",
    "check_duplicate",
    "bump_hit_count",
]
