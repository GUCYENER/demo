"""VYRA v3.30.0 — Akıllı Veri Keşfi (DB Smart Wizard) API.

12 endpoint (prefix: /api/db-smart):

    Sessions
        POST   /sessions                               — yeni oturum aç
        GET    /sessions/{uid}                         — hydrate (refresh-safe)
        POST   /sessions/{uid}/step/{n}                — kullanıcı seçimi + next step
        POST   /sessions/{uid}/preview                 — SQL render + EXPLAIN + cost
        POST   /sessions/{uid}/execute                 — safe_sql_executor SSE
        POST   /sessions/{uid}/save-report             — dbsmart_saved_reports

    Discovery
        GET    /sources                                — kullanıcının data_sources'u
        GET    /sources/{id}/tables?q=                 — hybrid domain araması
        GET    /sources/{id}/tables/{tid}/related      — FK graph genişletme
        GET    /sources/{id}/tables/{tid}/columns      — kolon enrichment

    Metrics & Insights
        GET    /metrics?source_id=&table_signature=    — eligible metric list
        GET    /recommendations/{exec_id}              — rapor önerisi (Prompt H)

Auth: Depends(get_current_user) — Bearer token.
RLS: ARES carry-over → her endpoint kendi transaction'ında
     `apply_vyra_user_context(cur, current_user)` ile `vyra.user_id` /
     `vyra.company_id` / `vyra.is_admin` set eder. dbsmart_* tabloları
     migration 032'deki RLS policy ile izole edilir.

FAZ 1 status:
    - Auth + RLS plumbing      ✅ gerçek
    - Service çağrıları        🟡 stub (gerçek SQL FAZ 1 G1.2-G1.5'te dolacak)
    - Pydantic kontratları     ✅ stabil (UI bu şemayla yazılacak)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context
from app.services.db_smart.rls_context import apply_vyra_user_context
from app.services.db_smart import (
    session_manager,
    state_machine,
    eligibility,     # v3.30.0 FAZ 1 G1.2
    fk_graph,        # v3.30.0 FAZ 1 G1.3
    metric_engine,   # v3.30.0 FAZ 1 P3 G1.4
    recommendation,  # v3.30.0 FAZ 2 P9 G2.3
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db-smart", tags=["db_smart"])


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas (UI kontratı — FAZ 1 sonrası UI bunu kullanır)
# ─────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    source_id: Optional[int] = Field(default=None, description="Başlangıç data_source.id (opsiyonel)")


class CreateSessionResponse(BaseModel):
    session_uid: str
    current_step: int = 0
    status: str = "active"


class StepRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict, description="Adıma özgü kullanıcı seçimleri")


class StepResponse(BaseModel):
    session_uid: str
    current_step: int
    next_step: Optional[int] = None
    node: str
    suggestions: Dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    sql: str = ""
    dialect: str = "postgresql"
    explain: Dict[str, Any] = Field(default_factory=dict)
    estimated_rows: Optional[int] = None
    streaming_strategy: str = "direct"  # direct | cursor | sse_chunk


class ExecuteRequest(BaseModel):
    stream: bool = False
    limit: Optional[int] = Field(default=1000, ge=1, le=1000000)


# Migration 032 ck_dbsmart_metric_viz CHECK constraint ile uyumlu enum.
# Genişletme yaparken hem bu set hem migration 032:201 güncellenmeli.
VALID_VIZ_TYPES: List[str] = [
    "table", "bar", "line", "area", "kpi", "pie", "donut", "heatmap",
    "treemap", "funnel", "cohort", "map", "scatter", "box", "sankey",
    "sunburst", "calendar",
]
_VIZ_PATTERN = r"^(" + "|".join(VALID_VIZ_TYPES) + r")$"


class SaveReportRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    is_public: bool = False
    default_viz: str = Field(default="table", pattern=_VIZ_PATTERN)


class SaveReportResponse(BaseModel):
    report_id: int
    saved_at: str


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _require_user_id(current_user: Dict[str, Any]) -> int:
    uid = current_user.get("id")
    if uid is None:
        raise HTTPException(status_code=401, detail="Kullanıcı kimliği belirlenemedi.")
    return int(uid)


# ─────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────

@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(
    body: CreateSessionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CreateSessionResponse:
    """Yeni wizard oturumu açar. session_uid (UUID4) döner."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            session_uid = session_manager.create_session(
                cur, current_user, body.source_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            # RLS reddi veya INSERT failure → 403
            raise HTTPException(status_code=403, detail=str(e))
        conn.commit()
    return CreateSessionResponse(session_uid=session_uid, current_step=0, status="active")


