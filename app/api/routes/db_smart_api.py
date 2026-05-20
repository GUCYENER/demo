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
from fastapi.responses import StreamingResponse
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
    recommendation,        # v3.30.0 FAZ 2 P9 G2.3
    custom_metric_parser,  # v3.30.0 FAZ 2 P11 G2.2
    saved_reports,         # v3.30.0 FAZ 3 P13 G3.3
    template_marketplace,  # v3.30.0 FAZ 3 P18 G3.3
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
    # FAZ 3 P13 — `title` legacy alanı; aynı zamanda `name` ile gelen istekleri kabul et
    title: Optional[str] = Field(default=None, max_length=200)
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    is_public: bool = False
    default_viz: str = Field(default="table", pattern=_VIZ_PATTERN)
    tags: Optional[List[str]] = None


class SaveReportResponse(BaseModel):
    report_id: int
    saved_at: str


# FAZ 3 P13 — Saved Reports (CRUD + share)
class SavedReportUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    wizard_state: Optional[Dict[str, Any]] = None
    last_sql: Optional[str] = None
    last_dialect: Optional[str] = None


class CreateShareTokenRequest(BaseModel):
    ttl_hours: int = Field(default=24, ge=1, le=720)


class CreateShareTokenResponse(BaseModel):
    share_token: str
    share_expires_at: Optional[str] = None
    ttl_hours: int


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
                  / modify_join / reorder_by / reorder_columns / set_limit
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
    "reorder_columns",   # v3.30.0 FAZ 3 P19 G3.4 — drag-drop SELECT reorder
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


# ─────────────────────────────────────────────────────────────
# v3.30.0 FAZ 3 P19 G3.4 — AST diff API + EXPLAIN cache
# ─────────────────────────────────────────────────────────────

class AstDiffRequest(BaseModel):
    """İki AST snapshot arasında yapısal fark — drag-drop "ne değişti?" preview."""
    from_ast: Dict[str, Any] = Field(default_factory=dict)
    to_ast: Dict[str, Any] = Field(default_factory=dict)


