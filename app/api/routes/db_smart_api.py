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

import hashlib
import json
import logging
import threading
import time as _time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response
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
    insight_detector,      # v3.30.0 FAZ 2 P28
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
    # FIX3 P0-4 (HERMES+ORACLE): le=1_000_000 → le=100_000.
    # Sync fetchall OOM riski: 1M satır × ortalama 200B = 200MB+ memory.
    # limit > 50_000 ise stream=True zorunlu (executor'da enforce).
    stream: bool = False
    limit: Optional[int] = Field(default=1000, ge=1, le=100_000)


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
    # F10b Fix 3 (POSEIDON+ATHENA): client wizard_state body override — backend
    # session context'i stale/empty kalabilir; client'ın canonical state'ini
    # tercih et. None ise eski davranış (ctx.get("wizard_state")) geçerli.
    wizard_state: Optional[Dict[str, Any]] = None
    generated_sql: Optional[str] = None
    metric_key: Optional[str] = None
    schema_version: Optional[str] = None


class SaveReportFlatRequest(BaseModel):
    """F10b Fix 1 (POSEIDON+ARES): session-less flat save payload.

    Modal-mode veya session drop sonrası kayıt yapabilmek için session_uid
    bağımsız kayıt route'u. Tenant scoping current_user'dan (RLS bound).
    """
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    source_id: Optional[int] = None
    wizard_state: Dict[str, Any] = Field(default_factory=dict)
    generated_sql: Optional[str] = None
    metric_key: Optional[str] = None
    tags: Optional[List[str]] = None
    schema_version: Optional[str] = Field(default="v3.36", max_length=20)


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


# v3.34.x B10 — LLM column-order suggestion (Filtre step "✨ LLM ile öner")
# v3.36.x F8b (ATHENA+APOLLO+POSEIDON): F7 multi-table desteğinde aynı kolon
# adı farklı tablolarda olabilir (örn. iki tabloda `id`). `table_id` istek
# tarafına ve `ordered_pairs` yanıt tarafına additive olarak eklendi.
# Geriye uyum: eski client `ordered` (List[str]) alanını kullanmaya devam
# edebilir; eski client table_id göndermezse first-match heuristic devreye
# girer.
class ColumnInfo(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    semantic_type: Optional[str] = Field(default=None, max_length=60)
    table: Optional[str] = Field(default=None, max_length=200)
    table_id: Optional[int] = Field(default=None, ge=1)


class SuggestOrderReq(BaseModel):
    source_id: int = Field(..., ge=1)
    primary_table_id: int = Field(..., ge=1)
    join_table_ids: List[int] = Field(default_factory=list)
    available_columns: List[ColumnInfo] = Field(..., min_length=1, max_length=200)


class OrderedColumn(BaseModel):
    """F8b — response item with table_id disambiguator."""
    name: str = Field(..., min_length=1, max_length=200)
    table_id: Optional[int] = Field(default=None, ge=1)


class SuggestOrderResp(BaseModel):
    # Legacy field — sadece kolon adı listesi (geriye uyum).
    ordered: List[str]
    # F8b additive: (name, table_id) çiftleri. Eğer istekte hiçbir
    # available_columns item'ında table_id yoksa, bu alandaki table_id'ler
    # null kalır (heuristic fallback de table_id taşıyamadığı için).
    ordered_pairs: List[OrderedColumn] = Field(default_factory=list)
    rationale: str
    fallback: bool = False


# v3.36.x F9 — Generate-report (LLM → validated SELECT → SafeSQLExecutor)
class GenerateReportReq(BaseModel):
    source_id: int = Field(..., ge=1)
    primary_table_id: int = Field(..., ge=1)
    join_table_ids: List[int] = Field(default_factory=list)
    # report_columns: [{name, table_name?, semantic_type?}]
    report_columns: List[Dict[str, Any]] = Field(default_factory=list)
    metric: Optional[Dict[str, Any]] = None
    user_note: str = Field(default="", max_length=2000)
    # fk_context: [{from_table, to_table, from_col, to_col}]
    fk_context: List[Dict[str, Any]] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)


class GenerateReportResp(BaseModel):
    sql: str
    rationale: str
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    elapsed_ms: int = 0
    truncated: bool = False
    success: bool
    fallback: bool = False
    error: Optional[str] = None


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

# F-020 (ARES ORTA): set_limit dispatch'inde args.limit üst sınır clamp'i.
# ast_renderer.set_limit non-negative int'i kabul eder ama upper-bound yok →
# `limit: 10**18` → SQL syntax error / OOM riski. Bu dosyada clamp ederek
# ast_renderer.py'ye dokunmuyoruz (başka agent'lar paralel çalışıyor).
_AST_SET_LIMIT_MAX = 10_000_000  # 10M satır cap


