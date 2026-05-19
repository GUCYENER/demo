"""VYRA v3.29.1 — Code Value Extractor (Faz 6 G2).

ds_db_samples.sample_data JSONB içeriklerinden, kardinalitesi düşük
(≤ MAX_DISTINCT) string kolonların DISTINCT değerlerini topla;
opsiyonel LLM çağrısıyla Türkçe etiket öner; ds_code_values'a UPSERT et.

Kullanım:
    from app.services.db_learning import code_value_extractor
    stats = code_value_extractor.extract_from_samples(cur, source_id, company_id)

Algoritma:
    1. ds_db_samples JOIN ds_db_objects ile (schema, table) bazlı sample_data oku
    2. ds_db_objects.columns_json'dan string-türü kolonları belirle (text, varchar, char, code, enum)
    3. Her (table, column) için DISTINCT değer sayımı
        - <= 1: muhtemelen tek-değerli, atla
        - > MAX_DISTINCT (30): code dictionary değil, atla
    4. Her distinct değer için UPSERT (source_id, table, column, code_value)
        - confidence: sample_scan yolu → 0.40 (LLM'siz)
        - LLM enriched → 0.85 (admin onay gerekmiyor ama admin_verified=FALSE)
    5. label_tr eksikse `llm_label_fn` opsiyonel — None ise bos bırakılır.

LLM enjeksiyonu: caller tarafından opsiyonel callable verilir
    llm_label_fn(table, column, code_value) -> {"label_tr": str, "label_en": str|None, "description_tr": str|None}
Hata durumunda None döner; biz sadece sample_scan ile yazarız.

LOOKUP:
    lookup_label(cur, source_id, table, column, code_value) → label_tr | None
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


MAX_DISTINCT = 30
MIN_DISTINCT = 2
STRING_TYPES = {
    "text", "varchar", "char", "character", "character varying",
    "code", "enum", "string", "bpchar", "name",
}


# ─────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    return ("" if s is None else str(s)).strip().lower()


def _is_string_type(col_type: Optional[str]) -> bool:
    if not col_type:
        return False
    t = str(col_type).strip().lower()
    # PG-specific normalization
    for key in STRING_TYPES:
        if key in t:
            return True
    return False


def _load_string_columns(cur, source_id: int) -> Dict[Tuple[str, str], List[str]]:
    """Tablo → string-tür kolon adları."""
    cur.execute(
        """
        SELECT schema_name, object_name, columns_json
        FROM ds_db_objects
        WHERE source_id = %s AND object_type IN ('table','view')
        """,
        (source_id,),
    )
    out: Dict[Tuple[str, str], List[str]] = {}
    for row in cur.fetchall():
        if isinstance(row, dict):
            sch, name, cols = row.get("schema_name"), row.get("object_name"), row.get("columns_json")
        else:
            sch, name, cols = row[0], row[1], row[2]
        if isinstance(cols, str):
            try:
                cols = json.loads(cols)
            except Exception:
                cols = []
        if not isinstance(cols, list):
            continue
        str_cols = [c.get("name") for c in cols if c.get("name") and _is_string_type(c.get("type"))]
        if str_cols:
            out[(_norm(sch), _norm(name))] = str_cols
    return out


def _load_samples(cur, source_id: int) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """ds_db_samples'tan her tablo için sample_data satırlarını topla."""
    cur.execute(
        """
        SELECT o.schema_name, o.object_name, s.sample_data
        FROM ds_db_samples s
        JOIN ds_db_objects o ON s.object_id = o.id
        WHERE s.source_id = %s
        """,
        (source_id,),
    )
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in cur.fetchall():
        if isinstance(row, dict):
            sch, name, data = row.get("schema_name"), row.get("object_name"), row.get("sample_data")
        else:
            sch, name, data = row[0], row[1], row[2]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                data = []
        if not isinstance(data, list):
            continue
        # data: [{col: val, ...}, ...]
        out[(_norm(sch), _norm(name))].extend(d for d in data if isinstance(d, dict))
    return out