@router.get("/sessions/{session_uid}")
def get_session(
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Mevcut oturum context'ini döner (refresh-safe hydrate)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        ctx = session_manager.load_session(cur, session_uid, current_user)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı veya yetkiniz yok.")
    return ctx


@router.post("/sessions/{session_uid}/step/{step_n}", response_model=StepResponse)
def post_step(
    body: StepRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    # NOT: WIZARD_NODES uzunluğu import-time freeze (mevcut 9 node).
    # WIZARD_NODES değişirse OpenAPI şeması yeniden yüklenmeli.
    step_n: int = Path(..., ge=0, le=len(state_machine.WIZARD_NODES) - 1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> StepResponse:
    """Kullanıcı seçimini kaydet + next step önerilerini döner.

    P5: state_machine sonucu ek olarak session_manager.update_context ile
    DB'ye persiste edilir (context'e step_{n} key'i altında payload yazılır).
    """
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        result = state_machine.run_wizard_step(session_uid, step_n, body.payload, current_user)
        # P5: payload + current_step persist
        partial = {("step_" + str(step_n)): body.payload}
        # state_machine bir merge ipucu döndürdüyse (context_patch), onu da uygula
        ctx_patch = result.get("context_patch") if isinstance(result, dict) else None
        if isinstance(ctx_patch, dict):
            partial.update(ctx_patch)
        next_step = result.get("next_step")
        session_manager.update_context(
            cur, session_uid, partial,
            current_user, current_step=next_step if next_step is not None else step_n,
        )
        conn.commit()
    return StepResponse(
        session_uid=session_uid,
        current_step=step_n,
        next_step=result.get("next_step"),
        node=result.get("node", state_machine.WIZARD_NODES[step_n]),
        suggestions=result.get("suggestions", {}),
    )


class AstPatchRequest(BaseModel):
    """FAZ 2 G2.1 — drag-drop AST patch.

    op whitelist: add_column / remove_column / add_filter / remove_filter
                  / modify_join / reorder_by / set_limit
    args: ilgili ast_renderer fonksiyonunun kwargs payload'ı.
    render_preview: True → yanıt SQL/binds da içerir (cost rozet için).
    """
    op: str
    args: Dict[str, Any] = Field(default_factory=dict)
    render_preview: bool = False
    dialect: Optional[str] = None


class AstPatchResponse(BaseModel):
    ast: Dict[str, Any]
    sql: Optional[str] = None
    binds: Optional[Dict[str, Any]] = None
    dialect: Optional[str] = None


_AST_OP_WHITELIST = {
    "add_column",
    "remove_column",
    "add_filter",
    "remove_filter",
    "modify_join",
    "reorder_by",
    "set_limit",
}


@router.post("/sessions/{session_uid}/ast/patch", response_model=AstPatchResponse)
def post_ast_patch(
    body: AstPatchRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> AstPatchResponse:
    """Drag-drop AST patch — deterministik, LLM-siz (<100ms latency budget).

    ARES: op whitelist + ast_renderer içinde identifier+operator+join-kind guard'ları.
    """
    _require_user_id(current_user)
    op = (body.op or "").strip()
    if op not in _AST_OP_WHITELIST:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen AST op: {op!r}")

    from app.services.db_smart import ast_renderer

    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        ctx = session_manager.load_session(cur, session_uid, current_user)
        if ctx is None:
            raise HTTPException(status_code=404, detail="Oturum bulunamadı veya yetkiniz yok.")

        ast = (ctx.get("context") or {}).get("ast") or {}
        if not ast:
            raise HTTPException(
                status_code=409,
                detail="AST henüz oluşturulmadı. Önce wizard'dan ilerleyin.",
            )

        fn = getattr(ast_renderer, op, None)
        if not callable(fn):
            raise HTTPException(status_code=400, detail=f"AST op çağrılamadı: {op}")
        try:
            new_ast = fn(ast, **(body.args or {}))
        except TypeError as e:
            # args mismatch — caller hatası
            raise HTTPException(status_code=400, detail=f"AST args hatası: {e}")
        except ValueError as e:
            # identifier/operator whitelist veya semantik guard
            raise HTTPException(status_code=400, detail=str(e))

        # Patch'i context'e yaz
        ok = session_manager.update_context(
            cur, session_uid, {"ast": new_ast}, current_user,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Oturum bulunamadı (RLS).")
        conn.commit()

    sql = binds = dialect_out = None
    if body.render_preview:
        dialect = body.dialect or ctx.get("dialect") or "postgresql"
        try:
            rendered = ast_renderer.render(new_ast, dialect, current_user)
            sql = rendered["sql"]
            binds = rendered["binds"]
            dialect_out = rendered["dialect"]
        except ValueError as e:
            # AST patch geçerliydi ama render'da kalan kısımda problem var
            logger.warning("[db_smart.ast] preview render skipped uid=%s: %s", session_uid, e)

    return AstPatchResponse(
        ast=new_ast,
        sql=sql,
        binds=binds,
        dialect=dialect_out,
    )


class PreviewRequest(BaseModel):
    """Transient preview: session_manager (G1.7) gelene kadar caller wizard_state'i
    request body'sine koyabilir. Body boşsa session_manager.load_session() denenir."""
    wizard_state: Optional[Dict[str, Any]] = None


@router.post("/sessions/{session_uid}/preview", response_model=PreviewResponse)
def post_preview(
    session_uid: str = Path(..., min_length=8, max_length=64),
    body: Optional[PreviewRequest] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PreviewResponse:
    """SQL render + EXPLAIN + maliyet tahmini + streaming kararı.

    G1.5 hazır: query_assembler.assemble() çalışır. G1.7 session persist yok →
    caller `body.wizard_state` ile geçici state gönderebilir (transient mod).
    """
    _require_user_id(current_user)
    # Lazy import — circular guard
    from app.services.db_smart import query_assembler

    wizard_state: Optional[Dict[str, Any]] = body.wizard_state if body else None
    if not wizard_state:
        # P5: gerçek session_manager.load_session — cursor RLS-scoped.
        with get_db_context() as _conn_lookup:
            _cur_lookup = _conn_lookup.cursor()
            apply_vyra_user_context(_cur_lookup, current_user)
            loaded = session_manager.load_session(_cur_lookup, session_uid, current_user)
        # Context içine wizard_state'i step_* anahtarlarından inşa etmek state_machine
        # işi; ham context'i transient wizard_state olarak kullan.
        ctx = (loaded or {}).get("context") if loaded else None
        wizard_state = ctx.get("wizard_state") if isinstance(ctx, dict) else None

    if not wizard_state:
        # G1.7 öncesi: state bulunmadıysa boş şablonu döndür
        return PreviewResponse(
            sql="-- preview unavailable: wizard_state not provided and session storage pending (G1.7)",
            dialect="postgresql",
            estimated_rows=None,
        )

    dialect = wizard_state.get("dialect", "postgresql")
    out = query_assembler.assemble(wizard_state, current_user, dialect=dialect)
    sql = out.get("sql") or ""

    explain: Dict[str, Any] = {}
    cost: Optional[float] = None
    if sql and dialect == "postgresql":
        try:
            with get_db_context() as conn:
                cur = conn.cursor()
                apply_vyra_user_context(cur, current_user)
                cost = query_assembler.explain_cost(
                    cur, sql, dialect, current_user, binds=out.get("binds"),
                )
                if cost is not None:
                    explain = {"total_cost": cost}
        except Exception as e:
            logger.warning("[db_smart] explain failed: %s", e)

    # G1.5 Step 7 — üç-yollu streaming kararı (direct | cursor | sse_chunk)
    # query_assembler.decide_streaming_strategy() row threshold öncelikli,
    # cost fallback. estimated_rows FAZ 2'de pg_class.reltuples'tan dolacak.
    estimated_rows: Optional[int] = None
    streaming_strategy = query_assembler.decide_streaming_strategy(
        cost=cost, estimated_rows=estimated_rows,
    )

    return PreviewResponse(
        sql=sql or "-- assembly failed: " + "; ".join(out.get("errors") or []),
        dialect=dialect,
        explain=explain,
        estimated_rows=estimated_rows,
        streaming_strategy=streaming_strategy,
    )


@router.post("/sessions/{session_uid}/execute")
def post_execute(
    body: ExecuteRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """safe_sql_executor üzerinden çalıştır (SSE destekli).

    FAZ 1 stub: gerçek streaming SSE FAZ 2'de bağlanacak.
    """
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 2): safe_sql_executor.run(...) + SSE chunk if stream=True
    return {
        "session_uid": session_uid,
        "exec_id": None,
        "rows": [],
        "row_count": 0,
        "status": "stub",
    }


@router.post("/sessions/{session_uid}/save-report", response_model=SaveReportResponse)
def post_save_report(
    body: SaveReportRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> SaveReportResponse:
    """dbsmart_saved_reports'a yaz (snapshot of context + SQL + viz)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1): INSERT INTO dbsmart_saved_reports + RETURNING id, saved_at
    # FAZ 1 stub değeri
    from datetime import datetime, timezone
    return SaveReportResponse(report_id=0, saved_at=datetime.now(timezone.utc).isoformat())


# ─────────────────────────────────────────────────────────────
# Discovery (sources, tables, columns, related)
# ─────────────────────────────────────────────────────────────

@router.get("/sources")
def list_sources(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Kullanıcının erişebildiği data_sources'u döner (company-scoped)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1.2): SELECT id, name, db_type FROM data_sources + permission filter
    return {"items": [], "count": 0}


@router.get("/sources/{source_id}/tables")
def search_tables(
    source_id: int = Path(..., ge=1),
    q: str = Query("", description="Doğal dil arama sorgusu"),
    limit: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Hybrid arama: ds_db_objects + business_glossary embedding + cardinality boost."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            items = eligibility.search_domains(
                cur, source_id=source_id, query=q,
                user_ctx=current_user, limit=limit,
            )
        except Exception as e:
            logger.warning("[db_smart] search_tables failed source=%s: %s", source_id, e)
            items = []
    return {"items": items, "tables": items, "query": q, "source_id": source_id, "count": len(items)}


@router.get("/sources/{source_id}/tables/{table_id}/related")
def related_tables(
    source_id: int = Path(..., ge=1),
    table_id: int = Path(..., ge=1),
    depth: int = Query(1, ge=1, le=3),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """FK graph genişletme — direct neighbors + cardinality + junction tespiti."""
    _require_user_id(current_user)
    neighbors: List[Dict[str, Any]] = []
    junctions: List[Dict[str, Any]] = []
    subgraph: Dict[str, Any] = {"nodes": [], "edges": [], "stats": {}}
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            neighbors = fk_graph.expand_with_fk(
                cur, source_id=source_id, table_ids=[table_id], depth=depth,
            )
            subgraph = fk_graph.build_subgraph(
                cur, source_id=source_id, table_ids=[table_id],
                user_ctx=current_user, depth=depth,
            )
            junctions = fk_graph.detect_junctions(subgraph)
        except Exception as e:
            logger.warning("[db_smart] related_tables failed source=%s table=%s: %s",
                           source_id, table_id, e)
    return {
        "neighbors": neighbors,
        "junctions": junctions,
        "subgraph": subgraph,
        "source_id": source_id,
        "table_id": table_id,
    }


@router.get("/sources/{source_id}/tables/{table_id}/columns")
def list_columns(
    source_id: int = Path(..., ge=1),
    table_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Kolon enrichment + semantic_type + cardinality + sample."""
    _require_user_id(current_user)
    columns: List[Dict[str, Any]] = []
    sample: Optional[Dict[str, Any]] = None
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            # ds_db_objects.columns_json + ds_column_enrichments (table_name LOWER match)
            cur.execute("""
                SELECT o.schema_name, o.object_name, o.columns_json
                FROM ds_db_objects o
                WHERE o.source_id = %s AND o.id = %s
                LIMIT 1
            """, (int(source_id), int(table_id)))
            row = cur.fetchone()
            obj_columns_json = (row[2] if row else None) or []
            schema = row[0] if row else None
            obj_name = row[1] if row else None

            # Enrichment: business_name_tr, semantic_type, business_meaning_tr
            enrich_map: Dict[str, Dict[str, Any]] = {}
            if obj_name:
                cur.execute("""
                    SELECT ce.column_name, ce.semantic_type, ce.business_name_tr,
                           ce.description_tr
                    FROM ds_column_enrichments ce
                    JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
                    WHERE te.source_id = %s
                      AND LOWER(te.table_name) = LOWER(%s)
                      AND LOWER(COALESCE(te.schema_name, '')) = LOWER(COALESCE(%s, ''))
                """, (int(source_id), obj_name, schema or ""))
                for r in cur.fetchall():
                    enrich_map[(r[0] or "").lower()] = {
                        "semantic_type": r[1],
                        "business_name_tr": r[2],
                        "description_tr": r[3],
                    }

            for c in (obj_columns_json or []):
                col_name = c.get("name") or c.get("column_name") or ""
                meta = enrich_map.get(col_name.lower(), {})
                columns.append({
                    "name": col_name,
                    "data_type": c.get("type") or c.get("data_type"),
                    "is_nullable": c.get("nullable", c.get("is_nullable", True)),
                    "semantic_type": meta.get("semantic_type"),
                    "business_name_tr": meta.get("business_name_tr"),
                    "description_tr": meta.get("description_tr"),
                })

            sample = eligibility.sample_preview(cur, table_id=table_id, user_ctx=current_user)
        except Exception as e:
            logger.warning("[db_smart] list_columns failed source=%s table=%s: %s",
                           source_id, table_id, e)
    return {
        "columns": columns,
        "sample": sample,
        "source_id": source_id,
        "table_id": table_id,
    }


# ─────────────────────────────────────────────────────────────
# Metrics & Recommendations
# ─────────────────────────────────────────────────────────────

@router.get("/metrics")
def list_metrics(
    source_id: int = Query(..., ge=1),
    table_id: Optional[int] = Query(None, ge=1, description="ds_db_objects.id — eligibility skor için tablo imzası bu id'den türetilir"),
    table_signature: str = Query("", description="(legacy) Hashed table-id list — UI v3 ile birlikte deprecated; table_id kullanın"),
    min_score: float = Query(0.6, ge=0.0, le=1.0),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Eligible metric list (applicable_when match + skor ile sıralı; threshold default 0.6).

    table_id verilirse: metric_engine.list_eligible() çağrılır (skorlu, filtrelenmiş).
    Aksi halde: tüm aktif metrik listesi döner (geriye dönük uyum).
    """
    _require_user_id(current_user)
    items: List[Dict[str, Any]] = []
    signature_meta: Optional[Dict[str, Any]] = None

    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            if table_id is not None:
                # FAZ 1 P3 G1.4: tablo imzasına göre eligible + skorlu liste
                sig = metric_engine.load_table_signature(cur, source_id, table_id)
                if sig is None:
                    raise HTTPException(status_code=404, detail="Tablo bulunamadı veya erişim yok.")
                items = metric_engine.list_eligible(cur, sig, current_user, min_score=min_score)
                signature_meta = {
                    "table_id": sig["table_id"],
                    "object_name": sig["object_name"],
                    "row_count": sig["row_count"],
                    "column_count": len(sig["columns"]),
                }
            else:
                # Geriye dönük: tüm aktif metrikleri kategori bazında listele
                cur.execute("""
                    SELECT metric_key, name_tr, category, description_tr,
                           default_viz, applicable_when, sql_templates
                    FROM dbsmart_metric_library
                    WHERE is_active IS TRUE OR is_active IS NULL
                    ORDER BY category, metric_key
                    LIMIT 60
                """)
                for r in cur.fetchall():
                    items.append({
                        "metric_key": r[0],
                        "name_tr": r[1],
                        "category": r[2],
                        "description_tr": r[3],
                        "default_viz": r[4],
                        "applicable_when": r[5],
                        "sql_templates": r[6],
                    })
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("[db_smart] list_metrics failed: %s", e)
    return {
        "items": items,
        "source_id": source_id,
        "table_id": table_id,
        "table_signature": table_signature,
        "signature": signature_meta,
        "min_score": min_score,
        "count": len(items),
    }


@router.get("/recommendations/{exec_id}")
def get_recommendations(
    exec_id: str = Path(..., min_length=1, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Sonuç analizi → rapor önerisi (Prompt H).

    FAZ 2 P9: gerçek dbsmart_executions/dbsmart_report_recommendations entegrasyonu
    bandit + öğrenme döngüsüyle (FAZ 4) bağlanacak. Şimdilik exec_id resolution
    stub — caller mevcut sonucu /recommendations/preview ile transient analiz edebilir.
    """
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 4): dbsmart_report_recommendations'tan bandit-skorlu öneriler
    return {"exec_id": exec_id, "recommendations": []}


class RecommendPreviewRequest(BaseModel):
    """FAZ 2 P9 G2.3 — Transient recommendation: caller execute sonucundan
    rows+columns ile direkt analiz çağırır (exec history persist YOK).
    """
    columns: List[str] = Field(default_factory=list)
    rows: List[Any] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)


@router.post("/recommendations/preview")
def post_recommendation_preview(
    body: RecommendPreviewRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Transient sonuç → chart önerileri + insight'lar (deterministik, LLM-siz).

    Latency budget: <50ms (rows sampled to first 500). Saf hesap, RLS gerekmez
    (caller'ın elindeki veri zaten kendi yetkisinde toplandı).
    """
    _require_user_id(current_user)
    try:
        charts = recommendation.recommend_charts(
            body.rows, body.columns, max_results=body.max_results,
        )
        insights = recommendation.detect_insights(body.rows, body.columns)
    except Exception as e:
        logger.warning("[db_smart.recommend] preview failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Recommend hesabı başarısız: {e}")
    return {
        "profile": charts.get("profile"),
        "charts": charts.get("items", []),
        "insights": insights,
    }
