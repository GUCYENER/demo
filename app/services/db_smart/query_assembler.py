"""wizard_state → AST → SQL pipeline (v3.30.0 FAZ 1 G1.5).

Pipeline:
    1. validate(wizard_state)           — eksik alan/yetki kontrolü
    2. build_ast(wizard_state, metric)  — Select/Join/Filter/Aggregate/Order/Limit
    3. ast_renderer.inject_rls(ast, ctx) — son adım, atlanamaz
    4. ast_renderer.render(ast, dialect) — dialect-aware SQL + binds
    5. explain_cost(sql, dialect)       — EXPLAIN cost ≤ threshold (opsiyonel)

GÜVENLİK:
    - identifier whitelist ast_renderer'a delege edilir
    - değerler her zaman bind; string-concat YOK
    - RLS atlanamaz; inject_rls render'dan önce zorunlu

Wizard state şekli (dbsmart_sessions.context'ten):
    {
      "source_id": int,
      "dialect": "postgresql" | "oracle" | "mssql" | "mysql",
      "base_table": {"schema": "...", "table": "...", "alias": "t"},
      "joins": [ {...} ],                  # ast_renderer formatında
      "selected_columns": [ {"expr": "...", "alias": "..."}, ... ],
      "filters": [ {"expr","op","value"}, ... ],
      "group_by": ["t.status"],
      "order_by": [ {"expr","dir"} ],
      "limit": int | None,
      "metric": {                           # opsiyonel — library'den seçilmişse
        "metric_key": "helpdesk.oldest_open",
        "sql_template": "...",              # dialect-resolved
        "placeholders": {"table": "...", ...},
      },
      "company_scoped_aliases": ["t","u"],   # RLS gate hint
    }
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.services.db_smart import ast_renderer

logger = logging.getLogger(__name__)

# Placeholder whitelist: yalnızca tanınmış token'lar template'te substitute edilir
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# Metric template substitute için kabul edilen anahtarlar
ALLOWED_PLACEHOLDERS = {
    "table", "schema", "alias",
    "status_col", "created_col", "updated_col", "resolved_col",
    "amount_col", "customer_col", "product_col", "category_col",
    "date_col", "priority_col", "team_col",
    "limit",
}


# ─────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────

def validate(wizard_state: Dict[str, Any]) -> List[str]:
    """Returns list of validation errors (empty = OK)."""
    errs: List[str] = []
    if not wizard_state.get("source_id"):
        errs.append("source_id missing")
    dialect = wizard_state.get("dialect", "postgresql")
    if dialect not in ast_renderer.SUPPORTED_DIALECTS:
        errs.append(f"unsupported dialect: {dialect}")
    base = wizard_state.get("base_table") or {}
    if not base.get("table"):
        errs.append("base_table.table missing")
    cols = wizard_state.get("selected_columns") or []
    metric = wizard_state.get("metric")
    if not cols and not metric:
        errs.append("selected_columns or metric required")
    return errs


# ─────────────────────────────────────────────────────────────
# build_ast
# ─────────────────────────────────────────────────────────────

def build_ast(wizard_state: Dict[str, Any]) -> Dict[str, Any]:
    """wizard_state → AST dict. Metric varsa onun template'ini AST'e dökmez —
    bu durumda assemble() metric path'i alır (raw SQL + bind).

    Burada sadece "free-form" wizard yolunda AST oluşturulur.
    """
    base = wizard_state.get("base_table") or {}
    ast: Dict[str, Any] = {
        "type": "select",
        "columns": list(wizard_state.get("selected_columns") or []),
        "from": {
            "schema": base.get("schema"),
            "table": base.get("table"),
            "alias": base.get("alias"),
        },
        "joins": list(wizard_state.get("joins") or []),
        "filters": list(wizard_state.get("filters") or []),
        "group_by": list(wizard_state.get("group_by") or []),
        "having": list(wizard_state.get("having") or []),
        "order_by": list(wizard_state.get("order_by") or []),
        "limit": wizard_state.get("limit"),
        "offset": wizard_state.get("offset"),
    }
    return ast


# ─────────────────────────────────────────────────────────────
# Metric template substitution (allow-listed)
# ─────────────────────────────────────────────────────────────

def _substitute_template(template: str, placeholders: Dict[str, Any]) -> str:
    """Template'teki {{token}}'ları whitelist'ten geçen identifier'lar ile değiştirir.

    DEĞER asla bind değildir — identifier (schema/table/kolon adı). Bu yüzden
    whitelist guard zorunlu: alphanumeric + underscore + nokta.
    """
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in ALLOWED_PLACEHOLDERS:
            raise ValueError(f"Unknown placeholder: {{{{{key}}}}}")
        val = placeholders.get(key)
        if val is None:
            raise ValueError(f"Placeholder '{key}' not provided")
        s = str(val)
        # Identifier whitelist (limit hariç — integer)
        if key == "limit":
            if not str(s).isdigit():
                raise ValueError("'limit' placeholder must be integer")
            return s
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$", s):
            raise ValueError(f"Placeholder '{key}'='{s}' fails identifier whitelist")
        return s
    return _PLACEHOLDER_RE.sub(_sub, template)


# ─────────────────────────────────────────────────────────────
# assemble (orchestrator)
# ─────────────────────────────────────────────────────────────

def assemble(
    wizard_state: Dict[str, Any],
    user_ctx: Dict[str, Any],
    dialect: Optional[str] = None,
) -> Dict[str, Any]:
    """wizard_state → {sql, ast_json, binds, dialect, warnings, errors}."""
    d = dialect or wizard_state.get("dialect", "postgresql")
    errors = validate(wizard_state)
    if errors:
        return {"sql": None, "ast_json": None, "binds": {},
                "dialect": d, "warnings": [], "errors": errors}

    warnings: List[str] = []
    metric = wizard_state.get("metric")

    # ── Metric path: kütüphane template'i kullanılır
    if metric and metric.get("sql_template"):
        try:
            sql = _substitute_template(
                metric["sql_template"],
                metric.get("placeholders") or {},
            )
        except ValueError as e:
            return {"sql": None, "ast_json": None, "binds": {},
                    "dialect": d, "warnings": warnings,
                    "errors": [f"metric_template_error: {e}"]}
        # Metric path'te AST yok; binds boş (template-only). UI override etmek
        # isterse ast path'e geçmeli.
        return {
            "sql": sql,
            "ast_json": None,
            "binds": {},
            "dialect": d,
            "warnings": warnings,
            "errors": [],
            "source": "metric_template",
            "metric_key": metric.get("metric_key"),
        }

    # ── Free-form AST path
    try:
        ast = build_ast(wizard_state)
        # RLS gate — atlanamaz
        ast = ast_renderer.inject_rls(
            ast, user_ctx,
            company_scoped_tables=wizard_state.get("company_scoped_aliases"),
        )
        rendered = ast_renderer.render(ast, d, user_ctx)
    except ValueError as e:
        return {"sql": None, "ast_json": None, "binds": {},
                "dialect": d, "warnings": warnings,
                "errors": [f"render_error: {e}"]}

    if not ast.get("_rls_injected") and not (user_ctx.get("is_admin") or user_ctx.get("role") == "admin"):
        warnings.append("rls_not_applied (no company_scoped_aliases provided)")

    return {
        "sql": rendered["sql"],
        "ast_json": ast_renderer.serialize_json(ast),
        "binds": rendered["binds"],
        "dialect": d,
        "warnings": warnings,
        "errors": [],
        "source": "ast",
    }


# ─────────────────────────────────────────────────────────────
# Streaming strategy (G1.5 Step 7)
# ─────────────────────────────────────────────────────────────

# Eşikler — UI/exec hattı bu üç moda göre davranır.
# - direct:    küçük sonuç; tek JSON payload yeterli
# - cursor:    orta hacim; server-side cursor ile chunked fetch
# - sse_chunk: büyük hacim; SSE üzerinden satır akışı + back-pressure
STREAM_DIRECT_MAX_ROWS = 1_000
STREAM_CURSOR_MAX_ROWS = 100_000
STREAM_DIRECT_MAX_COST = 1_000.0
STREAM_CURSOR_MAX_COST = 100_000.0


def decide_streaming_strategy(
    cost: Optional[float] = None,
    estimated_rows: Optional[int] = None,
) -> str:
    """Üç-yollu streaming kararı: direct | cursor | sse_chunk.

    Karar sırası:
      1. estimated_rows verildiyse satır eşikleri uygulanır.
      2. yoksa cost verildiyse cost eşikleri uygulanır.
      3. ikisi de yoksa güvenli default = "direct".

    Args:
        cost: PG EXPLAIN total_cost (float) veya None
        estimated_rows: caller'ın tahmini satır sayısı (int) veya None

    Returns:
        "direct" | "cursor" | "sse_chunk"
    """
    if estimated_rows is not None:
        if estimated_rows < STREAM_DIRECT_MAX_ROWS:
            return "direct"
        if estimated_rows <= STREAM_CURSOR_MAX_ROWS:
            return "cursor"
        return "sse_chunk"
    if cost is not None:
        if cost < STREAM_DIRECT_MAX_COST:
            return "direct"
        if cost <= STREAM_CURSOR_MAX_COST:
            return "cursor"
        return "sse_chunk"
    return "direct"


# ─────────────────────────────────────────────────────────────
# explain_cost
# ─────────────────────────────────────────────────────────────

def explain_cost(
    cur,
    sql: str,
    dialect: str,
    user_ctx: Dict[str, Any],
    binds: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """EXPLAIN cost numerik döner (None = hesaplanamadı / desteklenmeyen dialect).

    NOT: Caller cursor'ı sağlar; RLS context set edilmiş olmalı.
    """
    if dialect != "postgresql":
        # Diğer dialect'lerde EXPLAIN parse maliyetli — FAZ 2'ye bırakıldı
        return None
    try:
        cur.execute(f"EXPLAIN (FORMAT JSON) {sql}", binds or {})
        row = cur.fetchone()
        if not row:
            return None
        plan = row[0]
        # psycopg2 zaten dict döndürebilir veya str — normalize
        if isinstance(plan, str):
            import json
            plan = json.loads(plan)
        if isinstance(plan, list) and plan:
            return float(plan[0].get("Plan", {}).get("Total Cost", 0.0))
    except Exception as e:
        logger.debug("[db_smart.assembler] explain_cost failed: %s", e)
    return None
