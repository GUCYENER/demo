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
            tgt = h.get("table") or h.get("mapped_table") or ""
            exp = h.get("expansion_tr")
            extra = f" ({exp})" if exp else ""
            lines.append(f"  '{term}' -> {tgt}{extra}")

    # v3.29.1 Faz 6 G2 — CODE VALUE HINTS
    # Seçili tablolardaki kodlu kolonların TR etiketleri prompt'a enjekte edilir.
    cur = state.get("_cursor")
    source_id = state.get("source_id")
    if cur is not None and source_id is not None and selected:
        try:
            from app.services.db_learning.code_value_extractor import list_for_column
            code_lines: List[str] = []
            for cand in selected[:5]:
                tbl = cand.get("table_name") or ""
                if not tbl:
                    continue
                for col in (cand.get("columns") or [])[:30]:
                    cname = col.get("column_name") or ""
                    if not cname:
                        continue
                    rows = list_for_column(cur, source_id, tbl, cname, limit=12)
                    if not rows:
                        continue
                    parts = []
                    for r in rows:
                        cv = r.get("code_value")
                        lbl = r.get("label_tr") or r.get("label_en")
                        if cv and lbl:
                            parts.append(f"{cv}={lbl}")
                        elif cv:
                            parts.append(str(cv))
                    if parts:
                        code_lines.append(f"  {tbl}.{cname}: " + ", ".join(parts[:12]))
                    if len(code_lines) >= 12:
                        break
                if len(code_lines) >= 12:
                    break
            if code_lines:
                lines.append("\nCODE VALUE HINTS:")
                lines.extend(code_lines)
        except Exception as exc:
            logger.debug("[sql_generate] code value injection skipped: %s", exc)

    # v3.29.3 Faz 6 G4 — SAMPLE DATA injection (PII-maskeli, prompt budget'lı)
    # Seçili tablolar için ds_db_samples'tan max 3 satır, is_pii=TRUE kolonlar
    # mask_value() ile maskelenerek LLM'in tip/format anlaması için verilir.
    if cur is not None and source_id is not None and selected:
        try:
            from app.services.db_learning.sample_data_loader import (
                format_for_prompt, load_samples_for_tables,
            )
            tbl_specs = [
                {"schema_name": c.get("schema_name"), "table_name": c.get("table_name")}
                for c in selected[:4]
                if c.get("table_name")
            ]
            if tbl_specs:
                payloads = load_samples_for_tables(cur, source_id, tbl_specs)
                block = format_for_prompt(payloads)
                if block:
                    lines.append("")
                    lines.append(block)
        except Exception as exc:
            logger.debug("[sql_generate] sample data injection skipped: %s", exc)

    # v3.32.0 Ajan-E — JOIN HINTS injection
    # Seçili tablolar arasında ds_db_relationships'te tanımlı FK edge'leri LLM'e
    # yapılandırılmış formatta sunulur. Amaç: customer+orders gibi FK ile birleşik
    # sorgularda LLM'in JOIN yolunu doğru kurabilmesi (ambiguity_gate'in gereksiz
    # clarification açmasını azaltır).
    if cur is not None and source_id is not None and selected and len(selected) >= 2:
        try:
            table_pairs = [
                (c.get("schema_name") or "", c.get("table_name") or "")
                for c in selected
                if c.get("table_name")
            ]
            hint_block = _fetch_join_hints(cur, source_id, table_pairs)
            if hint_block:
                lines.append("")
                lines.append(hint_block)
        except Exception as exc:
            logger.debug("[sql_generate] join hints injection skipped: %s", exc)

    return "\n".join(lines)


