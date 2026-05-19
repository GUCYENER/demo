"""disambiguation_card — Faz 6 G4 (v3.29.3)
==========================================
ambiguity_gate `needs_clarification=True` döndüğünde, her aday tabloya
"did you mean?" kartı için zengin metadata ekler:

    - sample_rows         (ds_db_samples'tan, PII-maskeli, 3 satır)
    - preview_sql         (SELECT * FROM <table> LIMIT 3)
    - join_paths_to_target (fk_graph_resolver — başka adayla en kısa yol)
    - row_count_estimate  (best-effort — ds_db_objects.row_count varsa)
    - label_tr            (admin_label_tr || business_name_tr || table_name)

Çıktı state diff:
    {"clarification_cards": [card, ...]}

Frontend SSE event `clarification_v2` ile gönderilir; kullanıcı seçince
`selected_tables` state'e yazılır → sql_generate tetiklenir.

Bu node defensive: cursor/source_id eksikse veya ds_db_samples boşsa
boş kartlar döndürür (gate akışını kırmaz).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# v3.29.5 — Identifier whitelist (SQL injection defense-in-depth)
# Geçerli SQL identifier'lar yalnızca harf/digit/underscore + dolar (PG izinli) içerir.
# Bu validation ds_db_objects'ten gelen güvenilir veriye ek savunma katmanıdır.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")


def _safe_ident(s: Optional[str]) -> Optional[str]:
    """Identifier güvenli mi? (Whitelist regex). Değilse None döner."""
    if not s:
        return None
    if _IDENT_RE.match(s):
        return s
    return None


def _label_for(cand: Dict[str, Any]) -> str:
    """Admin label > business name > raw table_name."""
    return (
        cand.get("admin_label_tr")
        or cand.get("business_name_tr")
        or cand.get("table_name")
        or ""
    )


def _preview_sql(schema: Optional[str], table: str, dialect: str = "postgresql") -> str:
    """SELECT * FROM "schema"."table" LIMIT 3 — okunaklı PG quoting.

    v3.29.5: schema/table whitelist regex'i geçemezse boş string döner
    (defense-in-depth — ds_db_objects'ten gelen veriye ek savunma).
    """
    safe_table = _safe_ident(table)
    if not safe_table:
        return ""
    safe_schema = _safe_ident(schema) if schema else None
    if dialect == "mssql":
        if safe_schema and safe_schema != "public":
            return f"SELECT TOP 3 * FROM [{safe_schema}].[{safe_table}]"
        return f"SELECT TOP 3 * FROM [{safe_table}]"
    quote = '"'
    if safe_schema and safe_schema != "public":
        return f"SELECT * FROM {quote}{safe_schema}{quote}.{quote}{safe_table}{quote} LIMIT 3"
    return f"SELECT * FROM {quote}{safe_table}{quote} LIMIT 3"


def _row_count_estimate(cand: Dict[str, Any]) -> Optional[int]:
    """ranked_candidates payload'unda olabilirse alır; yoksa None."""
    rc = cand.get("row_count") or cand.get("row_count_estimate")
    try:
        return int(rc) if rc is not None else None
    except Exception:
        return None


def _join_paths_to_peers(
    cur,
    source_id: int,
    cand: Dict[str, Any],
    peers: List[Dict[str, Any]],
    max_paths: int = 2,
    max_hops: int = 4,
    *,
    graph=None,
) -> List[List[str]]:
    """Bu aday ile diğer adaylar arasındaki en kısa yolları topla.

    v3.29.5: `graph` opsiyonel — caller önceden bir kez `build_graph` yaparak
    geçebilir; bu durumda N² rebuild olmaz. Yoksa fonksiyon kendi inşa eder
    (backward-compat).
    """
    if not peers:
        return []
    try:
        from app.services.db_learning.fk_graph_resolver import (
            build_graph as _build_graph, find_paths,
        )
    except Exception:
        return []
    g = graph
    if g is None:
        if cur is None or source_id is None:
            return []
        try:
            g = _build_graph(cur, source_id)
        except Exception:
            return []
    src_schema = (cand.get("schema_name") or "").strip().lower()
    src_table = (cand.get("table_name") or "").strip().lower()
    src = (src_schema, src_table)
    paths_out: List[List[str]] = []
    for peer in peers[:max_paths]:
        dst_schema = (peer.get("schema_name") or "").strip().lower()
        dst_table = (peer.get("table_name") or "").strip().lower()
        if (dst_schema, dst_table) == src:
            continue
        try:
            paths = find_paths(g, src, (dst_schema, dst_table), k=1, max_hops=max_hops)
        except Exception:
            paths = []
        if paths:
            p = paths[0]
            paths_out.append([f"{n[0]}.{n[1]}".strip(".") for n in p])
    return paths_out


def build_card(
    cand: Dict[str, Any],
    *,
    cur=None,
    source_id: Optional[int] = None,
    peers: Optional[List[Dict[str, Any]]] = None,
    dialect: str = "postgresql",
    rows_per_table: int = 3,
    graph=None,
) -> Dict[str, Any]:
    """Tek aday için kart dict'i üret (sample rows + preview + join paths)."""
    schema = cand.get("schema_name")
    table = cand.get("table_name") or ""
    card: Dict[str, Any] = {
        "schema": schema or None,
        "table": table,
        "label_tr": _label_for(cand),
        "score": float(cand.get("final_score") or 0.0),
        "matched_terms": cand.get("matched_terms") or [],
        "row_count_estimate": _row_count_estimate(cand),
        "preview_sql": _preview_sql(schema, table, dialect=dialect),
        "sample_rows": [],
        "masked_columns": [],
        "join_paths_to_target": [],
        "truncated": False,
    }

    # Sample rows + PII mask
    if cur is not None and source_id is not None and table:
        try:
            from app.services.db_learning.sample_data_loader import load_samples_for_tables
            payloads = load_samples_for_tables(
                cur, source_id,
                [{"schema_name": schema, "table_name": table}],
                rows_per_table=rows_per_table,
            )
            key = next(iter(payloads.keys())) if payloads else None
            if key:
                p = payloads[key]
                card["sample_rows"] = p.get("rows") or []
                card["masked_columns"] = p.get("masked_columns") or []
                card["truncated"] = bool(p.get("truncated"))
        except Exception as exc:
            logger.debug("[disambig_card] sample load skipped: %s", exc)

    # Join paths to peers — graph pre-built ise N² inşa olmaz
    if peers:
        card["join_paths_to_target"] = _join_paths_to_peers(
            cur, source_id or 0, cand, peers, graph=graph,
        )
    return card


def disambiguation_card_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — clarification gerekli ise kart listesi üret.

    Yalnızca state.ambiguity.needs_clarification = True olduğunda çalışır;
    aksi halde pass-through (boş diff).
    """
    amb = state.get("ambiguity") or {}
    if not amb.get("needs_clarification"):
        return {}
    candidates = amb.get("candidates_for_user") or []
    if not candidates:
        return {}
    cur = state.get("_cursor")
    source_id = state.get("source_id")
    dialect = state.get("db_dialect", "postgresql")

    # v3.29.5: FK graph'ı bir kez kur, tüm kartlara paylaştır (N² → N).
    shared_graph = None
    if cur is not None and source_id:
        try:
            from app.services.db_learning.fk_graph_resolver import build_graph
            shared_graph = build_graph(cur, source_id)
        except Exception as exc:
            logger.debug("[disambig_card] shared graph skipped: %s", exc)

    cards: List[Dict[str, Any]] = []
    for i, cand in enumerate(candidates):
        peers = [c for j, c in enumerate(candidates) if j != i]
        cards.append(
            build_card(
                cand, cur=cur, source_id=source_id,
                peers=peers, dialect=dialect, graph=shared_graph,
            )
        )
    # clarification_payload zaten ambiguity_gate'te dolduruldu — kartları enjekte et.
    out: Dict[str, Any] = {"clarification_cards": cards}
    existing = state.get("clarification_payload") or {}
    if existing:
        # Cards'ı mevcut payload üzerine birleştir (frontend backward-compat).
        payload = dict(existing)
        payload["cards"] = cards
        out["clarification_payload"] = payload
    return out


__all__ = ["build_card", "disambiguation_card_node"]
