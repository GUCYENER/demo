"""OpenTelemetry setup for VYRA L1 Support API (FAZ 5 P36).

Optional — gated by settings.OTEL_EXPORTER_OTLP_ENDPOINT. If empty/None or
SDK not installed, all helpers no-op so business code can call
`with span(...)` unconditionally.

Public API:
    init_otel(app, settings) -> bool
    get_tracer() -> Tracer | None
    span(name, **attributes) -> context manager (yields Span | None)
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# All OTel imports are guarded — missing deps must NOT break app startup.
try:
    from opentelemetry import trace  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME  # type: ignore
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
    _HAS_OTEL = True
except Exception:  # pragma: no cover - depends on local install
    _HAS_OTEL = False

try:
    from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor  # type: ignore
    _HAS_PSYCOPG2_INSTR = True
except Exception:  # pragma: no cover
    _HAS_PSYCOPG2_INSTR = False


_initialized: bool = False
_tracer: Optional[Any] = None


def init_otel(app: Any, settings: Any) -> bool:
    """Initialize OpenTelemetry tracing.

    Returns True if active (exporter configured + SDK present), False if
    no-op (missing dep or no endpoint configured).

    Idempotent: subsequent calls return the cached activation flag.
    """
    global _initialized, _tracer

    if _initialized:
        return _tracer is not None
    _initialized = True

    endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", None)
    if not _HAS_OTEL or not endpoint:
        logger.info(
            "[otel] disabled (has_sdk=%s endpoint=%s)", _HAS_OTEL, bool(endpoint)
        )
        return False

    try:
        resource = Resource.create({
            SERVICE_NAME: "vyra-l1-support-api",
            "service.version": getattr(settings, "APP_VERSION", "3.30.0"),
            "deployment.environment": (
                "prod" if not getattr(settings, "debug", True) else "dev"
            ),
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(__name__)
    except Exception as e:  # pragma: no cover
        logger.warning("[otel] provider init failed: %s", e)
        _tracer = None
        return False

    # FastAPI auto-instrumentation — best-effort
    try:
        FastAPIInstrumentor.instrument_app(app)
    except Exception as e:  # pragma: no cover
        logger.debug("[otel] FastAPIInstrumentor skipped: %s", e)

    # psycopg2 auto-instrumentation — best-effort
    if _HAS_PSYCOPG2_INSTR:
        try:
            Psycopg2Instrumentor().instrument()
        except Exception as e:  # pragma: no cover
            logger.debug("[otel] Psycopg2Instrumentor skipped: %s", e)

    logger.info("[otel] active endpoint=%s", endpoint)
    return True


def get_tracer() -> Optional[Any]:
    """Return the configured tracer or None if OTel is not active."""
    return _tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Optional[Any]]:
    """Defensive span context manager.

    Works whether OTel is active or not — if inactive yields None so
    callers can `with span(...) as s: ...` unconditionally.
    """
    if _tracer is None:
        yield None
        return
    try:
        with _tracer.start_as_current_span(name) as s:
            for k, v in attributes.items():
                try:
                    s.set_attribute(k, v)
                except Exception:
                    pass
            yield s
    except Exception as e:  # pragma: no cover
        logger.debug("[otel.span] %s failed: %s", name, e)
        yield None


def _reset_for_tests() -> None:
    """Test-only helper to reset module state."""
    global _initialized, _tracer
    _initialized = False
    _tracer = None
