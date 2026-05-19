"""FK graph subgraph + path-suggest (v3.30.0 FAZ 0 iskelet).

Gerçek implementasyon FAZ 1 G1.3'te:
    - build_subgraph(source_id, table_ids) → NetworkX DiGraph
      (declared + inferred FK'lar; ds_db_relationships'ten)
    - expand_with_fk(table_ids, depth=1) → direct neighbors + cardinality
    - suggest_join_path(table_a, table_b) → shortest path (path_weight)
    - detect_junctions(subgraph) → middle tables (N-N için)

FAZ 0'da NetworkX bağımlılığı opsiyonel; yoksa pure-Python adj-list fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import networkx as nx  # type: ignore
    _HAS_NX = True
except Exception:
    _HAS_NX = False
    logger.info("[db_smart.fk] NetworkX yuklu degil — adj-list fallback")


def build_subgraph(
    source_id: int,
    table_ids: List[int],
    user_ctx: Dict[str, Any],
) -> Optional[Any]:
    """Belirtilen tablolar etrafında FK alt-grafı oluştur.

    FAZ 0 stub: None.
    """
    logger.debug("[db_smart.fk] build stub source=%s tables=%s", source_id, table_ids)
    return None


def expand_with_fk(
    source_id: int,
    table_ids: List[int],
    depth: int = 1,
) -> List[Dict[str, Any]]:
    """Direct/indirect FK komşularını döndür.

    FAZ 0 stub: boş.
    """
    return []


def suggest_join_path(
    source_id: int,
    table_a: int,
    table_b: int,
) -> Optional[List[Tuple[int, int]]]:
    """İki tablo arasında en hafif join yolunu öner."""
    return None
