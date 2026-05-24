"""FK graph subgraph + path-suggest (v3.30.0 FAZ 1 G1.3).

Wraps existing `app/services/db_learning/fk_graph_resolver.py` (Yen K-shortest
paths üzerinde NetworkX) ve wizard UI'sinin ihtiyaç duyduğu ek operasyonları
ekler:

Public API:
    build_subgraph(cur, source_id, table_ids, user_ctx, depth=1) → Dict
        Seçili tablolar + `depth` hop komşuları → nodes/edges payload.
    expand_with_fk(cur, source_id, table_ids, depth=1) → List[Dict]
        Direct/indirect FK komşuları (junction'lar dahil, kardinalite ile).
    suggest_join_path(cur, source_id, table_a, table_b, k=3) → Dict
        İki tablo arasında en hafif join yolu + k-1 alternatif.
    detect_junctions(subgraph) → List[Tuple[str, str]]
        is_junction=TRUE olan ara tablolar (UI'da “bağlantı tablosu” rozeti).

NOT:
    - Cursor caller'dan gelir (apply_vyra_user_context set edilmiş olmalı).
    - table_ids = ds_db_objects.id; resolver (schema, table) string node kullanır;
      bu modül id ↔ (schema, table) eşlemesini sağlar.
    - NetworkX yoksa best-effort fallback (sadece direct neighbors).
"""
from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.db_learning import fk_graph_resolver as _fkr

logger = logging.getLogger(__name__)

# FIX10 S1 (NIKE+HEPHAESTUS+ARES): Redis cache for expand_with_fk
_FK_CACHE = None
_FK_CACHE_LOCK = threading.Lock()
_FK_CACHE_TTL = 3600  # 1 saat


def _get_fk_cache():
    """Singleton RedisCache accessor (graceful fallback to None)."""
    global _FK_CACHE
    if _FK_CACHE is not None:
        return _FK_CACHE
    with _FK_CACHE_LOCK:
        if _FK_CACHE is not None:
            return _FK_CACHE
        try:
            from app.core.config import settings
            from app.core.redis_cache import RedisCache
            url = getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
            _FK_CACHE = RedisCache(
                redis_url=url,
                default_ttl=_FK_CACHE_TTL,
                key_prefix="vyra:fk_expand:",
            )
        except Exception as e:
            logger.info("[db_smart.fk] cache init failed (graceful): %s", e)
            _FK_CACHE = False  # sentinel: tried+failed
    return _FK_CACHE or None


def _fk_cache_key(source_id: int, table_ids: List[int], depth: int) -> str:
    """Deterministic cache key — tenant-aware via source_id."""
    ids_sig = ",".join(str(int(t)) for t in sorted(table_ids))
    raw = f"{int(source_id)}|{depth}|{ids_sig}"
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"s{int(source_id)}:d{int(depth)}:{h}"

try:
    import networkx as nx  # type: ignore
    _HAS_NX = True
except Exception:
    nx = None  # type: ignore
    _HAS_NX = False
    logger.info("[db_smart.fk] NetworkX yuklu degil — adj-list fallback")


Node = Tuple[str, str]   # (schema, table) lowercased


# ─────────────────────────────────────────────────────────────
# RealDictCursor ↔ tuple cursor uyumu (eligibility.py ile aynı pattern)
# Connection pool RealDictCursor döndürdüğü için satırlar dict; integer
# indeksleme KeyError fırlatır. Bu helper iki tip için de güvenli erişim sağlar.
# ─────────────────────────────────────────────────────────────

def _col(row, key, idx):
    return row[key] if isinstance(row, dict) else row[idx]


# ─────────────────────────────────────────────────────────────
# table_id ↔ (schema, table) eşleme
# ─────────────────────────────────────────────────────────────

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _lookup_nodes_by_ids(
    cur,
    source_id: int,
    table_ids: List[int],
) -> Dict[int, Node]:
    """ds_db_objects.id → (schema, table) (lowercased). Bilinmeyen id'ler atlanır."""
    if not table_ids:
        return {}
    cur.execute(
        """
        SELECT id, schema_name, object_name
        FROM ds_db_objects
        WHERE source_id = %s AND id = ANY(%s)
        """,
        (int(source_id), [int(t) for t in table_ids]),
    )
    return {
        _col(row, 'id', 0): (
            _norm(_col(row, 'schema_name', 1)),
            _norm(_col(row, 'object_name', 2)),
        )
        for row in cur.fetchall()
    }


