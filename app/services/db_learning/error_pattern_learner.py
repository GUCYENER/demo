"""VYRA v3.29.4 — Error Pattern Learner (Faz 6 G5).

self_heal node SQL hatalarını burada loglar; benzer soru-hata kombosu için
LLM'e "geçen sefer aynı hata almıştın → şu düzeltme" ipucu üretir.
3+ kez tekrar eden hatalar admin queue'ya alınır.

Public API:
    classify_error(category: str) -> str  # self_heal kategorisi → error_class
    record_failure(cur, *, source_id, company_id, question, failed_sql,
                   error_class, error_message=None) -> Dict
    suggest_fix(cur, *, source_id, question, error_class) -> Optional[Dict]
    mark_corrected(cur, failure_id, corrected_sql) -> None
    admin_approve(cur, failure_id, pattern_hint=None) -> None
    review_queue(cur, *, min_recurrence=3, limit=20) -> List[Dict]

`failure_signature` = SHA1(normalize(question) + '|' + error_class) — UNIQUE key.
record_failure idempotent: aynı imza için recurrence_count++ ve last_seen_at=NOW.

Mantık: corrected_sql admin_approved=FALSE iken yalnız LLM retry HINT'i olarak
verilir, asla few-shot pool'a girmez (zehirli pattern koruması).
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# self_heal kategori → DB error_class eşlemesi
_CATEGORY_MAP: Dict[str, str] = {
    "SYNTAX": "syntax",
    "SCHEMA": "missing_table",   # ham + amb_column union; suggest_fix daha sonra refine eder
    "SEMANTIC": "semantic",
    "PERMISSION": "permission",
    "TIMEOUT": "timeout",
    "UNKNOWN": "unknown",
}

# Boş sonuç hatası tipini ham mesajdan tespit (self_heal'in göremediği)
_AMB_COLUMN_RE = re.compile(r"ambiguous|amb_column|column reference .* is ambiguous", re.IGNORECASE)
_MISSING_TABLE_RE = re.compile(r"relation .* does not exist|undefined table|invalid object name|ORA-00942", re.IGNORECASE)
_EMPTY_RESULT_RE = re.compile(r"no rows|empty result|row_count=0", re.IGNORECASE)
_MIN_RECURRENCE_FOR_REVIEW = 3
_MAX_HINT_LEN = 240


def classify_error(category: str, error_message: Optional[str] = None) -> str:
    """self_heal kategorisi + ham mesaj → DB error_class.

    Mesajdan AMB_COLUMN / MISSING_TABLE ayrımı yapılır (SCHEMA fallback'i refine).
    """
    cat = (category or "").upper()
    base = _CATEGORY_MAP.get(cat, "unknown")
    msg = error_message or ""
    if base == "missing_table":
        if _AMB_COLUMN_RE.search(msg):
            return "amb_column"
        if _MISSING_TABLE_RE.search(msg):
            return "missing_table"
        # SCHEMA olup spesifik regex bulamadıysak hâlâ missing_table
        return "missing_table"
    if base == "unknown" and msg and _EMPTY_RESULT_RE.search(msg):
        return "empty"
    return base


def _normalize_question(q: str) -> str:
    """Lowercase + collapse whitespace + Turkish-safe normalize (basit)."""
    q = (q or "").strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q


def _signature(question: str, error_class: str) -> str:
    norm = _normalize_question(question)
    raw = f"{norm}|{error_class}".encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()


def record_failure(
    cur,
    *,
    source_id: int,
    company_id: int,
    question: str,
    failed_sql: str,
    error_class: str,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Yeni hata yaz veya recurrence_count++ (UPSERT).

    Returns:
        {"status": "inserted"|"recurred"|"error",
         "id": int|None,
         "recurrence_count": int,
         "needs_review": bool}
    """
    if not question or not failed_sql or not error_class:
        return {"status": "error", "error": "missing_required_fields"}
    sig = _signature(question, error_class)
    q_norm = _normalize_question(question)
    msg = (error_message or "")[:1000]
    try:
        cur.execute(
            """
            INSERT INTO learned_query_failures
              (source_id, company_id, question, question_normalized,
               failed_sql, error_class, error_message, failure_signature)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, failure_signature)
              DO UPDATE SET
                recurrence_count = learned_query_failures.recurrence_count + 1,
                last_seen_at = NOW(),
                error_message = COALESCE(EXCLUDED.error_message, learned_query_failures.error_message),
                failed_sql = EXCLUDED.failed_sql
            RETURNING id, recurrence_count, (xmax = 0) AS inserted
            """,
            (source_id, company_id, question, q_norm,
             failed_sql, error_class, msg, sig),
        )
        row = cur.fetchone()
        if not row:
            return {"status": "error", "error": "no_returning_row"}
        # row: (id, recurrence_count, inserted_bool)
        fid = int(row[0] if not hasattr(row, "get") else row["id"])
        rc = int(row[1] if not hasattr(row, "get") else row["recurrence_count"])
        inserted = bool(row[2] if not hasattr(row, "get") else row["inserted"])
        return {
            "status": "inserted" if inserted else "recurred",
            "id": fid,
            "recurrence_count": rc,
            "needs_review": rc >= _MIN_RECURRENCE_FOR_REVIEW,
        }
    except Exception as e:
        logger.warning("[error_learner.record] %s", e)
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}