@router.post("/ast/diff")
def post_ast_diff(
    body: AstDiffRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """`ast_renderer.diff_ast` çıktısı — DB hit yok, pure compute, <10ms.

    Drag-drop sırasında frontend `from_ast` (önceki snapshot) +
    `to_ast` (yeni patch sonucu) gönderir. Yanıt: changed_sections summary +
    her bölüm için added/removed/modified detayları. Sadece auth gerekli.
    """
    _require_user_id(current_user)
    from app.services.db_smart import ast_renderer
    try:
        return ast_renderer.diff_ast(body.from_ast or {}, body.to_ast or {})
    except Exception as e:
        logger.warning("[db_smart.ast] diff failed: %s", e)
        raise HTTPException(status_code=400, detail=f"AST diff hatası: {e}")


# In-process EXPLAIN cache — 5sn TTL, max 256 entry (FIFO eviction).
# Drag-drop sırasında aynı AST için tekrar EXPLAIN çağrılmasın diye.
import hashlib  # noqa: E402
import json     # noqa: E402
import time as _time  # noqa: E402

_EXPLAIN_CACHE: Dict[str, Any] = {}
_EXPLAIN_CACHE_TTL_S = 5.0
_EXPLAIN_CACHE_MAX = 256


def _explain_cache_key(user_id: int, ast: Dict[str, Any], dialect: str) -> str:
    payload = json.dumps({"u": user_id, "d": dialect, "a": ast},
                         sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _explain_cache_get(key: str) -> Optional[Dict[str, Any]]:
    entry = _EXPLAIN_CACHE.get(key)
    if not entry:
        return None
    if _time.monotonic() - entry["ts"] > _EXPLAIN_CACHE_TTL_S:
        _EXPLAIN_CACHE.pop(key, None)
        return None
    return entry["value"]


def _explain_cache_put(key: str, value: Dict[str, Any]) -> None:
    if len(_EXPLAIN_CACHE) >= _EXPLAIN_CACHE_MAX:
        # FIFO eviction — en eski entry'yi at
        try:
            oldest = next(iter(_EXPLAIN_CACHE))
            _EXPLAIN_CACHE.pop(oldest, None)
        except StopIteration:
            pass
    _EXPLAIN_CACHE[key] = {"ts": _time.monotonic(), "value": value}


class ExplainAstRequest(BaseModel):
    """EXPLAIN cache — drag-drop sırasında cost rozeti için sub-100ms feedback."""
    ast: Dict[str, Any] = Field(default_factory=dict)
    dialect: str = "postgresql"


@router.post("/sessions/{session_uid}/explain")
def post_explain_ast(
    body: ExplainAstRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """AST → SQL render + EXPLAIN (PG) + 5sn in-process cache.

    Drag-drop sırasında her patch sonrası çağrılır; aynı AST/dialect kombinasyonu
    için 5sn boyunca cached cost döner (DB hit yok).
    Cache key: sha1(user_id + dialect + canonical_json(ast)).
    """
    uid = _require_user_id(current_user)
    from app.services.db_smart import ast_renderer, query_assembler

    ast = body.ast or {}
    dialect = (body.dialect or "postgresql").strip().lower()
    if not ast or ast.get("type") != "select":
        raise HTTPException(status_code=400, detail="AST geçersiz (type=select bekleniyor).")

    cache_key = _explain_cache_key(uid, ast, dialect)
    cached = _explain_cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    try:
        rendered = ast_renderer.render(ast, dialect, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"AST render hatası: {e}")

    sql = rendered.get("sql") or ""
    cost: Optional[float] = None
    explain: Dict[str, Any] = {}
    if sql and dialect == "postgresql":
        try:
            with get_db_context() as conn:
                cur = conn.cursor()
                apply_vyra_user_context(cur, current_user)
                cost = query_assembler.explain_cost(
                    cur, sql, dialect, current_user,
                    binds=rendered.get("binds"),
                )
                if cost is not None:
                    explain = {"total_cost": cost}
        except Exception as e:
            logger.warning("[db_smart.explain] failed uid=%s: %s", session_uid, e)

    streaming_strategy = query_assembler.decide_streaming_strategy(
        cost=cost, estimated_rows=None,
    )
    payload = {
        "sql": sql,
        "dialect": dialect,
        "explain": explain,
        "streaming_strategy": streaming_strategy,
        "cached": False,
    }
    _explain_cache_put(cache_key, {k: v for k, v in payload.items() if k != "cached"})
    return payload


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


class ExecuteStreamRequest(BaseModel):
    """P15 G3.2 — Streaming SQL execute via SSE."""
    sql: Optional[str] = Field(default=None, description="Direkt SQL (preview'den)")
    wizard_state: Optional[Dict[str, Any]] = Field(default=None, description="SQL üretimi için (sql verilmezse assemble edilir)")
    dialect: str = Field(default="postgresql", max_length=20)
    source_id: Optional[int] = Field(default=None, ge=1)
    batch_size: int = Field(default=200, ge=10, le=1000)
    max_rows: int = Field(default=10_000, ge=1, le=100_000)


def _load_source(
    cur: Any,
    source_id: int,
    current_user: Dict[str, Any],
) -> Optional[tuple]:
    """data_sources kaydını yükle + permission gate + password decrypt.

    Returns:
        (source_dict_no_password, password_plaintext, dialect) tuple veya None.

    ARES guard'ları:
        - `user_can_access_source(permission='can_execute')` — kullanıcı bu kaynağı
          execute yetkisiyle açabiliyor mu? (Admin bypass mevcut.)
        - `password` plaintext döndürülen dict'e KOYULMAZ — ayrı değer.
        - `db_password_encrypted` → `_decrypt_stored_password()` (Fernet/base64).
        - SELECT sadece is_active=TRUE kayıtları döner.
    """
    # 1) Permission gate (RLS yetmiyor — admin bypass + org membership için explicit)
    from app.services.data_source_access import user_can_access_source
    uid = int(current_user.get("id") or 0)
    is_admin = bool(current_user.get("is_admin", False))
    if uid <= 0:
        return None
    if not user_can_access_source(
        uid, int(source_id),
        is_admin=is_admin,
        permission="can_execute",
    ):
        return None

    # 2) Kayıt yükle — gerçek sütun adları (migration 002)
    cur.execute(
        """
        SELECT id, company_id, name, db_type, host, port,
               db_name, db_user, db_password_encrypted
        FROM data_sources
        WHERE id = %s
          AND is_active = TRUE
        LIMIT 1
        """,
        (int(source_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    keys = ["id", "company_id", "name", "db_type", "host", "port",
            "db_name", "db_user", "db_password_encrypted"]
    rec = dict(zip(keys, row))

    # 3) Password decrypt — _decrypt_stored_password Fernet/base64 fallback
    password_plain = ""
    encrypted = rec.pop("db_password_encrypted", None)
    if encrypted:
        try:
            from app.api.routes.data_sources_api import _decrypt_stored_password
            password_plain = _decrypt_stored_password(encrypted) or ""
        except Exception as e:
            logger.warning("[db_smart.stream] password decrypt failed source=%s: %s",
                           source_id, e)
            password_plain = ""

    # 4) source dict — _get_db_connector'ın beklediği sade alanlar
    source_dict = {
        "id": rec["id"],
        "db_type": rec["db_type"],
        "host": rec["host"],
        "port": rec["port"],
        "db_name": rec["db_name"],
        "db_user": rec["db_user"],
    }
    dialect = (rec.get("db_type") or "postgresql").lower()
    return source_dict, password_plain, dialect


@router.post("/sessions/{session_uid}/execute/stream")
def post_execute_stream(
    body: ExecuteStreamRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """P15 G3.2 — Server-Sent Events ile streaming SQL execute.

    SSE event'leri:
        event: start    — {sql_preview}
        event: columns  — {columns: [...]}
        event: rows     — {rows: [...], batch_index}
        event: end      — {row_count, elapsed_ms, truncated}
        event: error    — {message}

    PG path: server-side named cursor + fetchmany. Diğer dialect'ler standart
    cursor + fetchmany (ileride engine-spesifik opt — oracledb arraysize,
    pymysql SSCursor).
    """
    _require_user_id(current_user)
    # Lazy import — circular guard
    from app.services.db_smart import sql_executor_stream
    from app.services.pipeline.streaming_execute import stream_to_sse

    # SQL hazırlığı: body.sql > wizard_state assembly > load session
    sql_str = (body.sql or "").strip()
    dialect = body.dialect or "postgresql"
    src_id = body.source_id

    if not sql_str:
        from app.services.db_smart import query_assembler
        wizard_state = body.wizard_state
        if not wizard_state:
            with get_db_context() as conn:
                cur = conn.cursor()
                apply_vyra_user_context(cur, current_user)
                loaded = session_manager.load_session(cur, session_uid, current_user)
            if loaded is None:
                raise HTTPException(status_code=404, detail="Oturum bulunamadı veya yetkiniz yok.")
            ctx = (loaded.get("context") if isinstance(loaded, dict) else None) or {}
            wizard_state = ctx.get("wizard_state") if isinstance(ctx, dict) else None
            if not src_id and isinstance(loaded, dict):
                src_id = loaded.get("source_id")
        if not wizard_state:
            raise HTTPException(status_code=400, detail="SQL veya wizard_state gerekli.")
        out = query_assembler.assemble(wizard_state, current_user, dialect=dialect)
        sql_str = (out.get("sql") or "").strip()
        if not sql_str:
            errs = "; ".join(out.get("errors") or [])
            raise HTTPException(status_code=400, detail=f"SQL üretilemedi: {errs}")

    if not src_id:
        raise HTTPException(status_code=400, detail="source_id gerekli.")

    # data_sources kaydını yükle (permission gate + password decrypt)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        loaded_src = _load_source(cur, int(src_id), current_user)
    if loaded_src is None:
        # 404 vs 403 ayırmıyoruz — varlık vs yetki sızıntısını önler
        raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı veya erişim yok.")
    src_dict, src_password, src_dialect = loaded_src
    # source.db_type request.dialect ile uyumsuzsa source'a güven (ARES)
    if src_dialect and src_dialect != dialect:
        logger.info("[db_smart.stream] dialect override request=%s source=%s",
                    dialect, src_dialect)
        dialect = src_dialect

    # SSE generator
    def _event_stream():
        try:
            for evt in sql_executor_stream.stream_safe_sql(
                sql_str, src_dict, dialect,
                password=src_password,
                allowed_tables=None,
                user_ctx=current_user,
                batch_size=body.batch_size,
                max_rows=body.max_rows,
            ):
                yield stream_to_sse(evt)
        except Exception as e:
            logger.exception("[db_smart.stream] event loop error")
            import json as _json
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{session_uid}/save-report", response_model=SaveReportResponse)
def post_save_report(
    body: SaveReportRequest,
    session_uid: str = Path(..., min_length=8, max_length=64),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> SaveReportResponse:
    """Oturum context'ini dbsmart_saved_reports'a yaz (snapshot of context + SQL + viz).

    P13: session_manager.load_session ile context çekilir; saved_reports.save() ile
    INSERT yapılır. name/title alanlarından biri kullanılır.
    """
    _require_user_id(current_user)
    raw_name = (body.name or body.title or "").strip()
    if not raw_name:
        raise HTTPException(status_code=400, detail="name (veya title) zorunlu.")

    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        loaded = session_manager.load_session(cur, session_uid, current_user)
        if loaded is None:
            raise HTTPException(status_code=404, detail="Oturum bulunamadı veya yetkiniz yok.")
        ctx = (loaded.get("context") if isinstance(loaded, dict) else None) or {}
        wizard_state = ctx.get("wizard_state") if isinstance(ctx, dict) else None
        if not isinstance(wizard_state, dict):
            wizard_state = dict(ctx) if isinstance(ctx, dict) else {}
        last_sql = ctx.get("last_sql") if isinstance(ctx, dict) else None
        last_dialect = ctx.get("dialect") if isinstance(ctx, dict) else None
        source_id = loaded.get("source_id") if isinstance(loaded, dict) else None

        out = saved_reports.save(
            cur, current_user,
            name=raw_name,
            wizard_state=wizard_state,
            last_sql=last_sql,
            last_dialect=last_dialect,
            source_id=source_id,
            description=body.description,
            tags=body.tags,
        )
        if out is None:
            raise HTTPException(status_code=500, detail="Rapor kaydedilemedi.")
        conn.commit()

    created = out.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return SaveReportResponse(report_id=int(out["id"]), saved_at=str(created or ""))


# ─────────────────────────────────────────────────────────────
# FAZ 3 P13 G3.3 — Saved Reports CRUD + Share
# ─────────────────────────────────────────────────────────────

@router.get("/saved-reports")
def list_saved_reports(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Kullanıcının kayıtlı raporları (RLS-bound, updated_at DESC)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        items = saved_reports.list_for_user(cur, current_user, limit=limit, offset=offset)
    return {"items": items, "count": len(items), "limit": limit, "offset": offset}


@router.get("/saved-reports/{report_id}")
def get_saved_report(
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Tek rapor — wizard_state + last_sql dahil (RLS-bound)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        rep = saved_reports.get_by_id(cur, report_id, current_user)
    if rep is None:
        raise HTTPException(status_code=404, detail="Rapor bulunamadı veya yetkiniz yok.")
    return rep


@router.patch("/saved-reports/{report_id}")
def patch_saved_report(
    body: SavedReportUpdateRequest,
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Patch update — yalnızca verilen alanlar değişir."""
    _require_user_id(current_user)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="En az bir alan güncellenmeli.")
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            ok = saved_reports.update(cur, report_id, current_user, **patch)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not ok:
            raise HTTPException(status_code=404, detail="Rapor bulunamadı veya değişiklik yok.")
        conn.commit()
    return {"ok": True, "report_id": report_id}


@router.post("/saved-reports/{report_id}/share", response_model=CreateShareTokenResponse)
def post_share_report(
    body: CreateShareTokenRequest,
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CreateShareTokenResponse:
    """Share token üret + is_shared=TRUE + expires_at."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            out = saved_reports.create_share_token(
                cur, report_id, current_user, ttl_hours=body.ttl_hours,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if out is None:
            raise HTTPException(status_code=404, detail="Rapor bulunamadı veya yetkiniz yok.")
        conn.commit()
    exp = out.get("share_expires_at")
    if hasattr(exp, "isoformat"):
        exp = exp.isoformat()
    return CreateShareTokenResponse(
        share_token=out["share_token"],
        share_expires_at=exp,
        ttl_hours=out["ttl_hours"],
    )


@router.post("/saved-reports/{report_id}/revoke-share")
def post_revoke_share(
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """is_shared=FALSE; token audit için saklı kalır."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        ok = saved_reports.revoke_share(cur, report_id, current_user)
        if not ok:
            raise HTTPException(status_code=404, detail="Rapor bulunamadı veya yetkiniz yok.")
        conn.commit()
    return {"ok": True, "report_id": report_id}


@router.post("/saved-reports/{report_id}/mark-run")
def post_mark_run(
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """run_count++ + last_run_at=NOW(). Snapshot opsiyonel (sonraki iterasyon)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        ok = saved_reports.mark_run(cur, report_id, current_user)
        if not ok:
            raise HTTPException(status_code=404, detail="Rapor bulunamadı veya yetkiniz yok.")
        conn.commit()
    return {"ok": True, "report_id": report_id}


# PUBLIC — auth YOK, token-bound erişim. RLS bypass'a güvenmez (saved_reports.get_by_share_token
# içinde explicit is_shared=TRUE AND share_expires_at > NOW() filtresi var).
@router.get("/saved-reports/by-token/{token}")
def get_saved_report_by_token(
    token: str = Path(..., min_length=8, max_length=128),
) -> Dict[str, Any]:
    """PUBLIC share view — token süreli, expiry geçince 404."""
    with get_db_context() as conn:
        cur = conn.cursor()
        # apply_vyra_user_context BİLİNÇLİ OLARAK çağrılmıyor; sorgu explicit filtreliyor
        rep = saved_reports.get_by_share_token(cur, token)
    if rep is None:
        raise HTTPException(status_code=404, detail="Paylaşım bulunamadı veya süresi doldu.")
    # PII açısından güvenli alanlar — user_id/company_id dışarı sızdırılmıyor
    return {
        "id": rep.get("id"),
        "name": rep.get("name"),
        "description": rep.get("description"),
        "source_id": rep.get("source_id"),
        "wizard_state": rep.get("wizard_state"),
        "last_sql": rep.get("last_sql"),
        "last_dialect": rep.get("last_dialect"),
        "tags": rep.get("tags"),
        "last_run_snapshot": rep.get("last_run_snapshot"),
        "share_expires_at": rep.get("share_expires_at"),
    }


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


# ─────────────────────────────────────────────────────────────
# FAZ 2 P11 G2.2 — Custom Metric NL→SQL
# ─────────────────────────────────────────────────────────────

class CustomMetricRequest(BaseModel):
    """Türkçe doğal dil metrik tanımı → SQL + opsiyonel kütüphaneye kaydet."""
    nl_query: str = Field(..., min_length=2, max_length=2000)
    source_id: int = Field(..., ge=1)
    table_ids: List[int] = Field(default_factory=list, max_length=10)
    dialect: str = Field(default="postgresql", max_length=20)
    save: bool = Field(default=False, description="True → dbsmart_metric_library'ye kaydet")
    name_tr: Optional[str] = Field(default=None, max_length=160, description="save=True ise zorunlu")
    description_tr: Optional[str] = Field(default=None, max_length=2000)
    default_viz: str = Field(default="table", max_length=40)


class CustomMetricResponse(BaseModel):
    success: bool
    sql: Optional[str] = None
    intent: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    explanation: Optional[str] = None
    saved_metric_id: Optional[int] = None
    metric_key: Optional[str] = None


@router.post("/metrics/custom", response_model=CustomMetricResponse)
def post_custom_metric(
    body: CustomMetricRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> CustomMetricResponse:
    """Doğal dilden özel metrik üret + opsiyonel olarak kütüphaneye kaydet.

    Pipeline:
        1. Schema context build (table_ids ile slim — LLM'in görmesi gereken
           tablo/kolon kümesi sınırlı tutulur, prompt boyutu küçük).
        2. parse_to_sql → generate_sql + validate_sql + check_table_whitelist.
        3. save=True ise dbsmart_metric_library INSERT (is_official=FALSE).

    save=True ama name_tr boş → 400.
    table_ids boş → parser zaten error döner; status 200 (success=False).
    """
    _require_user_id(current_user)
    if body.save and not (body.name_tr and body.name_tr.strip()):
        raise HTTPException(status_code=400, detail="save=True için name_tr zorunlu.")
    if body.default_viz not in VALID_VIZ_TYPES:
        raise HTTPException(status_code=400, detail=f"Geçersiz viz tipi: {body.default_viz}")

    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            schema_ctx = custom_metric_parser.build_metric_schema_context(
                cur, body.source_id, body.table_ids, dialect=body.dialect,
            )
        except Exception as e:
            logger.warning("[db_smart] custom_metric schema build failed: %s", e)
            raise HTTPException(status_code=500, detail=f"Schema context kurulumu başarısız: {e}")

        result = custom_metric_parser.parse_to_sql(body.nl_query, schema_ctx)

        saved_id: Optional[int] = None
        metric_key: Optional[str] = None
        if result.get("success") and body.save:
            metric_key = custom_metric_parser._make_metric_key(
                body.name_tr or "", int(current_user["id"]),
            )
            saved_id = custom_metric_parser.save_custom_metric(
                cur,
                user_ctx=current_user,
                name_tr=body.name_tr or "",
                sql=result["sql"],
                source_id=body.source_id,
                description_tr=body.description_tr,
                default_viz=body.default_viz,
                intent=result.get("intent"),
            )
            if saved_id is not None:
                try:
                    conn.commit()
                except Exception:
                    pass

    return CustomMetricResponse(
        success=bool(result.get("success")),
        sql=result.get("sql"),
        intent=result.get("intent") or {},
        error=result.get("error"),
        explanation=result.get("explanation"),
        saved_metric_id=saved_id,
        metric_key=metric_key if saved_id is not None else None,
    )


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


# ─────────────────────────────────────────────────────────────
# FAZ 3 P18 G3.3 — Template Marketplace (internal)
# ─────────────────────────────────────────────────────────────

@router.get("/templates")
def list_templates(
    category: Optional[str] = Query(default=None, max_length=60),
    q: Optional[str] = Query(default=None, max_length=80),
    is_official: Optional[bool] = Query(default=None),
    owner: str = Query(default="all", pattern="^(all|mine|community|official)$"),
    order: str = Query(default="popular", pattern="^(popular|recent|name)$"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Metric library üzerinden filtreli template browse (marketplace).

    Parametre:
        category: helpdesk/sales/generic vb.
        q: name_tr/description_tr ILIKE arama (escape edilmiş)
        is_official: TRUE / FALSE / null
        owner: mine | community | official | all
        order: popular | recent | name
        limit: 1..200
    """
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            items = template_marketplace.browse(
                cur, current_user,
                category=category, q=q, is_official=is_official,
                owner=owner, order=order, limit=limit,
            )
        except Exception as e:
            logger.warning("[db_smart] templates browse failed: %s", e)
            raise HTTPException(status_code=400, detail="Şablon listesi alınamadı.")
    return {
        "items": items,
        "count": len(items),
        "filter": {
            "category": category, "q": q, "is_official": is_official,
            "owner": owner, "order": order, "limit": limit,
        },
    }


@router.get("/templates/categories")
def list_template_categories(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Marketplace UI sol panel — kategori + sayım listesi."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        cats = template_marketplace.get_categories(cur)
    return {"items": cats, "count": len(cats)}


@router.get("/templates/{metric_key}")
def get_template(
    metric_key: str = Path(..., min_length=1, max_length=120),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Tek template detayı (apply için: sql_templates / applicable_when / required_features)."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        rec = template_marketplace.get_by_key(cur, metric_key, current_user)
    if rec is None:
        raise HTTPException(status_code=404, detail="Şablon bulunamadı.")
    return rec