def _lookup_ids_by_nodes(
    cur,
    source_id: int,
    nodes: Set[Node],
) -> Dict[Node, int]:
    """Reverse map — node → ds_db_objects.id (görüntü için)."""
    if not nodes:
        return {}
    schemas = [n[0] for n in nodes]
    tables = [n[1] for n in nodes]
    cur.execute(
        """
        SELECT id AS table_id,
               LOWER(COALESCE(schema_name,'')) AS schema_lc,
               LOWER(object_name) AS object_lc
        FROM ds_db_objects
        WHERE source_id = %s
          AND LOWER(COALESCE(schema_name,'')) = ANY(%s)
          AND LOWER(object_name) = ANY(%s)
        """,
        (int(source_id), schemas, tables),
    )
    out: Dict[Node, int] = {}
    for row in cur.fetchall():
        key = (_col(row, 'schema_lc', 1) or "", _col(row, 'object_lc', 2) or "")
        if key in nodes:
            out[key] = _col(row, 'table_id', 0)
    return out


def _node_str(n: Node) -> str:
    return f"{n[0]}.{n[1]}".strip(".")


# ─────────────────────────────────────────────────────────────
# build_subgraph
# ─────────────────────────────────────────────────────────────

def build_subgraph(
    cur,
    source_id: int,
    table_ids: List[int],
    user_ctx: Dict[str, Any],
    depth: int = 1,
) -> Dict[str, Any]:
    """Seçili tablolar etrafında `depth` hop genişliğinde FK alt-grafı.

    Returns:
        {
          "nodes": [{table_id, schema, table, is_seed, is_junction}],
          "edges": [{from, to, from_column, to_column, cardinality_from,
                     cardinality_to, is_junction, confidence_score, weight}],
          "stats": {"node_count", "edge_count", "junction_count", "seed_count"},
        }
    """
    base = {"nodes": [], "edges": [], "stats": {
        "node_count": 0, "edge_count": 0, "junction_count": 0,
        "seed_count": len(table_ids or []),
    }}

    if not table_ids:
        return base

    id_to_node = _lookup_nodes_by_ids(cur, source_id, table_ids)
    if not id_to_node:
        return base
    seed_nodes: Set[Node] = set(id_to_node.values())

    if not _HAS_NX:
        # Fallback: tek ds_db_relationships sorgusu, depth=1 ile sınırlı
        return _fallback_build_subgraph(cur, source_id, seed_nodes)

    try:
        g = _fkr.build_graph(cur, source_id)
    except Exception as e:
        logger.warning("[db_smart.fk] build_graph failed: %s", e)
        return base

    # BFS depth genişlemesi (yönsüz görünüm)
    reachable: Set[Node] = set(seed_nodes)
    frontier: Set[Node] = set(seed_nodes)
    for _ in range(max(1, int(depth))):
        next_frontier: Set[Node] = set()
        for n in frontier:
            if n not in g:
                continue
            for nb in g.successors(n):
                if nb not in reachable:
                    next_frontier.add(nb)
            for nb in g.predecessors(n):
                if nb not in reachable:
                    next_frontier.add(nb)
        if not next_frontier:
            break
        reachable |= next_frontier
        frontier = next_frontier

    # Node payloads + id geri eşleme
    node_to_id = _lookup_ids_by_nodes(cur, source_id, reachable)

    junctions: Set[Node] = set()
    edges: List[Dict[str, Any]] = []
    seen_edge_keys: Set[Tuple[Node, Node]] = set()
    for u in reachable:
        if u not in g:
            continue
        for v in g.successors(u):
            if v not in reachable:
                continue
            key = (u, v)
            if key in seen_edge_keys:
                continue
            seen_edge_keys.add(key)
            e = g.get_edge_data(u, v) or {}
            if e.get("is_junction"):
                junctions.add(u)
                junctions.add(v)
            edges.append({
                "from": _node_str(u),
                "to": _node_str(v),
                "from_table_id": node_to_id.get(u),
                "to_table_id": node_to_id.get(v),
                "from_column": e.get("from_column"),
                "to_column": e.get("to_column"),
                "cardinality_from": e.get("cardinality_from"),
                "cardinality_to": e.get("cardinality_to"),
                "is_junction": bool(e.get("is_junction")),
                "confidence_score": e.get("confidence_score"),
                "weight": e.get("weight"),
                "direction": e.get("direction"),
            })

    node_payloads = [
        {
            "table_id": node_to_id.get(n),
            "schema": n[0],
            "table": n[1],
            "is_seed": n in seed_nodes,
            "is_junction": n in junctions,
        }
        for n in sorted(reachable)
    ]

    return {
        "nodes": node_payloads,
        "edges": edges,
        "stats": {
            "node_count": len(node_payloads),
            "edge_count": len(edges),
            "junction_count": len(junctions),
            "seed_count": len(seed_nodes),
        },
    }


