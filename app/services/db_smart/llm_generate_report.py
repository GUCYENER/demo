"""LLM-driven full-report SQL generation for the DB Smart wizard Önizleme step.

v3.36.x — F9 (Plan: 2026-05-25_0330_v336_smart_discovery_completion_v1)
Council: APOLLO (prompt + JSON validation) + POSEIDON (data flow) +
ARES (SafeSQLExecutor guard + SELECT-only validation) + HEBE (UX contract).

The Önizleme step's "▶️ Çalıştır" button posts the full wizard state (primary
table + join tables + FK context + report columns + metric + free-text user
note) to /api/db-smart/generate-report. This service asks the LLM to produce a
single dialect-aware SELECT, validates it defensively, and returns
{sql, rationale, fallback, validation_error}. The route then executes the SQL
through SafeSQLExecutor (5 s / row cap).

Design rules (mirror llm_column_order.suggest_order):
    1. NEVER raise on LLM transport failures — return a safe deterministic
       fallback (`SELECT * FROM <primary>` + dialect row-limit) with
       `fallback=True` so the UI degrades gracefully.
    2. NEVER trust the LLM output — every returned SQL is checked against:
        - SELECT/WITH start.
        - Whole-word DML/DDL blocklist (UPDATE/DELETE/INSERT/DROP/CREATE/
          ALTER/TRUNCATE/GRANT/REVOKE/MERGE/EXEC/EXECUTE/CALL).
        - Single-statement (no inner `;` after string-stripping).
       SafeSQLExecutor adds its own defense in depth at the route layer.
    3. Tenant isolation is enforced by the API layer BEFORE calling this
       service; the service still applies RLS context defensively.
    4. Token budget bounded — report_columns capped at 50, user_note 2000,
       fk_context 50 lines.
    5. Temperature pinned at 0.3 for a small amount of phrasing creativity
       without hurting determinism.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.core.db import get_db_context
from app.core.llm import (
    LLMConfigError,
    LLMConnectionError,
    LLMResponseError,
    call_llm_api,
    extract_json_obj,
)
from app.services.db_smart.rls_context import apply_vyra_user_context

logger = logging.getLogger(__name__)

# Token budget guards.
MAX_REPORT_COLUMNS = 50
MAX_FK_LINES = 50
MAX_USER_NOTE_LEN = 2000

# Whole-word DML/DDL blocklist — kept in sync with safe_sql_executor.BLOCKED_KEYWORDS
# but applied here as a fast pre-filter so we don't waste an execution attempt.
_BLOCKED_KEYWORDS = (
    "UPDATE", "DELETE", "INSERT", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "GRANT", "REVOKE", "MERGE", "EXEC", "EXECUTE", "CALL",
)
_BLOCKED_RE = re.compile(
    r"\b(" + "|".join(_BLOCKED_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Dialect → row-limit fragment used by both the prompt hint and the safe
# fallback SQL. SafeSQLExecutor.apply_row_limit will re-enforce its own cap
# regardless of what the LLM produces.
_DIALECT_LIMIT_RULES = {
    "oracle":     "FETCH FIRST {n} ROWS ONLY",
    "postgresql": "LIMIT {n}",
    "postgres":   "LIMIT {n}",
    "mysql":      "LIMIT {n}",
    "mariadb":    "LIMIT {n}",
    "mssql":      "TOP ({n})  (SELECT TOP (n) ... biçiminde)",
    "sqlserver":  "TOP ({n})  (SELECT TOP (n) ... biçiminde)",
}


# ─────────────────────────────────────────────────────────────
# Helpers — table metadata
# ─────────────────────────────────────────────────────────────

def _fetch_table_names(
    cur, source_id: int, table_ids: List[int]
) -> Dict[int, str]:
    """Return {table_id: 'schema.object_name'} for the given ids on a source.

    Mirrors llm_column_order._fetch_table_names — kept local to avoid an
    inter-module private import.
    """
    if not table_ids:
        return {}
    uniq = list({int(t) for t in table_ids})
    try:
        cur.execute(
            """
            SELECT id, schema_name, object_name
            FROM ds_db_objects
            WHERE source_id = %s AND id = ANY(%s)
            """,
            (int(source_id), uniq),
        )
        out: Dict[int, str] = {}
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                tid = row.get("id")
                schema = row.get("schema_name") or ""
                obj = row.get("object_name") or ""
            else:
                tid, schema, obj = row[0], row[1] or "", row[2] or ""
            if tid is None:
                continue
            name = f"{schema}.{obj}" if schema else str(obj)
            out[int(tid)] = name
        return out
    except Exception as e:
        logger.warning(
            "[llm_generate_report] _fetch_table_names failed source=%s ids=%s: %s",
            source_id, uniq, e,
        )
        return {}


# Bulgular3 / Review fix #3: shared balanced-brace parser (app.core.llm).
_extract_json_obj = extract_json_obj


# ─────────────────────────────────────────────────────────────
# SQL validation (SELECT-only, single statement, blocklist)
# ─────────────────────────────────────────────────────────────

def _validate_select_sql(sql: str) -> Optional[str]:
    """Return None if SQL is acceptable, else a short Turkish reason string.

    Defense in depth — SafeSQLExecutor.validate_sql also runs at the route
    layer; this stricter pre-check lets us trigger the fallback SQL path
    BEFORE wasting an execution attempt.
    """
    if not sql or not isinstance(sql, str):
        return "SQL boş döndü."
    s = sql.strip()
    if not s:
        return "SQL boş döndü."

    # Strip a single trailing semicolon (acceptable).
    if s.endswith(";"):
        s = s[:-1].rstrip()

    upper = s.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return "Yalnızca SELECT/WITH sorguları kabul edilir."

    # Blocked keywords (whole-word). Note: this is intentionally case-insensitive.
    m = _BLOCKED_RE.search(s)
    if m:
        return f"Yasak SQL komutu: {m.group(1).upper()}"

    # Multi-statement guard: strip 'string literals' then any inner ';' is bad.
    sql_no_strings = re.sub(r"'[^']*'", "", s)
    if ";" in sql_no_strings:
        return "Çoklu SQL ifadesi yasak."

    return None


# ─────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────

def _normalize_dialect(d: Optional[str]) -> str:
    return (d or "postgresql").strip().lower()


def _build_prompt(
    dialect: str,
    primary_table_name: Optional[str],
    join_table_names: List[str],
    fk_lines: List[str],
    report_columns: List[Dict[str, Any]],
    metric: Optional[Dict[str, Any]],
    user_note: str,
    limit: int,
) -> List[Dict[str, str]]:
    """Return chat-messages list for `call_llm_api`."""
    d = _normalize_dialect(dialect)
    limit_rule = _DIALECT_LIMIT_RULES.get(d, "LIMIT {n}").format(n=int(limit))

    # Report columns lines.
    col_lines: List[str] = []
    for c in (report_columns or [])[:MAX_REPORT_COLUMNS]:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        table = (c.get("table_name") or c.get("table") or "?").strip() or "?"
        stype = (c.get("semantic_type") or "?").strip() or "?"
        col_lines.append(f"- {table}.{name}  (tip: {stype})")
    if not col_lines:
        col_lines.append("- (kullanıcı kolon seçmedi — uygun bir SELECT * çalıştır)")

    # Tables block.
    tables_parts: List[str] = []
    if primary_table_name:
        tables_parts.append(f"Ana tablo: {primary_table_name}")
    if join_table_names:
        tables_parts.append("İlişkili tablolar: " + ", ".join(join_table_names))
    if not tables_parts:
        tables_parts.append("Tablo bağlamı yok.")
    tables_block = "\n".join(tables_parts)

    # FK lines.
    fk_block_lines = (fk_lines or [])[:MAX_FK_LINES]
    fk_block = (
        "FK ilişkileri:\n" + "\n".join(f"- {l}" for l in fk_block_lines)
        if fk_block_lines else "FK ilişkisi belirtilmedi."
    )

    # Metric block.
    if metric and isinstance(metric, dict):
        mk = metric.get("metric_key") or "?"
        appl = metric.get("applicable_when") or metric.get("description_tr") or ""
        # Keep small — avoid blowing the prompt with huge metric metadata.
        appl_str = str(appl)[:300]
        metric_block = (
            f"Metrik:\n- metric_key: {mk}\n- applicable_when: {appl_str or '(yok)'}"
        )
    else:
        metric_block = "Metrik: (seçilmedi)"

    # User note.
    note_clean = (user_note or "").strip()
    if len(note_clean) > MAX_USER_NOTE_LEN:
        note_clean = note_clean[:MAX_USER_NOTE_LEN]
    note_block = f'Kullanıcı talebi: "{note_clean}"' if note_clean else "Kullanıcı talebi: (boş)"

    user_prompt = (
        f"Dialect: {d}\n"
        f"Satır limiti: {int(limit)}  — Dialect kuralı: {limit_rule}\n\n"
        f"{tables_block}\n\n"
        f"{fk_block}\n\n"
        "Rapor kolonları (kullanıcı seçti):\n"
        + "\n".join(col_lines) + "\n\n"
        f"{metric_block}\n\n"
        f"{note_block}\n\n"
        "Görev: Yukarıdaki kaynakları kullanarak BI kullanıcısının talebine cevap veren "
        "TEK bir SELECT üret. Mümkünse FK ile join yap; rapor kolonlarını öncelikli olarak "
        "listelerken metrik aggregate'ini ek kolon olarak ekleyebilirsin. "
        "Identifier'ları dialect quote karakteri ile kapat "
        "(PG/Oracle: çift tırnak, MSSQL: köşeli parantez, MySQL: backtick). "
        "F15 — Identifier case kuralı: Oracle dialect'inde şema ve tablo "
        "isimlerini UPPERCASE olarak çift tırnak içine yaz "
        '(ör. "VYRA_TEST"."MUSTERILER"). PostgreSQL/MySQL için lowercase. '
        "Şüphede kalırsan metadata'da verildiği case'i birebir koru. "
        "Çıktı SADECE JSON: "
        '{"sql": "...", "rationale": "kısa Türkçe açıklama"}'
    )

    system_prompt = (
        "Sen kıdemli bir BI/SQL uzmanısın. Yalnızca tek bir geçerli SELECT cümlesi üret. "
        "Asla UPDATE/DELETE/INSERT/DROP/CREATE/ALTER/TRUNCATE/GRANT/REVOKE/MERGE/EXEC/EXECUTE/CALL "
        "anahtar sözcüklerini kullanma. Asla birden fazla ifade üretme (noktalı virgül "
        "ile ayrılmış zincir yok). Çıktı SADECE şu JSON: "
        '{"sql": "...", "rationale": "kısa Türkçe açıklama"}'
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ─────────────────────────────────────────────────────────────
# Safe fallback SQL — used when LLM is unavailable / invalid
# ─────────────────────────────────────────────────────────────

def _build_fallback_sql(
    dialect: str,
    primary_table_name: Optional[str],
    limit: int,
) -> str:
    """Deterministic `SELECT * FROM <primary>` with dialect-correct row limit.

    SafeSQLExecutor will additionally cap rows; this is just a sensible default
    so the modal still shows *something* when the LLM is unreachable.
    """
    d = _normalize_dialect(dialect)
    n = int(limit)
    tbl = primary_table_name or "dual"  # last-resort placeholder (Oracle has DUAL)

    if d in ("mssql", "sqlserver"):
        return f"SELECT TOP ({n}) * FROM {tbl}"
    if d == "oracle":
        return f"SELECT * FROM {tbl} FETCH FIRST {n} ROWS ONLY"
    # postgresql / mysql / mariadb / default
    return f"SELECT * FROM {tbl} LIMIT {n}"


# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────

def generate_report(
    source_id: int,
    dialect: str,
    primary_table_id: int,
    join_table_ids: List[int],
    report_columns: List[Dict[str, Any]],
    metric: Optional[Dict[str, Any]],
    user_note: str,
    fk_context: List[Dict[str, Any]],
    current_user: Dict[str, Any],
    limit: int = 100,
) -> Dict[str, Any]:
    """Ask the LLM to generate a single SELECT SQL for the requested report.

    Args:
        source_id:           data_sources.id. Tenant scope is the CALLER's
                             responsibility (the route enforces company_id);
                             this service additionally applies RLS GUC.
        dialect:             postgresql | oracle | mssql | mysql
        primary_table_id:    ds_db_objects.id of the primary table.
        join_table_ids:      ds_db_objects.id list of joined tables (may be []).
        report_columns:      [{name, table_name?, semantic_type?}]
        metric:              full metric dict from wizard or None.
        user_note:           free-text user request (≤2000 chars enforced).
        fk_context:          [{from_table, to_table, from_col, to_col}]
        current_user:        FastAPI auth dict ({id, company_id, ...}).
        limit:               row cap hint for the prompt (default 100).

    Returns:
        {
            "sql":              str,             # generated or fallback SQL
            "rationale":        str,             # short Turkish explanation
            "fallback":         bool,            # True if LLM unavailable or rejected
            "validation_error": Optional[str],   # set when LLM SQL was rejected
        }
    """
    # ── 1. Resolve table names (best-effort) ────────────────
    primary_name: Optional[str] = None
    join_names: List[str] = []
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                apply_vyra_user_context(cur, current_user)
            except Exception as e:
                logger.info(
                    "[llm_generate_report] RLS apply soft-fail (continuing): %s", e
                )
            all_ids = [int(primary_table_id)] + [int(t) for t in (join_table_ids or [])]
            name_map = _fetch_table_names(cur, int(source_id), all_ids)
            primary_name = name_map.get(int(primary_table_id))
            join_names = [
                name_map[int(t)] for t in (join_table_ids or [])
                if int(t) in name_map
            ]
    except Exception as e:
        logger.warning("[llm_generate_report] table-name lookup failed: %s", e)

    # ── 2. Build FK lines from the caller-supplied context ──
    # The frontend can supply explicit FK hints (preferred); we don't re-derive
    # from the FK graph here — F7's multi-column endpoint already exposes FK
    # neighbours, and the wizard knows which joins are "active".
    fk_lines: List[str] = []
    for fk in (fk_context or []):
        if not isinstance(fk, dict):
            continue
        ft = (fk.get("from_table") or "").strip()
        tt = (fk.get("to_table") or "").strip()
        fc = (fk.get("from_col") or "").strip()
        tc = (fk.get("to_col") or "").strip()
        if ft and tt and fc and tc:
            fk_lines.append(f"{ft}.{fc} = {tt}.{tc}")

    # ── 3. LLM call (defensive) ─────────────────────────────
    messages = _build_prompt(
        dialect=dialect,
        primary_table_name=primary_name,
        join_table_names=join_names,
        fk_lines=fk_lines,
        report_columns=report_columns or [],
        metric=metric,
        user_note=user_note or "",
        limit=int(limit),
    )

    try:
        raw = call_llm_api(messages, temperature=0.3)
    except (LLMConnectionError, LLMConfigError) as e:
        logger.info("[llm_generate_report] LLM unavailable, fallback: %s", e)
        return {
            "sql": _build_fallback_sql(dialect, primary_name, limit),
            "rationale": (
                "LLM servisine ulaşılamadı; varsayılan SELECT * uygulandı."
            ),
            "fallback": True,
            "validation_error": None,
        }
    except LLMResponseError as e:
        logger.info("[llm_generate_report] LLM bad response, fallback: %s", e)
        return {
            "sql": _build_fallback_sql(dialect, primary_name, limit),
            "rationale": (
                "LLM yanıt formatı geçersiz; varsayılan SELECT * uygulandı."
            ),
            "fallback": True,
            "validation_error": None,
        }
    except Exception as e:
        logger.warning("[llm_generate_report] LLM unexpected error: %s", e)
        return {
            "sql": _build_fallback_sql(dialect, primary_name, limit),
            "rationale": (
                "LLM beklenmedik hata; varsayılan SELECT * uygulandı."
            ),
            "fallback": True,
            "validation_error": None,
        }

    # ── 4. Parse JSON ───────────────────────────────────────
    parsed = _extract_json_obj(raw)
    if not parsed or not isinstance(parsed.get("sql"), str):
        logger.info(
            "[llm_generate_report] LLM JSON unparseable, fallback. raw_head=%r",
            (raw or "")[:200],
        )
        return {
            "sql": _build_fallback_sql(dialect, primary_name, limit),
            "rationale": (
                "LLM yanıtı çözümlenemedi; varsayılan SELECT * uygulandı."
            ),
            "fallback": True,
            "validation_error": None,
        }

    sql_candidate = parsed.get("sql", "").strip()
    rationale = parsed.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = "LLM önerisi uygulandı."
    rationale = rationale.strip()[:500]

    # ── 5. Validate SELECT-only / single-statement ──────────
    ve = _validate_select_sql(sql_candidate)
    if ve is not None:
        logger.warning(
            "[llm_generate_report] LLM SQL rejected: %s | sql_head=%r",
            ve, sql_candidate[:200],
        )
        return {
            "sql": _build_fallback_sql(dialect, primary_name, limit),
            "rationale": (
                f"LLM SQL'i güvenlik kontrolünden geçemedi ({ve}); "
                "varsayılan SELECT * uygulandı."
            ),
            "fallback": True,
            "validation_error": ve,
        }

    # Strip a trailing semicolon defensively (SafeSQLExecutor accepts but
    # apply_row_limit can struggle with trailing-`;`).
    if sql_candidate.endswith(";"):
        sql_candidate = sql_candidate[:-1].rstrip()

    return {
        "sql": sql_candidate,
        "rationale": rationale,
        "fallback": False,
        "validation_error": None,
    }
