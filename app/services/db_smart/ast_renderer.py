"""AST node tree + 4 dialect render + RLS guard (v3.30.0 FAZ 0 iskelet).

AST node tipleri (FAZ 1'de gerçeklenir):
    SelectNode, JoinNode, FilterNode, AggregateNode, WindowNode,
    OrderNode, LimitNode, CTENode

Manipulation API (drag-drop için):
    add_column / remove_column / add_filter / modify_join / reorder_by
    serialize_json / deserialize_json (dbsmart_sessions.context snapshot)

Render:
    PostgreSQL / Oracle / MSSQL / MySQL — `dialect_dictionary.py`'a delege.

GÜVENLİK:
    inject_rls(ast, user_ctx) son adım — atlanamaz. LLM yolu (custom_metric)
    olsa bile çıktı AST'e parse edilir; identifier whitelist ve RLS tekrar
    uygulanır.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SUPPORTED_DIALECTS = ("postgresql", "oracle", "mssql", "mysql")


def render(ast: Dict[str, Any], dialect: str, user_ctx: Dict[str, Any]) -> str:
    """AST → SQL (dialect-aware).

    FAZ 0 stub: boş string.
    """
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(f"Unsupported dialect: {dialect}")
    logger.debug("[db_smart.ast] render stub dialect=%s", dialect)
    return ""


def inject_rls(ast: Dict[str, Any], user_ctx: Dict[str, Any]) -> Dict[str, Any]:
    """LLM atlamış olsa bile son adımda RLS predicate'ini AST'e enjekte et.

    FAZ 0 stub: ast'i değişmeden döndürür.
    """
    return ast


def serialize_json(ast: Dict[str, Any]) -> Dict[str, Any]:
    """dbsmart_sessions.context içine snapshot için JSON-safe çıktı."""
    return ast or {}


def deserialize_json(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot'tan AST geri yükle."""
    return snapshot or {}