# ─────────────────────────────────────────────────────────────
# Fallback (NetworkX yoksa) — sadece depth=1 direct neighbors
# ─────────────────────────────────────────────────────────────

def _fallback_build_subgraph(
    cur,
    source_id: int,
    seed_nodes: Set[Node],
) -> Dict[str, Any]:
    if not seed_nodes:
        return {"nodes": [], "edges": [], "stats": {
            "node_count": 0, "edge_count": 0, "junction_count": 0, "seed_count": 0,
        }}
    schemas = [n[0] for n in seed_nodes]
    tables = [n[1] for n in seed_nodes]
    try:
        cur.execute(
            """
            SELECT from_schema, from_table, from_column,
                   to_schema, to_table, to_column,
                   COALESCE(cardinality_from,'N') AS cardinality_from,
                   COALESCE(cardinality_to,'1')   AS cardinality_to,
                   COALESCE(is_junction, FALSE)   AS is_junction,
                   COALESCE(confidence_score, 0.5) AS confidence_score
            FROM ds_db_relationships
            WHERE source_id = %s
              AND (
                  (LOWER(COALESCE(from_schema,'')) = ANY(%s)
                   AND LOWER(from_table) = ANY(%s))
               OR (LOWER(COALESCE(to_schema,'')) = ANY(%s)
                   AND LOWER(to_table) = ANY(%s))
              )
            """,
            (int(source_id), schemas, tables, schemas, tables),
        )
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("[db_smart.fk] fallback query failed: %s", e)
        rows = []

    all_nodes: Set[Node] = set(seed_nodes)
    edges: List[Dict[str, Any]] = []
    junctions: Set[Node] = set()
    for r in rows:
        from_schema = _col(r, 'from_schema', 0)
        from_table = _col(r, 'from_table', 1)
        from_column = _col(r, 'from_column', 2)
        to_schema = _col(r, 'to_schema', 3)
        to_table = _col(r, 'to_table', 4)
        to_column = _col(r, 'to_column', 5)
        cardinality_from = _col(r, 'cardinality_from', 6)
        cardinality_to = _col(r, 'cardinality_to', 7)
        is_junction = _col(r, 'is_junction', 8)
        confidence_score = _col(r, 'confidence_score', 9)
        u = (_norm(from_schema), _norm(from_table))
        v = (_norm(to_schema), _norm(to_table))
        all_nodes.add(u)
        all_nodes.add(v)
        if is_junction:
            junctions.add(u)
            junctions.add(v)
        edges.append({
            "from": _node_str(u), "to": _node_str(v),
            "from_column": from_column, "to_column": to_column,
            "cardinality_from": cardinality_from, "cardinality_to": cardinality_to,
            "is_junction": bool(is_junction), "confidence_score": float(confidence_score or 0.5),
        })
    node_to_id = _lookup_ids_by_nodes(cur, source_id, all_nodes)
    node_payloads = [
        {"table_id": node_to_id.get(n), "schema": n[0], "table": n[1],
         "is_seed": n in seed_nodes, "is_junction": n in junctions}
        for n in sorted(all_nodes)
    ]
    return {
        "nodes": node_payloads,
        "edges": edges,
        "stats": {
            "node_count": len(node_payloads),
            "edge_count": len(edges),
            "junction_count": len(junctions),
            "seed_count": len(seed_nodes),
        },
    }


# ─────────────────────────────────────────────────────────────
# expand_with_fk
# ─────────────────────────────────────────────────────────────

