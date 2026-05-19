"""VYRA v3.27.0 — Synonym Auto-Learner (C.G5).

Kullanıcı sorularındaki terimler ile veritabanı kolon adları arasında orta
seviyede (0.65 ≤ cosine < 0.85) benzerlik bulunduğunda, LLM doğrulayıcısı
ile aday eşanlamı kontrol eder. Onaylanan adaylar ``synonym_suggestions``
tablosuna ``status='pending'`` olarak yazılır; admin onaylarsa kalıcı
sözlüğe aktarılır.

Limit:
  * Sadece 0.65 ≤ similarity < 0.85 dilimi (üst sınır net match, alt sınır gürültü)
  * Aynı (source_id, user_term, col_full_name) için UNIQUE → observed_count++
  * LLM çağrısı tek atış (best-effort, hata cache_miss + verdict=None)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────

SIM_LOW = 0.65
SIM_HIGH = 0.85
DEFAULT_VERDICT = "uncertain"


# ─────────────────────────────────────────────────────────────
# DTO
# ─────────────────────────────────────────────────────────────

@dataclass
class SuggestionResult:
    status: str          # 'inserted' | 'bumped' | 'skipped' | 'error'
    id: Optional[int] = None
    verdict: Optional[str] = None
    reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Eligibility
# ─────────────────────────────────────────────────────────────

def is_borderline(similarity: float) -> bool:
    """Cosine similarity 'belirsiz' diliminde mi?"""
    try:
        s = float(similarity)
    except (TypeError, ValueError):
        return False
    return SIM_LOW <= s < SIM_HIGH


# ─────────────────────────────────────────────────────────────
# LLM doğrulayıcı
# ─────────────────────────────────────────────────────────────

_VERIFY_PROMPT_TR = (
    "Aşağıdaki kullanıcı terimi ile veritabanı kolon adı bir veri sorgusunda "
    "eşanlamlı (aynı anlama gelen) mı?\n\n"
    "Kullanıcı terimi: {user_term}\n"
    "Kolon: {schema}.{table}.{column}\n\n"
    "Sadece bir kelime cevap ver: match / no_match / uncertain"
)


def _llm_verdict(
    user_term: str,
    schema: str,
    table: str,
    column: str,
    llm_callable: Optional[Callable[[str], str]],
) -> Tuple[str, Optional[str]]:
    """LLM'i tek atış sor → (verdict, rationale).

    llm_callable verilmemişse 'uncertain' döner (LLM çağrısı yapılmaz).
    """
    if llm_callable is None:
        return DEFAULT_VERDICT, None

    prompt = _VERIFY_PROMPT_TR.format(
        user_term=user_term, schema=schema or "", table=table, column=column,
    )
    try:
        raw = llm_callable(prompt) or ""
        text = str(raw).strip().lower()
        # Whitespace + punctuation kırp
        text = text.split()[0] if text else ""
        text = text.strip(".,;:!?")
        if text in ("match", "evet", "yes", "eşanlamlı", "esanlamli"):
            return "match", raw[:500]
        if text in ("no_match", "no", "hayır", "hayir", "no-match", "different"):
            return "no_match", raw[:500]
        return "uncertain", raw[:500]
    except Exception as e:
        logger.debug("[synonym.llm] err: %s", e)
        return DEFAULT_VERDICT, None


# ─────────────────────────────────────────────────────────────
# DB ops
# ─────────────────────────────────────────────────────────────

def _find_existing(
    cur,
    source_id: int,
    user_term: str,
    schema_name: Optional[str],
    table_name: str,
    column_name: str,
) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, status, observed_count
        FROM synonym_suggestions
        WHERE source_id = %s
          AND LOWER(user_term) = LOWER(%s)
          AND COALESCE(LOWER(schema_name), '') = COALESCE(LOWER(%s), '')
          AND LOWER(table_name) = LOWER(%s)
          AND LOWER(column_name) = LOWER(%s)
        LIMIT 1
        """,
        (source_id, user_term, schema_name, table_name, column_name),
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(row) if not isinstance(row, dict) else row


def _bump_observed(cur, sugg_id: int) -> None:
    cur.execute(
        """
        UPDATE synonym_suggestions
        SET observed_count = observed_count + 1,
            updated_at = NOW()
        WHERE id = %s
        """,
        (sugg_id,),
    )


