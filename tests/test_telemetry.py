"""
Telemetry service unit tests.
Uses local TracerProvider + InMemorySpanExporter — no real OTLP endpoint needed,
no global provider manipulation.
"""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.services.telemetry_service import get_current_trace_id, record_span


def _make_tracer(name: str = "test"):
    """Creates an isolated tracer with an InMemorySpanExporter. Returns (tracer, exporter)."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(name), exporter


class TestGetCurrentTraceId:
    def test_returns_none_outside_span(self):
        assert get_current_trace_id() is None

    def test_returns_hex_string_inside_span(self):
        tracer, _ = _make_tracer()
        with tracer.start_as_current_span("root"):
            trace_id = get_current_trace_id()
        assert trace_id is not None
        assert len(trace_id) == 32
        int(trace_id, 16)  # must be valid hex

    def test_returns_none_after_span_exits(self):
        tracer, _ = _make_tracer()
        with tracer.start_as_current_span("root"):
            pass
        # After the span exits, no active span remains
        assert get_current_trace_id() is None


class TestRecordSpan:
    def test_span_exported_with_correct_name(self):
        tracer, exporter = _make_tracer()
        with record_span(tracer, "my.operation"):
            pass
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "my.operation"

    def test_span_attributes_stored(self):
        tracer, exporter = _make_tracer()
        with record_span(tracer, "attr.op", attributes={"run_id": "abc", "route": "log_triage"}):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].attributes["run_id"] == "abc"
        assert spans[0].attributes["route"] == "log_triage"

    def test_attributes_are_stringified(self):
        tracer, exporter = _make_tracer()
        with record_span(tracer, "typed.attrs", attributes={"count": 42, "flag": True}):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].attributes["count"] == "42"
        assert spans[0].attributes["flag"] == "True"

    def test_exception_sets_error_status(self):
        tracer, exporter = _make_tracer()
        with pytest.raises(ValueError):
            with record_span(tracer, "failing.op"):
                raise ValueError("boom")
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code == StatusCode.ERROR
        assert "boom" in spans[0].status.description

    def test_exception_is_reraised(self):
        tracer, _ = _make_tracer()
        with pytest.raises(RuntimeError, match="propagate me"):
            with record_span(tracer, "op"):
                raise RuntimeError("propagate me")

    def test_no_exception_span_is_ok(self):
        tracer, exporter = _make_tracer()
        with record_span(tracer, "ok.op"):
            pass
        spans = exporter.get_finished_spans()
        assert spans[0].status.status_code != StatusCode.ERROR


class TestSetupTelemetry:
    def test_disabled_otel_returns_none(self, monkeypatch):
        from app.services import telemetry_service
        monkeypatch.setattr(telemetry_service.settings, "otel_enabled", False)
        result = telemetry_service.setup_telemetry()
        assert result is None

    def test_setup_with_exporter_creates_provider(self):
        from app.services.telemetry_service import setup_telemetry_with_exporter
        exporter = InMemorySpanExporter()
        provider = setup_telemetry_with_exporter(exporter)
        assert provider is not None
        assert type(provider).__name__ == "TracerProvider"
