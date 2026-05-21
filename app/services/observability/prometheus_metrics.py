"""Prometheus metrics for VYRA DB Smart Wizard (FAZ 5 P36).

Gated by settings.PROMETHEUS_ENABLED. If disabled or the prometheus_client
package is missing, all helpers no-op so business code calls don't break.

Metrics exposed (all aggregate; no row-level data):
    wizard_started_total            Counter
    wizard_completed_total          Counter
    recommendation_acceptance_total Counter{outcome}
    override_rate_total             Counter
    time_to_first_result_seconds    Histogram
    abandonment_step_total          Counter{step_id}
    cache_hit_total                 Counter{namespace,result}
    wizard_step_latency_ms          Histogram{step}
    sql_repair_attempt_total        Counter{outcome}

Note: `pipeline_events` table remains the ground truth for business funnel
metrics; this module is a stateless sink for Prometheus scrape only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

try:
    from prometheus_client import (  # type: ignore
        Counter,
        Histogram,
        Gauge,
        REGISTRY,
        CollectorRegistry,
    )
    _HAS_PROM = True
except Exception:  # pragma: no cover - depends on local install
    _HAS_PROM = False
    REGISTRY = None  # type: ignore
    CollectorRegistry = None  # type: ignore


_initialized: bool = False
_metrics: Dict[str, Any] = {}


class _NoOp:
    """Drop-in replacement when Prometheus is disabled.

    Supports the methods used by the codebase: .labels(...).inc/.observe/.set
    Always chainable, never raises.
    """

    def labels(self, *args: Any, **kwargs: Any) -> "_NoOp":
        return self

    def inc(self, *args: Any, **kwargs: Any) -> None:
        return None

    def observe(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set(self, *args: Any, **kwargs: Any) -> None:
        return None


_NOOP = _NoOp()


def init_prometheus(settings: Any, registry: Any = None) -> bool:
    """Register metrics on the given registry (default global REGISTRY).

    Returns True if active, False otherwise. Idempotent — calling twice
    will NOT re-register collectors (avoiding `Duplicated timeseries` on
    test reload).
    """
    global _initialized, _metrics

    if _initialized:
        return bool(_metrics)
    _initialized = True

    if not _HAS_PROM or not getattr(settings, "PROMETHEUS_ENABLED", False):
        logger.info(
            "[prom] disabled (has_client=%s enabled=%s)",
            _HAS_PROM,
            getattr(settings, "PROMETHEUS_ENABLED", False),
        )
        return False

    reg = registry if registry is not None else REGISTRY

    try:
        _metrics["wizard_started_total"] = Counter(
            "wizard_started_total",
            "DB Smart Wizard sessions started",
            registry=reg,
        )
        _metrics["wizard_completed_total"] = Counter(
            "wizard_completed_total",
            "DB Smart Wizard sessions completed",
            registry=reg,
        )
        _metrics["recommendation_acceptance_total"] = Counter(
            "recommendation_acceptance_total",
            "Recommendation outcomes",
            ["outcome"],  # accepted | rejected | modified
            registry=reg,
        )
        _metrics["override_rate_total"] = Counter(
            "override_rate_total",
            "Manual edits after recommendation",
            registry=reg,
        )
        _metrics["time_to_first_result_seconds"] = Histogram(
            "time_to_first_result_seconds",
            "Wizard start -> first result time (seconds)",
            buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
            registry=reg,
        )
        _metrics["abandonment_step_total"] = Counter(
            "abandonment_step_total",
            "Wizard abandonment by step id",
            ["step_id"],
            registry=reg,
        )
        _metrics["cache_hit_total"] = Counter(
            "cache_hit_total",
            "Cache lookup outcome by namespace",
            ["namespace", "result"],  # result: hit | miss
            registry=reg,
        )
        _metrics["wizard_step_latency_ms"] = Histogram(
            "wizard_step_latency_ms",
            "Wizard step transition latency (ms)",
            ["step"],
            buckets=(50, 100, 200, 500, 1000, 2000, 5000),
            registry=reg,
        )
        _metrics["sql_repair_attempt_total"] = Counter(
            "sql_repair_attempt_total",
            "SQL self-heal attempt outcomes",
            ["outcome"],
            registry=reg,
        )
    except Exception as e:  # pragma: no cover
        logger.warning("[prom] metric registration failed: %s", e)
        _metrics = {}
        return False

    logger.info("[prom] active metrics=%d", len(_metrics))
    return True


def get(name: str) -> Any:
    """Return the named metric or a NoOp shim if missing.

    Always safe to call .labels/.inc/.observe/.set on the result.
    """
    return _metrics.get(name, _NOOP)


def is_enabled() -> bool:
    """Return True iff metrics are registered."""
    return bool(_metrics)


def _reset_for_tests() -> None:
    """Test-only: clear registered metrics so a fresh init can run.

    Note: this does NOT unregister collectors from the global REGISTRY —
    tests that need a clean registry should pass a fresh CollectorRegistry
    to init_prometheus().
    """
    global _initialized, _metrics
    _initialized = False
    _metrics = {}
