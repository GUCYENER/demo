"""VYRA v3.29.2 — FK Graph Resolver (Faz 6 G3).

ds_db_relationships üzerinde NetworkX DiGraph kurar; iki tablo arasında
K-shortest yolu bulur. G1'de eklenen `cardinality_*`, `is_junction`,
`path_weight`, `confidence_score` alanlarını edge ağırlığı olarak kullanır.

Public API:
    build_graph(cur, source_id) -> nx.DiGraph
    find_paths(graph, src, dst, k=5, max_hops=5) -> list[Path]
    score_path(graph, path) -> float (düşük=daha iyi)
    expand_one_to_many(graph, path) -> list[bool]
        her edge için "N tarafına gidiyor mu" → aggregation hint flag

Tipler:
    Path = list[(schema, table)]
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# NetworkX import lazy yapılır (test pure-logic için optional)
try:
    import networkx as nx
    _HAS_NX = True
except Exception:  # pragma: no cover
    nx = None  # type: ignore
    _HAS_NX = False


Node = Tuple[str, str]   # (schema, table)
Path = List[Node]

# v3.29.5 — Settings'ten oku (override edilebilir). Settings import edilemezse
# güvenli default'a düşer.
try:
    from app.core.config import settings as _settings
    DEFAULT_K = int(getattr(_settings, "FK_GRAPH_DEFAULT_K", 5))
    DEFAULT_MAX_HOPS = int(getattr(_settings, "FK_GRAPH_DEFAULT_MAX_HOPS", 5))
except Exception:  # pragma: no cover
    DEFAULT_K = 5
    DEFAULT_MAX_HOPS = 5

JUNCTION_PENALTY = 100      # path_weight 200 base + bu (toplam ~300)
LOW_CONF_PENALTY = 50       # confidence < 0.5 olan edge için ek ceza
HOP_PENALTY = 10            # her ek hop


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _node_of(schema: Optional[str], table: str) -> Node:
    return (_norm(schema), _norm(table))


# ─────────────────────────────────────────────────────────────
# Graf kurulumu
# ─────────────────────────────────────────────────────────────

def build_graph(cur, source_id: int):
    """ds_db_relationships'i okuyup DiGraph kurar.

    Her edge data:
        relationship_id, from_column, to_column,
        cardinality_from, cardinality_to, is_junction,
        path_weight, confidence_score, weight
    weight = path_weight + (low_conf_penalty if conf<0.5) + (junction_penalty if junction)
    """
    if not _HAS_NX:
        raise RuntimeError("networkx not installed")
    g = nx.DiGraph()
    cur.execute(
        """
        SELECT id, from_schema, from_table, from_column,
               to_schema, to_table, to_column,
               COALESCE(cardinality_from,'N') AS cf,
               COALESCE(cardinality_to,'1')   AS ct,
               COALESCE(is_junction, FALSE)   AS isj,
               COALESCE(path_weight, 100)     AS pw,
               COALESCE(confidence_score, 0.5) AS conf
        FROM ds_db_relationships
        WHERE source_id = %s
        """,
        (source_id,),
    )
    for row in cur.fetchall():
        if isinstance(row, dict):
            r = row
        else:
            r = {
                "id": row[0], "from_schema": row[1], "from_table": row[2], "from_column": row[3],
                "to_schema": row[4], "to_table": row[5], "to_column": row[6],
                "cf": row[7], "ct": row[8], "isj": row[9], "pw": row[10], "conf": row[11],
            }
        u = _node_of(r["from_schema"], r["from_table"])
        v = _node_of(r["to_schema"], r["to_table"])
        pw = int(r["pw"] or 100)
        conf = float(r["conf"] or 0.5)
        isj = bool(r["isj"])
        w = pw
        if conf < 0.5:
            w += LOW_CONF_PENALTY
        if isj:
            w += JUNCTION_PENALTY
        # Hem ileri hem geri yön ekle (FK keşfi tek yön kayıt eder ama join her iki yönde mümkün)
        edge_data = {
            "relationship_id": r["id"],
            "from_column": r["from_column"],
            "to_column": r["to_column"],
            "cardinality_from": r["cf"],
            "cardinality_to": r["ct"],
            "is_junction": isj,
            "path_weight": pw,
            "confidence_score": conf,
            "weight": float(w),
            "direction": "fwd",
        }
        # Daha düşük weight korunsun
        if g.has_edge(u, v):
            if g[u][v]["weight"] > w:
                g[u][v].update(edge_data)
        else:
            g.add_edge(u, v, **edge_data)
        # Geri yön — biraz daha pahalı (parent → child)
        rev_data = dict(edge_data)
        rev_data["direction"] = "rev"
        rev_data["weight"] = float(w + 5)
        if g.has_edge(v, u):
            if g[v][u]["weight"] > rev_data["weight"]:
                g[v][u].update(rev_data)
        else:
            g.add_edge(v, u, **rev_data)
    return g


# ─────────────────────────────────────────────────────────────
# Path arama
# ─────────────────────────────────────────────────────────────

def find_paths(
    graph,
    src: Node,
    dst: Node,
    k: int = DEFAULT_K,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> List[Path]:
    """Yen's K-shortest paths. Hops > max_hops olan yollar dışlanır."""
    if not _HAS_NX:
        raise RuntimeError("networkx not installed")
    if src not in graph or dst not in graph:
        return []
    if src == dst:
        return [[src]]
    try:
        gen = nx.shortest_simple_paths(graph, src, dst, weight="weight")
    except nx.NetworkXNoPath:
        return []
    paths: List[Path] = []
    for p in gen:
        if len(p) - 1 > max_hops:
            # paths weight artıyor; bundan sonrası da daha uzun → bitir
            break
        paths.append(p)
        if len(paths) >= k:
            break
    return paths


