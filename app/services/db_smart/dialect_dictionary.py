"""Dialect dictionary — 4 RDBMS feature/syntax map (v3.30.0 FAZ 3 P12 G3.1).

Amaç:
    text_to_sql / ast_renderer / query_assembler dialect-aware kod yazarken
    hard-coded if-else dağılımı yerine tek kaynak doğruluk. **Immutable** —
    runtime'da değiştirilmez. Test edilebilir saf veri yapısı.

Bölüm haritası (her dialect için):
    * features: bool flag'lar (supports_ilike, supports_lateral, ...)
    * syntax  : küçük sözlük (limit_clause, case_insensitive_like, ...)
    * functions: agg/string/date/window mapping (canonical_name → dialect SQL)
    * hints   : tested-and-safe hint metni (P6'da ast_renderer.inject_dialect_hints
                ile uyumlu — orada tekrar parametrik üretiliyor; burada
                yalnızca isim/sözdizimi referansı tutuluyor).

Yansıma noktaları:
    - safe_sql_executor.check_table_whitelist (quote pattern)
    - ast_renderer (LIMIT/FETCH FIRST, ILIKE→LOWER(LIKE))
    - inject_dialect_hints (Oracle PARALLEL, MSSQL OPTION(...), MySQL
      MAX_EXECUTION_TIME, PG SET LOCAL work_mem)
    - custom_metric_parser (LLM prompt'a dialect bilgisi)
    - text_to_sql.build_text_to_sql_prompt (dialect_rules)

NOT: Yeni dialect eklendiğinde:
    1. SUPPORTED_DIALECTS güncellenir (ast_renderer.py).
    2. Bu dosyada yeni anahtarın tam taksonomisi doldurulur.
    3. ast_renderer.inject_dialect_hints whitelist'i güncellenir.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional


# ─────────────────────────────────────────────────────────────
# Canonical feature names (kullanıcıya açık çağrı arayüzü)
# ─────────────────────────────────────────────────────────────

# Bool feature flag'leri
FEATURE_KEYS = (
    "supports_ilike",
    "supports_lateral",
    "supports_grouping_sets",  # GROUPING SETS / CUBE / ROLLUP (P31)
    "supports_cube",           # P31 — PG/Oracle/MSSQL
    "supports_rollup",         # P31 — PG/Oracle/MSSQL/MySQL(8.0+)
    "supports_recursive_cte",
    "supports_window",
    "supports_string_agg",
    "supports_array_agg",
    "supports_jsonb_agg",
    "supports_jsonb_build_object",  # P31 — PG-specific jsonb constructor
    "supports_jsonb_object_agg",    # P31 — PG-specific jsonb aggregator
    "supports_brin",                # P31 — PG BRIN scan hint marker
    "supports_listagg",
    "supports_pivot",
    "supports_fetch_first",   # SQL:2008 FETCH FIRST N ROWS ONLY
    "supports_top",           # MSSQL TOP N
    "supports_offset_limit",  # PG/MySQL/MSSQL2012+ standart OFFSET..LIMIT
    "supports_with_clause",
    "supports_connect_by",
    "supports_nvl2",              # P32 — Oracle NVL2()
    "supports_decode",            # P32 — Oracle DECODE()
    "supports_cross_apply",       # P32 — MSSQL CROSS APPLY (LATERAL equiv)
    "supports_outer_apply",       # P32 — MSSQL OUTER APPLY (LEFT LATERAL equiv)
    "supports_json_table",        # P32 — MySQL 8.0.17+ JSON_TABLE
    "case_sensitive_identifiers",
)


def _feature_dict(**flags: bool) -> Mapping[str, bool]:
    out = {k: False for k in FEATURE_KEYS}
    out.update({k: bool(v) for k, v in flags.items()})
    return MappingProxyType(out)


# ─────────────────────────────────────────────────────────────
# Per-dialect features (immutable)
# ─────────────────────────────────────────────────────────────

_FEATURES: Mapping[str, Mapping[str, bool]] = MappingProxyType({
    "postgresql": _feature_dict(
        supports_ilike=True, supports_lateral=True, supports_grouping_sets=True,
        supports_cube=True, supports_rollup=True,
        supports_recursive_cte=True, supports_window=True,
        supports_string_agg=True, supports_array_agg=True, supports_jsonb_agg=True,
        supports_jsonb_build_object=True, supports_jsonb_object_agg=True,
        supports_brin=True,
        supports_fetch_first=True, supports_offset_limit=True,
        supports_with_clause=True, case_sensitive_identifiers=True,
    ),
    "oracle": _feature_dict(
        supports_ilike=False, supports_lateral=True, supports_grouping_sets=True,
        supports_cube=True, supports_rollup=True,
        supports_recursive_cte=True, supports_window=True,
        supports_listagg=True, supports_pivot=True,
        supports_fetch_first=True,
        supports_with_clause=True, supports_connect_by=True,
        supports_nvl2=True, supports_decode=True,
        case_sensitive_identifiers=False,
    ),
    "mssql": _feature_dict(
        supports_ilike=False, supports_lateral=True, supports_grouping_sets=True,
        supports_cube=True, supports_rollup=True,
        supports_recursive_cte=True, supports_window=True,
        supports_string_agg=True,  # 2017+
        supports_pivot=True,
        supports_cross_apply=True, supports_outer_apply=True,  # LATERAL eşdeğeri
        supports_top=True, supports_offset_limit=True, supports_fetch_first=True,
        supports_with_clause=True, case_sensitive_identifiers=False,
    ),
    "mysql": _feature_dict(
        supports_ilike=False, supports_lateral=True, supports_grouping_sets=False,
        supports_rollup=True,         # MySQL: WITH ROLLUP modifier (8.0+)
        supports_recursive_cte=True,  # 8.0+
        supports_window=True,         # 8.0+
        supports_string_agg=False,    # GROUP_CONCAT alternatif
        supports_json_table=True,     # 8.0.17+
        supports_offset_limit=True,
        supports_with_clause=True, case_sensitive_identifiers=False,
    ),
})


# ─────────────────────────────────────────────────────────────
# Syntax fragmanları (token-level)
# ─────────────────────────────────────────────────────────────

_SYNTAX: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "postgresql": MappingProxyType({
        "ident_quote_open": '"',
        "ident_quote_close": '"',
        "string_quote": "'",
        "limit_clause": "LIMIT {n}",
        "limit_offset_clause": "LIMIT {n} OFFSET {o}",
        "ilike": "ILIKE",
        "case_insensitive_like": "ILIKE",
        "current_date": "CURRENT_DATE",
        "current_timestamp": "NOW()",
        # P31 — group/lateral/hint markers (rendered tokens; not bind vehicles)
        "grouping_sets": "GROUPING SETS ({sets})",
        "cube": "CUBE ({cols})",
        "rollup": "ROLLUP ({cols})",
        "lateral_keyword": "LATERAL",
        "brin_hint_comment": "/*+ SeqScan(brin_advisory) */",
        "parallel_workers_setting": "SET LOCAL parallel_workers_per_gather = {n}",
    }),
    "oracle": MappingProxyType({
        "ident_quote_open": '"',
        "ident_quote_close": '"',
        "string_quote": "'",
        "limit_clause": "FETCH FIRST {n} ROWS ONLY",
        "limit_offset_clause": "OFFSET {o} ROWS FETCH NEXT {n} ROWS ONLY",
        "ilike": "LIKE",  # case-insensitive değil; LOWER(col) LIKE LOWER(pat) deyimi
        "case_insensitive_like": "LOWER({col}) LIKE LOWER({val})",
        "current_date": "TRUNC(SYSDATE)",
        "current_timestamp": "SYSTIMESTAMP",
        # P32 — Oracle-specific hierarchical + pivot syntax
        "connect_by": "CONNECT BY {prior_expr}",
        "start_with": "START WITH {expr}",
        "pivot": "PIVOT ({agg} FOR {col} IN ({values}))",
        "unpivot": "UNPIVOT ({value_col} FOR {name_col} IN ({cols}))",
        "grouping_sets": "GROUPING SETS ({sets})",
        "cube": "CUBE ({cols})",
        "rollup": "ROLLUP ({cols})",
    }),
    "mssql": MappingProxyType({
        "ident_quote_open": "[",
        "ident_quote_close": "]",
        "string_quote": "'",
        "limit_clause": "OFFSET 0 ROWS FETCH NEXT {n} ROWS ONLY",
        "limit_offset_clause": "OFFSET {o} ROWS FETCH NEXT {n} ROWS ONLY",
        "ilike": "LIKE",  # collation Latin1_General_CI_AS varsayımı
        "case_insensitive_like": "LOWER({col}) LIKE LOWER({val})",
        "current_date": "CAST(GETDATE() AS DATE)",
        "current_timestamp": "SYSDATETIME()",
        # P32 — MSSQL-specific APPLY + PIVOT + OPTION hints
        "cross_apply": "CROSS APPLY {table_expr}",
        "outer_apply": "OUTER APPLY {table_expr}",
        "pivot": "PIVOT ({agg} FOR {col} IN ({values}))",
        "unpivot": "UNPIVOT ({value_col} FOR {name_col} IN ({cols}))",
        "option_maxdop": "OPTION (MAXDOP {n})",
        "option_recompile": "OPTION (RECOMPILE)",
        "option_optimize_unknown": "OPTION (OPTIMIZE FOR UNKNOWN)",
        "grouping_sets": "GROUPING SETS ({sets})",
        "cube": "CUBE ({cols})",
        "rollup": "ROLLUP ({cols})",
    }),
    "mysql": MappingProxyType({
        "ident_quote_open": "`",
        "ident_quote_close": "`",
        "string_quote": "'",
        "limit_clause": "LIMIT {n}",
        "limit_offset_clause": "LIMIT {n} OFFSET {o}",
        "ilike": "LIKE",  # default collation utf8mb4_0900_ai_ci CI zaten
        "case_insensitive_like": "LIKE",
        "current_date": "CURDATE()",
        "current_timestamp": "NOW()",
        # P32 — MySQL-specific
        "with_rollup": "WITH ROLLUP",  # GROUP BY col1, col2 WITH ROLLUP
        "json_table": "JSON_TABLE({json_expr}, {path} COLUMNS ({col_defs}))",
        "recursive_cte": "WITH RECURSIVE {name} AS ({query})",
    }),
})


# ─────────────────────────────────────────────────────────────
# Function mapping — canonical → dialect-spesifik SQL fragmanı
# ─────────────────────────────────────────────────────────────
# {arg0}/{arg1}/{sep} placeholder'ları caller'a aittir (format YOK; sadece şablon).

_FUNCTIONS: Mapping[str, Mapping[str, Optional[str]]] = MappingProxyType({
    "postgresql": MappingProxyType({
        "string_agg":   "STRING_AGG({arg0}, {sep})",
        "group_concat": "STRING_AGG({arg0}, {sep})",
        "array_agg":    "ARRAY_AGG({arg0})",
        "jsonb_agg":    "JSONB_AGG({arg0})",
        # P31 — jsonb constructor + aggregator + regexp_replace
        "jsonb_build_object": "JSONB_BUILD_OBJECT({arg0}, {arg1})",
        "jsonb_object_agg":   "JSONB_OBJECT_AGG({arg0}, {arg1})",
        "regexp_replace":     "REGEXP_REPLACE({arg0}, {arg1}, {arg2})",
        "median":       "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {arg0})",
        "date_trunc":   "DATE_TRUNC({arg1}, {arg0})",
        "date_diff":    "({arg0} - {arg1})",
        "concat":       "{arg0} || {arg1}",
        "substring":    "SUBSTRING({arg0} FROM {arg1} FOR {arg2})",
        "now":          "NOW()",
        "regex_match":  "{arg0} ~ {arg1}",
        # FIX4 B7 — cross-dialect parity (COALESCE SQL standard, ROW_NUMBER SQL:2003)
        "coalesce":     "COALESCE({arg0}, {arg1})",
        "row_number":   "ROW_NUMBER() OVER ({arg0})",
    }),
    "oracle": MappingProxyType({
        "string_agg":   "LISTAGG({arg0}, {sep}) WITHIN GROUP (ORDER BY {arg0})",
        "group_concat": "LISTAGG({arg0}, {sep}) WITHIN GROUP (ORDER BY {arg0})",
        "array_agg":    None,
        "jsonb_agg":    "JSON_ARRAYAGG({arg0})",
        "median":       "MEDIAN({arg0})",
        "date_trunc":   "TRUNC({arg0}, {arg1})",
        "date_diff":    "({arg0} - {arg1})",
        "concat":       "{arg0} || {arg1}",
        "substring":    "SUBSTR({arg0}, {arg1}, {arg2})",
        "now":          "SYSTIMESTAMP",
        "regex_match":  "REGEXP_LIKE({arg0}, {arg1})",
        # P32 — Oracle-specific functions
        "nvl2":         "NVL2({arg0}, {arg1}, {arg2})",
        "decode":       "DECODE({arg0}, {arg1}, {arg2})",
        "connect_by_root":       "CONNECT_BY_ROOT {arg0}",
        "sys_connect_by_path":   "SYS_CONNECT_BY_PATH({arg0}, {arg1})",
        "regexp_replace":        "REGEXP_REPLACE({arg0}, {arg1}, {arg2})",
        "to_char":      "TO_CHAR({arg0}, {arg1})",
        "to_date":      "TO_DATE({arg0}, {arg1})",
        # FIX4 B7 — cross-dialect parity (COALESCE Oracle 9i+, ROW_NUMBER 9i+)
        "coalesce":     "COALESCE({arg0}, {arg1})",
        "row_number":   "ROW_NUMBER() OVER ({arg0})",
    }),
    "mssql": MappingProxyType({
        "string_agg":   "STRING_AGG({arg0}, {sep})",
        "group_concat": "STRING_AGG({arg0}, {sep})",
        "array_agg":    None,
        "jsonb_agg":    None,
        "median":       "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {arg0}) OVER ()",
        "date_trunc":   "DATETRUNC({arg1}, {arg0})",  # 2022+; eski sürümlerde DATEADD/DATEPART
        "date_diff":    "DATEDIFF(day, {arg1}, {arg0})",
        "concat":       "CONCAT({arg0}, {arg1})",
        "substring":    "SUBSTRING({arg0}, {arg1}, {arg2})",
        "now":          "SYSDATETIME()",
        "regex_match":  None,  # built-in regex yok
        # P32 — MSSQL-specific functions
        "iif":          "IIF({arg0}, {arg1}, {arg2})",
        "try_convert":  "TRY_CONVERT({arg0}, {arg1})",
        "format":       "FORMAT({arg0}, {arg1})",
        "isdate":       "ISDATE({arg0})",
        "isnull":       "ISNULL({arg0}, {arg1})",
        # FIX4 B7 — cross-dialect parity (COALESCE ANSI, ROW_NUMBER 2005+)
        "coalesce":     "COALESCE({arg0}, {arg1})",
        "row_number":   "ROW_NUMBER() OVER ({arg0})",
    }),
    "mysql": MappingProxyType({
        "string_agg":   "GROUP_CONCAT({arg0} SEPARATOR {sep})",
        "group_concat": "GROUP_CONCAT({arg0} SEPARATOR {sep})",
        "array_agg":    "JSON_ARRAYAGG({arg0})",
        "jsonb_agg":    "JSON_ARRAYAGG({arg0})",
        "median":       None,  # window function workaround gerekir
        "date_trunc":   "DATE_FORMAT({arg0}, {arg1})",
        "date_diff":    "DATEDIFF({arg0}, {arg1})",
        "concat":       "CONCAT({arg0}, {arg1})",
        "substring":    "SUBSTRING({arg0}, {arg1}, {arg2})",
        "now":          "NOW()",
        "regex_match":  "{arg0} REGEXP {arg1}",
        # P32 — MySQL-specific functions
        "group_concat_order": "GROUP_CONCAT({arg0} ORDER BY {arg1} SEPARATOR {sep})",
        "ifnull":       "IFNULL({arg0}, {arg1})",
        "if_expr":      "IF({arg0}, {arg1}, {arg2})",
        "json_extract": "JSON_EXTRACT({arg0}, {arg1})",
        "json_unquote": "JSON_UNQUOTE({arg0})",
        "regexp_replace": "REGEXP_REPLACE({arg0}, {arg1}, {arg2})",
        # FIX4 B7 — cross-dialect parity (COALESCE 4.0+, ROW_NUMBER 8.0+)
        "coalesce":     "COALESCE({arg0}, {arg1})",
        "row_number":   "ROW_NUMBER() OVER ({arg0})",
    }),
})


# ─────────────────────────────────────────────────────────────
# Hint catalog — desteklenen optimizer hint isimleri
# ─────────────────────────────────────────────────────────────

_HINT_CATALOG: Mapping[str, tuple] = MappingProxyType({
    # P31 — PG: brin scan marker + parallel_workers_per_gather knob added
    "postgresql": (
        "work_mem_mb", "enable_seqscan", "brin",
        "parallel_workers_per_gather",
    ),
    # P32 — Oracle: full scan, no_merge, use_hash added
    "oracle":     ("parallel", "result_cache", "index", "materialize",
                   "full", "no_merge", "use_hash", "leading"),
    # P32 — MSSQL: hash/merge join hints, fast N rows
    "mssql":      ("maxdop", "recompile", "optimize_for_unknown",
                   "hash_join", "merge_join", "fast_rows"),
    # P32 — MySQL: no_index_merge, join_order
    "mysql":      ("max_execution_time_ms", "sql_no_cache",
                   "no_index_merge", "join_order"),
})


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def _normalize(dialect: str) -> str:
    if not isinstance(dialect, str):
        raise ValueError("dialect string olmalı")
    d = dialect.lower().strip()
    if d not in _FEATURES:
        raise ValueError(f"Desteklenmeyen dialect: {dialect}")
    return d


def supports(dialect: str, feature: str) -> bool:
    """Belirli bir özelliği destekliyor mu?"""
    d = _normalize(dialect)
    return bool(_FEATURES[d].get(feature, False))


def features(dialect: str) -> Mapping[str, bool]:
    """Tüm bool feature flag'leri (readonly mapping)."""
    return _FEATURES[_normalize(dialect)]


