"""
retrieve & query_expand — Faz 3d
================================
- query_expand_node: business_glossary'den terim eşleşmesi → adayları zenginleştirir.
- retrieve_node: hybrid_retrieval ile tablo+kolon adaylarını çeker.

Çalışma sırası (graph):
    intent_extract → query_expand → retrieve → multi_signal_rank → ambiguity_gate

RLS: caller `get_db_context_scoped(source_id)` altında çalışmalı (Faz 1c sözleşmesi).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def _expand_with_glossary(
    cur,
    query_text: str,
    company_id: Optional[int],
    limit: int = 5,
) -> Dict[str, Any]:
    """
    business_glossary'de tsv match + synonyms[] match ile terim ara.

    Returns:
        {
            "expanded_terms": [str, ...],      # eklenmiş eşanlamlılar
            "canonical_hints": [               # SQL üreticiye ipucu
                {"term", "schema", "table", "column", "description"}, ...
            ]
        }
    """
    if not query_text:
        return {"expanded_terms": [], "canonical_hints": []}

    expanded_terms: List[str] = []
    hints: List[Dict[str, Any]] = []
    seen: set = set()

    where = []
    params: List[Any] = []
    if company_id is not None:
        where.append("(company_id IS NULL OR company_id = %s)")
        params.append(company_id)

    # 1) tsv match (term + synonyms + description + expansion_tr + mapped_table)
    # v3.29.1 G2: term_type, expansion_tr, mapped_table, mapped_columns alanları okunur.
    used_ids: List[int] = []
    try:
        tsv_where = " AND ".join(where + ["tsv @@ plainto_tsquery('pg_catalog.simple', %s)"])
        params_tsv = list(params) + [query_text]
        common_cols = ("id, term, synonyms, canonical_schema, canonical_table, canonical_column, description, "
                       "term_type, expansion_tr, mapped_table, mapped_columns, admin_verified")
        if where:
            sql = f"""
                SELECT {common_cols}
                  FROM business_glossary
                 WHERE {tsv_where}
                 ORDER BY admin_verified DESC NULLS LAST, usage_count DESC NULLS LAST,
                          ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %s)) DESC
                 LIMIT %s
            """
            cur.execute(sql, params_tsv + [query_text, limit])
        else:
            sql = f"""
                SELECT {common_cols}
                  FROM business_glossary
                 WHERE tsv @@ plainto_tsquery('pg_catalog.simple', %s)
                 ORDER BY admin_verified DESC NULLS LAST, usage_count DESC NULLS LAST,
                          ts_rank(tsv, plainto_tsquery('pg_catalog.simple', %s)) DESC
                 LIMIT %s
            """
            cur.execute(sql, [query_text, query_text, limit])
        for r in cur.fetchall():
            term = r["term"]
            if term and term not in seen:
                seen.add(term)
                expanded_terms.append(term)
                for s in (r["synonyms"] or []):
                    if s not in seen:
                        seen.add(s)
                        expanded_terms.append(s)
            # expansion_tr → genişletmeye de eklenir (örn 'L1' → 'Level 1 destek')
            exp_tr = r.get("expansion_tr") if hasattr(r, "get") else None
            if exp_tr and exp_tr not in seen:
                seen.add(exp_tr)
                expanded_terms.append(exp_tr)
            hints.append({
                "term": term,
                "term_type": r.get("term_type") if hasattr(r, "get") else None,
                "expansion_tr": exp_tr,
                "schema": r.get("canonical_schema"),
                "table": r.get("canonical_table"),
                "column": r.get("canonical_column"),
                "mapped_table": r.get("mapped_table") if hasattr(r, "get") else None,
                "mapped_columns": (r.get("mapped_columns") if hasattr(r, "get") else None) or [],
                "admin_verified": bool(r.get("admin_verified")) if hasattr(r, "get") else False,
                "description": r.get("description"),
            })
            rid = r.get("id") if hasattr(r, "get") else None
            if rid is not None:
                used_ids.append(rid)
    except Exception as e:
        logger.warning("[QueryExpand] glossary tsv hata: %s", e)

    # usage_count + last_used_at bump (best-effort)
    if used_ids:
        try:
            cur.execute(
                "UPDATE business_glossary SET usage_count = usage_count + 1, last_used_at = NOW() WHERE id = ANY(%s)",
                (used_ids,),
            )
        except Exception:
            pass

    return {"expanded_terms": expanded_terms, "canonical_hints": hints}


def query_expand_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node — business_glossary genişletme."""
    cur = state.get("_cursor")  # caller psycopg2 cursor injects
    if cur is None:
        return {"glossary_hints": [], "expanded_query": state.get("question", "")}

    query = state.get("question", "")
    company_id = state.get("company_id")

    result = _expand_with_glossary(cur, query, company_id)
    expanded = query
    if result["expanded_terms"]:
        # Sorguyu eşanlamlılarla zenginleştir (retrieval için)
        expanded = query + " " + " ".join(result["expanded_terms"][:10])

    return {
        "glossary_hints": result["canonical_hints"],
        "expanded_query": expanded,
    }


