"""
self_heal — Faz 4d
==================
SQL validation/execution hatalarını sınıflandırır ve retry stratejisi seçer.

Hata kategorileri:
    SYNTAX        — parser/grammar hatası (LLM yeniden üretir, hata tracebackini gör)
    SCHEMA        — bilinmeyen tablo/kolon (retrieve fazına geri dönüş düşünülebilir;
                    Faz 4'te: bağlama "Bilinmiyor: X" hint ekle, LLM yeniden dener)
    PERMISSION    — RLS / privilege (kullanıcıya dönülmeli, retry boş)
    SEMANTIC      — JOIN missing, agg type mismatch (LLM hint ile yeniden dener)
    TIMEOUT       — sorgu çok yavaş (LIMIT ekle / WHERE daralt önerisi)
    UNKNOWN       — fallback

Routing kararı:
    - PERMISSION → 'abort' (kullanıcıya bildir, retry yok)
    - TIMEOUT    → 'rewrite' (LIMIT/WHERE hint ile retry, 1 kez)
    - SYNTAX/SCHEMA/SEMANTIC → 'retry' (retry_count < 2)
    - UNKNOWN    → 'retry' (retry_count < 1)

Hint üretimi:
    classify_error() bir kategori + LLM'e gönderilecek "ipucu mesajı" döner.
    sql_generate node bu hint'i prompt'a "Önceki hata: ..." satırı olarak ekler.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging
import re

logger = logging.getLogger(__name__)

# Sınıflandırma anahtar kelimeleri (regex pattern → kategori)
_PATTERNS: List[Tuple[str, str]] = [
    # PostgreSQL — daha spesifik SEMANTIC pattern'ler önce
    (r"operator does not exist|type mismatch|cannot cast|invalid input syntax", "SEMANTIC"),
    (r"aggregate function|group by|missing FROM-clause|ambiguous", "SEMANTIC"),
    (r"syntax error|unterminated|unexpected token|near \"", "SYNTAX"),
    (r"relation .* does not exist|undefined table|undefined column", "SCHEMA"),
    (r"column .* does not exist|invalid reference|undefined function", "SCHEMA"),
    (r"permission denied|insufficient privilege|role .* cannot|RLS|row-level security", "PERMISSION"),
    (r"canceling statement due to statement timeout|query.*timeout|deadline exceeded", "TIMEOUT"),
    # Oracle
    (r"ORA-00942|table or view does not exist", "SCHEMA"),
    (r"ORA-00904|invalid identifier", "SCHEMA"),
    (r"ORA-00936|missing expression", "SYNTAX"),
    (r"ORA-01017|invalid username/password", "PERMISSION"),
    (r"ORA-01031|insufficient privileges", "PERMISSION"),
    (r"ORA-01013|user requested cancel", "TIMEOUT"),
    # MSSQL
    (r"Msg 102|Msg 156|Incorrect syntax near", "SYNTAX"),
    (r"Msg 208|Invalid object name", "SCHEMA"),
    (r"Msg 207|Invalid column name", "SCHEMA"),
    (r"Msg 229|permission was denied", "PERMISSION"),
    # MySQL
    (r"ERROR 1064|You have an error in your SQL syntax", "SYNTAX"),
    (r"ERROR 1146|doesn't exist", "SCHEMA"),
    (r"ERROR 1054|Unknown column", "SCHEMA"),
    (r"ERROR 1142|command denied", "PERMISSION"),
]


CATEGORY_HINTS = {
    "SYNTAX": "Önceki denemede SQL sözdizimi hatası: {msg}. Lütfen dialect '{dialect}' kurallarına uygun, doğru sözdizimi ile yeniden yaz.",
    "SCHEMA": "Önceki denemede bilinmeyen tablo veya kolon hatası: {msg}. Sadece şemada listelenen tablo/kolonları kullan. Şüpheli ise daha emin olduğun tabloyu seç.",
    "PERMISSION": "Yetkisiz erişim — sorgu kullanıcıya iade edilmeli.",
    "SEMANTIC": "Önceki denemede anlamsal hata: {msg}. JOIN koşullarını, tip dönüşümlerini ve GROUP BY listesini gözden geçir.",
    "TIMEOUT": "Önceki sorgu zaman aşımına uğradı. LIMIT 100 ekle veya WHERE filtresini daralt.",
    "UNKNOWN": "Önceki denemede bilinmeyen hata: {msg}. Daha basit bir yaklaşımla yeniden dene.",
}


def classify_error(error_message: str) -> str:
    """Hata mesajından kategori çıkar."""
    if not error_message:
        return "UNKNOWN"
    msg_lower = error_message.lower()
    msg_orig = error_message
    for pattern, category in _PATTERNS:
        try:
            if re.search(pattern, msg_orig, re.IGNORECASE):
                return category
        except Exception:
            continue
    # Lower-case fallback
    if "syntax" in msg_lower:
        return "SYNTAX"
    if "not exist" in msg_lower or "unknown" in msg_lower or "invalid" in msg_lower:
        return "SCHEMA"
    if "permission" in msg_lower or "denied" in msg_lower or "privilege" in msg_lower:
        return "PERMISSION"
    if "timeout" in msg_lower or "cancel" in msg_lower:
        return "TIMEOUT"
    return "UNKNOWN"


def build_retry_hint(category: str, error_message: str, dialect: str = "postgresql") -> str:
    """LLM prompt'una eklenecek hint mesajı."""
    template = CATEGORY_HINTS.get(category, CATEGORY_HINTS["UNKNOWN"])
    return template.format(msg=(error_message or "")[:200], dialect=dialect)


