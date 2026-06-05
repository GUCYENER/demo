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
# v3.55.0: LLM'e tablo başına verilecek GERÇEK kolon sayısı capi (kolon grounding —
# halüsinasyon önleme: LLM yalnız GERÇEK kolonları görsün, uydurmasın).
# v3.75.0 (kullanıcı direktifi "ne kadar varsa öğren"): 80→500 — geniş tablo (312 kolon)
# SQL-gen'de TAM görünür; 500 güvenlik tavanı pathological >500-kolon prompt token-patlamasını
# önler. Anti-halüsinasyon (_check_column_hallucination) tam kolon setiyle çalışır → korunur.
MAX_SCHEMA_COLUMNS_PER_TABLE = 500

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


def _fetch_table_columns(
    cur, source_id: int, table_ids: List[int]
) -> Dict[str, List[tuple]]:
    """Return {'schema.object_name': [(col_name, data_type), ...]} — ds_db_objects.columns_json.

    v3.55.0: LLM'i GERÇEK kolonlara grounding'ler (halüsinasyon önleme — LLM olmayan kolon
    'CreatedDate' uydurmasın). Aynı RLS-scoped cur. columns_json JSONB → psycopg2 list[dict]
    döner; str gelirse json.loads (defensive). Hata → boş (fail-soft, eski davranışa düşer).
    """
    if not table_ids:
        return {}
    uniq = list({int(t) for t in table_ids})
    out: Dict[str, List[tuple]] = {}
    try:
        import json as _json
        cur.execute(
            """
            SELECT schema_name, object_name, columns_json
            FROM ds_db_objects
            WHERE source_id = %s AND id = ANY(%s)
            """,
            (int(source_id), uniq),
        )
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                schema = row.get("schema_name") or ""
                obj = row.get("object_name") or ""
                cols_raw = row.get("columns_json")
            else:
                schema, obj, cols_raw = (row[0] or ""), (row[1] or ""), row[2]
            if not obj:
                continue
            if isinstance(cols_raw, str):
                try:
                    cols_raw = _json.loads(cols_raw)
                except Exception:
                    cols_raw = None
            cols: List[tuple] = []
            for c in (cols_raw or []):
                if not isinstance(c, dict):
                    continue
                cn = (c.get("name") or "").strip()
                if not cn:
                    continue
                dt = (c.get("data_type") or "").strip()
                cols.append((cn, dt))
            name = f"{schema}.{obj}" if schema else str(obj)
            out[name] = cols
    except Exception as e:
        logger.warning(
            "[llm_generate_report] _fetch_table_columns failed source=%s ids=%s: %s",
            source_id, uniq, e,
        )
    return out


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