def _distinct_per_column(
    rows: List[Dict[str, Any]],
    str_cols: List[str],
) -> Dict[str, Set[str]]:
    """Her string kolon için DISTINCT değer kümesi."""
    out: Dict[str, Set[str]] = defaultdict(set)
    for r in rows:
        for c in str_cols:
            if c not in r:
                continue
            v = r[c]
            if v is None:
                continue
            sv = str(v).strip()
            if not sv:
                continue
            # Long values are not code dictionaries
            if len(sv) > 64:
                continue
            out[c].add(sv)
    return out


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def extract_from_samples(
    cur,
    source_id: int,
    company_id: Optional[int] = None,
    *,
    llm_label_fn: Optional[Callable[[str, str, str], Optional[Dict[str, Any]]]] = None,
    max_distinct: int = MAX_DISTINCT,
) -> Dict[str, Any]:
    """Sample data'dan code value sözlüğü inşa et.

    Args:
        cur: psycopg cursor (caller commit'lemekten sorumlu)
        source_id: data_sources.id
        company_id: tenant scope
        llm_label_fn: opsiyonel TR etiket üretici
        max_distinct: kardinalite üst sınırı (default 30)

    Returns:
        {
            "tables_scanned": int,
            "columns_scanned": int,
            "code_columns_detected": int,
            "values_upserted": int,
            "llm_labeled": int,
            "skipped_cardinality": int,
            "errors": [...]
        }
    """
    if not source_id:
        return {"errors": ["empty source_id"]}

    errors: List[str] = []
    try:
        str_cols_by_tbl = _load_string_columns(cur, source_id)
        samples_by_tbl = _load_samples(cur, source_id)
    except Exception as exc:
        logger.exception("[CodeValue] load failed source_id=%s", source_id)
        return {"errors": [f"{type(exc).__name__}: {str(exc)[:200]}"]}

    if not samples_by_tbl:
        return {
            "tables_scanned": 0, "columns_scanned": 0, "code_columns_detected": 0,
            "values_upserted": 0, "llm_labeled": 0, "skipped_cardinality": 0, "errors": [],
        }

    tables_scanned = 0
    columns_scanned = 0
    code_columns_detected = 0
    values_upserted = 0
    llm_labeled = 0
    skipped_cardinality = 0

    for tbl_key, rows in samples_by_tbl.items():
        str_cols = str_cols_by_tbl.get(tbl_key)
        if not str_cols:
            continue
        tables_scanned += 1
        distinct_map = _distinct_per_column(rows, str_cols)
        for col_name, values in distinct_map.items():
            columns_scanned += 1
            n = len(values)
            if n < MIN_DISTINCT or n > max_distinct:
                skipped_cardinality += 1
                continue
            code_columns_detected += 1
            sch, tbl = tbl_key
            for code_val in sorted(values):
                label_tr = None
                label_en = None
                desc_tr = None
                conf = 0.40
                if llm_label_fn:
                    try:
                        suggestion = llm_label_fn(tbl, col_name, code_val)
                        if suggestion:
                            label_tr = suggestion.get("label_tr")
                            label_en = suggestion.get("label_en")
                            desc_tr = suggestion.get("description_tr")
                            if label_tr:
                                conf = 0.85
                                llm_labeled += 1
                    except Exception as exc:
                        errors.append(f"llm[{tbl}.{col_name}={code_val}]: {type(exc).__name__}")
                        if len(errors) >= 50:
                            break
                inferred_by = "llm" if label_tr and llm_label_fn else "sample_scan"
                try:
                    cur.execute(
                        """
                        INSERT INTO ds_code_values
                            (source_id, company_id, table_name, column_name, code_value,
                             label_tr, label_en, description_tr,
                             inferred_by, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_id, table_name, column_name, code_value)
                        DO UPDATE SET
                            label_tr       = COALESCE(EXCLUDED.label_tr, ds_code_values.label_tr),
                            label_en       = COALESCE(EXCLUDED.label_en, ds_code_values.label_en),
                            description_tr = COALESCE(EXCLUDED.description_tr, ds_code_values.description_tr),
                            confidence     = GREATEST(ds_code_values.confidence, EXCLUDED.confidence),
                            updated_at     = NOW()
                        """,
                        (
                            source_id, company_id,
                            (tbl or "")[:256], (col_name or "")[:256], (code_val or "")[:256],
                            label_tr, label_en, desc_tr,
                            inferred_by, conf,
                        ),
                    )
                    values_upserted += 1
                except Exception as exc:
                    errors.append(f"upsert[{tbl}.{col_name}={code_val}]: {type(exc).__name__}: {str(exc)[:120]}")
                    if len(errors) >= 50:
                        break

    logger.info(
        "[CodeValue] source_id=%s tables=%d cols=%d code_cols=%d upserted=%d llm=%d skipped=%d errs=%d",
        source_id, tables_scanned, columns_scanned, code_columns_detected,
        values_upserted, llm_labeled, skipped_cardinality, len(errors),
    )
    return {
        "tables_scanned": tables_scanned,
        "columns_scanned": columns_scanned,
        "code_columns_detected": code_columns_detected,
        "values_upserted": values_upserted,
        "llm_labeled": llm_labeled,
        "skipped_cardinality": skipped_cardinality,
        "errors": errors,
    }


