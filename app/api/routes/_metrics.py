"""GET /metrics - Prometheus scrape endpoint (FAZ 5 P36).

Security model:
    - IP allowlist via settings.METRICS_IP_ALLOWLIST (comma-separated).
    - Closed by default: empty allowlist -> 403 for every request.
    - No row-level data; only aggregate counters/histograms.
    - No authentication header required (Prometheus uses IP-pinned scrapes).

If prometheus_client is not installed -> 503.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
    _HAS_PROM = True
except Exception:  # pragma: no cover
    _HAS_PROM = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str:
    """Resolve the originating client IP, honouring X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host or ""
    return ""


def _is_allowed(ip: str) -> bool:
    """True iff `ip` is in METRICS_IP_ALLOWLIST. Closed by default."""
    raw = getattr(settings, "METRICS_IP_ALLOWLIST", "") or ""
    allowlist = [a.strip() for a in raw.split(",") if a.strip()]
    if not allowlist:
        return False  # closed by default
    if "0.0.0.0/0" in allowlist:  # explicit open (dev/debug only)
        return True
    return ip in allowlist


@router.get("/metrics")
async def prometheus_metrics(request: Request) -> Response:
    """Prometheus scrape endpoint. IP-allowlisted; aggregate metrics only."""
    if not _HAS_PROM:
        raise HTTPException(status_code=503, detail="Prometheus client not installed")

    ip = _client_ip(request)
    if not _is_allowed(ip):
        logger.debug("[/metrics] denied ip=%s", ip)
        raise HTTPException(status_code=403, detail="Forbidden")

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