def suggest_fix(
    cur,
    *,
    source_id: int,
    question: str,
    error_class: str,
) -> Optional[Dict[str, Any]]:
    """Aynı imza için daha önce kaydedilmiş düzeltme/hint var mı?

    Returns:
        {"pattern_hint": str, "corrected_sql": str|None,
         "recurrence_count": int, "admin_approved": bool} or None
    """
    if not question or not error_class:
        return None
    sig = _signature(question, error_class)
    try:
        cur.execute(
            """
            SELECT id, pattern_hint, corrected_sql, recurrence_count, admin_approved
            FROM learned_query_failures
            WHERE source_id = %s AND failure_signature = %s
            LIMIT 1
            """,
            (source_id, sig),
        )
        row = cur.fetchone()
        if not row:
            return None
        def _g(k, idx):
            if hasattr(row, "get"):
                return row.get(k)
            return row[idx]
        hint = _g("pattern_hint", 1) or None
        corrected = _g("corrected_sql", 2) or None
        rc = int(_g("recurrence_count", 3) or 1)
        approved = bool(_g("admin_approved", 4))
        if not hint and not corrected:
            return None
        out_hint = hint or ""
        # Admin onaylı corrected_sql varsa hint'e ekle (LLM görür)
        if approved and corrected:
            snippet = corrected.strip().replace("\n", " ")
            if len(snippet) > _MAX_HINT_LEN:
                snippet = snippet[:_MAX_HINT_LEN] + "..."
            out_hint = (
                (out_hint + " | ") if out_hint else ""
            ) + f"Önceden başarılı düzeltme: {snippet}"
        return {
            "pattern_hint": out_hint[:_MAX_HINT_LEN] or None,
            "corrected_sql": corrected if approved else None,
            "recurrence_count": rc,
            "admin_approved": approved,
        }
    except Exception as e:
        logger.debug("[error_learner.suggest] %s", e)
        return None


def mark_corrected(cur, failure_id: int, corrected_sql: str) -> None:
    """LLM retry başarılı olduğunda — corrected_sql kaydedilir.

    NOT: admin_approved=FALSE kalır; few-shot'a girmez, sadece hint olarak verilir.
    """
    if not corrected_sql:
        return
    try:
        cur.execute(
            """
            UPDATE learned_query_failures
            SET corrected_sql = %s,
                corrected_at = NOW()
            WHERE id = %s
            """,
            (corrected_sql, int(failure_id)),
        )
    except Exception as e:
        logger.warning("[error_learner.mark_corrected] %s", e)


def admin_approve(cur, failure_id: int, pattern_hint: Optional[str] = None) -> None:
    """Admin tarafından onaylanan düzeltme — few-shot'a girebilir."""
    try:
        cur.execute(
            """
            UPDATE learned_query_failures
            SET admin_approved = TRUE,
                pattern_hint = COALESCE(%s, pattern_hint)
            WHERE id = %s
            """,
            (pattern_hint, int(failure_id)),
        )
    except Exception as e:
        logger.warning("[error_learner.admin_approve] %s", e)


def review_queue(cur, *, min_recurrence: int = _MIN_RECURRENCE_FOR_REVIEW, limit: int = 20) -> List[Dict[str, Any]]:
    """Tekrarlama eşiğini geçen, admin'in incelemesi için bekleyen hatalar."""
    try:
        cur.execute(
            """
            SELECT id, source_id, question, error_class, error_message,
                   recurrence_count, corrected_sql, admin_approved,
                   last_seen_at, created_at
            FROM learned_query_failures
            WHERE recurrence_count >= %s
              AND admin_approved = FALSE
            ORDER BY recurrence_count DESC, last_seen_at DESC
            LIMIT %s
            """,
            (int(min_recurrence), int(limit)),
        )
        rows = cur.fetchall() or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            def _g(k, idx):
                if hasattr(r, "get"):
                    return r.get(k)
                return r[idx]
            out.append({
                "id": int(_g("id", 0)),
                "source_id": int(_g("source_id", 1) or 0),
                "question": _g("question", 2) or "",
                "error_class": _g("error_class", 3) or "unknown",
                "error_message": _g("error_message", 4),
                "recurrence_count": int(_g("recurrence_count", 5) or 1),
                "corrected_sql": _g("corrected_sql", 6),
                "admin_approved": bool(_g("admin_approved", 7)),
                "last_seen_at": _g("last_seen_at", 8),
                "created_at": _g("created_at", 9),
            })
        return out
    except Exception as e:
        logger.debug("[error_learner.review_queue] %s", e)
        return []


__all__ = [
    "classify_error",
    "record_failure",
    "suggest_fix",
    "mark_corrected",
    "admin_approve",
    "review_queue",
]
