"""Observability stack (FAZ 5 P36).

- otel_setup: OpenTelemetry TracerProvider + OTLP HTTP exporter +
  FastAPI/psycopg2 auto-instrumentation
- prometheus_metrics: Custom counters/histograms/gauges for DB Smart Wizard
- Langfuse adapter: existing at app/services/pipeline/langfuse_adapter.py

`pipeline_events` table remains the ground truth for funnel/business
metrics; OTel and Prometheus are sinks (not new persistence).
"""
