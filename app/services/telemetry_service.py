"""
OpenTelemetry tracing setup and helpers.

Usage:
  Call setup_telemetry(app) once at startup (main.py lifespan).
  Use get_tracer(__name__) in any module to create spans.
  Use get_current_trace_id() to inject trace context into logs.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode

from app.config import settings


def _build_exporter() -> SpanExporter:
    """Returns OTLP exporter when endpoint is configured, else console."""
    if settings.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        return OTLPSpanExporter(endpoint=settings.otlp_endpoint)
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    return ConsoleSpanExporter()


def setup_telemetry(app: Any = None) -> TracerProvider | None:
    """
    Initialise the global TracerProvider.
    Returns the provider (useful for tests that want to inspect spans).
    No-ops when otel_enabled=False.
    """
    if not settings.otel_enabled:
        return None

    resource = Resource.create({
        "service.name": "ai-workflow-orchestrator",
        "service.version": "1.0.0",
        "deployment.environment": settings.app_env,
    })

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(_build_exporter()))
    trace.set_tracer_provider(provider)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    HTTPXClientInstrumentor().instrument()

    return provider


def setup_telemetry_with_exporter(exporter: SpanExporter) -> TracerProvider:
    """
    Test helper: set up a provider with a synchronous (SimpleSpanProcessor) exporter
    so spans are immediately available after the span context manager exits.
    Returns the provider so callers can introspect exported spans.
    """
    resource = Resource.create({"service.name": "ai-workflow-orchestrator-test"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def get_current_trace_id() -> str | None:
    """Returns the current trace ID as a 32-char hex string, or None outside a span."""
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return None


@contextmanager
def record_span(
    tracer: trace.Tracer,
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Span, None, None]:
    """
    Context manager that creates a named span and automatically records
    exceptions as ERROR status if they propagate out.
    """
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
