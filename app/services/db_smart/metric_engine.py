"""Metrik kütüphanesi engine (v3.30.0 FAZ 0 iskelet).

Gerçek implementasyon FAZ 1 G1.4'te:
    - list_eligible(table_signature, user_ctx) → ranked metric list
      applicable_when JSONB → kolon tip/cardinality/FK presence/sample data eşleştir
      skor = pattern_strength * 0.5 + usage_count_norm * 0.3 + user_pref * 0.2
      >0.6 olanları döndür.
    - get_template(metric_key, dialect) → SQL template + parametre listesi
    - record_usage(metric_key, success) → usage_count++, success_rate güncelle
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def list_eligible(
    table_signature: Dict[str, Any],
    user_ctx: Dict[str, Any],
    min_score: float = 0.6,
) -> List[Dict[str, Any]]:
    """Tablo imzasına uyan metrik listesini sıralı döndür.

    FAZ 0 stub: boş.
    """
    logger.debug("[db_smart.metric] eligible stub keys=%s", list(table_signature.keys()))
    return []


def get_template(metric_key: str, dialect: str) -> Optional[Dict[str, Any]]:
    """metric_library.sql_templates[dialect] döndür."""
    return None


def record_usage(metric_key: str, success: bool, user_ctx: Dict[str, Any]) -> None:
    """usage_count++ + success_rate moving average."""
    logger.debug("[db_smart.metric] usage stub key=%s ok=%s", metric_key, success)