def _extract_diagnostic(sql_candidate: str, raw: str) -> Optional[str]:
    """v3.41.6: LLM, seçilen tablolar arasında ilişki/yol bulamayınca 'sql' alanına
    '-- DIAGNOSTIC: ...' / açıklama / yorum koyabiliyor. Eski akış bunu `_validate_select_sql`
    ile reddedip SESSİZCE 'SELECT * FROM <primary>' fallback'ine düşüyordu — kullanıcı istediği
    join yerine sebepsiz sadece ana tabloyu görüyordu ("saçmaladı"). DIAGNOSTIC/yorum-only
    metnini döndür ki çağıran NET bir sebep gösterebilsin; yoksa None.
    """
    # code-review fix: GEÇERLİ bir SQL statement varsa DIAGNOSTIC'e DÜŞME. Aksi halde
    # rationale/raw içinde tesadüfen "DIAGNOSTIC:" geçen (ör. "DIAGNOSTIC: müşteri_id ile bağlı")
    # GEÇERLİ bir JOIN sorgusu sessizce 'SELECT * FROM <primary>' fallback'ine çevriliyordu —
    # tam da bu değişikliğin kapatmaya çalıştığı "saçmaladı" semptomu. Yalnız SQL yok/yorum-only
    # iken DIAGNOSTIC açıklamasını çıkar.
    has_real_sql = bool(
        sql_candidate
        and re.sub(r"--[^\n]*|/\*.*?\*/", "", sql_candidate, flags=re.DOTALL).strip()
    )
    if has_real_sql:
        return None
    # Gerçek SQL yok (boş veya yorum-only) → açıklamayı önce sql alanından, sonra raw'dan al.
    for src in (sql_candidate or "", raw or ""):
        m = re.search(r"DIAGNOSTIC:\s*(.+)", src, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()[:300]
    # sql alanı yalnızca yorumdan ibaretse (DIAGNOSTIC token'ı yoksa bile) metni döndür
    if sql_candidate:
        return sql_candidate.strip()[:300]
    return None


# ─────────────────────────────────────────────────────────────
# B4 (v3.37.9 — METIS+ARES+POSEIDON): glued garbage keyword-prefix repair
# ─────────────────────────────────────────────────────────────
# LLM ham çıktısında ara sıra bir SQL keyword'ünün hemen önüne BOŞLUKSUZ
# yapışmış kısa bir garbage token görülüyor ("W0SELECT", "WDFROM" gibi —
# v3.37.4 telemetri notuna bkz: "W0SELECT/W0FROM garbage-prefix failure mode
# is upstream"). Bu SQL'i hem DB'de patlatıyor hem de _validate_select_sql'in
# "SELECT/WITH ile başlamalı" kontrolünü bozuyordu.
#
# Hedefli onarım: bir SQL keyword'üne YAPIŞIK (araya separator girmeden) gelen
# 1-3 karakterlik harf/rakam token'ını temizle. Gözlenen bozulma modunda garbage
# DAİMA satırbaşında belirir ("W0SELECT" ilk satır, "\nW0FROM" sonraki satır).
# Bu yüzden lookbehind `(?<![^\n])` ile token'ın YALNIZ string-başı veya bir
# newline'dan hemen sonra gelmesini şart koşarız (satır-içi boşluk sonrası HARİÇ):
#   - String literal içindeki keyword ('fooSELECT bar', 'abUNION x') tırnak/harf
#     gibi boşluk-OLMAYAN bir karakterle öncelenir → eşleşmez → korunur.
#   - Satır-içi bareword ("SELECT myWITH FROM t") keyword'den önce boşlukla
#     gelir → newline değil → eşleşmez → korunur.
#   - Çift-tırnaklı identifier ("VYRA_TEST"."WITHHOLDING") zaten `KEYWORD\b`
#     sınırını sağlamaz (HOLDING devam eder) → güvende.
# Code-review (medium, v3.37.9): eski `(?<![A-Za-z0-9_."])` lookbehind tırnak
# sonrasını ('fooSELECT) chop ediyordu (string filtre değerlerini bozan CONFIRMED
# FP). Ara adım `(?<!\S)` literal'ı kurtardı ama satır-içi bareword'ü (myWITH)
# hâlâ kesiyordu; `(?<![^\n])` ankoru her iki FP'yi de sıfırlar, gözlenen
# satırbaşı garbage'ını (W0SELECT/W0FROM) onarır.
# Telemetri (raw LLM log'u) bu onarımın ÖNCESİNDE çalışır → kök neden sinyali
# kaybolmaz; onarım yalnız kullanıcıya giden semptomu kapatır.
# Bulgular4 B4-2 (v3.38.1): eski `(?<![^\n])` anchor'ı YALNIZ satır başı garbage'ını
# yakalıyordu; LLM SQL'i tek satır üretince (FROM boşlukla ayrılır) `W0FROM` kaçıyordu
# (test: `W0SELECT a, b W0FROM tbl` → W0FROM kalıyordu). Anchor `(?:^|(?<=\s))` =
# string başı VEYA herhangi bir whitespace (newline DAHİL) sonrası → satır-içi garbage
# da onarılır. String-literal FP yok ('fooSELECT' quote-öncesi, whitespace değil); clause
# keyword'leri (SELECT/FROM/...) zaten glued identifier olamaz.
_GLUED_KW_RE = re.compile(
    r'(?:^|(?<=\s))'
    r'[A-Za-z][A-Za-z0-9]{0,2}'
    r'(?=(?:SELECT|FROM|WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|'
    r'LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|FULL\s+JOIN|CROSS\s+JOIN|'
    r'OUTER\s+JOIN|JOIN|UNION\s+ALL|UNION|INTERSECT|EXCEPT|'
    r'LIMIT|OFFSET|FETCH\s+FIRST|WITH)\b)',
    re.IGNORECASE,
)


def _repair_glued_keyword_garbage(sql: str) -> tuple:
    """Return (repaired_sql, changed: bool). Bkz. _GLUED_KW_RE notu."""
    if not sql:
        return sql, False
    repaired = _GLUED_KW_RE.sub("", sql)
    return repaired, (repaired != sql)


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
    filters: Optional[List[Dict[str, Any]]] = None,
    order_by: Optional[List[Dict[str, Any]]] = None,
    table_columns: Optional[Dict[str, List[tuple]]] = None,
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

    # v3.55.0: GERÇEK kolon envanteri (grounding — LLM olmayan kolon uydurmasın).
    # Her tablo için columns_json'dan ad+tip; per-table cap (token bütçesi).
    schema_cols_block = ""
    if table_columns:
        _parts: List[str] = []
        for _tname, _cols in table_columns.items():
            if not _cols:
                continue
            _capped = _cols[:MAX_SCHEMA_COLUMNS_PER_TABLE]
            _col_strs = [
                (f'"{cn}"({dt})' if dt else f'"{cn}"') for (cn, dt) in _capped
            ]
            _more = "" if len(_cols) <= MAX_SCHEMA_COLUMNS_PER_TABLE else f" …(+{len(_cols) - MAX_SCHEMA_COLUMNS_PER_TABLE})"
            _parts.append(f"{_tname}: " + ", ".join(_col_strs) + _more)
        if _parts:
            schema_cols_block = (
                "Tablo kolonları (GERÇEK şema — SADECE bu kolonları kullan; "
                "listede OLMAYAN bir kolonu ASLA uydurma):\n" + "\n".join(_parts)
            )

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

    # v3.42.0: Yapılandırılmış WHERE/ORDER BY → LLM'e ZORUNLU kısıt. Wizard'ın
    # AST editör (WHERE chip) + SIRALAMA chip barı bunları gönderir; LLM üretilen
    # SQL'e AYNEN koymalı (kullanıcı önizlemede gördüğü filtreyi sonuçta da bekler).
    # code-review: değeri Python repr (!r) yerine SQL literal olarak göster —
    # repr("O'Brien") → "O'Brien" (çift tırnak = SQL identifier), LLM'i yanıltır.
    from app.services.db_smart.query_assembler import _literal as _sql_lit
    _constraint_lines: List[str] = []
    for _f in (filters or []):
        if not isinstance(_f, dict):
            continue
        _col = (_f.get("expr") or _f.get("column") or "").strip()
        if not _col:
            continue
        _op = (_f.get("op") or "=").strip()
        if _op.upper() in ("IS NULL", "IS NOT NULL"):
            _constraint_lines.append(f"- {_col} {_op}")
        else:
            _constraint_lines.append(f"- {_col} {_op} {_sql_lit(_f.get('value'))}")
    _order_lines: List[str] = []
    for _o in (order_by or []):
        if not isinstance(_o, dict):
            continue
        _ocol = (_o.get("expr") or _o.get("column") or _o.get("column_name") or "").strip()
        if not _ocol:
            continue
        _odir = (_o.get("dir") or _o.get("direction") or "ASC").strip().upper()
        _order_lines.append(f"- {_ocol} {'DESC' if _odir == 'DESC' else 'ASC'}")
    constraints_block = ""
    if _constraint_lines:
        constraints_block += (
            "ZORUNLU WHERE koşulları (bu filtreleri SQL'e AYNEN, atlamadan uygula):\n"
            + "\n".join(_constraint_lines) + "\n\n"
        )
    if _order_lines:
        constraints_block += (
            "ZORUNLU ORDER BY (bu sıralamayı uygula):\n"
            + "\n".join(_order_lines) + "\n\n"
        )

    user_prompt = (
        f"Dialect: {d}\n"
        f"Satır limiti: {int(limit)}  — Dialect kuralı: {limit_rule}\n\n"
        f"{tables_block}\n\n"
        + (f"{schema_cols_block}\n\n" if schema_cols_block else "")
        + f"{fk_block}\n\n"
        "Rapor kolonları (kullanıcı seçti):\n"
        + "\n".join(col_lines) + "\n\n"
        f"{metric_block}\n\n"
        f"{note_block}\n\n"
        f"{constraints_block}"
        "Görev: Yukarıdaki kaynakları kullanarak BI kullanıcısının talebine cevap veren "
        "TEK bir SELECT üret. Mümkünse FK ile join yap; rapor kolonlarını öncelikli olarak "
        "listelerken metrik aggregate'ini ek kolon olarak ekleyebilirsin. "
        + ("KRİTİK: Yalnızca yukarıdaki 'Tablo kolonları' listesinde GERÇEKTEN VAR OLAN "
           "kolonları kullan. Listede olmayan bir kolon adı ASLA UYDURMA (ör. tarih/zaman "
           "metriği gerekiyorsa yalnız listedeki gerçek timestamp/date kolonunu kullan; uygun "
           "kolon YOKSA o metriği hesaplama ve rationale'da 'uygun kolon bulunamadı' belirt). "
           if schema_cols_block else "")
        + "Identifier'ları dialect quote karakteri ile kapat "
        "(PG/Oracle: çift tırnak \"...\", MSSQL: köşeli parantez [...], MySQL: backtick `...`). "
        "F15 KÖK KURAL (v3.64.0) — Identifier CASE: şema, tablo ve kolon adlarını metadata'da "
        "VERİLDİĞİ case ile BİREBİR yaz; ASLA lowercase/uppercase'e ÇEVİRME. Kaynak case-duyarlıdır: "
        'ör. PostgreSQL\'de "T_ORG_USER" tablosunu t_org_user yaparsan "relation does not exist" '
        "hatası alırsın. Yukarıdaki 'Tablo kolonları' ve tablo adlarında görünen büyük/küçük harfi "
        "AYNEN kullan ve her identifier'ı tırnakla. Tabloyu şema ile nitele, şema case'ini de koru. "
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
    filters: Optional[List[Dict[str, Any]]] = None,
    order_by: Optional[List[Dict[str, Any]]] = None,
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
    table_columns: Dict[str, List[tuple]] = {}  # v3.55.0: gerçek kolon envanteri (grounding)
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
            # v3.55.0: LLM kolon grounding — gerçek kolonları çek (halüsinasyon önleme).
            table_columns = _fetch_table_columns(cur, int(source_id), all_ids)
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

    # ── 2b. (v3.42.0 Faz 3b) Frontend fk_context GÖNDERMEDİYSE, seçili tablolar arası
    # DETERMİNİSTİK FK join koşullarını FK grafiğinden SERVER-SIDE türet (join_planner) →
    # LLM doğru join'i alır, 'FATURALAR.MUSTERI_ID' gibi olmayan kolon/yanlış join uydurmaz.
    # Yalnız fk_lines BOŞken devreye girer (frontend'in curated join'lerini ezme). Fail-soft;
    # yetki yine route'ta (enforce_sql_scope) korunur.
    if primary_name and join_names and not fk_lines:
        try:
            from app.services.db_smart.join_planner import find_join_path, load_fk_edges
            # code-review fix: in_scope = SEÇİLEN tablolar. lambda:True idi → join_planner
            # seçilmemiş KÖPRÜ tablo üzerinden join üretip prompt'a koyabiliyordu (bridge-leak).
            # Yalnız tüm yol seçili tablolardaysa (ok) join ver; köprü seçilmemişse HİÇ ekleme
            # (kullanıcı köprüyü seçmeli — uydurma join yok). Yetki yine route'ta (enforce_sql_scope).
            _picked = {primary_name.rsplit(".", 1)[-1].lower()}
            _picked |= {n.rsplit(".", 1)[-1].lower() for n in join_names}
            _jp = find_join_path(
                load_fk_edges(int(source_id)), primary_name, join_names,
                lambda _t: _t.rsplit(".", 1)[-1].lower() in _picked,
            )
            if _jp.get("ok"):
                for j in _jp.get("joins", []):
                    _l = j["left"].rsplit(".", 1)[-1]
                    _r = j["right"].rsplit(".", 1)[-1]
                    fk_lines.append(f"{_l}.{j['left_col']} = {_r}.{j['right_col']}")
            if fk_lines:
                logger.info(
                    "[llm_generate_report] join_planner FK türetildi (frontend hint yoktu): %d join",
                    len(fk_lines),
                )
        except Exception as e:
            logger.warning("[llm_generate_report] join_planner FK augment atlandı: %s", e)

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
        filters=filters or [],
        order_by=order_by or [],
        table_columns=table_columns,
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

    # v3.37.4 Bug B telemetry: the W0SELECT/W0FROM garbage-prefix failure
    # mode is upstream — the sanitizer that used to live here masked the
    # symptom and made the root cause harder to trace. Log the raw LLM
    # response head + the parsed SQL head + a length comparison so the
    # next prod hit gives us the artifact signature in plain text.
    logger.info(
        "[llm_generate_report] LLM raw len=%d sql_len=%d "
        "raw_head=%r sql_head=%r",
        len(raw or ""),
        len(sql_candidate),
        (raw or "")[:240],
        sql_candidate[:240],
    )

    # ── 4b. B4 (v3.37.9): glued garbage keyword-prefix onar (telemetri'den
    # SONRA → raw sinyal log'da korunur). Bkz. _repair_glued_keyword_garbage.
    sql_candidate, _kw_repaired = _repair_glued_keyword_garbage(sql_candidate)
    if _kw_repaired:
        logger.warning(
            "[llm_generate_report] B4 glued keyword-prefix garbage repaired "
            "(upstream LLM artifact); repaired_head=%r",
            sql_candidate[:200],
        )

    # ── 4c. (v3.41.6) DIAGNOSTIC / yorum-only çıktı → SESSİZ 'SELECT *' fallback yerine
    # net sebep. LLM, seçilen tablolar arasında ilişki kuramayınca açıklama döndürüyor;
    # bunu kullanıcıya iletmeden ana tabloya düşmek "saçmaladı" algısı yaratıyordu. ───────
    _diag = _extract_diagnostic(sql_candidate, raw)
    if _diag:
        logger.info(
            "[llm_generate_report] LLM DIAGNOSTIC/yorum-only çıktı → net rationale (fallback): %r",
            _diag[:160],
        )
        return {
            "sql": _build_fallback_sql(dialect, primary_name, limit),
            "rationale": (
                "Seçtiğiniz tablolar arasında istenen ilişki kurulamadı: " + _diag
                + " — yalnızca ana tablo listelendi (ilgili tabloyu da seçin veya yetki alın)."
            ),
            "fallback": True,
            "validation_error": "diagnostic",
        }

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
