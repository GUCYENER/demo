"""Unit tests for app.services.observability.prometheus_metrics + /metrics route.

These tests cover:
    - init_prometheus respects PROMETHEUS_ENABLED flag
    - init_prometheus is idempotent
    - get() returns _NoOp shim when disabled / unknown name
    - Counters and histograms record values on the bound registry
    - Labelled counters expose per-label samples
    - /metrics endpoint enforces IP allowlist (403 by default)
    - /metrics returns 200 + text/plain when IP is allowed
    - /metrics returns 503 when prometheus_client is unavailable

Skipped automatically if prometheus_client is not installed locally.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Iterator

import pytest

prom_client = pytest.importorskip(
    "prometheus_client",
    reason="prometheus_client not installed locally (CI provides it)",
)
from prometheus_client import CollectorRegistry  # noqa: E402

from app.services.observability import prometheus_metrics as pm  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_module_state() -> Iterator[None]:
    """Each test starts with a clean module-level _initialized flag."""
    pm._reset_for_tests()
    yield
    pm._reset_for_tests()


# ---------------------------------------------------------------------------
# init_prometheus behaviour
# ---------------------------------------------------------------------------
def test_init_disabled_returns_false_and_noop():
    settings = SimpleNamespace(PROMETHEUS_ENABLED=False)
    assert pm.init_prometheus(settings) is False
    assert pm.is_enabled() is False
    m = pm.get("wizard_started_total")
    # NoOp shim — all ops chainable and silent
    m.labels(foo="bar").inc()
    m.observe(1.0)
    m.set(5)
    assert isinstance(m, pm._NoOp)


def test_init_enabled_returns_true_and_registers_metrics():
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    assert pm.init_prometheus(settings, registry=reg) is True
    assert pm.is_enabled() is True
    # All expected metric names are registered
    for name in [
        "wizard_started_total",
        "wizard_completed_total",
        "recommendation_acceptance_total",
        "override_rate_total",
        "time_to_first_result_seconds",
        "abandonment_step_total",
        "cache_hit_total",
        "wizard_step_latency_ms",
        "sql_repair_attempt_total",
    ]:
        assert name in pm._metrics, f"missing metric {name}"


def test_init_is_idempotent():
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    assert pm.init_prometheus(settings, registry=reg) is True
    # Second call must not raise "Duplicated timeseries" — it short-circuits
    assert pm.init_prometheus(settings, registry=reg) is True


def test_get_unknown_metric_returns_noop():
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    pm.init_prometheus(settings, registry=reg)
    m = pm.get("does_not_exist")
    assert isinstance(m, pm._NoOp)


# ---------------------------------------------------------------------------
# Counter / histogram / label behaviour
# ---------------------------------------------------------------------------
def test_counter_increment_visible_in_registry():
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    pm.init_prometheus(settings, registry=reg)

    pm.get("wizard_completed_total").inc()
    pm.get("wizard_completed_total").inc()

    val = reg.get_sample_value("wizard_completed_total_total")
    # prometheus_client appends "_total" to Counter samples — handle both styles
    if val is None:
        val = reg.get_sample_value("wizard_completed_total")
    assert val == 2.0


def test_labelled_counter_per_label_samples():
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    pm.init_prometheus(settings, registry=reg)

    pm.get("recommendation_acceptance_total").labels(outcome="accepted").inc()
    pm.get("recommendation_acceptance_total").labels(outcome="accepted").inc()
    pm.get("recommendation_acceptance_total").labels(outcome="rejected").inc()

    def _v(name: str, **labels: str) -> float:
        for n in (name, f"{name}_total"):
            v = reg.get_sample_value(n, labels)
            if v is not None:
                return v
        return 0.0

    assert _v("recommendation_acceptance_total", outcome="accepted") == 2.0
    assert _v("recommendation_acceptance_total", outcome="rejected") == 1.0


def test_histogram_observation_increments_bucket():
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    pm.init_prometheus(settings, registry=reg)

    # observe 500 ms on step "domain_select" — falls in (200, 500] bucket
    pm.get("wizard_step_latency_ms").labels(step="domain_select").observe(500)

    # The +Inf bucket count must equal total observations (1)
    val = reg.get_sample_value(
        "wizard_step_latency_ms_bucket",
        {"step": "domain_select", "le": "+Inf"},
    )
    assert val == 1.0
    # And the 500 bucket must include the observation
    val_500 = reg.get_sample_value(
        "wizard_step_latency_ms_bucket",
        {"step": "domain_select", "le": "500.0"},
    )
    assert val_500 == 1.0


# ---------------------------------------------------------------------------
# /metrics endpoint security
# ---------------------------------------------------------------------------
def _build_test_app():
    """Build a minimal FastAPI app with only the /metrics router mounted."""
    from fastapi import FastAPI

    # Force-reimport the route module so it picks up current settings each time
    from app.api.routes import _metrics as metrics_route
    importlib.reload(metrics_route)

    app = FastAPI()
    app.include_router(metrics_route.router)
    return app, metrics_route


def test_metrics_endpoint_denies_when_allowlist_empty(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "METRICS_IP_ALLOWLIST", "", raising=False)

    app, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 403


def test_metrics_endpoint_allows_listed_ip(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core import config as cfg

    # TestClient default client.host is "testclient" — allow it explicitly
    monkeypatch.setattr(
        cfg.settings, "METRICS_IP_ALLOWLIST", "testclient,127.0.0.1", raising=False
    )

    # Make sure metrics are registered on the default REGISTRY so generate_latest
    # has something (or nothing) to emit — either way must be 200.
    reg = CollectorRegistry()
    settings = SimpleNamespace(PROMETHEUS_ENABLED=True)
    pm.init_prometheus(settings, registry=reg)

    app, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/plain")


def test_metrics_endpoint_503_when_prometheus_missing(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core import config as cfg
    from app.api.routes import _metrics as metrics_route

    # Allowlist is irrelevant — 503 is returned before the auth check.
    monkeypatch.setattr(cfg.settings, "METRICS_IP_ALLOWLIST", "testclient", raising=False)
    monkeypatch.setattr(metrics_route, "_HAS_PROM", False)

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(metrics_route.router)
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 503


def test_metrics_endpoint_honours_x_forwarded_for(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "METRICS_IP_ALLOWLIST", "10.0.0.5", raising=False)

    app, _ = _build_test_app()
    with TestClient(app) as client:
        # Without XFF -> denied (testclient not in allowlist)
        r1 = client.get("/metrics")
        assert r1.status_code == 403
        # With XFF matching allowlist -> allowed
        r2 = client.get("/metrics", headers={"x-forwarded-for": "10.0.0.5"})
        assert r2.status_code == 200
        # XFF chain — first hop wins
        r3 = client.get(
            "/metrics", headers={"x-forwarded-for": "10.0.0.5, 192.168.1.1"}
        )
        assert r3.status_code == 200


def test_metrics_endpoint_explicit_open(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "METRICS_IP_ALLOWLIST", "0.0.0.0/0", raising=False)

    app, _ = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