def _fetch_join_hints(cur, source_id: int, table_pairs: List[tuple]) -> str:
    """v3.32.0 — Seçili tablolar arasındaki FK edge'lerini LLM-okuyabilir formatta üret.

    Args:
        cur: aktif DB cursor
        source_id: aktif data_source.id
        table_pairs: [(schema, table), ...] selected tables

    Returns:
        Formatted "JOIN HINTS:" bloğu (string), edge yoksa "".

    Notes:
        - Sadece her İKİ tablo da selected içindeyse edge döndürülür (transitive değil).
        - Composite FK'ler `constraint_name` ile gruplanır → tek satır.
        - `confidence_score >= 0.7` threshold (junction + inferred low-conf filter).
        - Max 20 edge (prompt budget koruması).
        - Schema kıyaslamasında boş schema ve "public" eşdeğer kabul edilir.
    """
    if not table_pairs or len(table_pairs) < 2:
        return ""

    def _norm_schema(s: str) -> str:
        return (s or "").lower() if (s or "").lower() not in ("", "public") else ""

    selected_keys = {(_norm_schema(s), (t or "").lower()) for s, t in table_pairs if t}
    if len(selected_keys) < 2:
        return ""

    cur.execute(
        """
        SELECT from_schema, from_table, from_column,
               to_schema, to_table, to_column,
               constraint_name, confidence_score, is_inferred
        FROM ds_db_relationships
        WHERE source_id = %s
          AND confidence_score >= 0.7
        ORDER BY constraint_name NULLS LAST, fk_position
        """,
        (source_id,),
    )
    rows = cur.fetchall() or []
    if not rows:
        return ""

    # Composite FK'leri constraint_name ile grupla
    grouped: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        # Row hem dict hem tuple olabilir; ikisini de tolere et
        if isinstance(r, dict):
            from_sch = r.get("from_schema") or ""
            from_tbl = r.get("from_table") or ""
            from_col = r.get("from_column") or ""
            to_sch = r.get("to_schema") or ""
            to_tbl = r.get("to_table") or ""
            to_col = r.get("to_column") or ""
            cname = r.get("constraint_name")
            conf = r.get("confidence_score") or 0.0
            is_inferred = r.get("is_inferred") or False
        else:
            from_sch, from_tbl, from_col, to_sch, to_tbl, to_col, cname, conf, is_inferred = r

        from_key = (_norm_schema(from_sch), (from_tbl or "").lower())
        to_key = (_norm_schema(to_sch), (to_tbl or "").lower())
        if from_key not in selected_keys or to_key not in selected_keys:
            continue

        # Composite group key (constraint_name yoksa unique fallback)
        gkey = (cname, from_key, to_key) if cname else (f"__id_{id(r)}", from_key, to_key)
        if gkey not in grouped:
            grouped[gkey] = {
                "from_sch": from_sch, "from_tbl": from_tbl,
                "to_sch": to_sch, "to_tbl": to_tbl,
                "from_cols": [], "to_cols": [],
                "constraint": cname or "",
                "conf": float(conf or 0.0),
                "is_inferred": bool(is_inferred),
            }
        grouped[gkey]["from_cols"].append(from_col)
        grouped[gkey]["to_cols"].append(to_col)

    if not grouped:
        return ""

    hint_lines: List[str] = ["JOIN HINTS (bilinen FK ilişkileri):"]
    for gkey, g in list(grouped.items())[:20]:
        from_qual = f"{g['from_sch']}." if g["from_sch"] and g["from_sch"] != "public" else ""
        to_qual = f"{g['to_sch']}." if g["to_sch"] and g["to_sch"] != "public" else ""
        if len(g["from_cols"]) == 1:
            cols_part = f"{from_qual}{g['from_tbl']}.{g['from_cols'][0]} → {to_qual}{g['to_tbl']}.{g['to_cols'][0]}"
        else:
            from_cols = ", ".join(g["from_cols"])
            to_cols = ", ".join(g["to_cols"])
            cols_part = (
                f"{from_qual}{g['from_tbl']}.({from_cols}) → "
                f"{to_qual}{g['to_tbl']}.({to_cols})  [composite]"
            )
        origin = "inferred" if g["is_inferred"] else "declared"
        hint_lines.append(f"  {cols_part}  [{origin}, conf={g['conf']:.2f}]")

    return "\n".join(hint_lines)