def _insert_suggestion(
    cur,
    *,
    source_id: int,
    company_id: Optional[int],
    user_term: str,
    schema_name: Optional[str],
    table_name: str,
    column_name: str,
    similarity: float,
    verdict: str,
    rationale: Optional[str],
) -> Optional[int]:
    cur.execute(
        """
        INSERT INTO synonym_suggestions (
            source_id, company_id, user_term,
            schema_name, table_name, column_name,
            similarity, llm_verdict, llm_rationale, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        RETURNING id
        """,
        (
            source_id, company_id, user_term,
            schema_name, table_name, column_name,
            float(similarity), verdict, rationale,
        ),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row.get("id") if hasattr(row, "get") else row[0]


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def propose_synonym(
    cur,
    *,
    source_id: int,
    company_id: Optional[int],
    user_term: str,
    schema_name: Optional[str],
    table_name: str,
    column_name: str,
    similarity: float,
    llm_callable: Optional[Callable[[str], str]] = None,
) -> SuggestionResult:
    """Tek bir aday eşanlamı kuyruğa yazar (eligibility gate + dedupe + LLM).

    Akış:
        1. Cosine ∈ [SIM_LOW, SIM_HIGH) değilse → skip (reason='out_of_range')
        2. Aynı (source, term, kolon) varsa → observed_count++ (status korunur)
        3. LLM'e sor → verdict (match/no_match/uncertain)
        4. verdict='no_match' ise yazılmaz (gürültü) — skip (reason='llm_no_match')
        5. Aksi halde INSERT status='pending'
    """
    if not (user_term and table_name and column_name and source_id):
        return SuggestionResult(status="skipped", reason="missing_fields")
    if not is_borderline(similarity):
        return SuggestionResult(status="skipped", reason="out_of_range")

    user_term = user_term.strip()
    if not user_term:
        return SuggestionResult(status="skipped", reason="empty_term")

    try:
        existing = _find_existing(cur, source_id, user_term, schema_name, table_name, column_name)
        if existing:
            _bump_observed(cur, existing["id"])
            return SuggestionResult(status="bumped", id=existing["id"])

        verdict, rationale = _llm_verdict(user_term, schema_name or "", table_name, column_name, llm_callable)
        if verdict == "no_match":
            return SuggestionResult(status="skipped", verdict=verdict, reason="llm_no_match")

        new_id = _insert_suggestion(
            cur,
            source_id=source_id, company_id=company_id,
            user_term=user_term, schema_name=schema_name,
            table_name=table_name, column_name=column_name,
            similarity=similarity, verdict=verdict, rationale=rationale,
        )
        return SuggestionResult(status="inserted", id=new_id, verdict=verdict)
    except Exception as e:
        logger.warning("[synonym.propose] err: %s", e)
        return SuggestionResult(status="error", reason=str(e)[:200])


def list_pending(cur, source_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Admin onay kuyruğu — pending kayıtlar."""
    if source_id:
        cur.execute(
            """
            SELECT id, source_id, user_term, schema_name, table_name, column_name,
                   similarity, llm_verdict, observed_count, created_at
            FROM synonym_suggestions
            WHERE status = 'pending' AND source_id = %s
            ORDER BY observed_count DESC, created_at DESC
            LIMIT %s
            """,
            (source_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT id, source_id, user_term, schema_name, table_name, column_name,
                   similarity, llm_verdict, observed_count, created_at
            FROM synonym_suggestions
            WHERE status = 'pending'
            ORDER BY observed_count DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
    rows = cur.fetchall() or []
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def review(cur, sugg_id: int, *, decision: str, reviewer_user_id: Optional[int]) -> bool:
    """Admin kararı uygula: 'approved' | 'rejected'."""
    if decision not in ("approved", "rejected"):
        return False
    cur.execute(
        """
        UPDATE synonym_suggestions
        SET status = %s, reviewer_user_id = %s, reviewed_at = NOW(), updated_at = NOW()
        WHERE id = %s AND status = 'pending'
        """,
        (decision, reviewer_user_id, sugg_id),
    )
    return (cur.rowcount or 0) > 0


__all__ = [
    "SIM_LOW", "SIM_HIGH",
    "SuggestionResult",
    "is_borderline",
    "propose_synonym",
    "list_pending",
    "review",
]
