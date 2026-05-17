"""
metric_registry — v3.26.0 Faz 3 (P1-b)
=======================================
Semantic/Metric Layer servisi. Kullanıcı doğal dilinden → kanonik metrik
tanımına eşleşme + SQL bağlamı zenginleştirme.

Public API:
    list_metrics(cur, company_id, source_id=None) -> List[dict]
    get_metric(cur, metric_id, company_id) -> Optional[dict]
    create_metric(cur, company_id, **fields) -> int
    update_metric(cur, metric_id, company_id, **fields) -> bool
    delete_metric(cur, metric_id, company_id) -> bool
    resolve_metrics_in_question(question, metrics) -> List[dict]  (matched)
    format_metrics_for_prompt(metrics) -> str
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


_METRIC_COLS = [
    "id", "company_id", "source_id", "name", "display_name", "description",
    "sql_expression", "base_tables", "dimensions", "filters", "unit",
    "aggregation_type", "synonyms", "is_active", "created_by",
    "created_at", "updated_at",
]


def _row_to_dict(row: Any, cols: List[str]) -> Dict[str, Any]:
    if isinstance(row, dict):
        return {k: row.get(k) for k in cols}
    return {cols[i]: row[i] for i in range(len(cols))}


def list_metrics(
    cur,
    company_id: int,
    source_id: Optional[int] = None,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    """Tenant'a ait metric tanımlarını döner."""
    where = ["company_id = %s"]
    params: List[Any] = [company_id]
    if source_id is not None:
        # source_id NULL → tüm sources için geçerli; spesifik source seçilirse ikisi de gelsin
        where.append("(source_id IS NULL OR source_id = %s)")
        params.append(source_id)
    if not include_inactive:
        where.append("is_active = TRUE")
    sql = f"""
        SELECT {', '.join(_METRIC_COLS)}
          FROM metric_definitions
         WHERE {' AND '.join(where)}
         ORDER BY display_name ASC
    """
    cur.execute(sql, params)
    rows = cur.fetchall() or []
    return [_row_to_dict(r, _METRIC_COLS) for r in rows]


def get_metric(cur, metric_id: int, company_id: int) -> Optional[Dict[str, Any]]:
    sql = f"""
        SELECT {', '.join(_METRIC_COLS)}
          FROM metric_definitions
         WHERE id = %s AND company_id = %s
    """
    cur.execute(sql, (metric_id, company_id))
    row = cur.fetchone()
    return _row_to_dict(row, _METRIC_COLS) if row else None


def create_metric(
    cur,
    company_id: int,
    name: str,
    display_name: str,
    sql_expression: str,
    *,
    source_id: Optional[int] = None,
    description: Optional[str] = None,
    base_tables: Optional[List[str]] = None,
    dimensions: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    unit: Optional[str] = None,
    aggregation_type: Optional[str] = None,
    synonyms: Optional[List[str]] = None,
    created_by: Optional[int] = None,
) -> int:
    """Yeni metric oluşturur. Aynı (company_id, name) varsa IntegrityError."""
    cur.execute("""
        INSERT INTO metric_definitions
            (company_id, source_id, name, display_name, description,
             sql_expression, base_tables, dimensions, filters, unit,
             aggregation_type, synonyms, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        RETURNING id
    """, (
        company_id, source_id, name, display_name, description,
        sql_expression, base_tables or [], dimensions or [],
        json.dumps(filters or {}), unit, aggregation_type,
        synonyms or [], created_by,
    ))
    row = cur.fetchone()
    return int(row[0] if not isinstance(row, dict) else row["id"])


