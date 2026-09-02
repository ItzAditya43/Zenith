"""Prometheus/OpenMetrics scrape endpoint.

Exposes the usage data already computed in app/db/storage.py (from the
usage_events table fed by app/api/chat.py's turn-completion path) in a
format any homelab Grafana/Prometheus setup can scrape directly, rather
than only via the JSON usage endpoints the frontend dashboard uses.

This is a snapshot-on-scrape design: each GET /metrics call re-reads
storage and rebuilds a fresh CollectorRegistry, so the Gauges below
reflect the current state of usage_events at scrape time. They are not
live counters incremented at the turn-completion call site (that call
site lives in app/api/chat.py, a file this module does not own/edit).

Requires the `prometheus-client` package (not yet added to
requirements.txt/pyproject.toml — that's owned by another agent).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from app.core.logging import get_logger
from app.db import storage

log = get_logger(__name__)
router = APIRouter(tags=["metrics"])

_VERSION = "0.1.0"  # mirrors app.main's FastAPI(version=...)


@router.get("/metrics")
async def metrics():
    """Renders current usage_events data as Prometheus/OpenMetrics text
    exposition format. Uses a fresh CollectorRegistry per request so
    concurrent scrapes never share/clobber Gauge state."""
    registry = CollectorRegistry()

    turns_total = Gauge(
        "zenith_usage_turns_total",
        "Total recorded chat turns per model over the usage window (snapshot, not a live counter)",
        ["model"],
        registry=registry,
    )
    avg_tokens_per_sec = Gauge(
        "zenith_usage_avg_tokens_per_sec",
        "Average tokens/sec throughput per model over the usage window",
        ["model"],
        registry=registry,
    )
    latency_ms = Gauge(
        "zenith_usage_latency_ms",
        "Turn latency (duration_ms) percentiles across recent usage events",
        ["quantile"],
        registry=registry,
    )
    info = Gauge(
        "zenith_info",
        "Static build/version info for the running Zenith instance",
        ["version"],
        registry=registry,
    )

    try:
        by_model = storage.usage_by_model()
    except Exception as exc:  # storage/db issues shouldn't break the scrape endpoint
        log.warning("metrics.usage_by_model_failed", error=str(exc))
        by_model = []

    for row in by_model:
        model = row.get("model") or "unknown"
        turns_total.labels(model=model).set(row.get("turns", 0) or 0)
        tps = row.get("avg_tokens_per_sec")
        if tps is not None:
            avg_tokens_per_sec.labels(model=model).set(tps)

    try:
        percentiles = storage.usage_latency_percentiles()
    except Exception as exc:
        log.warning("metrics.usage_latency_percentiles_failed", error=str(exc))
        percentiles = {"p50_ms": None, "p90_ms": None, "p99_ms": None}

    for quantile, key in (("p50", "p50_ms"), ("p90", "p90_ms"), ("p99", "p99_ms")):
        value = percentiles.get(key)
        if value is not None:
            latency_ms.labels(quantile=quantile).set(value)

    info.labels(version=_VERSION).set(1)

    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
