"""Metrics 契约：指标存在、单位/属性正确、没有高基数业务 ID。

用 subprocess 是因为 MeterProvider 一个进程只能设置一次；独立进程能保证
读到的是本次测试自己记录的数据。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

_SCRIPT = r"""
import json
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))

import personal_assistant.metrics as m
m.record_agent_run(
    outcome="completed", kind="chat", role="employee", duration_ms=12.3
)
m.record_rag(outcome="hit", duration_ms=4.5)

points = []
data = reader.get_metrics_data()
for resource_metrics in data.resource_metrics:
    for scope_metrics in resource_metrics.scope_metrics:
        for metric in scope_metrics.metrics:
            for point in metric.data.data_points:
                points.append(
                    {"name": metric.name, "attrs": dict(point.attributes)}
                )
print(json.dumps(points, ensure_ascii=False))
"""


def test_metric_record_functions_are_noop_without_provider() -> None:
    from personal_assistant import metrics

    metrics.record_agent_run(
        outcome="failed", kind="resume", role="hr", duration_ms=1.0
    )
    metrics.record_tool(
        tool_name="search_company_knowledge", outcome="completed", duration_ms=1.0
    )
    metrics.record_rag(outcome="no_evidence", duration_ms=1.0)
    metrics.record_llm_usage(model="model", input_tokens=3, output_tokens=4)
    metrics.record_llm_usage(model="", input_tokens=None, output_tokens=None)
    metrics.inc_active_streams()
    metrics.dec_active_streams()


def test_metrics_exist_and_have_no_business_ids() -> None:
    env = os.environ.copy()
    env.pop("OTEL_SDK_DISABLED", None)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    points = json.loads(result.stdout.strip().splitlines()[-1])
    names = {point["name"] for point in points}

    assert "agent.run.count" in names
    assert "agent.run.duration" in names
    assert "rag.search.count" in names
    assert "rag.search.duration" in names

    for point in points:
        assert "thread_id" not in point["attrs"]
        assert "request_id" not in point["attrs"]
        assert "run_id" not in point["attrs"]