def update_metric(cur, metric_id: int, company_id: int, **fields) -> bool:
    """Verilen alanları günceller. is_active toggle dahil."""
    allowed = {
        "display_name", "description", "sql_expression", "base_tables",
        "dimensions", "filters", "unit", "aggregation_type", "synonyms",
        "is_active",
    }
    sets: List[str] = []
    params: List[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "filters" and v is not None:
            sets.append(f"{k} = %s::jsonb")
            params.append(json.dumps(v))
        else:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_at = NOW()")
    params.extend([metric_id, company_id])
    cur.execute(
        f"UPDATE metric_definitions SET {', '.join(sets)} WHERE id = %s AND company_id = %s",
        params,
    )
    return cur.rowcount > 0


def delete_metric(cur, metric_id: int, company_id: int) -> bool:
    cur.execute(
        "DELETE FROM metric_definitions WHERE id = %s AND company_id = %s",
        (metric_id, company_id),
    )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# NL eşleşme — kullanıcı sorusunda metric tespiti
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Türkçe lowercase + basit normalize."""
    if not text:
        return ""
    # Türkçe karakterleri ASCII'ye yaklaşır (kaba)
    tr_map = str.maketrans("ÇĞİÖŞÜçğıöşü", "CGIOSUcgiosu")
    return text.translate(tr_map).lower()


def resolve_metrics_in_question(
    question: str, metrics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Soruda geçen metric'leri tespit eder (display_name, name, synonyms eşleşmesi).

    Strateji:
        - Tam ifade eşleşmesi (case-insensitive, TR-normalize)
        - Önce display_name → sonra synonyms → en son name (snake_case)
        - Skor: ifade uzunluğu (daha uzun eşleşme daha güçlü)

    Returns: matched metric dict listesi (en güçlü eşleşme ilk).
    """
    if not question or not metrics:
        return []
    q_norm = _normalize(question)
    out: List[Dict[str, Any]] = []
    for m in metrics:
        if not m.get("is_active", True):
            continue
        targets: List[str] = []
        if m.get("display_name"):
            targets.append(m["display_name"])
        targets.extend(m.get("synonyms") or [])
        # name (snake_case) — boşluksuz, son aday
        if m.get("name"):
            targets.append(m["name"].replace("_", " "))
        best_len = 0
        matched_phrase = None
        for t in targets:
            t_norm = _normalize(t)
            if not t_norm or len(t_norm) < 3:
                continue
            # word-boundary kontrolü
            if re.search(rf"\b{re.escape(t_norm)}\b", q_norm):
                if len(t_norm) > best_len:
                    best_len = len(t_norm)
                    matched_phrase = t
        if matched_phrase is not None:
            mm = dict(m)
            mm["_matched_phrase"] = matched_phrase
            mm["_match_score"] = best_len
            out.append(mm)
    out.sort(key=lambda x: x.get("_match_score", 0), reverse=True)
    return out


def format_metrics_for_prompt(metrics: List[Dict[str, Any]], *, limit: int = 5) -> str:
    """
    sql_generate prompt'una eklenecek "Tanımlı Metrikler" bloğunu üretir.

    Format:
        TANIMLI METRİKLER:
          - <display_name> (`name`): <description>
            SQL: <sql_expression kısa>
            Tablolar: <base_tables>
    """
    if not metrics:
        return ""
    lines: List[str] = ["TANIMLI METRİKLER:"]
    for m in metrics[:limit]:
        nm = m.get("name") or ""
        dn = m.get("display_name") or nm
        desc = m.get("description") or ""
        expr = (m.get("sql_expression") or "").strip()
        if len(expr) > 200:
            expr = expr[:197] + "..."
        bt = m.get("base_tables") or []
        line = f"  - {dn} (`{nm}`)"
        if desc:
            line += f": {desc}"
        lines.append(line)
        if expr:
            lines.append(f"    SQL: {expr}")
        if bt:
            lines.append(f"    Tablolar: {', '.join(bt)}")
    lines.append(
        "NOT: Kullanıcı bu metriklerden birini kastetmiş olabilir. Sorgudan emin "
        "değilsen önce metric SQL ifadesini referans al."
    )
    return "\n".join(lines)
