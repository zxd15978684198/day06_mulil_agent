"""telemetry 配置分支的单元测试（不启动真实 exporter）。"""

from __future__ import annotations

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from personal_assistant import telemetry


def test_flag_and_resource(monkeypatch) -> None:
    monkeypatch.setenv("TEST_FLAG", "yes")
    assert telemetry._flag("TEST_FLAG") is True
    monkeypatch.setenv("TEST_FLAG", "0")
    assert telemetry._flag("TEST_FLAG") is False
    monkeypatch.delenv("TEST_FLAG", raising=False)
    assert telemetry._flag("TEST_FLAG", True) is True

    monkeypatch.setenv("OTEL_SERVICE_NAME", "svc")
    monkeypatch.setenv("DEPLOYMENT_ENV", "test")
    resource = telemetry._resource()
    assert resource.attributes["service.name"] == "svc"
    assert resource.attributes["deployment.environment.name"] == "test"


def test_trace_exporter_modes(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    assert telemetry._trace_exporter() is None

    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "console")
    assert isinstance(telemetry._trace_exporter(), ConsoleSpanExporter)

    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
    assert telemetry._trace_exporter() is None

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    assert isinstance(telemetry._trace_exporter(), OTLPSpanExporter)


def test_metric_exporter_modes(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
    assert telemetry._metric_exporter() is None

    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "console")
    assert isinstance(telemetry._metric_exporter(), ConsoleMetricExporter)

    monkeypatch.setenv("OTEL_METRICS_EXPORTER", "otlp")
    assert telemetry._metric_exporter() is None

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    assert isinstance(telemetry._metric_exporter(), OTLPMetricExporter)


def test_metric_interval_and_sampler(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "not-int")
    assert telemetry._metric_interval_millis() == 5000
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "100")
    assert telemetry._metric_interval_millis() == 1000

    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    assert telemetry._sampler().get_description() == "AlwaysOffSampler"
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    assert telemetry._sampler().get_description() == "AlwaysOnSampler"
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "not-a-float")
    assert "TraceIdRatioBased" in telemetry._sampler().get_description()


def test_current_trace_ids_without_span_and_shutdown_noop() -> None:
    assert telemetry.current_trace_ids() == (None, None)
    telemetry.shutdown_telemetry()
    telemetry.shutdown_telemetry()
