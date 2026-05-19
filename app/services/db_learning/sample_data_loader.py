"""VYRA v3.29.3 — Sample Data Loader (G4).

ds_db_samples + ds_column_enrichments birleştirerek, her tablo için
prompt'a uygun (PII-maskeli, token-budget'lı) örnek satır dilimi üretir.

Public API:
    load_samples_for_tables(cur, source_id, tables, *, rows_per_table=3,
                            char_budget_per_row=200, max_chars_per_table=600,
                            mask=True) -> Dict[full_table, SamplePayload]
    mask_value(value, strategy='redact') -> str
    format_for_prompt(payloads) -> str   # "SAMPLE DATA:\n  …" blok metni

`tables` her bir item: {"schema_name": str|None, "table_name": str}.
Sonuç payload:
    {
      "full": "schema.table",
      "rows": [{col: masked_value, ...}, ...],   # max rows_per_table
      "columns": [col_name, ...],                # rows sırasındaki kolonlar
      "masked_columns": [col_name, ...],         # is_pii=TRUE eşleşenler
      "truncated": bool,
    }
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_ROWS_PER_TABLE = 3
DEFAULT_CHAR_BUDGET_PER_ROW = 200
DEFAULT_MAX_CHARS_PER_TABLE = 600


# ─────────────────────────────────────────────────────────────
# PII Masking
# ─────────────────────────────────────────────────────────────

def mask_value(value: Any, strategy: str = "redact") -> str:
    """PII değerini stratejiye göre maskele.

    redact   → "***"
    partial  → ilk + son char görünür, ortası "*"  ("ahmet@x.com" → "a***m")
    hash     → 8-char sha1 prefix
    none     → string-cast (mask uygulanmaz)
    """
    if value is None:
        return ""
    s = str(value)
    if strategy == "none":
        return s
    if strategy == "hash":
        return "#" + hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:8]
    if strategy == "partial":
        if len(s) <= 2:
            return "*" * len(s)
        return s[0] + "*" * max(1, len(s) - 2) + s[-1]
    # default → redact
    return "***"


# ─────────────────────────────────────────────────────────────
# Lookup helpers
# ─────────────────────────────────────────────────────────────

def _pii_map(cur, source_id: int, schema: Optional[str], table: str) -> Dict[str, str]:
    """ds_column_enrichments'tan tablonun is_pii=TRUE kolonları + stratejisi.

    Returns: {column_name: strategy}
    """
    try:
        cur.execute(
            """
            SELECT ce.column_name, COALESCE(ce.pii_mask_strategy, 'redact') AS strat
            FROM ds_column_enrichments ce
            JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
            WHERE ce.source_id = %s
              AND ce.is_pii = TRUE
              AND te.table_name = %s
              AND (te.schema_name = %s OR (te.schema_name IS NULL AND %s IS NULL))
            """,
            (source_id, table, schema, schema),
        )
        out: Dict[str, str] = {}
        for r in cur.fetchall() or []:
            col = r["column_name"] if hasattr(r, "get") else r[0]
            strat = (r["strat"] if hasattr(r, "get") else r[1]) or "redact"
            out[col] = strat
        return out
    except Exception as exc:
        logger.debug("[sample_loader.pii_map] %s", exc)
        return {}


def _fetch_sample_rows(
    cur,
    source_id: int,
    schema: Optional[str],
    table: str,
    rows_per_table: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """ds_db_samples'tan en yeni sample_data JSONB'sini çek + ilk N satırını döndür."""
    try:
        cur.execute(
            """
            SELECT s.sample_data, s.row_count
            FROM ds_db_samples s
            JOIN ds_db_objects o ON o.id = s.object_id
            WHERE s.source_id = %s
              AND o.table_name = %s
              AND (o.schema_name = %s OR (o.schema_name IS NULL AND %s IS NULL))
            ORDER BY s.fetched_at DESC
            LIMIT 1
            """,
            (source_id, table, schema, schema),
        )
        row = cur.fetchone()
    except Exception as exc:
        logger.debug("[sample_loader.fetch_rows] %s", exc)
        return [], []
    if not row:
        return [], []
    data = row["sample_data"] if hasattr(row, "get") else row[0]
    if isinstance(data, str):
        # JSONB bazen string olarak gelebilir
        import json
        try:
            data = json.loads(data)
        except Exception:
            return [], []
    if not isinstance(data, list) or not data:
        return [], []
    rows = data[:rows_per_table]
    # Kolon sırası: ilk satırın anahtarları
    columns: List[str] = list(rows[0].keys()) if isinstance(rows[0], dict) else []
    return rows, columns


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def load_samples_for_tables(
    cur,
    source_id: int,
    tables: List[Dict[str, Any]],
    *,
    rows_per_table: int = DEFAULT_ROWS_PER_TABLE,
    char_budget_per_row: int = DEFAULT_CHAR_BUDGET_PER_ROW,
    max_chars_per_table: int = DEFAULT_MAX_CHARS_PER_TABLE,
    mask: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Her tablo için maskelenmiş sample rows döndür.

    Args:
        tables: [{"schema_name": str|None, "table_name": str}, ...]
        rows_per_table: max satır
        char_budget_per_row: her satır string-temsili bu cap'i aşarsa truncate
        max_chars_per_table: tablonun toplam char budget'ı
        mask: False → PII mask devre dışı (test/dev için)

    Returns:
        {"schema.table" or "table": SamplePayload}
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not tables:
        return out
    for t in tables:
        schema = (t.get("schema_name") or "").strip() or None
        table = (t.get("table_name") or "").strip()
        if not table:
            continue
        full = f"{schema}.{table}" if schema and schema != "public" else table

        rows, columns = _fetch_sample_rows(cur, source_id, schema, table, rows_per_table)
        if not rows:
            continue

        pii = _pii_map(cur, source_id, schema, table) if mask else {}

        masked_rows: List[Dict[str, Any]] = []
        total_chars = 0
        truncated = False
        for r in rows:
            if not isinstance(r, dict):
                continue
            mr: Dict[str, Any] = {}
            char_used = 0
            for k, v in r.items():
                if k in pii:
                    masked = mask_value(v, pii[k])
                else:
                    s = "" if v is None else str(v)
                    masked = s if len(s) <= 60 else (s[:57] + "...")
                # char budget per-row
                if char_used + len(str(masked)) > char_budget_per_row:
                    truncated = True
                    break
                mr[k] = masked
                char_used += len(str(masked))
            masked_rows.append(mr)
            total_chars += char_used
            if total_chars > max_chars_per_table:
                truncated = True
                break

        out[full] = {
            "full": full,
            "schema": schema,
            "table": table,
            "rows": masked_rows,
            "columns": columns,
            "masked_columns": sorted(pii.keys()),
            "truncated": truncated,
        }
    return out


def format_for_prompt(payloads: Dict[str, Dict[str, Any]]) -> str:
    """SAMPLE DATA bloğunu LLM prompt'a hazır metne çevir."""
    if not payloads:
        return ""
    lines: List[str] = ["SAMPLE DATA (PII-maskeli, prompt budget'lı):"]
    for full, p in payloads.items():
        lines.append(f"  {full}:")
        cols = p.get("columns") or []
        for row in p.get("rows") or []:
            kv = ", ".join(f"{k}={row.get(k)}" for k in cols if k in row)
            if kv:
                lines.append(f"    - {kv}")
        if p.get("masked_columns"):
            lines.append(f"    [PII maskeli kolonlar: {', '.join(p['masked_columns'])}]")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_ROWS_PER_TABLE",
    "DEFAULT_CHAR_BUDGET_PER_ROW",
    "DEFAULT_MAX_CHARS_PER_TABLE",
    "mask_value",
    "load_samples_for_tables",
    "format_for_prompt",
]