def expand_with_fk(
    cur,
    source_id: int,
    table_ids: List[int],
    depth: int = 1,
) -> List[Dict[str, Any]]:
    """Direct/indirect FK komşularını liste halinde döndür.

    Returns:
        [{table_id, schema, table, distance, via_relationship_count,
          inbound_count, outbound_count, is_junction}, ...]
        Distance 0 = seed (filtrelenir; sadece komşular).
    """
    # FIX10 S1 (NIKE+HEPHAESTUS+ARES): Redis cache check
    cache = _get_fk_cache()
    cache_key = None
    if cache is not None and table_ids:
        cache_key = _fk_cache_key(source_id, table_ids, depth)
        try:
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
        except Exception as e:
            logger.debug("[db_smart.fk] cache read failed: %s", e)
    sub = build_subgraph(cur, source_id, table_ids, {}, depth=depth)
    seeds: Set[Node] = {
        (n["schema"], n["table"]) for n in sub["nodes"] if n["is_seed"]
    }
    # Edge sayımı + komşu sınıflandırma
    inbound: Dict[Node, int] = {}
    outbound: Dict[Node, int] = {}
    for e in sub["edges"]:
        a = tuple(e["from"].split(".", 1)) if "." in e["from"] else ("", e["from"])
        b = tuple(e["to"].split(".", 1)) if "." in e["to"] else ("", e["to"])
        a_n: Node = (a[0], a[1])
        b_n: Node = (b[0], b[1])
        outbound[a_n] = outbound.get(a_n, 0) + 1
        inbound[b_n] = inbound.get(b_n, 0) + 1

    out: List[Dict[str, Any]] = []
    for n in sub["nodes"]:
        node: Node = (n["schema"], n["table"])
        if node in seeds:
            continue
        out.append({
            "table_id": n["table_id"],
            "schema": n["schema"],
            "table": n["table"],
            "distance": 1,  # build_subgraph BFS sonucu (depth-limited)
            "inbound_count": inbound.get(node, 0),
            "outbound_count": outbound.get(node, 0),
            "via_relationship_count": inbound.get(node, 0) + outbound.get(node, 0),
            "is_junction": bool(n["is_junction"]),
        })
    # Daha fazla ilişkili → daha üstte
    out.sort(key=lambda x: x["via_relationship_count"], reverse=True)
    # FIX10 S1: cache write (best-effort)
    if cache is not None and cache_key is not None:
        try:
            cache.set(cache_key, out, ttl=_FK_CACHE_TTL)
        except Exception as e:
            logger.debug("[db_smart.fk] cache write failed: %s", e)
    return out


# ─────────────────────────────────────────────────────────────
# suggest_join_path
# ─────────────────────────────────────────────────────────────

def suggest_join_path(
    cur,
    source_id: int,
    table_a: int,
    table_b: int,
    k: int = 3,
    max_hops: int = 5,
) -> Dict[str, Any]:
    """İki tablo arasında en hafif join yolu + k-1 alternatif.

    Underlying resolver: `fk_graph_resolver.resolve_best_path`.
    """
    id_to_node = _lookup_nodes_by_ids(cur, source_id, [table_a, table_b])
    a = id_to_node.get(int(table_a))
    b = id_to_node.get(int(table_b))
    if not a or not b:
        return {"found": False, "error": "unknown_table_id",
                "table_a": table_a, "table_b": table_b}

    result = _fkr.resolve_best_path(
        cur, source_id,
        src_schema=a[0], src_table=a[1],
        dst_schema=b[0], dst_table=b[1],
        k=int(k), max_hops=int(max_hops),
    )
    # UI için ek metadata
    result["table_a"] = table_a
    result["table_b"] = table_b
    return result


# ─────────────────────────────────────────────────────────────
# detect_junctions
# ─────────────────────────────────────────────────────────────

def detect_junctions(subgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """build_subgraph payload'ından ara (junction) tabloları çıkar.

    UI: "Bu tablo iki taraflı ilişkide aracı tablo" rozeti.
    """
    return [
        {"table_id": n["table_id"], "schema": n["schema"], "table": n["table"]}
        for n in subgraph.get("nodes", [])
        if n.get("is_junction")
    ]
