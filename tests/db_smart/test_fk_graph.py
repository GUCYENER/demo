"""fk_graph.py — wrapper around db_learning/fk_graph_resolver
(v3.30.0 FAZ 1 G1.3)."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from app.services.db_smart import fk_graph as fkg


# ─────────────────────────────────────────────────────────────
# Cursor helpers
# ─────────────────────────────────────────────────────────────

class _FakeCursor:
    """Sıralı sorgu yanıtı veren minimal cursor mock."""

    def __init__(self, queue: List[List[tuple]]):
        self._queue = queue
        self._idx = 0
        self._last = []
        self.executed: List[tuple] = []

    def execute(self, sql, params=None):
        self.executed.append((sql.strip()[:60], params))
        # Sıradaki resp'i sıraya bağlı olarak ata
        if self._idx < len(self._queue):
            self._last = self._queue[self._idx]
            self._idx += 1
        else:
            self._last = []

    def fetchall(self):
        return self._last

    def fetchone(self):
        return self._last[0] if self._last else None


# ─────────────────────────────────────────────────────────────
# build_subgraph
# ─────────────────────────────────────────────────────────────

def test_build_subgraph_empty_ids(fake_user_ctx):
    cur = _FakeCursor([])
    out = fkg.build_subgraph(cur, source_id=1, table_ids=[], user_ctx=fake_user_ctx)
    assert out["nodes"] == [] and out["edges"] == []
    assert out["stats"]["seed_count"] == 0


def test_build_subgraph_unknown_ids(fake_user_ctx):
    # _lookup_nodes_by_ids → empty
    cur = _FakeCursor([[]])
    out = fkg.build_subgraph(cur, source_id=1, table_ids=[999], user_ctx=fake_user_ctx)
    assert out["stats"]["node_count"] == 0


def test_build_subgraph_with_seed_and_neighbors(fake_user_ctx):
    """Seed=tickets, FK ile users'a bağlı; depth=1 ile users gelmeli."""
    # _lookup_nodes_by_ids → seed
    seed_resp = [(10, "public", "tickets")]
    # build_graph (fk_graph_resolver) → tickets→users edge
    edges_resp = [
        (1, "public", "tickets", "user_id",
         "public", "users", "id",
         "N", "1", False, 100, 0.9),
    ]
    # _lookup_ids_by_nodes → reverse map
    reverse_resp = [
        (10, "public", "tickets"),
        (20, "public", "users"),
    ]
    cur = _FakeCursor([seed_resp, edges_resp, reverse_resp])
    out = fkg.build_subgraph(cur, source_id=1, table_ids=[10], user_ctx=fake_user_ctx, depth=1)
    # En az tickets node'u olmalı
    nodes_by_table = {n["table"]: n for n in out["nodes"]}
    assert "tickets" in nodes_by_table
    assert nodes_by_table["tickets"]["is_seed"] is True
    # users de gelmeli (depth=1)
    assert "users" in nodes_by_table
    assert nodes_by_table["users"]["is_seed"] is False


# ─────────────────────────────────────────────────────────────
# expand_with_fk
# ─────────────────────────────────────────────────────────────

def test_expand_with_fk_excludes_seeds(fake_user_ctx):
    seed_resp = [(10, "public", "tickets")]
    edges_resp = [
        (1, "public", "tickets", "user_id",
         "public", "users", "id",
         "N", "1", False, 100, 0.9),
    ]
    reverse_resp = [
        (10, "public", "tickets"),
        (20, "public", "users"),
    ]
    cur = _FakeCursor([seed_resp, edges_resp, reverse_resp])
    out = fkg.expand_with_fk(cur, source_id=1, table_ids=[10], depth=1)
    # tickets seed → çıkarılmalı; users kalmalı
    tables = {n["table"] for n in out}
    assert "tickets" not in tables
    assert "users" in tables


# ─────────────────────────────────────────────────────────────
# suggest_join_path
# ─────────────────────────────────────────────────────────────

def test_suggest_join_path_unknown_id(fake_user_ctx):
    # _lookup_nodes_by_ids → empty
    cur = _FakeCursor([[]])
    out = fkg.suggest_join_path(cur, source_id=1, table_a=999, table_b=998)
    assert out["found"] is False
    assert out["error"] == "unknown_table_id"


def test_suggest_join_path_found(fake_user_ctx):
    """tickets(10) → users(20) — tek hop yol."""
    # 1) _lookup_nodes_by_ids
    lookup_resp = [(10, "public", "tickets"), (20, "public", "users")]
    # 2) resolve_best_path → build_graph
    edges_resp = [
        (1, "public", "tickets", "user_id",
         "public", "users", "id",
         "N", "1", False, 100, 0.9),
    ]
    cur = _FakeCursor([lookup_resp, edges_resp])
    out = fkg.suggest_join_path(cur, source_id=1, table_a=10, table_b=20)
    assert out["found"] is True
    assert out["best"]["hops"] == 1


# ─────────────────────────────────────────────────────────────
# detect_junctions
# ─────────────────────────────────────────────────────────────

def test_detect_junctions_filters_flagged_nodes():
    subgraph = {
        "nodes": [
            {"table_id": 1, "schema": "p", "table": "tickets", "is_junction": False},
            {"table_id": 2, "schema": "p", "table": "user_role", "is_junction": True},
            {"table_id": 3, "schema": "p", "table": "users", "is_junction": False},
        ],
    }
    out = fkg.detect_junctions(subgraph)
    assert len(out) == 1
    assert out[0]["table"] == "user_role"


def test_detect_junctions_empty():
    assert fkg.detect_junctions({"nodes": []}) == []
    assert fkg.detect_junctions({}) == []
