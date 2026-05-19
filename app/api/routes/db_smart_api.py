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
        # FAZ 1 stub — session_manager gerçek INSERT FAZ 1 G1 dolduracak.
        session_uid = session_manager.create_session(current_user, body.source_id)
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
        ctx = session_manager.load_session(session_uid, current_user)
    if ctx is None:
        # FAZ 1 stub — gerçek 404 mantığı session_manager dolunca devreye girer.
        return {"session_uid": session_uid, "context": {}, "current_step": 0, "status": "stub"}
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
    """Kullanıcı seçimini kaydet + next step önerilerini döner."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        result = state_machine.run_wizard_step(session_uid, step_n, body.payload, current_user)
    return StepResponse(
        session_uid=session_uid,
        current_step=step_n,
        next_step=result.get("next_step"),
        node=result.get("node", state_machine.WIZARD_NODES[step_n]),
        suggestions=result.get("suggestions", {}),
    )


@router.post("/sessions/{session_uid}/preview", response_model=PreviewResponse)
def post_preview(
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> PreviewResponse:
    """SQL render + EXPLAIN + maliyet tahmini + streaming kararı.

    FAZ 1 stub: query_assembler + ast_renderer FAZ 1 G1.5'te dolacak.
    """
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1.5): query_assembler.assemble(ctx) → ast_renderer.render(ast, dialect)
    return PreviewResponse(sql="-- preview stub (FAZ 1 G1.5)", dialect="postgresql")


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
    """Hybrid arama: ds_db_objects + business_glossary_v2 embedding + cardinality boost."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1.2): eligibility.search_domains(source_id, q, limit)
    return {"items": [], "query": q, "source_id": source_id}


@router.get("/sources/{source_id}/tables/{table_id}/related")
def related_tables(
    source_id: int = Path(..., ge=1),
    table_id: int = Path(..., ge=1),
    depth: int = Query(1, ge=1, le=3),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """FK graph genişletme — direct neighbors + cardinality + junction tespiti."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1.3): fk_graph.expand_with_fk([table_id], depth)
    return {"neighbors": [], "junctions": [], "source_id": source_id, "table_id": table_id}


@router.get("/sources/{source_id}/tables/{table_id}/columns")
def list_columns(
    source_id: int = Path(..., ge=1),
    table_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Kolon enrichment + semantic_type + cardinality + sample."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1.2): JOIN ds_db_objects + ds_column_enrichments + ds_db_samples
    return {"columns": [], "source_id": source_id, "table_id": table_id}


# ─────────────────────────────────────────────────────────────
# Metrics & Recommendations
# ─────────────────────────────────────────────────────────────

@router.get("/metrics")
def list_metrics(
    source_id: int = Query(..., ge=1),
    table_signature: str = Query("", description="Hashed table-id list (sorted)"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Eligible metric list (skor ile sıralı; threshold > 0.6)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 1 G1.4): metric_engine.list_eligible(source_id, table_signature)
    return {"items": [], "source_id": source_id, "table_signature": table_signature}


@router.get("/recommendations/{exec_id}")
def get_recommendations(
    exec_id: str = Path(..., min_length=1, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Sonuç analizi → rapor önerisi (Prompt H)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 2): dbsmart_report_recommendations'tan bandit-skorlu öneriler
    return {"exec_id": exec_id, "recommendations": []}
