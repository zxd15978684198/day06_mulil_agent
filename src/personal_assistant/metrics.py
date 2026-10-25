"""OTel Metrics 指标定义与记录函数。

指标只放**低基数、非敏感**维度：outcome / kind / role / tool / model / token_type。
禁止把 thread_id、request_id、run_id、Prompt、用户输入放进 attributes。

导出链路：应用 → OTLP → Collector → `prometheus` exporter :8889 → Prometheus 拉取。
"""

from __future__ import annotations

from opentelemetry import metrics

_METER = metrics.get_meter("personal_assistant.agent")

_AGENT_RUN_COUNT = _METER.create_counter(
    "agent.run.count",
    unit="1",
    description="Agent 每轮执行次数",
)
_AGENT_RUN_DURATION = _METER.create_histogram(
    "agent.run.duration",
    unit="ms",
    description="Agent 单轮执行耗时",
)
_AGENT_TOOL_COUNT = _METER.create_counter(
    "agent.tool.count",
    unit="1",
    description="Agent Tool / 业务 Tool 调用次数",
)
_AGENT_TOOL_DURATION = _METER.create_histogram(
    "agent.tool.duration",
    unit="ms",
    description="Tool 调用耗时",
)
_RAG_SEARCH_COUNT = _METER.create_counter(
    "rag.search.count",
    unit="1",
    description="知识库检索次数",
)
_RAG_SEARCH_DURATION = _METER.create_histogram(
    "rag.search.duration",
    unit="ms",
    description="知识库检索耗时",
)
_LLM_TOKEN_USAGE = _METER.create_counter(
    "llm.token.usage",
    unit="1",
    description="模型 Token 用量（按 input/output 分组）",
)
_ACTIVE_STREAMS = _METER.create_up_down_counter(
    "agent.active_streams",
    unit="1",
    description="当前活跃 SSE 流数量",
)


def record_agent_run(*, outcome: str, kind: str, role: str, duration_ms: float) -> None:
    attributes = {"outcome": outcome, "agent_kind": kind}
    if role:
        attributes["role"] = role
    _AGENT_RUN_COUNT.add(1, attributes)
    _AGENT_RUN_DURATION.record(duration_ms, attributes)


def record_tool(*, tool_name: str, outcome: str, duration_ms: float) -> None:
    attributes = {"tool_name": tool_name, "outcome": outcome}
    _AGENT_TOOL_COUNT.add(1, attributes)
    _AGENT_TOOL_DURATION.record(duration_ms, attributes)


def record_rag(*, outcome: str, duration_ms: float) -> None:
    attributes = {"outcome": outcome}
    _RAG_SEARCH_COUNT.add(1, attributes)
    _RAG_SEARCH_DURATION.record(duration_ms, attributes)


def record_llm_usage(
    *, model: str, input_tokens: int | None, output_tokens: int | None
) -> None:
    if model and input_tokens:
        _LLM_TOKEN_USAGE.add(input_tokens, {"token_type": "input", "model": model})
    if model and output_tokens:
        _LLM_TOKEN_USAGE.add(output_tokens, {"token_type": "output", "model": model})


def inc_active_streams() -> None:
    _ACTIVE_STREAMS.add(1)


def dec_active_streams() -> None:
    _ACTIVE_STREAMS.add(-1)
