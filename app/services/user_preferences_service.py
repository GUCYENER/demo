"""
user_preferences_service — Faz 4e
=================================
Per-user kişiselleştirme katmanı CRUD + pipeline integration helper'ları.

Pipeline kullanımı:
    prefs = load_preferences(cur, user_id)
    state["scoring_weights"] = apply_weight_overrides(DEFAULT_WEIGHTS, prefs)
    state["preferred_tables"] = prefs.get("preferred_tables", [])
    state["blacklisted_tables"] = prefs.get("blacklisted_tables", [])

multi_signal_rank ve retrieve node'ları bu state alanlarını okur.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)


def load_preferences(cur, user_id: int) -> Dict[str, Any]:
    """
    user_id için tercihleri yükler. Kayıt yoksa {} döner (no-op).

    Returns: {
        "weight_overrides": {...},
        "preferred_tables": [...],
        "blacklisted_tables": [...],
        "frequent_patterns": {...},
        "settings": {...}
    }
    """
    if not user_id:
        return {}
    try:
        cur.execute("""
            SELECT weight_overrides, preferred_tables, blacklisted_tables,
                   frequent_patterns, settings
              FROM user_preferences
             WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
    except Exception as e:
        logger.debug("[user_prefs] load skipped: %s", e)
        return {}

    if not row:
        return {}

    wo, pref_t, blk_t, freq_p, settings = row
    return {
        "weight_overrides": wo or {},
        "preferred_tables": pref_t or [],
        "blacklisted_tables": blk_t or [],
        "frequent_patterns": freq_p or {},
        "settings": settings or {},
    }


def apply_weight_overrides(
    default_weights: Dict[str, float],
    prefs: Dict[str, Any],
) -> Dict[str, float]:
    """
    Default ağırlıkları user overrides ile birleştir. Sum != 1 ise normalize.
    Yalnızca tanınan key'ler kabul edilir.
    """
    overrides = prefs.get("weight_overrides") or {}
    if not overrides:
        return dict(default_weights)

    merged = dict(default_weights)
    for k, v in overrides.items():
        if k in default_weights:
            try:
                merged[k] = float(v)
            except (TypeError, ValueError):
                continue

    # Normalize
    total = sum(merged.values())
    if total > 0 and abs(total - 1.0) > 0.01:
        merged = {k: v / total for k, v in merged.items()}
    return merged


def apply_table_filters(
    candidates: List[Dict[str, Any]],
    prefs: Dict[str, Any],
    preferred_boost: float = 1.15,
    blacklisted_factor: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Adayları user tercihleriyle filtreler/boost'lar.
        - blacklisted_tables: final_score = 0 (effectively filtre)
        - preferred_tables: final_score *= boost_factor

    Tablo eşleştirme: "schema.table" formatında (case-insensitive).
    """
    pref = set((t or "").lower() for t in (prefs.get("preferred_tables") or []))
    blk = set((t or "").lower() for t in (prefs.get("blacklisted_tables") or []))
    if not pref and not blk:
        return candidates

    def _full(c):
        sch = (c.get("schema_name") or "").lower()
        tbl = (c.get("table_name") or "").lower()
        return f"{sch}.{tbl}" if sch and sch != "public" else tbl

    out = []
    for c in candidates:
        full = _full(c)
        if full in blk:
            # Soft drop — score sıfırla, ama listeden çıkarma (UI'da görünebilsin diyorsak)
            c2 = dict(c)
            c2["final_score"] = blacklisted_factor * float(c.get("final_score", 0.0))
            c2["pref_status"] = "blacklisted"
            out.append(c2)
            continue
        if full in pref:
            c2 = dict(c)
            c2["final_score"] = preferred_boost * float(c.get("final_score", 0.0))
            c2["pref_status"] = "preferred"
            out.append(c2)
            continue
        out.append(c)

    # Re-sort
    out.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
    return out


def upsert_preferences(cur, user_id: int, company_id: int, **fields) -> None:
    """
    weight_overrides / preferred_tables / blacklisted_tables / frequent_patterns / settings
    alanlarından gelenleri upsert eder.
    """
    if not user_id:
        return
    allowed = {"weight_overrides", "preferred_tables", "blacklisted_tables",
               "frequent_patterns", "settings"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

    cols = ["user_id", "company_id"] + list(updates.keys())
    placeholders = ["%s", "%s"] + ["%s" for _ in updates]
    values: List[Any] = [user_id, company_id]
    for k, v in updates.items():
        if k in ("weight_overrides", "frequent_patterns", "settings"):
            values.append(json.dumps(v) if v is not None else "{}")
        else:
            values.append(v or [])

    set_clauses = ", ".join(f"{k} = EXCLUDED.{k}" for k in updates.keys())
    sql = f"""
        INSERT INTO user_preferences ({', '.join(cols)})
        VALUES ({', '.join(placeholders)})
        ON CONFLICT (user_id) DO UPDATE SET {set_clauses}
    """
    cur.execute(sql, values)