def lookup_label(
    cur,
    source_id: int,
    table_name: str,
    column_name: str,
    code_value: str,
) -> Optional[Dict[str, Any]]:
    """Tek code lookup — pipeline'da intent/sql_generate node'undan çağrılır."""
    if not (source_id and table_name and column_name and code_value):
        return None
    cur.execute(
        """
        SELECT label_tr, label_en, description_tr, confidence, inferred_by
        FROM ds_code_values
        WHERE source_id = %s AND table_name = %s AND column_name = %s AND code_value = %s
          AND is_active = TRUE
        LIMIT 1
        """,
        (source_id, table_name, column_name, code_value),
    )
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        out = dict(row)
    else:
        out = {
            "label_tr": row[0], "label_en": row[1],
            "description_tr": row[2], "confidence": row[3],
            "inferred_by": row[4],
        }
    # usage_count bump (best-effort)
    try:
        cur.execute(
            """
            UPDATE ds_code_values
               SET usage_count = usage_count + 1,
                   last_used_at = NOW()
             WHERE source_id = %s AND table_name = %s AND column_name = %s AND code_value = %s
            """,
            (source_id, table_name, column_name, code_value),
        )
    except Exception:
        pass
    return out


def list_for_column(
    cur,
    source_id: int,
    table_name: str,
    column_name: str,
    only_active: bool = True,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Bir kolonun tüm code value listesi — prompt enjeksiyonu için."""
    where = "source_id = %s AND table_name = %s AND column_name = %s"
    args: List[Any] = [source_id, table_name, column_name]
    if only_active:
        where += " AND is_active = TRUE"
    cur.execute(
        f"""
        SELECT code_value, label_tr, label_en, description_tr, confidence, ordinal, inferred_by
        FROM ds_code_values
        WHERE {where}
        ORDER BY ordinal NULLS LAST, code_value
        LIMIT %s
        """,
        tuple(args + [int(limit)]),
    )
    rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(dict(r))
        else:
            out.append({
                "code_value": r[0], "label_tr": r[1], "label_en": r[2],
                "description_tr": r[3], "confidence": r[4],
                "ordinal": r[5], "inferred_by": r[6],
            })
    return out


def upsert_admin(
    cur,
    *,
    source_id: int,
    company_id: Optional[int],
    table_name: str,
    column_name: str,
    code_value: str,
    label_tr: Optional[str] = None,
    label_en: Optional[str] = None,
    description_tr: Optional[str] = None,
    ordinal: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> Dict[str, Any]:
    """Admin manuel ekleme/güncelleme — inferred_by='admin', confidence=1.0."""
    if not (source_id and table_name and column_name and code_value):
        return {"status": "error", "error": "missing fields"}
    try:
        cur.execute(
            """
            INSERT INTO ds_code_values
                (source_id, company_id, table_name, column_name, code_value,
                 label_tr, label_en, description_tr, ordinal,
                 is_active, inferred_by, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    COALESCE(%s, TRUE), 'admin', 1.0)
            ON CONFLICT (source_id, table_name, column_name, code_value)
            DO UPDATE SET
                label_tr       = COALESCE(EXCLUDED.label_tr, ds_code_values.label_tr),
                label_en       = COALESCE(EXCLUDED.label_en, ds_code_values.label_en),
                description_tr = COALESCE(EXCLUDED.description_tr, ds_code_values.description_tr),
                ordinal        = COALESCE(EXCLUDED.ordinal, ds_code_values.ordinal),
                is_active      = COALESCE(EXCLUDED.is_active, ds_code_values.is_active),
                inferred_by    = 'admin',
                confidence     = 1.0,
                updated_at     = NOW()
            RETURNING id
            """,
            (
                source_id, company_id,
                table_name[:256], column_name[:256], code_value[:256],
                label_tr, label_en, description_tr, ordinal,
                is_active,
            ),
        )
        rid = cur.fetchone()
        rid_val = (rid[0] if not isinstance(rid, dict) else rid.get("id")) if rid else None
        return {"status": "ok", "id": rid_val}
    except Exception as exc:
        logger.exception("[CodeValue] admin upsert failed")
        return {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


# ─────────────────────────────────────────────────────────────
# v3.29.5 Faz 7 — Scheduler hook: stale source'ları otomatik yenile
# ─────────────────────────────────────────────────────────────

def rescan_stale_sources(min_age_minutes: int = 60, max_sources: int = 5) -> int:
    """Son taraması eski olan source'lar için extract_from_samples'ı yeniden çalıştır.

    "Stale" tanımı: ds_db_samples.fetched_at MAX(updated_at(ds_code_values)) >
    min_age_minutes ÖNCESINE göre yeniyse (yani sample'lar code_value'lardan
    sonra güncellenmiş) → yeniden tarama gerek.

    Returns:
        İşlenen source sayısı (best-effort; hatalar log'lanır, döngü kırılmaz).
    """
    from app.core.db import get_db_context, apply_company_scope

    processed = 0
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                # Tenant-bazlı ayrı işle — RLS PERMISSIVE; scope set etmeden de bu
                # sorgu çalışır ama biz her source'u kendi company_id'sine set edip
                # extract çağırıyoruz (cross-tenant kaçak yok).
                cur.execute(
                    """
                    SELECT s.id AS source_id, s.company_id,
                           MAX(samp.fetched_at)  AS last_sample,
                           MAX(cv.updated_at)    AS last_cv
                    FROM data_sources s
                    JOIN ds_db_samples samp ON samp.source_id = s.id
                    LEFT JOIN ds_code_values cv ON cv.source_id = s.id
                    GROUP BY s.id, s.company_id
                    HAVING MAX(samp.fetched_at) IS NOT NULL
                       AND (
                            MAX(cv.updated_at) IS NULL
                            OR MAX(samp.fetched_at) > MAX(cv.updated_at) + (%s || ' minutes')::interval
                       )
                    ORDER BY MAX(samp.fetched_at) DESC
                    LIMIT %s
                    """,
                    (str(min_age_minutes), max_sources),
                )
                rows = cur.fetchall() or []
            finally:
                cur.close()

            for r in rows:
                sid = int(r[0])
                cid = int(r[1] or 0) or None
                cur2 = conn.cursor()
                try:
                    if cid:
                        apply_company_scope(cur2, company_id=cid)
                    result = extract_from_samples(cur2, source_id=sid, company_id=cid)
                    conn.commit()
                    if not result.get("errors"):
                        processed += 1
                    else:
                        logger.warning(
                            "[CodeValue.rescan] source_id=%s partial errors: %s",
                            sid, result.get("errors"),
                        )
                except Exception as exc:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logger.warning("[CodeValue.rescan] source_id=%s failed: %s", sid, exc)
                finally:
                    cur2.close()
    except Exception as exc:
        logger.warning("[CodeValue.rescan] outer failed: %s", exc)
    return processed
