"""OpenTelemetry 初始化的行为测试。

为什么用 subprocess：
    `trace.set_tracer_provider()` 一个进程只能生效一次。如果在一个 pytest 进程里
    反复用不同配置调用 `setup_telemetry()`，第二次会静默复用第一次的 Provider，
    测试结果取决于执行顺序。每个场景起一个独立 Python 进程，隔离干净。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env["PYTHONPATH"] = (
        str(SRC_DIR) + os.pathsep + process_env.get("PYTHONPATH", "")
    )
    # 先清掉可能从开发机 .env / shell 继承的值，再按测试覆盖。
    process_env["OTEL_SDK_DISABLED"] = "false"
    process_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
    process_env["OTEL_TRACES_EXPORTER"] = "none"
    process_env["OTEL_METRICS_EXPORTER"] = "none"
    process_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        env=process_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_default_is_noop() -> None:
    result = _run(
        "from personal_assistant.telemetry import setup_telemetry; "
        "print(setup_telemetry())"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("False")


def test_sdk_disabled_is_noop() -> None:
    result = _run(
        "from personal_assistant.telemetry import setup_telemetry; "
        "print(setup_telemetry())",
        OTEL_SDK_DISABLED="true",
        OTEL_TRACES_EXPORTER="console",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("False")


def test_console_exporter_emits_span() -> None:
    result = _run(
        "\n".join(
            [
                "from opentelemetry import trace",
                "from personal_assistant.telemetry import (",
                "    setup_telemetry, shutdown_telemetry,",
                ")",
                "enabled = setup_telemetry()",
                "tracer = trace.get_tracer('test')",
                "with tracer.start_as_current_span('test.span'):",
                "    pass",
                "shutdown_telemetry()",
                "print(f'enabled={enabled}')",
            ]
        ),
        OTEL_TRACES_EXPORTER="console",
    )

    assert result.returncode == 0, result.stderr
    assert "enabled=True" in result.stdout
    assert "test.span" in result.stdout


def test_sampler_from_env(monkeypatch) -> None:
    from personal_assistant import telemetry

    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    assert telemetry._sampler().get_description() == "AlwaysOffSampler"

    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.5")
    assert telemetry._sampler().get_description().startswith("ParentBased")


def test_resource_from_env(monkeypatch) -> None:
    from personal_assistant import telemetry

    monkeypatch.setenv("OTEL_SERVICE_NAME", "test-service")
    monkeypatch.setenv("DEPLOYMENT_ENV", "test")
    resource = telemetry._resource()

    assert resource.attributes["service.name"] == "test-service"
    assert resource.attributes["deployment.environment.name"] == "test"
