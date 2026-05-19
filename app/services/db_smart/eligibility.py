"""Domain + tablo eligibility / arama (v3.30.0 FAZ 0 iskelet).

Gerçek implementasyon FAZ 1 G1.2'de:
    - search_domains(source_id, query, user_ctx) → ranked table list
      Hybrid: ds_db_objects.object_name + ds_column_enrichments.business_name_tr
      + business_glossary_v2 expansion (embedding ≥ 0.7) + cardinality skoru
      + dbsmart_user_preferences.frequent_tables boost.
    - sample_preview(table_id) → 5 satır ds_db_samples'tan
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def search_domains(
    source_id: int,
    query: str,
    user_ctx: Dict[str, Any],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Türkçe iş dilinden tabloya search.

    FAZ 0 stub: boş liste.
    """
    logger.debug("[db_smart.eligibility] search stub source=%s q=%r", source_id, query)
    return []


def sample_preview(table_id: int, user_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Hover preview için 5 satır örnek (ds_db_samples)."""
    logger.debug("[db_smart.eligibility] sample stub table=%s", table_id)
    return None