def syntax(dialect: str, key: str, default: Optional[str] = None) -> Optional[str]:
    """Syntax fragmanı (limit_clause, ilike, ident_quote_open, ...)."""
    d = _normalize(dialect)
    return _SYNTAX[d].get(key, default)


def func(dialect: str, canonical_name: str) -> Optional[str]:
    """Fonksiyon şablonu (None → dialect desteklemiyor; caller fallback üretmeli)."""
    d = _normalize(dialect)
    return _FUNCTIONS[d].get(canonical_name)


def hint_catalog(dialect: str) -> tuple:
    """Bu dialect için desteklenen hint isim listesi."""
    return _HINT_CATALOG[_normalize(dialect)]


def quote_identifier(dialect: str, ident: str) -> str:
    """Identifier'ı dialect-uyumlu quote'la (basit form — kaçış: çift karakter).

    ÖNEMLI: ast_renderer.IDENT_RE zaten whitelist uyguluyor; bu fonksiyon
    quote layer'ı; SQL injection guard değildir. Her zaman whitelist + quote
    kombinasyonu kullanılmalıdır.
    """
    if not isinstance(ident, str) or not ident:
        return ident
    d = _normalize(dialect)
    o = _SYNTAX[d]["ident_quote_open"]
    c = _SYNTAX[d]["ident_quote_close"]
    # MSSQL [..] içinde ] kaçışı (]→]]); diğerleri için " veya `: çiftle.
    if o == "[" and c == "]":
        escaped = ident.replace("]", "]]")
    else:
        escaped = ident.replace(o, o + o)
    return f"{o}{escaped}{c}"


def build_limit_offset_clause(dialect: str, limit: int, offset: int = 0) -> str:
    """LIMIT/OFFSET clause döndürür (dialect-uyumlu, parametre güvenli — int).

    limit < 0 → boş string; offset < 0 → 0; integer enforcement.
    """
    try:
        n = int(limit)
        o = int(offset)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    if o < 0:
        o = 0
    d = _normalize(dialect)
    tmpl = _SYNTAX[d]["limit_offset_clause"] if o > 0 else _SYNTAX[d]["limit_clause"]
    return tmpl.format(n=n, o=o)


def render_function(
    dialect: str, canonical_name: str, *args: str, sep: str = "','",
) -> Optional[str]:
    """Canonical fonksiyonu dialect şablonu ile doldurur. None → desteklenmiyor."""
    tmpl = func(dialect, canonical_name)
    if tmpl is None:
        return None
    placeholders: Dict[str, str] = {"sep": sep}
    for i, a in enumerate(args):
        placeholders[f"arg{i}"] = a
    try:
        return tmpl.format(**placeholders)
    except KeyError:
        return None


def supported_dialects() -> tuple:
    """Readonly tuple — değişmez."""
    return tuple(_FEATURES.keys())