def retrieve_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node — hybrid_retrieval ile tablo + kolon adayları çek.

    state.candidates ← tablo adayları (TableCandidate-uyumlu)
    state.column_candidates ← kolon adayları
    state.column_index ← multi_signal_rank için (schema,table)→cols lookup
    """
    cur = state.get("_cursor")
    if cur is None:
        return {"candidates": [], "column_candidates": []}

    from app.services.rag.hybrid_retrieval import search_combined

    source_id = state.get("source_id")
    if source_id is None:
        return {"candidates": [], "column_candidates": [], "errors": ["source_id_missing"]}

    query = state.get("expanded_query") or state.get("question") or ""
    query_embedding = state.get("query_embedding")  # opsiyonel — Faz 5'te wire edilebilir

    result = search_combined(
        cur, source_id=source_id, query_text=query,
        query_embedding=query_embedding,
        table_limit=state.get("table_limit", 8),
        column_limit=state.get("column_limit", 30),
    )

    # Tablo adayları → TableCandidate yapısına dönüştür
    candidates: List[Dict[str, Any]] = []
    for t in result["tables"]:
        meta = t.get("metadata") or {}
        # metadata tipi dict olmayabilir (JSONB), parse et
        if isinstance(meta, str):
            try:
                import json
                meta = json.loads(meta)
            except Exception:
                meta = {}
        candidates.append({
            "schema_name": meta.get("schema", ""),
            "table_name": meta.get("table_name", ""),
            "object_type": "table",
            "row_count_estimate": 0,
            "business_name_tr": meta.get("business_name", ""),
            "description": "",
            "semantic_score": t.get("semantic_score", 0.0),
            "hybrid_score": t.get("hybrid_score", 0.0),
            "_content_text": t.get("content_text", ""),
        })

    # Kolon index → multi_signal column_match için
    column_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for c in result["columns"]:
        k = (c.get("schema_name") or "", c.get("table_name") or "")
        column_index.setdefault(k, []).append({
            "column_name": c.get("column_name"),
            "business_name_tr": c.get("business_name_tr"),
            "synonyms": c.get("synonyms") or [],
            "data_type": c.get("data_type"),
            "is_pk": c.get("is_pk"),
            "is_fk": c.get("is_fk"),
            "hybrid_score": c.get("hybrid_score", 0.0),
        })

    # candidates'a kolon listesi göm (UI ve scorer için)
    for cand in candidates:
        k = (cand["schema_name"], cand["table_name"])
        if k in column_index:
            cand["columns"] = column_index[k]

    return {
        "candidates": candidates,
        "column_candidates": result["columns"],
        "column_index": column_index,
    }