def score_path(graph, path: Path) -> float:
    """Yol skoru = edge weights toplamı + hop ceza."""
    if not path or len(path) < 2:
        return 0.0
    total = 0.0
    for i in range(len(path) - 1):
        e = graph.get_edge_data(path[i], path[i + 1]) or {}
        total += float(e.get("weight", 100.0))
    total += HOP_PENALTY * (len(path) - 2)
    return total


def expand_one_to_many(graph, path: Path) -> List[bool]:
    """Her edge için 'N tarafına gidiyor' flag (aggregation hint)."""
    if not path or len(path) < 2:
        return []
    out: List[bool] = []
    for i in range(len(path) - 1):
        e = graph.get_edge_data(path[i], path[i + 1]) or {}
        cf = (e.get("cardinality_from") or "N").upper()
        ct = (e.get("cardinality_to") or "1").upper()
        direction = e.get("direction", "fwd")
        # fwd: child→parent ise from='N',to='1' → tek-yön (aggregation YOK)
        # rev: parent→child ise tablo 1→N (aggregation gerek!)
        if direction == "rev" and ct == "1":
            out.append(True)
        elif cf == "N" and ct == "N":
            out.append(True)
        else:
            out.append(False)
    return out


# ─────────────────────────────────────────────────────────────
# Convenience: en iyi yol + JSON-friendly payload
# ─────────────────────────────────────────────────────────────

def resolve_best_path(
    cur,
    source_id: int,
    src_schema: Optional[str],
    src_table: str,
    dst_schema: Optional[str],
    dst_table: str,
    k: int = DEFAULT_K,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> Dict[str, Any]:
    """En iyi yol + ipuçları (UI/prompt için JSON).

    Returns:
        {
          "found": bool,
          "best": {
              "path": ["schema.table", ...],
              "join_path": [...],   # alias for path
              "edges": [{from, to, from_column, to_column, cardinality_from, cardinality_to, is_junction, weight}, ...],
              "score": float,
              "aggregate_hints": [bool, ...],
              "hops": int,
          },
          "alternatives": [ {...}, ... ]   # max k-1 ek yol
        }
    """
    if not _HAS_NX:
        return {"found": False, "error": "networkx_not_installed"}
    try:
        g = build_graph(cur, source_id)
    except Exception as exc:
        logger.exception("[FKGraph] build_graph failed source_id=%s", source_id)
        return {"found": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    src = _node_of(src_schema, src_table)
    dst = _node_of(dst_schema, dst_table)
    paths = find_paths(g, src, dst, k=k, max_hops=max_hops)
    if not paths:
        return {"found": False, "src": src, "dst": dst}

    def _path_payload(p: Path) -> Dict[str, Any]:
        edges = []
        for i in range(len(p) - 1):
            e = g.get_edge_data(p[i], p[i + 1]) or {}
            edges.append({
                "from": f"{p[i][0]}.{p[i][1]}".strip("."),
                "to": f"{p[i + 1][0]}.{p[i + 1][1]}".strip("."),
                "from_column": e.get("from_column"),
                "to_column": e.get("to_column"),
                "cardinality_from": e.get("cardinality_from"),
                "cardinality_to": e.get("cardinality_to"),
                "is_junction": bool(e.get("is_junction")),
                "weight": e.get("weight"),
                "direction": e.get("direction"),
            })
        return {
            "path": [f"{n[0]}.{n[1]}".strip(".") for n in p],
            "join_path": [f"{n[0]}.{n[1]}".strip(".") for n in p],
            "edges": edges,
            "score": round(score_path(g, p), 2),
            "aggregate_hints": expand_one_to_many(g, p),
            "hops": len(p) - 1,
        }

    payloads = [_path_payload(p) for p in paths]
    return {
        "found": True,
        "src": f"{src[0]}.{src[1]}".strip("."),
        "dst": f"{dst[0]}.{dst[1]}".strip("."),
        "best": payloads[0],
        "alternatives": payloads[1:],
    }
