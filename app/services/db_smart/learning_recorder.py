"""dbsmart_interactions event recorder (v3.30.0 FAZ 0 iskelet).

Gerçek implementasyon FAZ 2 G2.4'te:
    - record(action, session_id, payload, user_ctx) — INSERT dbsmart_interactions
    - PII masking: ds_column_enrichments.is_pii=TRUE ise payload[col]='***MASKED***'
    - Retention: hot (3 ay), warm (1 yıl), cold (jsonb archive)

Event taxonomy (Prompt I):
    SessionStarted, DomainSelected, TableSelected, DateColumnSelected,
    FilterApplied, MetricChosen, CustomMetricWritten, SQLGenerated,
    SQLModified, QueryExecuted, ReportRecommendationShown,
    ReportRecommendationAccepted, ReportRecommendationRejected,
    WizardCompleted, WizardAbandoned, ReportSaved, ReportRerun,
    ExplicitFeedback
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Bilinen event aksiyonları — yanlış yazımı engellemek için sabit set
KNOWN_ACTIONS = frozenset({
    "SessionStarted", "DomainSelected", "TableSelected", "DateColumnSelected",
    "FilterApplied", "MetricChosen", "CustomMetricWritten", "SQLGenerated",
    "SQLModified", "QueryExecuted", "ReportRecommendationShown",
    "ReportRecommendationAccepted", "ReportRecommendationRejected",
    "WizardCompleted", "WizardAbandoned", "ReportSaved", "ReportRerun",
    "ExplicitFeedback",
})


def record(
    action: str,
    session_id: Optional[int],
    user_ctx: Dict[str, Any],
    step: Optional[int] = None,
    suggestion_shown: Optional[Dict[str, Any]] = None,
    suggestion_accepted: Optional[Dict[str, Any]] = None,
    user_override: Optional[Dict[str, Any]] = None,
    satisfaction: Optional[int] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Event yazar (FAZ 0 stub: yalnızca log)."""
    if action not in KNOWN_ACTIONS:
        logger.warning("[db_smart.lr] unknown action: %s", action)
        return
    logger.debug(
        "[db_smart.lr] %s session=%s step=%s sat=%s dur=%s",
        action, session_id, step, satisfaction, duration_ms,
    )
