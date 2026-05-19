"""wizard_state → AST → SQL pipeline (v3.30.0 FAZ 0 iskelet).

Gerçek implementasyon FAZ 1 G1.5'te:
    1. validate(wizard_state) — eksik alan/yetki kontrolü
    2. build_ast(wizard_state) — Select/Join/Filter/Aggregate/Window/Order/Limit/CTE
    3. ast_renderer.render(ast, dialect) — dialect-aware SQL
    4. ast_renderer.optimize(ast) — index awareness, partition pruning, subquery↔join
    5. ast_renderer.inject_hints(ast, dialect) — Oracle /*+ PARALLEL */, MSSQL OPTION
    6. ast_renderer.inject_rls(ast, user_ctx) — son adım, atlanamaz
    7. validate_explain(sql, dialect) — EXPLAIN cost ≤ threshold

Tüm bu adımlar deterministiktir; LLM bu pipeline'da kullanılmaz
(custom_metric_parser hariç — orada bile output AST'e parse edilip whitelist'e tabi).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def assemble(
    wizard_state: Dict[str, Any],
    user_ctx: Dict[str, Any],
    dialect: str = "postgresql",
) -> Dict[str, Any]:
    """wizard_state → {sql, ast_json, binds, dialect, warnings}.

    FAZ 0 stub: boş dict.
    """
    logger.debug("[db_smart.assembler] assemble stub dialect=%s", dialect)
    return {
        "sql": None,
        "ast_json": None,
        "binds": {},
        "dialect": dialect,
        "warnings": [],
    }


def explain_cost(sql: str, dialect: str, user_ctx: Dict[str, Any]) -> Optional[float]:
    """EXPLAIN cost numerik döner (None = hesaplanamadı)."""
    return None