def _detect_company_scoped_aliases(ast: Dict[str, Any]) -> List[str]:
    """AST'in from + joins yapısından alias listesi türet.

    F-021 (ARES KRİTİK) fix: `/ast/patch render_preview=true` path'i
    `inject_rls`'i atlıyordu — preview SQL'i başka context'e copy-paste
    edilirse cross-tenant sızıntı riski. Heuristic: tüm tablo alias'larını
    company-scoped say (over-restrictive ama güvenli). is_admin user için
    `inject_rls` zaten no-op döner; non-admin için company_id filter
    eklenir (alias.company_id = <ctx.company_id>).
    """
    # FIX3 P1 B2 (ARES): AST'ten gelen alias string'lerini ham olarak
    # inject_rls'e geçirmek, attacker-controlled AST üzerinden alias adına
    # SQL fragment enjekte etme riski yaratır (örn. alias = "u; DROP TABLE...").
    # ast_renderer._validate_ident regex whitelist'iyle her aliası doğrula;
    # geçersizler atılır + warning loglanır.
    from app.services.db_smart.ast_renderer import _validate_ident

    def _safe_add(a: Any, bucket: List[str]) -> None:
        if not isinstance(a, str) or not a:
            return
        try:
            _validate_ident(a)
            bucket.append(a)
        except ValueError:
            logger.warning("[db_smart.ast] invalid alias rejected: %r", a)

    aliases: List[str] = []
    if not isinstance(ast, dict):
        return aliases
    src = ast.get("from")
    if isinstance(src, dict):
        a = src.get("alias") or src.get("table")
        _safe_add(a, aliases)
    joins = ast.get("joins") or []
    if isinstance(joins, list):
        for j in joins:
            if not isinstance(j, dict):
                continue
            tbl = j.get("table")
            if isinstance(tbl, dict):
                a = tbl.get("alias") or tbl.get("table") or tbl.get("name")
            else:
                a = j.get("alias") or (tbl if isinstance(tbl, str) else None)
            _safe_add(a, aliases)
    # Dedup, sıralı
    seen = set()
    out: List[str] = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


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

    # F17 (ARES+POSEIDON+HERMES 2026-05-25): Top-level try/except. Önceden
    # session_manager.{load_session,update_context} DB errors veya
    # ast_renderer.{inject_rls,render} non-ValueError/TypeError exception'ları
    # FastAPI default 500 traceback olarak console spam yapıyordu. Artık
    # logger.exception ile log'a düşer + clean JSON 500 döner. HTTPException
    # bilerek raise edilenler re-raise edilir.
    try:
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

            # F-020: set_limit dispatch'inde args.limit clamp (10M cap).
            # _AST_OP_WHITELIST kontrolünden SONRA, fn(...) çağrısından ÖNCE.
            if op == "set_limit" and isinstance(body.args, dict) and "limit" in body.args:
                _lim = body.args.get("limit")
                if isinstance(_lim, int) and _lim > _AST_SET_LIMIT_MAX:
                    body.args["limit"] = _AST_SET_LIMIT_MAX

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
                # F-021 (ARES KRİTİK): render'dan ÖNCE inject_rls — preview SQL
                # başka path'e copy-paste edilirse cross-tenant sızıntı olmasın.
                # company_scoped_aliases AST'in from+joins yapısından heuristic
                # olarak türetilir; admin için inject_rls no-op döner.
                _company_aliases = _detect_company_scoped_aliases(new_ast)
                guarded_ast = ast_renderer.inject_rls(
                    new_ast, current_user,
                    company_scoped_tables=_company_aliases,
                )
                # Explicit skip flag: render() defense-in-depth would otherwise
                # auto-inject RLS again — `inject_rls` is idempotent (predicate
                # dedup), so this is purely a clarity/perf optimization.
                rendered = ast_renderer.render(
                    guarded_ast, dialect, current_user,
                    _rls_already_injected=True,
                )
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
    except HTTPException:
        # Bilerek raise edilen 400/404/409 — FastAPI'ye olduğu gibi geç.
        raise
    except Exception:
        # F17: önceden bare 500 + traceback console spam'i. Artık log'a yaz +
        # clean JSON body dön (frontend F6 policy 5xx + no-interaction → silent).
        logger.exception(
            "[db_smart.ast/patch] unhandled exception uid=%s op=%s",
            session_uid, op,
        )
        raise HTTPException(
            status_code=500,
            detail="AST yaması işlenirken iç hata oluştu (detay log'da).",
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
# N-4: dict mutation thread-safe değil; FIFO eviction'da next(iter(...)) +
# pop arasında concurrent put → KeyError race riski. Module-level Lock ile
# get/put kritik bölgeleri serialize.
_EXPLAIN_CACHE: Dict[str, Any] = {}
_EXPLAIN_CACHE_TTL_S = 5.0
_EXPLAIN_CACHE_MAX = 256
_EXPLAIN_CACHE_LOCK = threading.Lock()


def _explain_cache_key(user_id: int, ast: Dict[str, Any], dialect: str) -> str:
    # FIX3 P1 B5 (ARES): canonical JSON — sort_keys + compact separators.
    # Önceki versiyon default ", "/": " separator'ları kullanıyordu; aynı
    # AST için Python sürümleri / dict insertion order farklılıkları
    # whitespace driftine yol açabilir → false cache miss + EXPLAIN spam.
    # `separators=(",", ":")` ve `sort_keys=True` deterministic.
    payload = json.dumps(
        {"u": user_id, "d": dialect, "a": ast},
        sort_keys=True, default=str, separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _explain_cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _EXPLAIN_CACHE_LOCK:
        entry = _EXPLAIN_CACHE.get(key)
        if not entry:
            return None
        if _time.monotonic() - entry["ts"] > _EXPLAIN_CACHE_TTL_S:
            _EXPLAIN_CACHE.pop(key, None)
            return None
        return entry["value"]


def _explain_cache_put(key: str, value: Dict[str, Any]) -> None:
    with _EXPLAIN_CACHE_LOCK:
        if len(_EXPLAIN_CACHE) >= _EXPLAIN_CACHE_MAX:
            # FIFO eviction — en eski entry'yi at
            try:
                oldest = next(iter(_EXPLAIN_CACHE))
                _EXPLAIN_CACHE.pop(oldest, None)
            except (StopIteration, KeyError):
                # KeyError: concurrent eviction (lock altında olsa da defansif)
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
    # F17 (ARES+POSEIDON+HERMES 2026-05-25): AST henüz hazır değil (örn. wizard
    # starter AST'ında `type` set edilmemiş, veya F9 generate-report sonrası
    # session AST persist edilmemiş) — eskiden 400 dönüp console spam yapıyordu.
    # Artık 200 + has_ast:false ile graceful skip; frontend `_refreshExplain`
    # bu durumda cost badge'i temizler, hata kaydetmez.
    # F17b (ARES 2026-05-25): boş select listesi de "AST henüz hazır değil"
    # demektir — ast_renderer "SELECT requires at least one column" ValueError
    # fırlatıp 400'e yol açıyordu. Starter AST (kolon eklenmeden önce) ve F-9
    # öncesi tüm durumlar bu yolu kullanır.
    _sel = ast.get("select") if isinstance(ast, dict) else None
    _select_empty = not isinstance(_sel, list) or len(_sel) == 0
    if not ast or ast.get("type") != "select" or _select_empty:
        return {
            "has_ast": False,
            "sql": "",
            "dialect": dialect,
            "explain": {},
            "streaming_strategy": "direct",
            "cached": False,
        }

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

    FIX3 P0-4 (HERMES+ORACLE+ARES): limit > 50_000 ise stream=True şarttır
    (sync fetchall OOM koruması). Hard clamp 100_000 (Pydantic le=100_000
    zaten zorunlu kılıyor, defansif extra).
    """
    _require_user_id(current_user)
    # FIX3 P0-4: limit > 50k → stream zorunlu; ayrıca hard clamp 100k.
    _req_limit = body.limit if body.limit is not None else 1000
    if _req_limit > 100_000:
        _req_limit = 100_000  # defansif clamp (Pydantic le=100k zaten)
    if _req_limit > 50_000 and not body.stream:
        raise HTTPException(
            status_code=400,
            detail="limit > 50000 için stream=True zorunlu (OOM koruması).",
        )
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # TODO (FAZ 2): safe_sql_executor.run(..., limit=_req_limit) + SSE chunk if stream=True
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
    # F21c (ARES 2026-05-25): Optional + None default — caller (saved-report rerun)
    # dialect bilmek zorunda kalmasın; backend source.db_type'tan resolve eder.
    # Explicit dialect (eski caller'lar) verirse mismatch guard halen devrede.
    dialect: Optional[str] = Field(default=None, max_length=20)
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
    # FIX3 P1 B3 (HERMES+ARES): silent empty-string fallback yok. Decrypt
    # başarısız olursa connector "" password ile bağlanmaya çalışır → ya
    # auth fail (kafa karıştırıcı log) ya da (peer auth varsa) yanlış
    # identity'yle bağlantı. Explicit 500 fırlat, observability korunsun.
    password_plain = ""
    encrypted = rec.pop("db_password_encrypted", None)
    if encrypted:
        try:
            from app.api.routes.data_sources_api import _decrypt_stored_password
            password_plain = _decrypt_stored_password(encrypted) or ""
        except Exception as e:
            logger.error("[db_smart.stream] password decrypt failed source=%s: %s",
                         source_id, e)
            raise HTTPException(
                status_code=500,
                detail="Source credential decrypt failed",
            )

    # F22c (ARES 2026-05-25): db_type değeri data_sources kaydı oluşturulurken
    # yanlış girilmiş olabilir (örn. literal "db_type") → sql_executor_stream
    # whitelist'i {"postgresql","oracle","mssql","mysql"} dışında ise 500
    # değil sessiz fallback. Engine alias'larını da normalize ediyoruz.
    # NOTE v3.37.4: dialect normalization moved AHEAD of port defensive cast
    # because the port-default fallback below needs a normalized db_type to
    # pick the right default (oracle=1521 vs. postgresql=5432 etc.).
    _DIALECT_ALIAS = {
        "postgres": "postgresql", "psql": "postgresql", "pg": "postgresql",
        "ora": "oracle", "oracledb": "oracle",
        "sqlserver": "mssql", "sql_server": "mssql", "ms_sql": "mssql",
    }
    _SUPPORTED_DIALECTS = {"postgresql", "oracle", "mssql", "mysql"}
    _DEFAULT_PORTS = {
        "postgresql": 5432, "oracle": 1521, "mssql": 1433, "mysql": 3306,
    }
    raw_dt = (rec.get("db_type") or "").strip().lower()
    dialect = _DIALECT_ALIAS.get(raw_dt, raw_dt)
    if dialect not in _SUPPORTED_DIALECTS:
        logger.warning(
            "[db_smart._load_source] source_id=%s db_type=%r desteklenmiyor; "
            "postgresql fallback uygulanıyor.",
            source_id, rec.get("db_type"),
        )
        dialect = "postgresql"

    # Bug C v3.37.4 (revision 2): port defensive cast with db_type-aware
    # default fallback. Earlier revision raised 500 on bad port — actionable
    # for the DB admin, but a hard block for the end user whose only
    # recourse was filing a ticket. Now: try int cast; if the row carries
    # a literal "port" string (real data corruption case observed in
    # source_id=3 on 2026-05-28), WARN-log it AND substitute the canonical
    # port for the normalized dialect so the report run proceeds. The
    # admin still sees a single WARN line per source per process lifetime
    # because we don't suppress repeat hits.
    raw_port = rec.get("port")
    try:
        port_int = int(raw_port)
    except (TypeError, ValueError):
        default_port = _DEFAULT_PORTS.get(dialect)
        if default_port is None:
            # Should be unreachable — dialect is forced to postgresql above —
            # but kept as a guard so future dialect additions can't crash.
            logger.error(
                "[db_smart._load_source] data_sources.port invalid AND no "
                "default port for dialect=%r source_id=%s port=%r",
                dialect, source_id, raw_port,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Veri kaynağı port değeri bozuk (source_id={source_id}): "
                    f"{raw_port!r}. DB yöneticisine bildirin — örn. "
                    f"UPDATE data_sources SET port=<INT> WHERE id={source_id};"
                ),
            )
        port_int = default_port
        logger.warning(
            "[db_smart._load_source] data_sources.port invalid (=%r) for "
            "source_id=%s; using dialect=%r default port=%d. Schedule a "
            "data fix: UPDATE data_sources SET port=%d WHERE id=%s;",
            raw_port, source_id, dialect, port_int, port_int, source_id,
        )

    # 4) source dict — _get_db_connector'ın beklediği sade alanlar
    source_dict = {
        "id": rec["id"],
        "db_type": rec["db_type"],
        "host": rec["host"],
        "port": port_int,
        "db_name": rec["db_name"],
        "db_user": rec["db_user"],
    }
    # B1 fix v3.37.0: normalize db_type for downstream consumers
    # (ds_learning_service._get_db_connector saved-report rerun yolunda
    # source_dict["db_type"] değerini okur; alias/whitelist normalize'i
    # burada uygulanmazsa literal "db_type" gibi bozuk değerler hata verir).
    source_dict["db_type"] = dialect
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
    # F21c (ARES): dialect explicit-vs-implicit ayır; None ise source dialect kullan.
    dialect_explicit = body.dialect is not None and body.dialect.strip() != ""
    dialect = (body.dialect or "postgresql").strip()
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

    # v3.37.1 Brief A (HERMES→ZEUS direct-apply 2026-05-26):
    # body.source_id None ve body.wizard_state.source_id var ise fallback.
    # Saved-report rerun yolunda dbsmart_saved_reports.source_id NULL ise
    # frontend body.source_id göndermeyebilir; wizard_state snapshot her
    # zaman source_id taşır (v3.30+ yazma yolu garanti eder).
    if not src_id and isinstance(body.wizard_state, dict):
        ws_sid = body.wizard_state.get("source_id")
        if ws_sid:
            try:
                src_id = int(ws_sid)
                logger.debug(
                    "[db_smart.stream] source_id wizard_state fallback: %s",
                    src_id,
                )
            except (TypeError, ValueError):
                pass

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
    # v3.37.1 Brief A (HERMES→ZEUS direct-apply 2026-05-26):
    # port defensive — psycopg2/oracledb literal "port" string'i sızarsa ham
    # "invalid integer value 'port' for connection option 'port'" yerine
    # anlaşılır Türkçe mesaj. data_sources kolonu integer ama snapshot
    # path'lerde literal sızabilir; explicit cast + raise.
    try:
        src_dict["port"] = int(src_dict.get("port"))
    except (TypeError, ValueError) as _port_err:
        logger.error(
            "[db_smart.stream] invalid port literal source_id=%s value=%r: %s",
            src_id, src_dict.get("port"), _port_err,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Source port literal değil int olmalı "
                f"(source_id={src_id}): {src_dict.get('port')!r}"
            ),
        )
    # v3.37.1 Brief A — wizard_state.dialect ile data_sources.db_type mismatch
    # ise DEBUG log (data_sources yetkili olur; aşağıdaki F21c bloğu zaten
    # src_dialect'i adopte ediyor).
    if isinstance(body.wizard_state, dict):
        ws_dialect = body.wizard_state.get("dialect")
        if ws_dialect and src_dialect and ws_dialect != src_dialect:
            logger.debug(
                "[db_smart.stream] dialect mismatch wizard=%r db=%r — db_type yetkili",
                ws_dialect, src_dialect,
            )
    # FIX3 P1 B1 (ORACLE): dialect mismatch artık silent downgrade DEĞİL.
    # Caller'ın yanlış dialect ile SQL render ettiği query'yi sessizce başka
    # bir engine'de çalıştırmak data corruption / syntax error riski yaratır.
    # Explicit 400 ile reddet.
    # F21c (ARES 2026-05-25): dialect_explicit=False ise (saved-report rerun gibi
    # caller'lar source dialect'i bilmeden çağırır) source dialect'i adopte et.
    # Explicit caller mismatch hâlen reddedilir.
    if dialect_explicit and src_dialect and src_dialect != dialect:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Dialect mismatch: source is {src_dialect}, "
                f"request specified {dialect}"
            ),
        )
    if not dialect_explicit and src_dialect:
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

    # F16 (HEBE+ARES+POSEIDON): explicit try/except + logger.exception →
    # generic 500'ün gerçek kök sebebini server log'a çıkar + client'a
    # actionable detail döndür (FE generic "Sunucuda beklenmeyen…" yerine).
    out = None
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            apply_vyra_user_context(cur, current_user)
            loaded = session_manager.load_session(cur, session_uid, current_user)
            if loaded is None:
                raise HTTPException(status_code=404, detail="Oturum bulunamadı veya yetkiniz yok.")
            ctx = (loaded.get("context") if isinstance(loaded, dict) else None) or {}
            # F10b Fix 3 (POSEIDON+ATHENA): client body wizard_state > session ctx.
            # Session context auto-sync edilmiyorsa stale/empty kaydı önler.
            if isinstance(body.wizard_state, dict) and body.wizard_state:
                wizard_state = body.wizard_state
            else:
                wizard_state = ctx.get("wizard_state") if isinstance(ctx, dict) else None
                if not isinstance(wizard_state, dict):
                    wizard_state = dict(ctx) if isinstance(ctx, dict) else {}
            last_sql = body.generated_sql if body.generated_sql else (
                ctx.get("last_sql") if isinstance(ctx, dict) else None
            )
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
                # save() içinde yakalanmış DB exception veya RLS reddi.
                # Spesifik nedenler `saved_reports.save` logger.warning üretti.
                raise HTTPException(
                    status_code=500,
                    detail="Rapor kaydedilemedi (DB INSERT başarısız - server log'una bakın).",
                )
            conn.commit()
    except HTTPException:
        raise
    except ValueError as ve:
        # _require_user_ctx / name validation gibi açık hatalar 400 olmalı.
        logger.warning("[db_smart.save_report] validation error: %s", ve)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("[db_smart.save_report] unexpected failure session=%s", session_uid)
        raise HTTPException(
            status_code=500,
            detail=f"Rapor kaydedilemedi: {type(e).__name__}: {e}",
        )

    created = out.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return SaveReportResponse(report_id=int(out["id"]), saved_at=str(created or ""))


# ─────────────────────────────────────────────────────────────
# FAZ 3 P13 G3.3 — Saved Reports CRUD + Share
# ─────────────────────────────────────────────────────────────

@router.post("/saved-reports", response_model=SaveReportResponse)
def post_save_report_flat(
    body: SaveReportFlatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> SaveReportResponse:
    """F10b Fix 1 (POSEIDON+ARES+ATHENA): session-less flat save endpoint.

    Modal-mode veya session drop senaryosunda kullanılır. Tenant scoping
    current_user üzerinden RLS-bound (apply_vyra_user_context). Aynı
    response shape session-bound endpoint ile (report_id + saved_at).
    """
    _require_user_id(current_user)
    raw_name = (body.name or "").strip()
    if not raw_name:
        raise HTTPException(status_code=400, detail="name zorunlu.")

    wizard_state = body.wizard_state if isinstance(body.wizard_state, dict) else {}

    # F16 (HEBE+ARES+POSEIDON): mirror flat endpoint of try/except hardening.
    out = None
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            apply_vyra_user_context(cur, current_user)
            out = saved_reports.save(
                cur, current_user,
                name=raw_name,
                wizard_state=wizard_state,
                last_sql=body.generated_sql,
                last_dialect=None,
                source_id=body.source_id,
                description=body.description,
                tags=body.tags,
            )
            if out is None:
                raise HTTPException(
                    status_code=500,
                    detail="Rapor kaydedilemedi (DB INSERT başarısız - server log'una bakın).",
                )
            conn.commit()
    except HTTPException:
        raise
    except ValueError as ve:
        logger.warning("[db_smart.save_report_flat] validation error: %s", ve)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception("[db_smart.save_report_flat] unexpected failure")
        raise HTTPException(
            status_code=500,
            detail=f"Rapor kaydedilemedi: {type(e).__name__}: {e}",
        )

    created = out.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return SaveReportResponse(report_id=int(out["id"]), saved_at=str(created or ""))


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


# ─────────────────────────────────────────────────────────────
# Duplicate (Kopya Farklı Kaydet) + Delete
# ─────────────────────────────────────────────────────────────

class _DuplicateBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)


@router.post("/saved-reports/{report_id}/duplicate", status_code=201)
def duplicate_saved_report(
    report_id: int = Path(..., ge=1),
    body: Optional[_DuplicateBody] = Body(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Saved report'u kopyalar — yeni id döner.

    RLS sahiplik kontrolü: kaynak rapor `current_user`'a ait değilse RLS
    policy SELECT'i 0 satır döndürür → 404. INSERT'te user_id/company_id
    explicit verilir (default'lar yok); wizard_state JSONB cast edilir.
    """
    _require_user_id(current_user)
    uid = current_user.get("id") or current_user.get("user_id")
    cid = current_user.get("company_id")
    if uid is None or cid is None:
        raise HTTPException(status_code=401, detail="Kullanıcı bağlamı eksik (user_id/company_id).")

    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)

        # 1) Kaynak raporu oku — RLS policy non-owner için 0 satır döner.
        cur.execute(
            """
            SELECT name, description, wizard_state, source_id,
                   last_sql, last_dialect, tags
            FROM dbsmart_saved_reports
            WHERE id = %s
            """,
            (int(report_id),),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Rapor bulunamadı veya yetkiniz yok.")

        if isinstance(row, dict):
            src_name = row.get("name")
            src_desc = row.get("description")
            src_ws = row.get("wizard_state")
            src_source_id = row.get("source_id")
            src_last_sql = row.get("last_sql")
            src_last_dialect = row.get("last_dialect")
            src_tags = row.get("tags")
        else:
            src_name = row[0]
            src_desc = row[1]
            src_ws = row[2]
            src_source_id = row[3]
            src_last_sql = row[4]
            src_last_dialect = row[5]
            src_tags = row[6]

        req_name = body.name.strip() if (body and body.name and body.name.strip()) else None
        new_name = (req_name or f"Kopya - {src_name or ''}")[:200]

        # wizard_state JSONB — dict/list ise serialize, str ise olduğu gibi geç,
        # None ise boş objeye düş (kolon NOT NULL).
        if isinstance(src_ws, (dict, list)):
            ws_json = json.dumps(src_ws, default=str)
        elif src_ws is None:
            ws_json = "{}"
        else:
            ws_json = str(src_ws)

        # tags TEXT[] — None ise NULL bırak, list ise psycopg array adapter halleder.
        tags_param = list(src_tags) if isinstance(src_tags, (list, tuple)) else src_tags

        try:
            cur.execute(
                """
                INSERT INTO dbsmart_saved_reports
                    (user_id, company_id, source_id, name, description,
                     wizard_state, last_sql, last_dialect, tags,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, NOW(), NOW())
                RETURNING id, name, created_at
                """,
                (
                    int(uid), int(cid), src_source_id, new_name, src_desc,
                    ws_json, src_last_sql, src_last_dialect, tags_param,
                ),
            )
        except Exception as e:
            logger.warning("[db_smart] duplicate_saved_report INSERT failed id=%s: %s",
                           report_id, e)
            raise HTTPException(status_code=500, detail="Rapor kopyalanamadı.")

        new_row = cur.fetchone()
        if not new_row:
            raise HTTPException(status_code=500, detail="Rapor kopyalanamadı.")
        conn.commit()

        if isinstance(new_row, dict):
            new_id = new_row.get("id")
            ret_name = new_row.get("name")
            created = new_row.get("created_at")
        else:
            new_id = new_row[0]
            ret_name = new_row[1]
            created = new_row[2]

    return {
        "id": int(new_id),
        "name": ret_name,
        "created_at": created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
    }


@router.delete("/saved-reports/{report_id}", status_code=204)
def delete_saved_report(
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Saved report sil. RLS policy başka user'ın raporunu görmez → 404."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            cur.execute(
                "DELETE FROM dbsmart_saved_reports WHERE id = %s",
                (int(report_id),),
            )
        except Exception as e:
            logger.warning("[db_smart] delete_saved_report failed id=%s: %s",
                           report_id, e)
            raise HTTPException(status_code=500, detail="Rapor silinemedi.")
        affected = getattr(cur, "rowcount", 0) or 0
        conn.commit()
    if affected == 0:
        raise HTTPException(status_code=404, detail="Rapor bulunamadı veya yetkiniz yok.")
    return Response(status_code=204)


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
# P40 — Embed iframe endpoint (token-bound, CSP-gated)
# ─────────────────────────────────────────────────────────────

from fastapi.responses import HTMLResponse

_EMBED_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VYRA — Paylaşılan Rapor</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:system-ui,-apple-system,sans-serif;background:#f8f9fa;color:#1a1a2e}
  .embed-wrap{max-width:960px;margin:24px auto;padding:0 16px}
  .embed-header{display:flex;align-items:center;gap:12px;margin-bottom:16px}
  .embed-header h2{font-size:18px;font-weight:600}
  .embed-meta{font-size:13px;color:#6c757d;margin-bottom:12px}
  .embed-table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;
    overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
  .embed-table th{background:#e9ecef;text-align:left;padding:10px 14px;font-size:13px;
    font-weight:600;border-bottom:2px solid #dee2e6}
  .embed-table td{padding:10px 14px;font-size:13px;border-bottom:1px solid #f1f3f5}
  .embed-table tr:hover td{background:#f8f9fa}
  .embed-footer{margin-top:16px;font-size:11px;color:#adb5bd;text-align:center}
  .embed-err{padding:40px;text-align:center;color:#dc3545}
  .embed-sql{background:#f1f3f5;border-radius:6px;padding:12px;font-family:monospace;
    font-size:12px;overflow-x:auto;margin-bottom:16px;white-space:pre-wrap}
</style>
</head>
<body>
<div class="embed-wrap" id="root">
  <div class="embed-header"><h2 id="rName">—</h2></div>
  <div class="embed-meta" id="rMeta"></div>
  <div class="embed-sql" id="rSql" style="display:none"></div>
  <table class="embed-table" id="rTable"><thead id="rHead"></thead><tbody id="rBody"></tbody></table>
  <div class="embed-footer">VYRA Embedded Report</div>
</div>
<script>
(function(){
  var token=location.pathname.split('/').pop();
  if(!token){document.getElementById('root').innerHTML='<div class="embed-err">Token bulunamadı.</div>';return;}
  fetch('/api/db-smart/saved-reports/by-token/'+encodeURIComponent(token))
    .then(function(r){if(!r.ok)throw new Error(r.status);return r.json()})
    .then(function(d){
      document.getElementById('rName').textContent=d.name||'Rapor';
      document.getElementById('rMeta').textContent=(d.description||'')
        +(d.share_expires_at?' — Son geçerlilik: '+d.share_expires_at:'');
      if(d.last_sql){var el=document.getElementById('rSql');el.style.display='block';el.textContent=d.last_sql;}
      var snap=d.last_run_snapshot;
      if(snap&&snap.columns&&snap.rows){
        var hRow='<tr>'+snap.columns.map(function(c){return '<th>'+esc(c)+'</th>'}).join('')+'</tr>';
        document.getElementById('rHead').innerHTML=hRow;
        var body=snap.rows.map(function(r){
          return '<tr>'+r.map(function(v){return '<td>'+esc(v===null?'—':v)+'</td>'}).join('')+'</tr>'
        }).join('');
        document.getElementById('rBody').innerHTML=body;
      }
    })
    .catch(function(e){document.getElementById('root').innerHTML='<div class="embed-err">Rapor yüklenemedi ('+e.message+')</div>';});
  function esc(s){var d=document.createElement('div');d.textContent=String(s);return d.innerHTML;}
})();
</script>
</body>
</html>"""


@router.get("/embed/{token}", response_class=HTMLResponse)
def embed_report(
    token: str = Path(..., min_length=8, max_length=128),
):
    """P40 — iframe embed edilebilir rapor sayfası.

    CSP frame-ancestors kısıtlaması main.py middleware'inde uygulanır
    (EMBED_FRAME_ANCESTORS config).
    """
    # Token validation is deferred to the JS fetch call (by-token endpoint).
    # This endpoint only serves the shell HTML; data flows via the API.
    return HTMLResponse(content=_EMBED_HTML_TEMPLATE, status_code=200)


# ─────────────────────────────────────────────────────────────
# Discovery (sources, tables, columns, related)
# ─────────────────────────────────────────────────────────────

@router.get("/sources")
def list_sources(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Kullanıcının erişebildiği data_sources'u döner (company-scoped).

    RLS / company_id filtreleme `apply_vyra_user_context` ile uygulanır;
    `data_sources` tablosunda `connection_status` kolonu YOKTUR (migration 002),
    bu nedenle response kontratını korumak için sabit 'unknown' döner.
    """
    _require_user_id(current_user)
    items: List[Dict[str, Any]] = []
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            cur.execute(
                """
                SELECT id, name, db_type, is_active
                FROM data_sources
                WHERE COALESCE(is_active, true) = true
                ORDER BY name ASC
                LIMIT 100
                """
            )
            rows = cur.fetchall() or []
        except Exception as e:
            logger.warning("[db_smart] list_sources query failed: %s", e)
            rows = []
        for r in rows:
            if isinstance(r, dict):
                items.append({
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "db_type": r.get("db_type"),
                    "connection_status": "unknown",
                    "is_active": bool(r.get("is_active")) if r.get("is_active") is not None else True,
                })
            else:
                items.append({
                    "id": r[0],
                    "name": r[1],
                    "db_type": r[2],
                    "connection_status": "unknown",
                    "is_active": bool(r[3]) if r[3] is not None else True,
                })
    return {"items": items, "count": len(items)}


@router.get("/sources/{source_id}/tables")
def search_tables(
    source_id: int = Path(..., ge=1),
    q: str = Query("", description="Doğal dil arama sorgusu"),
    limit: int = Query(20, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Hybrid arama: ds_db_objects + business_glossary embedding + cardinality boost.

    Cap 500'e yükseltildi (v3.34.0): Tablo Seçici alt-modal'ı kaynağa ait
    tüm yetkili tabloları tek sayfada listeler (q boş + limit=200 default).
    """
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


# v3.36 F7 (POSEIDON+ARES): tek-tablo kolon enrich mantığı — hem single
# (`list_columns`) hem multi (`list_columns_multi`) route'ları bu helper'ı
# kullanır. RealDictCursor + tuple cursor uyumu korunur. Per-tablo 50 kolon cap
# (R-4): büyük tabloların multi payload'u şişirmesini engeller.
_MAX_COLUMNS_PER_TABLE = 50


def _fetch_table_columns(
    cur,
    source_id: int,
    table_id: int,
) -> Dict[str, Any]:
    """Returns {table_id, table_name, schema_name, business_name_tr, columns:[…]}.

    columns: [{name, data_type, is_nullable, semantic_type, business_name_tr, description_tr}]
    Hard-cap _MAX_COLUMNS_PER_TABLE per table.
    """
    def _col(r, key, idx):
        return r[key] if isinstance(r, dict) else r[idx]

    cur.execute("""
        SELECT o.schema_name, o.object_name, o.columns_json
        FROM ds_db_objects o
        WHERE o.source_id = %s AND o.id = %s
        LIMIT 1
    """, (int(source_id), int(table_id)))
    row = cur.fetchone()
    obj_columns_json = (_col(row, 'columns_json', 2) if row else None) or []
    schema = _col(row, 'schema_name', 0) if row else None
    obj_name = _col(row, 'object_name', 1) if row else None

    # Enrichment: business_name_tr, semantic_type, description_tr (column-level)
    # + table-level business_name_tr (for group header)
    enrich_map: Dict[str, Dict[str, Any]] = {}
    table_business_name: Optional[str] = None
    if obj_name:
        cur.execute("""
            SELECT te.business_name_tr
            FROM ds_table_enrichments te
            WHERE te.source_id = %s
              AND LOWER(te.table_name) = LOWER(%s)
              AND LOWER(COALESCE(te.schema_name, '')) = LOWER(COALESCE(%s, ''))
            LIMIT 1
        """, (int(source_id), obj_name, schema or ""))
        trow = cur.fetchone()
        if trow:
            table_business_name = _col(trow, 'business_name_tr', 0)

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
            enrich_map[(_col(r, 'column_name', 0) or "").lower()] = {
                "semantic_type": _col(r, 'semantic_type', 1),
                "business_name_tr": _col(r, 'business_name_tr', 2),
                "description_tr": _col(r, 'description_tr', 3),
            }

    columns: List[Dict[str, Any]] = []
    for c in (obj_columns_json or [])[:_MAX_COLUMNS_PER_TABLE]:
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

    return {
        "table_id": int(table_id),
        "table_name": obj_name,
        "schema_name": schema,
        "business_name_tr": table_business_name,
        "columns": columns,
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
            info = _fetch_table_columns(cur, source_id, table_id)
            columns = info["columns"]
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


@router.get("/sources/{source_id}/tables/columns")
def list_columns_multi(
    source_id: int = Path(..., ge=1),
    table_ids: str = Query(..., description="CSV table id listesi — request order preserved."),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """v3.36 F7 (POSEIDON+ARES+HEBE) — Çoklu tablo kolon listesi.

    Filter step master-detail UI'sı için: primary + join tabloların kolonlarını
    tek round-trip'te döner. Sıra `table_ids` CSV order'ına sadıktır
    (UI tablo grup başlıklarını bu sıra ile render eder). Per-tablo
    `_MAX_COLUMNS_PER_TABLE=50` cap (R-4 payload guard).

    Response:
      {
        "source_id": int,
        "tables": [
          {
            "table_id": int,
            "table_name": str|None,
            "schema_name": str|None,
            "business_name_tr": str|None,
            "columns": [{name, data_type, is_nullable, semantic_type,
                         business_name_tr, description_tr}, ...]
          }, ...
        ],
        "count": int
      }
    """
    _require_user_id(current_user)
    # Parse CSV → list[int], skip non-numeric, preserve order, dedup.
    ids: List[int] = []
    seen: set = set()
    for tok in (table_ids or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            tid = int(tok)
        except ValueError:
            continue
        if tid in seen:
            continue
        seen.add(tid)
        ids.append(tid)
    if not ids:
        raise HTTPException(status_code=400, detail="table_ids parametresi geçerli tablo id'si içermiyor.")

    tables: List[Dict[str, Any]] = []
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        for tid in ids:
            try:
                tables.append(_fetch_table_columns(cur, source_id, tid))
            except Exception as e:
                logger.warning("[db_smart] list_columns_multi failed source=%s table=%s: %s",
                               source_id, tid, e)
                # Hata olsa bile slot'u doldur (UI sıra korunsun, kolonlar boş kalır).
                tables.append({
                    "table_id": int(tid),
                    "table_name": None,
                    "schema_name": None,
                    "business_name_tr": None,
                    "columns": [],
                })
    return {
        "source_id": source_id,
        "tables": tables,
        "count": len(tables),
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
    fallback: bool = False

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
                # B7 fallback (POSEIDON+ARES): eligible 0 → tüm aktif library'yi göster
                # ds_column_enrichments boş veya skor threshold yüksek olduğunda kullanıcı
                # boş ekran yerine library'nin tamamını görür; UI hint için fallback=True.
                if not items:
                    items = metric_engine.list_all_active(cur)
                    fallback = True
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
                # RealDictCursor + tuple cursor uyumu — kolon adıyla eriş.
                def _col(r, key, idx):
                    return r[key] if isinstance(r, dict) else r[idx]
                for r in cur.fetchall():
                    items.append({
                        "metric_key": _col(r, 'metric_key', 0),
                        "name_tr": _col(r, 'name_tr', 1),
                        "category": _col(r, 'category', 2),
                        "description_tr": _col(r, 'description_tr', 3),
                        "default_viz": _col(r, 'default_viz', 4),
                        "applicable_when": _col(r, 'applicable_when', 5),
                        "sql_templates": _col(r, 'sql_templates', 6),
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
        "fallback": fallback,
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
    # v3.30.0 FAZ 2 P28 — deep insights (z-score seasonal + slope reversal +
    # missing category). Default False → backward compatible.
    deep: bool = Field(default=False)
    deep_time_col: Optional[str] = Field(default=None, max_length=120)
    deep_value_col: Optional[str] = Field(default=None, max_length=120)
    deep_category_col: Optional[str] = Field(default=None, max_length=120)
    deep_expected_categories: List[str] = Field(default_factory=list)
    deep_z_threshold: float = Field(default=2.5, ge=0.0, le=10.0)
    deep_slope_window: int = Field(default=3, ge=2, le=30)
    deep_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


@router.post("/recommendations/preview")
def post_recommendation_preview(
    body: RecommendPreviewRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Transient sonuç → chart önerileri + insight'lar (deterministik, LLM-siz).

    Latency budget: <50ms (rows sampled to first 500). Saf hesap, RLS gerekmez
    (caller'ın elindeki veri zaten kendi yetkisinde toplandı).

    body.deep=True → P28 derin tespitler (insights_v2 alanı eklenir).
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
    resp: Dict[str, Any] = {
        "profile": charts.get("profile"),
        "charts": charts.get("items", []),
        "insights": insights,
    }
    if body.deep:
        series = [r for r in body.rows if isinstance(r, dict)]
        deep_insights: List[Dict[str, Any]] = []
        try:
            if body.deep_time_col and body.deep_value_col:
                deep_insights.extend(insight_detector.detect_z_score_seasonality(
                    series, body.deep_time_col, body.deep_value_col,
                    threshold=body.deep_z_threshold,
                ))
                deep_insights.extend(insight_detector.detect_slope_reversal(
                    series, body.deep_time_col, body.deep_value_col,
                    window=body.deep_slope_window,
                ))
            if body.deep_category_col and body.deep_expected_categories:
                deep_insights.extend(insight_detector.detect_missing_category(
                    series, body.deep_expected_categories, body.deep_category_col,
                ))
            deep_insights = insight_detector.confidence_guard(
                deep_insights, threshold=body.deep_confidence_threshold,
            )
        except Exception as e:
            logger.warning("[db_smart.recommend] deep insight failed: %s", e)
            deep_insights = []
        resp["insights_v2"] = deep_insights
    return resp


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


# ─────────────────────────────────────────────────────────────
# B10 — LLM column-order suggestion (Filtre step)
# Plan: 2026-05-25_0030_metric_filter_dnd_llm_v1.md
# Council: POSEIDON + APOLLO + ARES
# ─────────────────────────────────────────────────────────────

@router.post("/columns/suggest-order", response_model=SuggestOrderResp)
def post_suggest_column_order(
    req: SuggestOrderReq,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> SuggestOrderResp:
    """LLM ile rapor kolon sıralama önerisi.

    Filtre step'inin "✨ LLM ile öner" butonu çağırır. Body'deki
    available_columns'ı kapsam dışına çıkarmadan (yalnızca verilen kolonları
    yeniden sıralayarak) JSON döner.

    Fail-soft: LLM ulaşılamaz veya geçersiz yanıt verirse heuristik sıralama
    uygulanır ve `fallback=true` döner — 502 değil 200 döner (UI bozulmasın).

    Tenant guard: source_id, current_user.company_id'ye ait olmalı.
    """
    _require_user_id(current_user)

    company_id = current_user.get("company_id")
    if not company_id:
        logger.warning(
            "[db_smart] suggest_order: current_user.company_id boş (user_id=%s)",
            current_user.get("id"),
        )
        raise HTTPException(status_code=403, detail="Şirket bağlamı tanımlı değil.")

    # Tenant scope — mirrors query_state_api._resolve_source_info pattern.
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            cur.execute(
                """
                SELECT company_id
                FROM data_sources
                WHERE id = %s
                """,
                (int(req.source_id),),
            )
            row = cur.fetchone()
        except Exception as e:
            logger.warning(
                "[db_smart] suggest_order tenant-check failed source=%s: %s",
                req.source_id, e,
            )
            raise HTTPException(status_code=500, detail="Kaynak doğrulanamadı.")

    if row is None:
        raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")
    src_co = row.get("company_id") if isinstance(row, dict) else row[0]
    if int(src_co or 0) != int(company_id):
        logger.warning(
            "[db_smart] suggest_order cross-tenant: source=%s belongs to co=%s, "
            "current_user co=%s",
            req.source_id, src_co, company_id,
        )
        raise HTTPException(status_code=403, detail="Bu veri kaynağına erişim yok.")

    # Delegate to service (handles LLM call + heuristic fallback).
    from app.services.db_smart import llm_column_order

    result = llm_column_order.suggest_order(
        source_id=req.source_id,
        primary_table_id=req.primary_table_id,
        join_table_ids=list(req.join_table_ids or []),
        available_columns=[c.model_dump() for c in req.available_columns],
        current_user=current_user,
    )
    # F8b: ordered_pairs (name + table_id) additive olarak döner. Service
    # `ordered_pairs` üretir; üretemiyorsa biz burada `ordered`'dan boş
    # table_id ile sentezleriz (yine de yanıt sözleşmesi tutarlı kalır).
    ordered_names = list(result.get("ordered") or [])
    raw_pairs = result.get("ordered_pairs")
    if isinstance(raw_pairs, list) and raw_pairs:
        pairs_out: List[OrderedColumn] = []
        for p in raw_pairs:
            if isinstance(p, dict) and p.get("name"):
                pairs_out.append(
                    OrderedColumn(
                        name=str(p.get("name")),
                        table_id=(int(p["table_id"]) if p.get("table_id") else None),
                    )
                )
    else:
        pairs_out = [OrderedColumn(name=n, table_id=None) for n in ordered_names]
    return SuggestOrderResp(
        ordered=ordered_names,
        ordered_pairs=pairs_out,
        rationale=result.get("rationale") or "",
        fallback=bool(result.get("fallback", False)),
    )


# ─────────────────────────────────────────────────────────────
# F9 — Generate-report LLM endpoint + SafeSQLExecutor (Önizleme step)
# Plan: 2026-05-25_0330_v336_smart_discovery_completion_v1.md
# Council: APOLLO + POSEIDON + ARES + HEBE
# ─────────────────────────────────────────────────────────────

@router.post("/generate-report", response_model=GenerateReportResp)
def post_generate_report(
    req: GenerateReportReq,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> GenerateReportResp:
    """LLM ile tek bir SELECT SQL üret ve SafeSQLExecutor ile çalıştır.

    Önizleme step'inin "▶️ Çalıştır" butonu çağırır.

    Pipeline:
      1. Tenant guard (current_user.company_id ↔ data_sources.company_id).
      2. Dialect + connection bilgisini data_sources'tan oku.
      3. allowed_tables = primary + join tabloların schema.object listesi
         (ds_db_objects'ten okunur — LLM yanlış tablo uydursa bile
         SafeSQLExecutor.check_table_whitelist reddi devreye girer).
      4. llm_generate_report.generate_report(...) → {sql, rationale, fallback}.
      5. SafeSQLExecutor.execute(sql, source, dialect, allowed_tables) — 5 s
         timeout, max_rows=limit, result_cache devre dışı (her çalıştır taze).
      6. Cevap: {sql, rationale, columns, rows, row_count, elapsed_ms,
         truncated, success, fallback, error}.

    Fail-soft: LLM ulaşılamaz veya yanıt invalid ise fallback `SELECT * FROM
    <primary>` + dialect row-limit ile çalışmaya devam eder. 502 değil 200
    döner (UI bozulmasın); response.fallback=True işaretlenir.
    """
    _require_user_id(current_user)

    company_id = current_user.get("company_id")
    if not company_id:
        logger.warning(
            "[db_smart] generate_report: current_user.company_id boş (user_id=%s)",
            current_user.get("id"),
        )
        raise HTTPException(status_code=403, detail="Şirket bağlamı tanımlı değil.")

    # ── Tenant guard + source resolution (connection dict for SafeSQLExecutor) ──
    source: Dict[str, Any] = {}
    dialect: str = "postgresql"
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        try:
            cur.execute(
                """
                SELECT id, db_type, host, port, db_name,
                       db_user, db_password_encrypted, company_id
                FROM data_sources
                WHERE id = %s
                """,
                (int(req.source_id),),
            )
            row = cur.fetchone()
        except Exception as e:
            logger.warning(
                "[db_smart] generate_report tenant-check failed source=%s: %s",
                req.source_id, e,
            )
            raise HTTPException(status_code=500, detail="Kaynak doğrulanamadı.")

        if row is None:
            raise HTTPException(status_code=404, detail="Veri kaynağı bulunamadı.")
        src = dict(row) if isinstance(row, dict) else dict(
            zip([d[0] for d in cur.description], row)
        )
        if int(src.get("company_id") or 0) != int(company_id):
            logger.warning(
                "[db_smart] generate_report cross-tenant: source=%s belongs to co=%s, "
                "current_user co=%s",
                req.source_id, src.get("company_id"), company_id,
            )
            raise HTTPException(status_code=403, detail="Bu veri kaynağına erişim yok.")
        source = src
        dialect = str(src.get("db_type") or "postgresql").lower()

        # ── allowed_tables: primary + joins → schema.object_name ──
        all_ids = [int(req.primary_table_id)] + [
            int(t) for t in (req.join_table_ids or [])
        ]
        allowed_tables: List[str] = []
        try:
            cur.execute(
                """
                SELECT schema_name, object_name
                FROM ds_db_objects
                WHERE source_id = %s AND id = ANY(%s)
                """,
                (int(req.source_id), list({int(t) for t in all_ids})),
            )
            # F15: allowed_tables case-insensitive defense in depth.
            # Oracle metadata genelde UPPERCASE saklar; LLM PG/MySQL tarzı
            # lowercase üretebilir veya tersi. SafeSQLExecutor parser tarafında
            # .lower() yapar; biz de hem orijinal hem upper hem lower formatları
            # ekleyerek herhangi bir karşılaştırma yolunun match etmesini sağlıyoruz.
            _seen: set = set()
            for r in cur.fetchall() or []:
                schema = (r.get("schema_name") if isinstance(r, dict) else r[0]) or ""
                obj = (r.get("object_name") if isinstance(r, dict) else r[1]) or ""
                if not obj:
                    continue
                variants: List[str] = []
                if schema:
                    qual = f"{schema}.{obj}"
                    variants.extend([qual, qual.lower(), qual.upper()])
                variants.extend([obj, obj.lower(), obj.upper()])
                for v in variants:
                    if v and v not in _seen:
                        _seen.add(v)
                        allowed_tables.append(v)
        except Exception as e:
            logger.warning(
                "[db_smart] generate_report allowed_tables lookup failed: %s", e
            )

    # ── LLM SQL generation (service handles all defensive paths) ──
    from app.services.db_smart import llm_generate_report

    gen = llm_generate_report.generate_report(
        source_id=int(req.source_id),
        dialect=dialect,
        primary_table_id=int(req.primary_table_id),
        join_table_ids=list(req.join_table_ids or []),
        report_columns=list(req.report_columns or []),
        metric=req.metric,
        user_note=req.user_note or "",
        fk_context=list(req.fk_context or []),
        current_user=current_user,
        limit=int(req.limit),
    )
    generated_sql: str = gen.get("sql") or ""
    rationale: str = gen.get("rationale") or ""
    fallback: bool = bool(gen.get("fallback"))

    if not generated_sql:
        # Service should always return a non-empty SQL (fallback path), but
        # guard anyway.
        return GenerateReportResp(
            sql="",
            rationale=rationale or "SQL üretilemedi.",
            success=False,
            fallback=True,
            error="SQL üretilemedi (LLM + fallback başarısız).",
        )

    # ── Execute via SafeSQLExecutor — defense in depth ──
    try:
        from app.services.safe_sql_executor import SafeSQLExecutor

        executor = SafeSQLExecutor(timeout=5, max_rows=int(req.limit))
        sql_result = executor.execute(
            generated_sql,
            source,
            dialect=dialect,
            allowed_tables=allowed_tables or None,
            use_result_cache=False,
        )
    except Exception:
        # Driver-level errors may leak schema/permission info — generic message.
        logger.exception("[db_smart] generate_report execute crashed")
        return GenerateReportResp(
            sql=generated_sql,
            rationale=rationale,
            success=False,
            fallback=fallback,
            error="Sorgu çalıştırılamadı (teknik detay log'da).",
        )

    columns = getattr(sql_result, "columns", []) or []
    rows = getattr(sql_result, "data", None) or getattr(sql_result, "rows", []) or []
    row_count = int(getattr(sql_result, "row_count", 0) or 0)
    elapsed_ms = int(getattr(sql_result, "elapsed_ms", 0) or 0)
    truncated = bool(getattr(sql_result, "truncated", False))

    # Normalize row format: SafeSQLExecutor may return list-of-dicts (RealDictCursor)
    # or list-of-tuples. The frontend modal expects list-of-lists keyed by `columns`.
    norm_rows: List[List[Any]] = []
    for r in rows:
        if isinstance(r, dict):
            norm_rows.append([r.get(c) for c in columns])
        elif isinstance(r, (list, tuple)):
            norm_rows.append(list(r))
        else:
            norm_rows.append([r])

    return GenerateReportResp(
        sql=generated_sql,
        rationale=rationale,
        columns=list(columns),
        rows=norm_rows,
        row_count=row_count,
        elapsed_ms=elapsed_ms,
        truncated=truncated,
        success=bool(getattr(sql_result, "success", False)),
        fallback=fallback,
        error=(None if getattr(sql_result, "success", False)
               else getattr(sql_result, "error", None) or "Sorgu başarısız."),
    )
