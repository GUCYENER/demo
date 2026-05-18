"""VYRA v3.27.0 — Schema Drift Detector (B.G6).

ds_diff_service.create_snapshot çıkışındaki `diff` dict'inden tüketir;
tablodaki + kolondaki değişikliklere göre öğrenilmiş kayıtları invalidate eder.

İnvalidation aksiyonları (G6.3):
  * learned_db_queries.is_active = FALSE
      → schema_signature içinde silinen/modifiye tablo geçen kayıtlar
  * few_shot_examples.success_rate *= 0.5
      → aynı schema_signature içerenler (cezalandır, kaldırma)
  * ds_column_embeddings DELETE
      → silinen kolonlar (modifiye tablodaki "removed_columns")

Notification (G6.4):
  * pipeline_events INSERT — event_type='schema_drift'
    metadata: {added, removed, modified, invalidated_learned, penalized_few_shot, dropped_embeddings}
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DTO
# ─────────────────────────────────────────────────────────────

@dataclass
class DriftActionSummary:
    source_id: int
    added_tables: List[str] = field(default_factory=list)
    removed_tables: List[str] = field(default_factory=list)
    modified_tables: List[str] = field(default_factory=list)
    invalidated_learned: int = 0
    penalized_few_shot: int = 0
    dropped_column_embeddings: int = 0
    skipped: bool = False
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _table_keys(items: Iterable[Any]) -> List[str]:
    """Diff item listesinden 'schema.table' string listesi çıkar."""
    out: List[str] = []
    for it in items or []:
        if isinstance(it, str):
            out.append(it.strip().lower())
        elif isinstance(it, dict):
            sch = (it.get("schema") or it.get("schema_name") or "").strip()
            tbl = (it.get("table") or it.get("table_name") or it.get("name") or "").strip()
            if tbl:
                key = f"{sch}.{tbl}".lower() if sch else tbl.lower()
                out.append(key)
    return out


def _collect_removed_columns(modified: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Modified tablolarda silinen kolonları topla.

    Beklenen yapı (ds_diff_service.compute_diff çıktısı):
      modified_tables: [{"schema":..., "table":..., "removed_columns": [...], ...}]
    """
    out: List[Dict[str, str]] = []
    for m in modified or []:
        if not isinstance(m, dict):
            continue
        sch = (m.get("schema") or m.get("schema_name") or "").strip()
        tbl = (m.get("table") or m.get("table_name") or "").strip()
        removed = m.get("removed_columns") or m.get("removed_cols") or []
        for col in removed:
            col_name = col if isinstance(col, str) else col.get("name") or col.get("column_name")
            if not col_name:
                continue
            out.append({
                "schema_name": sch,
                "table_name": tbl,
                "column_name": col_name,
            })
    return out


# ─────────────────────────────────────────────────────────────
# Invalidation actions
# ─────────────────────────────────────────────────────────────

def _invalidate_learned_for_tables(cur, source_id: int, table_keys: List[str]) -> int:
    """schema_signature içinde herhangi bir etkilenen tablo geçen kayıtları pasifleştir."""
    if not table_keys:
        return 0
    total = 0
    for key in table_keys:
        # schema_signature 'schema.tableA,schema.tableB' formatında — LIKE ile içerme kontrol
        like_pattern = f"%{key}%"
        try:
            cur.execute(
                """
                UPDATE learned_db_queries
                SET is_active = FALSE
                WHERE source_id = %s
                  AND is_active = TRUE
                  AND schema_signature ILIKE %s
                """,
                (source_id, like_pattern),
            )
            total += cur.rowcount or 0
        except Exception as e:
            logger.warning("[drift.invalidate_learned] %s: %s", key, e)
    return total


