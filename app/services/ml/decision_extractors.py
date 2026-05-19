"""
decision_extractors — v3.26.0 Faz 4 (P2-a)
==========================================
SQL string + pipeline state'inden column/filter/join karar satırlarını üretir.

Üç decision tipi:
    column : SELECT listesindeki kolonlar (positive samples) vs aday tabloların
             SELECT'e girmeyen kolonları (negative samples).
    filter : WHERE/HAVING clause'da geçen kolonlar (positive) vs adaylardan
             filter'a alınmamış kolonlar (negative).
    join   : Final SQL'deki (table_a, table_b) çiftleri (positive) vs aday
             tablolar arasında JOIN kurulmamış çiftler (negative).

Feature seti minimal ve forward-compatible — yeni feature eklemek migration
gerektirmez (features JSONB).

Bağımlılık: sqlglot YOK — lightweight regex parser. Yanlış pozitiflerin
training verisinde küçük bir gürültüye yol açması kabul edilir; CatBoost
robust.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Public feature ordering — model determinism için sabit
# ---------------------------------------------------------------------------

COLUMN_FEATURE_ORDER: List[str] = [
    "is_pk", "is_fk", "data_type_numeric", "data_type_string",
    "data_type_date", "name_match_score", "table_rank", "table_final_score",
    "intent_confidence", "candidate_count",
]

FILTER_FEATURE_ORDER: List[str] = [
    "is_pk", "is_fk", "data_type_numeric", "data_type_string",
    "data_type_date", "name_match_score", "table_rank",
    "question_has_temporal_word", "question_has_eq_word",
    "intent_confidence",
]

JOIN_FEATURE_ORDER: List[str] = [
    "rank_a", "rank_b", "score_a", "score_b",
    "has_fk_relation",
    "shared_column_count",
    "intent_confidence",
    "candidate_count",
]


# Türkçe + İngilizce yaygın "filtre" sözcükleri
_TEMPORAL_WORDS = {
    "bugun", "bugün", "dun", "dün", "gecen", "geçen", "haftalik", "haftalık",
    "aylik", "aylık", "yillik", "yıllık", "tarih", "tarihinde", "son",
    "today", "yesterday", "last", "month", "year", "week",
}
_EQ_WORDS = {
    "esit", "eşit", "olan", "olanlar", "kimlik", "id", "no", "kodu",
    "equals", "where", "filter",
}


# ---------------------------------------------------------------------------
# SQL string parser — minimal regex
# ---------------------------------------------------------------------------

_SELECT_RE = re.compile(r"\bselect\b(.+?)\bfrom\b", re.IGNORECASE | re.DOTALL)
_WHERE_RE = re.compile(r"\bwhere\b(.+?)(\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\blimit\b|\bfetch\b|;|$)", re.IGNORECASE | re.DOTALL)
_HAVING_RE = re.compile(r"\bhaving\b(.+?)(\border\s+by\b|\blimit\b|\bfetch\b|;|$)", re.IGNORECASE | re.DOTALL)
_JOIN_RE = re.compile(r"\bjoin\s+([\w\".]+)(?:\s+(?:as\s+)?([\w\"]+))?\s+on\s+(.+?)(?=\bjoin\b|\bwhere\b|\bgroup\b|\border\b|\bhaving\b|\blimit\b|\bfetch\b|;|$)", re.IGNORECASE | re.DOTALL)
_FROM_TABLE_RE = re.compile(r"\bfrom\s+([\w\".]+)(?:\s+(?:as\s+)?([\w\"]+))?", re.IGNORECASE)
_COL_REF_RE = re.compile(r"([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)")
_BARE_COL_RE = re.compile(r"\b([a-zA-Z_][\w]*)\b")

_SQL_KEYWORDS: Set[str] = {
    "select", "from", "where", "and", "or", "not", "in", "is", "null",
    "like", "ilike", "join", "inner", "left", "right", "outer", "full",
    "on", "as", "group", "by", "order", "asc", "desc", "having", "limit",
    "fetch", "first", "next", "rows", "only", "with", "distinct", "case",
    "when", "then", "else", "end", "between", "exists", "any", "all",
    "true", "false", "union", "intersect", "except", "into", "values",
}


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'", "`"):
        return s[1:-1]
    return s


def _normalize_table_ref(ref: str) -> Tuple[str, str]:
    """`schema.table` → ('schema', 'table'); `table` → ('', 'table')"""
    ref = _strip_quotes(ref)
    parts = ref.split(".")
    if len(parts) == 2:
        return parts[0].lower(), parts[1].lower()
    return "", parts[-1].lower()


def _parse_select_columns(sql: str) -> List[Tuple[Optional[str], str]]:
    """SELECT listesinden (alias_or_table, column) çiftleri çıkarır."""
    m = _SELECT_RE.search(sql)
    if not m:
        return []
    body = m.group(1)
    # `*` durumunu pas geç
    if "*" in body and "(" not in body:
        return []
    out: List[Tuple[Optional[str], str]] = []
    # `t.col`, `schema.t.col` pattern'leri
    for am in _COL_REF_RE.finditer(body):
        out.append((am.group(1).lower(), am.group(2).lower()))
    return out


def _parse_clause_columns(sql: str, clause_re) -> List[Tuple[Optional[str], str]]:
    m = clause_re.search(sql)
    if not m:
        return []
    body = m.group(1)
    out: List[Tuple[Optional[str], str]] = []
    for am in _COL_REF_RE.finditer(body):
        out.append((am.group(1).lower(), am.group(2).lower()))
    return out


def _parse_joins(sql: str) -> List[Tuple[Tuple[str, str], Tuple[str, str]]]:
    """JOIN ifadelerinden ((schema_a, tbl_a), (schema_b, tbl_b)) çiftleri çıkarır.

    FROM tablosu join'in sol tarafı kabul edilir; bunun yerine pratik olarak
    ON koşulundaki iki referansı kullanırız.
    """
    out: List[Tuple[Tuple[str, str], Tuple[str, str]]] = []
    for jm in _JOIN_RE.finditer(sql):
        on_clause = jm.group(3)
        refs = _COL_REF_RE.findall(on_clause)
        # ON koşulunda en az iki farklı alias görmeli
        seen: List[Tuple[str, str]] = []
        for alias, col in refs:
            key = (alias.lower(), col.lower())
            if not seen or seen[-1][0] != alias.lower():
                seen.append(key)
        if len(seen) >= 2:
            a = (seen[0][0],)  # alias
            b = (seen[1][0],)
            # alias'lar tablo adlarına eşit varsay (kaba). schema'yı bilmediğimiz
            # için boş bırakırız — meta'da tutulur.
            out.append((("", seen[0][0]), ("", seen[1][0])))
    return out


def _parse_alias_map(sql: str) -> Dict[str, str]:
    """`FROM x.tbl AS t` / `JOIN x.tbl t` ifadelerinden {alias_lower: table_lower} kurar.

    Tek-kelimelik referanslar için alias = tablo adı kabul edilir.
    """
    aliases: Dict[str, str] = {}
    # FROM
    for fm in _FROM_TABLE_RE.finditer(sql):
        ref = fm.group(1)
        alias = fm.group(2)
        sch, tbl = _normalize_table_ref(ref)
        if alias:
            a = _strip_quotes(alias).lower()
            if a not in _SQL_KEYWORDS:
                aliases[a] = tbl
        aliases.setdefault(tbl, tbl)
    # JOIN <table> [alias]
    for jm in _JOIN_RE.finditer(sql):
        ref = jm.group(1)
        alias = jm.group(2)
        sch, tbl = _normalize_table_ref(ref)
        if alias:
            a = _strip_quotes(alias).lower()
            if a not in _SQL_KEYWORDS:
                aliases[a] = tbl
        aliases.setdefault(tbl, tbl)
    return aliases


def parse_sql_decisions(sql: str) -> Dict[str, Any]:
    """Final SQL'den karar listelerini çıkar.

    Returns:
        {
          "alias_map":   {alias_lower: table_lower, ...},
          "select_cols": [(alias, col), ...],
          "filter_cols": [(alias, col), ...],
          "joins":       [((sch_a, tbl_a), (sch_b, tbl_b)), ...],
        }
    """
    if not sql:
        return {"alias_map": {}, "select_cols": [], "filter_cols": [], "joins": []}
    alias_map = _parse_alias_map(sql)
    select_cols = _parse_select_columns(sql)
    where_cols = _parse_clause_columns(sql, _WHERE_RE)
    having_cols = _parse_clause_columns(sql, _HAVING_RE)
    joins = _parse_joins(sql)
    # filter = WHERE + HAVING (dedup)
    fcols = list(dict.fromkeys(where_cols + having_cols))
    return {
        "alias_map": alias_map,
        "select_cols": select_cols,
        "filter_cols": fcols,
        "joins": joins,
    }


# ---------------------------------------------------------------------------
# Feature builders
# ---------------------------------------------------------------------------

def _type_buckets(dtype: Optional[str]) -> Tuple[int, int, int]:
    """data_type → (numeric, string, date) boolean flags."""
    if not dtype:
        return 0, 0, 0
    s = dtype.lower()
    is_num = any(t in s for t in ("int", "numeric", "decimal", "float", "double", "real", "number"))
    is_str = any(t in s for t in ("char", "text", "varchar", "string", "clob"))
    is_date = any(t in s for t in ("date", "time", "timestamp"))
    return int(is_num), int(is_str), int(is_date)


def _name_match_score(question_lc: str, col_name: str) -> float:
    """Basit token-overlap (TR-normalized değil — kaba)."""
    if not question_lc or not col_name:
        return 0.0
    cn = col_name.lower()
    if cn in question_lc:
        return 1.0
    # Snake/camel split
    parts = re.split(r"[_\s]+|(?<=[a-z])(?=[A-Z])", col_name)
    hits = sum(1 for p in parts if p and p.lower() in question_lc)
    return hits / max(len(parts), 1)


def _question_flags(question: str) -> Tuple[int, int]:
    if not question:
        return 0, 0
    q = question.lower()
    has_temporal = int(any(w in q for w in _TEMPORAL_WORDS))
    has_eq = int(any(w in q for w in _EQ_WORDS))
    return has_temporal, has_eq


def build_column_features(
    column: Dict[str, Any],
    *,
    table_rank: int,
    table_final_score: float,
    name_match: float,
    intent_confidence: float,
    candidate_count: int,
) -> Dict[str, float]:
    num, st, dt = _type_buckets(column.get("data_type"))
    return {
        "is_pk": int(bool(column.get("is_pk"))),
        "is_fk": int(bool(column.get("is_fk"))),
        "data_type_numeric": num,
        "data_type_string": st,
        "data_type_date": dt,
        "name_match_score": float(name_match),
        "table_rank": int(table_rank),
        "table_final_score": float(table_final_score),
        "intent_confidence": float(intent_confidence or 0.0),
        "candidate_count": int(candidate_count),
    }


def build_filter_features(
    column: Dict[str, Any],
    *,
    table_rank: int,
    name_match: float,
    has_temporal_word: int,
    has_eq_word: int,
    intent_confidence: float,
) -> Dict[str, float]:
    num, st, dt = _type_buckets(column.get("data_type"))
    return {
        "is_pk": int(bool(column.get("is_pk"))),
        "is_fk": int(bool(column.get("is_fk"))),
        "data_type_numeric": num,
        "data_type_string": st,
        "data_type_date": dt,
        "name_match_score": float(name_match),
        "table_rank": int(table_rank),
        "question_has_temporal_word": int(has_temporal_word),
        "question_has_eq_word": int(has_eq_word),
        "intent_confidence": float(intent_confidence or 0.0),
    }


def build_join_features(
    cand_a: Dict[str, Any],
    cand_b: Dict[str, Any],
    *,
    rank_a: int,
    rank_b: int,
    has_fk_relation: int,
    shared_column_count: int,
    intent_confidence: float,
    candidate_count: int,
) -> Dict[str, float]:
    return {
        "rank_a": int(rank_a),
        "rank_b": int(rank_b),
        "score_a": float(cand_a.get("final_score") or 0.0),
        "score_b": float(cand_b.get("final_score") or 0.0),
        "has_fk_relation": int(has_fk_relation),
        "shared_column_count": int(shared_column_count),
        "intent_confidence": float(intent_confidence or 0.0),
        "candidate_count": int(candidate_count),
    }


def features_to_vector(features: Dict[str, float], order: List[str]) -> List[float]:
    return [float(features.get(k, 0.0)) for k in order]


# ---------------------------------------------------------------------------
# Decision row collector — pipeline state'inden +/- örnek satırları
# ---------------------------------------------------------------------------

def _candidate_alias_set(cand: Dict[str, Any]) -> Set[str]:
    """Bir tablo için olası alias adları (table_name + schema.table)."""
    sch = (cand.get("schema_name") or "").lower()
    tbl = (cand.get("table_name") or "").lower()
    out = {tbl}
    if sch:
        out.add(f"{sch}.{tbl}")
    return out


def _columns_count_shared(cand_a: Dict[str, Any], cand_b: Dict[str, Any]) -> int:
    cols_a = {(c.get("column_name") or "").lower() for c in (cand_a.get("columns") or [])}
    cols_b = {(c.get("column_name") or "").lower() for c in (cand_b.get("columns") or [])}
    cols_a.discard("")
    return len(cols_a & cols_b)


def _has_fk_between(cand_a: Dict[str, Any], cand_b: Dict[str, Any]) -> bool:
    """Aday a'nın FK kolonu b'nin tablosunu işaret ediyorsa veya tersi."""
    tbl_b = (cand_b.get("table_name") or "").lower()
    tbl_a = (cand_a.get("table_name") or "").lower()
    for col in (cand_a.get("columns") or []):
        ref = (col.get("fk_table") or col.get("references_table") or "").lower()
        if ref and ref == tbl_b:
            return True
    for col in (cand_b.get("columns") or []):
        ref = (col.get("fk_table") or col.get("references_table") or "").lower()
        if ref and ref == tbl_a:
            return True
    return False


def collect_decision_rows(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pipeline run sonunda + ve - decision satırlarını üretir.

    Pozitif örnek: final SQL'de kullanılan kolon/filter/join.
    Negatif örnek: ranked_candidates içinde yer alıp final SQL'e GİRMEYENLER.
    """
    sql = (state.get("sql") or "").strip()
    if not sql:
        return []
    candidates = state.get("selected_tables") or state.get("ranked_candidates", [])[:5]
    if not candidates:
        return []
    parsed = parse_sql_decisions(sql)
    question = (state.get("question") or "").lower()
    intent_conf = float(state.get("intent_confidence") or 0.0)
    intent = state.get("intent")
    candidate_count = len(candidates)
    has_temporal, has_eq = _question_flags(question)

    import hashlib as _hl
    sql_norm = " ".join(sql.split()).strip().lower()
    sql_hash = _hl.sha1(sql_norm.encode("utf-8")).hexdigest()

    # SQL'den kullanılan kolon kümeleri — alias'a göre değil, table_name match'ine göre
    used_select: Set[Tuple[str, str]] = set()  # (table, col) lowercase
    used_filter: Set[Tuple[str, str]] = set()
    alias_map: Dict[str, str] = parsed.get("alias_map") or {}
    cand_table_lower = {(c.get("table_name") or "").lower() for c in candidates}

    def _resolve(alias: str, col: str) -> Optional[Tuple[str, str]]:
        """alias.col → (table_name_lower, col_lower). Eşleşme bulunamazsa None.

        1) alias_map ile aliası asıl tabloya çevir.
        2) Tabloyu candidate listesindeki tablo adlarıyla doğrula.
        3) Doğrudan eşleşme yoksa candidate alias kümelerine düş (schema.table biçimi).
        """
        a = alias.lower()
        mapped = alias_map.get(a)
        if mapped and mapped in cand_table_lower:
            return (mapped, col.lower())
        for cand in candidates:
            aliases = _candidate_alias_set(cand)
            if a in aliases:
                return ((cand.get("table_name") or "").lower(), col.lower())
        return None

    for alias, col in parsed["select_cols"]:
        r = _resolve(alias, col)
        if r:
            used_select.add(r)
    for alias, col in parsed["filter_cols"]:
        r = _resolve(alias, col)
        if r:
            used_filter.add(r)

    # JOIN positives: SQL'de tespit edilen alias çiftleri → tablo isimlerine map
    used_join_pairs: Set[Tuple[str, str]] = set()
    for (a_pair, b_pair) in parsed["joins"]:
        ta = alias_map.get(a_pair[1].lower(), a_pair[1].lower())
        tb = alias_map.get(b_pair[1].lower(), b_pair[1].lower())
        if ta in cand_table_lower and tb in cand_table_lower and ta != tb:
            pair = tuple(sorted((ta, tb)))
            used_join_pairs.add(pair)

    rows: List[Dict[str, Any]] = []

    # --- column decisions
    for rank, cand in enumerate(candidates):
        tbl = (cand.get("table_name") or "").lower()
        sch = (cand.get("schema_name") or "").lower()
        final_score = float(cand.get("final_score") or 0.0)
        for col in (cand.get("columns") or [])[:30]:
            cname = (col.get("column_name") or "").lower()
            if not cname:
                continue
            was = int((tbl, cname) in used_select)
            nm = _name_match_score(question, cname)
            feats = build_column_features(
                col,
                table_rank=rank,
                table_final_score=final_score,
                name_match=nm,
                intent_confidence=intent_conf,
                candidate_count=candidate_count,
            )
            rows.append({
                "decision_type": "column",
                "target_key": f"{sch}.{tbl}.{cname}" if sch else f"{tbl}.{cname}",
                "was_used": was,
                "features": feats,
                "meta": {"table": tbl, "schema": sch, "column": cname},
                "intent": intent,
                "sql_hash": sql_hash,
            })

    # --- filter decisions
    for rank, cand in enumerate(candidates):
        tbl = (cand.get("table_name") or "").lower()
        sch = (cand.get("schema_name") or "").lower()
        for col in (cand.get("columns") or [])[:30]:
            cname = (col.get("column_name") or "").lower()
            if not cname:
                continue
            was = int((tbl, cname) in used_filter)
            nm = _name_match_score(question, cname)
            feats = build_filter_features(
                col,
                table_rank=rank,
                name_match=nm,
                has_temporal_word=has_temporal,
                has_eq_word=has_eq,
                intent_confidence=intent_conf,
            )
            rows.append({
                "decision_type": "filter",
                "target_key": f"{sch}.{tbl}.{cname}" if sch else f"{tbl}.{cname}",
                "was_used": was,
                "features": feats,
                "meta": {"table": tbl, "schema": sch, "column": cname},
                "intent": intent,
                "sql_hash": sql_hash,
            })

    # --- join decisions
    n = len(candidates)
    for i in range(n):
        for j in range(i + 1, n):
            ca, cb = candidates[i], candidates[j]
            ta = (ca.get("table_name") or "").lower()
            tb = (cb.get("table_name") or "").lower()
            if not ta or not tb or ta == tb:
                continue
            pair = tuple(sorted((ta, tb)))
            was = int(pair in used_join_pairs)
            shared = _columns_count_shared(ca, cb)
            fk = int(_has_fk_between(ca, cb))
            feats = build_join_features(
                ca, cb,
                rank_a=i, rank_b=j,
                has_fk_relation=fk,
                shared_column_count=shared,
                intent_confidence=intent_conf,
                candidate_count=candidate_count,
            )
            rows.append({
                "decision_type": "join",
                "target_key": f"{pair[0]}::{pair[1]}",
                "was_used": was,
                "features": feats,
                "meta": {"table_a": pair[0], "table_b": pair[1]},
                "intent": intent,
                "sql_hash": sql_hash,
            })

    return rows


def persist_decisions(cur, state: Dict[str, Any], rows: List[Dict[str, Any]]) -> int:
    """Batch INSERT — agentic_query_decisions. Sessizce başarısız (best-effort)."""
    if not rows:
        return 0
    import json as _json
    company_id = state.get("company_id")
    source_id = state.get("source_id")
    user_id = state.get("user_id")
    run_id = state.get("_pipeline_run_id")
    sql = """
        INSERT INTO agentic_query_decisions
            (run_id, company_id, source_id, user_id,
             decision_type, target_key, was_used, features, meta,
             intent, sql_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
    """
    n = 0
    for r in rows:
        try:
            cur.execute(sql, (
                run_id, company_id, source_id, user_id,
                r["decision_type"], r["target_key"], int(r["was_used"]),
                _json.dumps(r["features"]),
                _json.dumps(r.get("meta") or {}),
                r.get("intent"),
                r.get("sql_hash"),
            ))
            n += 1
        except Exception:
            continue
    return n