def decide_retry_action(state: Dict[str, Any], category: str) -> str:
    """
    Routing kararı:
        - 'abort'   → kullanıcıya dön (permission)
        - 'rewrite' → LLM'i hint ile yeniden çağır (syntax/schema/semantic/timeout)
        - 'execute' → son denemedeyiz, kullanıcıya hata göster
    """
    retry_count = int(state.get("retry_count", 0))

    if category == "PERMISSION":
        return "abort"

    # TIMEOUT için sadece 1 kez retry
    if category == "TIMEOUT":
        return "rewrite" if retry_count < 1 else "execute"

    # UNKNOWN için 1 kez retry (sallayıp durmaya değmez)
    if category == "UNKNOWN":
        return "rewrite" if retry_count < 1 else "execute"

    # SYNTAX/SCHEMA/SEMANTIC için 2 retry
    return "rewrite" if retry_count < 2 else "execute"


def self_heal_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validation veya execute sonrası çağrılır.
    State delta:
        - error_category: sınıflandırma sonucu
        - error_class: DB error_class (G5 — syntax/missing_table/amb_column/…)
        - retry_hint: LLM'e gönderilecek ipucu (sql_generate okur)
        - retry_action: 'abort' | 'rewrite' | 'execute'
        - retry_count: rewrite ise +1
        - failure_log_id: learned_query_failures.id (G5 — telemetry)

    v3.29.4 G5: Hatalar `learned_query_failures` tablosuna kaydedilir; daha önce
    kayıtlı pattern_hint/corrected_sql varsa retry_hint zenginleştirilir.
    """
    errors = state.get("validation_errors") or state.get("errors") or []
    if not errors:
        # Hata yok — pass-through
        return {"retry_action": "execute"}

    # Son hata mesajını al
    last_err = str(errors[-1]) if errors else ""
    category = classify_error(last_err)
    dialect = state.get("db_dialect", "postgresql")
    hint = build_retry_hint(category, last_err, dialect)
    action = decide_retry_action(state, category)

    out: Dict[str, Any] = {
        "error_category": category,
        "retry_hint": hint,
        "retry_action": action,
    }
    if action == "rewrite":
        out["retry_count"] = int(state.get("retry_count", 0)) + 1

    # v3.29.4 G5 — Error pattern learning (best-effort)
    cur = state.get("_cursor")
    source_id = state.get("source_id")
    company_id = state.get("company_id")
    question = state.get("question") or ""
    failed_sql = state.get("sql") or ""
    if cur is not None and source_id and company_id and question and failed_sql:
        try:
            from app.services.db_learning.error_pattern_learner import (
                classify_error as _classify_db,
                record_failure,
                suggest_fix,
            )
            error_class = _classify_db(category, last_err)
            out["error_class"] = error_class

            # Önce mevcut pattern_hint var mı? — varsa retry_hint'i zenginleştir
            existing = suggest_fix(
                cur, source_id=source_id,
                question=question, error_class=error_class,
            )
            if existing and existing.get("pattern_hint"):
                out["retry_hint"] = (
                    (out["retry_hint"] or "") + "\n[Geçmiş pattern] " + existing["pattern_hint"]
                )

            # Failure'ı log + UPSERT (recurrence)
            rec = record_failure(
                cur,
                source_id=source_id, company_id=company_id,
                question=question, failed_sql=failed_sql,
                error_class=error_class, error_message=last_err,
            )
            if rec.get("id"):
                out["failure_log_id"] = rec["id"]
            if rec.get("needs_review"):
                out["needs_admin_review"] = True
        except Exception as exc:
            logger.debug("[self_heal] error pattern learning skipped: %s", exc)

    return out


def route_after_self_heal(state: Dict[str, Any]) -> str:
    """
    LangGraph conditional edge.
        - 'abort'   → END (kullanıcıya bildir)
        - 'rewrite' → sql_generate
        - 'execute' → execute
    """
    action = state.get("retry_action", "execute")
    if action == "abort":
        return "abort"
    if action == "rewrite":
        return "sql_generate"
    return "execute"
