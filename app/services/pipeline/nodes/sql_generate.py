"""
sql_generate — Faz 3e
=====================
Seçilen tablo+kolon bağlamı ile SQL üretir. Faz 3'te mevcut LLM çağrı zincirini
sarmalayan ince bir adapter — gerçek üretim DeepThinkService/safe_sql_executor
katmanında zaten yapılıyor.

Bu node'un sorumluluğu:
    1) state'ten selected_tables / candidates / intent / dialect oku
    2) Bağlam (schema_text) hazırla
    3) LLM çağrısı yap (mevcut servis)
    4) state.sql doldur

Faz 5'te AST query builder eklendiğinde bu node alternatif yola dallandırılır.
"""
from __future__ import annotations

from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


def _build_context(state: Dict[str, Any]) -> str:
    """Seçilen tablolardan + kolonlardan LLM bağlamı oluşturur."""
    selected = state.get("selected_tables") or state.get("ranked_candidates", [])[:3]
    if not selected:
        return ""
    lines: List[str] = []
    for cand in selected:
        sch = cand.get("schema_name") or ""
        tbl = cand.get("table_name") or ""
        full = f"{sch}.{tbl}" if sch and sch not in ("", "public") else tbl
        lines.append(f"TABLO: {full}")
        if cand.get("business_name_tr"):
            lines.append(f"  İş Adı: {cand['business_name_tr']}")
        for col in (cand.get("columns") or [])[:30]:
            cname = col.get("column_name") or ""
            ctype = col.get("data_type") or ""
            bname = col.get("business_name_tr") or ""
            extra = f" → {bname}" if bname else ""
            pk = " [PK]" if col.get("is_pk") else ""
            fk = " [FK]" if col.get("is_fk") else ""
            lines.append(f"  - {cname} ({ctype}){pk}{fk}{extra}")
    glos = state.get("glossary_hints") or []
    if glos:
        lines.append("\nGLOSSARY:")
        for h in glos[:5]:
            term = h.get("term") or ""
            tgt = h.get("table") or ""
            lines.append(f"  '{term}' -> {tgt}")
    return "\n".join(lines)


def sql_generate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node — bağlam + soru → SQL.

    Mevcut deep_think servisini DOĞRUDAN çağırmıyor; bunun yerine LLM client'ı
    state'ten alır (test edilebilirlik için). Eğer `_llm_callable` injekte
    edilmemişse — placeholder döner ve `errors`'a not düşer.
    """
    context = _build_context(state)
    question = state.get("question", "")
    dialect = state.get("db_dialect", "postgresql")
    intent = state.get("intent", "lookup")

    llm = state.get("_llm_callable")
    if llm is None:
        logger.warning("[sql_generate] _llm_callable yok — placeholder dönülüyor")
        return {
            "sql": "",
            "errors": (state.get("errors") or []) + ["llm_callable_missing"],
        }

    try:
        sql = llm(
            question=question,
            context=context,
            dialect=dialect,
            intent=intent,
            history=state.get("history", []),
        )
        return {"sql": (sql or "").strip()}
    except Exception as e:
        logger.error("[sql_generate] LLM hata: %s", e)
        return {
            "sql": "",
            "errors": (state.get("errors") or []) + [f"llm_error: {e}"],
        }
