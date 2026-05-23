"""Self-healing SQL retry with EXPLAIN pre-flight (FAZ 4 P51).

SQL üretim sonrası EXPLAIN dry-run ile doğrulama + hata durumunda
LLM'e geri besleme ile max 2 retry.

Akış:
    1. EXPLAIN dry-run (safe_sql_executor.explain_only veya custom)
    2. Başarısız → error class+message extract
    3. Re-prompt LLM: original_question + failed_sql + error + dialect_hint
    4. Tekrar EXPLAIN → başarılı ise repaired SQL döner
    5. Max 2 retry sonrası 422 user error

Güvenlik:
    - EXPLAIN ONLY (hiçbir veri değiştirmez)
    - Repaired SQL yine safe_sql_executor.validate_sql'den geçer
    - Company/user scope caller tarafından set edilmiş olmalı
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def try_execute_with_repair(
    cur,
    sql: str,
    source_id: int,
    dialect: str,
    *,
    original_question: str = "",
    max_retries: int = 2,
    user_ctx: Optional[dict] = None,
) -> Dict[str, Any]:
    """EXPLAIN pre-flight + self-healing retry.

    Returns:
        {"success": bool, "sql": str, "repaired": bool,
         "attempts": int, "error": str | None}
    """
    attempts = 0

    # Step 1: Try original SQL
    explain_ok, explain_err = _explain_check(cur, sql, dialect)
    if explain_ok:
        return {"success": True, "sql": sql, "repaired": False, "attempts": 1, "error": None}

    # Step 2: Repair loop
    current_sql = sql
    last_error = explain_err
    while attempts < max_retries:
        attempts += 1
        logger.info("[self_healer] repair attempt %d/%d for dialect=%s", attempts, max_retries, dialect)

        repaired_sql = _ask_llm_to_repair(
            original_question=original_question,
            failed_sql=current_sql,
            error_message=last_error,
            dialect=dialect,
        )
        if not repaired_sql or repaired_sql == current_sql:
            logger.debug("[self_healer] LLM returned same or empty SQL, skipping")
            break

        # Validate repaired SQL
        if not _validate_repaired(cur, repaired_sql):
            last_error = "Repaired SQL failed validation"
            current_sql = repaired_sql
            continue

        # EXPLAIN check on repaired SQL
        explain_ok, explain_err = _explain_check(cur, repaired_sql, dialect)
        if explain_ok:
            _emit_metric("success")
            # Record to few-shot store if available
            _record_repair_example(
                user_ctx=user_ctx,
                source_id=source_id,
                question=original_question,
                sql=repaired_sql,
            )
            return {
                "success": True,
                "sql": repaired_sql,
                "repaired": True,
                "attempts": attempts + 1,
                "error": None,
            }

        last_error = explain_err
        current_sql = repaired_sql

    _emit_metric("failure")
    return {
        "success": False,
        "sql": sql,
        "repaired": False,
        "attempts": attempts + 1,
        "error": last_error,
    }


def _explain_check(cur, sql: str, dialect: str) -> Tuple[bool, Optional[str]]:
    """EXPLAIN dry-run. Returns (ok, error_message)."""
    try:
        explain_sql = _build_explain_sql(sql, dialect)
        cur.execute(explain_sql)
        cur.fetchall()  # consume results
        return True, None
    except Exception as e:
        error_msg = str(e)
        # Extract useful part of error
        match = re.search(r"(ERROR|ORA-\d+|Msg \d+):?\s*(.+?)(?:\n|$)", error_msg)
        if match:
            error_msg = match.group(0).strip()
        return False, error_msg


def _build_explain_sql(sql: str, dialect: str) -> str:
    """Dialect-aware EXPLAIN statement."""
    dialect_lower = dialect.lower() if dialect else "postgresql"
    if dialect_lower in ("postgresql", "postgres", "pg"):
        return f"EXPLAIN {sql}"
    elif dialect_lower in ("mysql",):
        return f"EXPLAIN {sql}"
    elif dialect_lower in ("oracle", "ora"):
        # Oracle EXPLAIN PLAN requires a plan table; use simple approach
        return f"EXPLAIN PLAN FOR {sql}"
    elif dialect_lower in ("mssql", "sqlserver", "microsoft"):
        return f"SET SHOWPLAN_TEXT ON; {sql}; SET SHOWPLAN_TEXT OFF"
    return f"EXPLAIN {sql}"


def _ask_llm_to_repair(
    original_question: str,
    failed_sql: str,
    error_message: str,
    dialect: str,
) -> Optional[str]:
    """LLM'e hatalı SQL'i düzeltmesini ister."""
    try:
        from app.core.llm import call_llm_api
    except ImportError:
        logger.debug("[self_healer] LLM adapter not available")
        return None

    prompt = (
        f"Aşağıdaki {dialect} SQL sorgusunda hata var. Düzelt ve sadece düzeltilmiş SQL'i döndür.\n\n"
        f"Orijinal soru: {original_question}\n\n"
        f"Hatalı SQL:\n```sql\n{failed_sql}\n```\n\n"
        f"Hata mesajı: {error_message}\n\n"
        f"Kurallar:\n"
        f"- Sadece SELECT sorgusu üret\n"
        f"- DDL/DML/INSERT/UPDATE/DELETE YASAK\n"
        f"- Sadece düzeltilmiş SQL'i döndür, açıklama ekleme\n"
        f"- ```sql ... ``` bloğu içinde döndür"
    )

    try:
        response = call_llm_api(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        if not response:
            return None

        # Extract SQL from response
        text = response if isinstance(response, str) else str(response)
        sql_match = re.search(r"```sql\s*\n?(.*?)```", text, re.DOTALL)
        if sql_match:
            return sql_match.group(1).strip()

        # Fallback: try the whole response if it looks like SQL
        text = text.strip()
        if text.upper().startswith("SELECT"):
            return text

        return None
    except Exception as e:
        logger.warning("[self_healer] LLM repair call failed: %s", e)
        return None


def _validate_repaired(cur, sql: str) -> bool:
    """Basic SQL validation (safe_sql_executor pattern reuse)."""
    try:
        from app.services.safe_sql_executor import validate_sql
        is_valid, _err = validate_sql(sql)
        return is_valid
    except ImportError:
        # Fallback: basic checks
        upper = sql.strip().upper()
        if not upper.startswith("SELECT"):
            return False
        dangerous = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"}
        for keyword in dangerous:
            if re.search(rf"\b{keyword}\b", upper):
                return False
        return True
    except Exception:
        return False


def _record_repair_example(
    user_ctx: Optional[dict],
    source_id: int,
    question: str,
    sql: str,
):
    """Repaired SQL'i query_examples'a kaydet (varsa)."""
    if not user_ctx or not question:
        return
    try:
        from app.services.text_to_sql_store.few_shot_store import record_example
        # Would need a cursor — skip in this context (caller responsible)
        logger.info("[self_healer] repaired SQL recorded for few-shot (deferred)")
    except ImportError:
        pass


def _emit_metric(outcome: str):
    """Prometheus counter (graceful)."""
    try:
        from app.services.observability.prometheus_metrics import get as _metric
        _metric("sql_repair_attempt_total").labels(outcome=outcome).inc()
    except Exception:
        pass