def _penalize_few_shot_for_tables(cur, source_id: int, table_keys: List[str]) -> int:
    """Etkilenen schema_signature içeren few_shot_examples.success_rate *= 0.5."""
    if not table_keys:
        return 0
    total = 0
    for key in table_keys:
        like_pattern = f"%{key}%"
        try:
            cur.execute(
                """
                UPDATE few_shot_examples
                SET success_rate = GREATEST(success_rate * 0.5, 0.0),
                    updated_at = NOW()
                WHERE source_id = %s
                  AND schema_signature ILIKE %s
                """,
                (source_id, like_pattern),
            )
            total += cur.rowcount or 0
        except Exception as e:
            logger.warning("[drift.penalize_fs] %s: %s", key, e)
    return total


def _drop_column_embeddings(cur, source_id: int, removed_cols: List[Dict[str, str]]) -> int:
    """Silinen kolonların ds_column_embeddings kayıtlarını sil."""
    if not removed_cols:
        return 0
    total = 0
    for rc in removed_cols:
        try:
            cur.execute(
                """
                DELETE FROM ds_column_embeddings
                WHERE source_id = %s
                  AND COALESCE(schema_name, '') = COALESCE(%s, '')
                  AND table_name = %s
                  AND column_name = %s
                """,
                (
                    source_id,
                    rc.get("schema_name") or None,
                    rc.get("table_name"),
                    rc.get("column_name"),
                ),
            )
            total += cur.rowcount or 0
        except Exception as e:
            logger.warning("[drift.drop_embeddings] %s: %s", rc, e)
    return total


# ─────────────────────────────────────────────────────────────
# Admin notification (pipeline_events)
# ─────────────────────────────────────────────────────────────

def _emit_drift_event(
    cur,
    *,
    source_id: int,
    company_id: Optional[int],
    summary: DriftActionSummary,
) -> None:
    try:
        cur.execute(
            """
            INSERT INTO pipeline_events
                (run_id, company_id, source_id, event_type, status, metadata)
            VALUES (gen_random_uuid(), %s, %s, 'schema_drift', 'ok', %s::jsonb)
            """,
            (company_id, source_id, json.dumps(summary.to_dict())),
        )
    except Exception as e:
        logger.warning("[drift.event] emit failed: %s", e)


# ─────────────────────────────────────────────────────────────
# Public — main entry
# ─────────────────────────────────────────────────────────────

def apply_drift(
    cur,
    *,
    source_id: int,
    company_id: Optional[int],
    diff: Dict[str, Any],
) -> DriftActionSummary:
    """ds_diff_service çıktısı (diff) tüket — invalidation aksiyonlarını uygula.

    Args:
        cur: psycopg2 cursor (caller RLS scope + commit yapacak)
        source_id: data_sources.id
        company_id: tenant
        diff: {added_tables, removed_tables, modified_tables, unchanged_tables, ...}

    Returns:
        DriftActionSummary — aksiyonların özet sayıları
    """
    s = DriftActionSummary(source_id=source_id)

    if not isinstance(diff, dict):
        s.skipped = True
        s.reason = "invalid_diff"
        return s

    added = _table_keys(diff.get("added_tables"))
    removed = _table_keys(diff.get("removed_tables"))
    modified = _table_keys(diff.get("modified_tables"))
    s.added_tables = added
    s.removed_tables = removed
    s.modified_tables = modified

    # Hiç değişiklik yoksa erken çık
    if not (added or removed or modified):
        s.skipped = True
        s.reason = "no_change"
        return s

    # Etkilenen tablolar = removed + modified (added yeni → invalidate gerekmez)
    affected = list({k for k in (removed + modified) if k})

    try:
        if affected:
            s.invalidated_learned = _invalidate_learned_for_tables(cur, source_id, affected)
            s.penalized_few_shot = _penalize_few_shot_for_tables(cur, source_id, affected)

        removed_cols = _collect_removed_columns(diff.get("modified_tables") or [])
        s.dropped_column_embeddings = _drop_column_embeddings(cur, source_id, removed_cols)

        _emit_drift_event(cur, source_id=source_id, company_id=company_id, summary=s)
    except Exception as e:
        logger.exception("[drift.apply] hata: %s", e)
        s.reason = f"error: {str(e)[:200]}"

    return s


__all__ = [
    "DriftActionSummary",
    "apply_drift",
]