def _candidate_signature(state: Dict[str, Any]) -> str:
    """Seçilen tablolardan alfabetik schema_signature üretir (few-shot match)."""
    selected = state.get("selected_tables") or state.get("ranked_candidates", [])[:3]
    if not selected:
        return ""
    tokens: List[str] = []
    for cand in selected:
        sch = cand.get("schema_name") or ""
        tbl = cand.get("table_name") or ""
        full = f"{sch}.{tbl}" if sch and sch not in ("", "public") else tbl
        if full:
            tokens.append(full.lower())
    return ",".join(sorted(tokens))


def _select_few_shots(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Faz 4c — few_shot_selector çağrısı (best-effort). cursor + company_id state'ten gelir."""
    cur = state.get("_cursor")
    company_id = state.get("company_id")
    if cur is None or company_id is None:
        return []
    try:
        from app.services.rag.few_shot_selector import select_few_shots
        return select_few_shots(
            cur,
            company_id=company_id,
            source_id=state.get("source_id"),
            query_text=state.get("question", ""),
            query_embedding=state.get("query_embedding"),
            intent=state.get("intent"),
            candidate_signature=_candidate_signature(state),
            top_k=int(state.get("few_shot_k", 3)),
        )
    except Exception as e:
        logger.debug("[sql_generate] few-shot retrieval skipped: %s", e)
        return []


def sql_generate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node — bağlam + soru → SQL.

    Faz 4c: few-shot örnekleri varsa bağlama enjekte edilir.
    Faz 5d: AST yolu eligible ise LLM atlanır, deterministic SQL üretilir.

    Mevcut deep_think servisini DOĞRUDAN çağırmıyor; bunun yerine LLM client'ı
    state'ten alır (test edilebilirlik için). Eğer `_llm_callable` injekte
    edilmemişse — placeholder döner ve `errors`'a not düşer.
    """
    # Faz 5d — AST shortcut
    try:
        from .ast_query_builder import is_ast_eligible, ast_query_builder_node
        if is_ast_eligible(state):
            delta = ast_query_builder_node(state)
            if delta.get("sql"):
                return delta
    except Exception:
        pass
    context = _build_context(state)
    question = state.get("question", "")
    dialect = state.get("db_dialect", "postgresql")
    intent = state.get("intent", "lookup")

    # Faz 4c — few-shot örnekleri (best-effort)
    few_shots = _select_few_shots(state)
    if few_shots:
        try:
            from app.services.rag.few_shot_selector import format_examples_for_prompt
            context = context + "\n\n" + format_examples_for_prompt(few_shots)
        except Exception:
            pass

    # v3.26.0 Faz 3 — Semantic/Metric layer: soruda eşleşen metric'leri prompt'a ekle
    matched_metrics: List[Dict[str, Any]] = []
    available = state.get("available_metrics") or []
    if available:
        try:
            from app.services.metric_registry import (
                resolve_metrics_in_question, format_metrics_for_prompt,
            )
            matched_metrics = resolve_metrics_in_question(question, available)
            if matched_metrics:
                block = format_metrics_for_prompt(matched_metrics, limit=5)
                if block:
                    context = context + "\n\n" + block
        except Exception as e:
            logger.debug("[sql_generate] metric resolve skipped: %s", e)

    # Faz 4d — self-heal retry hint (önceki hata bilgisi)
    retry_hint = state.get("retry_hint")
    if retry_hint:
        context = context + "\n\nÖnceki Deneme Notu:\n  " + retry_hint

    llm = state.get("_llm_callable")
    if llm is None:
        logger.warning("[sql_generate] _llm_callable yok — placeholder dönülüyor")
        return {
            "sql": "",
            "few_shots_used": [fs["id"] for fs in few_shots],
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
        return {
            "sql": (sql or "").strip(),
            "few_shots_used": [fs["id"] for fs in few_shots],
            "matched_metrics": [m.get("id") for m in matched_metrics],
        }
    except Exception as e:
        logger.error("[sql_generate] LLM hata: %s", e)
        return {
            "sql": "",
            "few_shots_used": [fs["id"] for fs in few_shots],
            "matched_metrics": [m.get("id") for m in matched_metrics],
            "errors": (state.get("errors") or []) + [f"llm_error: {e}"],
        }
