"""cache_lookup — v3.27.0 (G3 — DB LLM Bypass Cache)
====================================================
Pipeline'in en başında çalışır. Daha önce öğrenilmiş benzer bir
(soru→SQL) kaydı varsa LLM tüm pipeline'ı atlayıp doğrudan execute'a gider.

Davranış:
  - Cache HIT (cosine ≥ 0.85) →
      state["_cache_hit"] = True
      state["sql"]        = cached.sql
      state["intent"]     = cached.intent or "cached"
      state["validation_passed"] = False  (validate node yine çalışır —
                                          schema drift'i yakalar)
      state["_cache_hit_id"]      = cached.id
      state["_cache_similarity"]  = cached.similarity
      state["_cache_source"]      = cached.source   ('user'|'synthetic'|'manual')
      state["selected_tables"]    = [<lookup>]      (mevcutsa skip)
  - Cache MISS → no-op (delta {} döner; normal pipeline yürür)

Best-effort: DB/embedding hatasında sessizce miss kabul edilir.
RLS: caller `app.current_company_id` set etmiş olmalı (set_app_context).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def cache_lookup_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """state.question → learned_db_queries lookup → SQL hit ise state'e koy."""
    question = (state.get("question") or "").strip()
    source_id = state.get("source_id")
    cur = state.get("_cursor")

    if not question or not source_id or cur is None:
        return {}

    # Aynı pipeline çağrısında zaten cache devre dışı bırakılmışsa atla
    if state.get("_cache_lookup_disabled"):
        return {}

    try:
        from app.services.db_learning.learned_queries_service import (
            lookup_cached_sql, LOOKUP_COSINE_THRESHOLD,
        )
        threshold = float(state.get("_cache_threshold") or LOOKUP_COSINE_THRESHOLD)
        cached = lookup_cached_sql(
            cur,
            source_id=int(source_id),
            question=question,
            threshold=threshold,
        )
    except Exception as e:
        logger.debug("[cache_lookup] skipped: %s", e)
        return {}

    if cached is None:
        return {}

    # Cache hit — state'i pre-populate et
    delta: Dict[str, Any] = {
        "_cache_hit": True,
        "_cache_hit_id": cached.id,
        "_cache_similarity": cached.similarity,
        "_cache_source": cached.source,
        "sql": cached.sql,
        "intent": cached.intent or "cached",
        "intent_confidence": 1.0,
    }

    # schema_signature'dan tablo isimleri çıkarılabilirse selected_tables koy
    if cached.schema_signature:
        try:
            tables = []
            for tok in (cached.schema_signature or "").split(","):
                tok = tok.strip()
                if not tok:
                    continue
                if "." in tok:
                    sch, tbl = tok.split(".", 1)
                else:
                    sch, tbl = "", tok
                tables.append({
                    "schema_name": sch,
                    "table_name": tbl,
                    "object_type": "table",
                    "row_count_estimate": 0,
                    "semantic_score": 1.0,
                    "final_score": 1.0,
                })
            if tables:
                delta["selected_tables"] = tables
                delta["ranked_candidates"] = tables
                delta["candidates"] = tables
        except Exception:
            pass

    # SSE event — frontend "⚡ Önceki öğrenmeden" gösterir
    try:
        from app.services.pipeline.observability import emit_event
        emit_event(state, "cache_hit", metadata={
            "id": cached.id,
            "similarity": round(cached.similarity, 4),
            "source": cached.source,
            "hit_count": cached.hit_count,
        })
    except Exception:
        pass

    return delta


def should_skip_after_cache_hit(state: Dict[str, Any]) -> str:
    """LangGraph conditional edge — cache hit varsa direkt validate'e atla."""
    if state.get("_cache_hit"):
        return "validate"
    return "intent_extract"
