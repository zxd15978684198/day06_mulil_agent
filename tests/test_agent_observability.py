"""agent.turn Span 的单元测试：不启动模型、不连数据库。

用一个假的 `_stream_chat_impl` 和假 Supervisor，验证：
* `stream_chat` 生成 `agent.turn`，带业务 ID 与 Langfuse 属性；
* 遇到 confirmation 事件时 outcome=waiting_confirmation；
* `resume` 生成独立的一轮，kind=resume；
* 异常原样抛出，不被埋点吞掉。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from personal_assistant.business_tools import RunContext
from personal_assistant.multi_agent import MultiAgentApplication, UserSession


@pytest.fixture(scope="module")
def exporter() -> InMemorySpanExporter:
    # conftest 默认设置 OTEL_SDK_DISABLED=true（防止测试向 Collector 发数据），
    # 但 SDK 会因此创建 no-op TracerProvider；本文件需要真实导出到内存 exporter。
    previous = os.environ.pop("OTEL_SDK_DISABLED", None)
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    provider.shutdown()
    if previous is not None:
        os.environ["OTEL_SDK_DISABLED"] = previous


def _session(supervisor: Any = None) -> UserSession:
    return UserSession(
        context=RunContext(
            user_id="USR-001",
            username="zhang_wei",
            display_name="张伟",
            role="employee",
            department_id="DEPT-001",
        ),
        thread_id="thread-1",
        supervisor=supervisor,
    )


def _application() -> MultiAgentApplication:
    # 绕过 __init__：这里只测包装层，不需要构造模型和三个 Agent。
    return object.__new__(MultiAgentApplication)


def test_annotate_current_span_adds_langfuse_attrs(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    from personal_assistant.telemetry import annotate_current_span

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("http.test"):
        annotate_current_span(
            thread_id="thread-1",
            role="employee",
            user_id_hash="abc123def456",
        )

    span = next(
        span for span in exporter.get_finished_spans() if span.name == "http.test"
    )
    attributes = span.attributes or {}
    assert attributes["langfuse.session.id"] == "thread-1"
    assert attributes["langfuse.user.id"] == "abc123def456"
    assert tuple(attributes["langfuse.trace.tags"]) == (
        "employee-agent",
        "employee",
    )


def test_stream_chat_creates_turn_span(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    app = _application()

    async def fake_stream(session: UserSession, user_text: str) -> Any:
        yield {"event": "text_delta", "data": {"text": "你好"}}
        yield {"event": "confirmation", "data": {"message": "请确认"}}

    app._stream_chat_impl = fake_stream  # type: ignore[method-assign]

    async def run() -> list[dict[str, Any]]:
        return [
            event
            async for event in app.stream_chat(
                _session(), "你好", request_id="req-12345678"
            )
        ]

    events = asyncio.run(run())

    assert len(events) == 2
    spans = exporter.get_finished_spans()
    turn = next(span for span in spans if span.name == "agent.turn")
    attributes = turn.attributes or {}

    assert attributes["thread_id"] == "thread-1"
    assert attributes["request_id"] == "req-12345678"
    assert attributes["agent.kind"] == "chat"
    assert attributes["outcome"] == "waiting_confirmation"
    assert attributes["langfuse.session.id"] == "thread-1"
    assert attributes["langfuse.user.id"] != "USR-001"


def test_stream_chat_does_not_swallow_exception(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()
    app = _application()

    async def failing_stream(session: UserSession, user_text: str) -> Any:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    app._stream_chat_impl = failing_stream  # type: ignore[method-assign]

    async def run() -> None:
        async for _ in app.stream_chat(_session(), "hi"):
            pass

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run())

    turn = next(
        span for span in exporter.get_finished_spans() if span.name == "agent.turn"
    )
    assert (turn.attributes or {})["outcome"] == "failed"


def test_chat_returns_result_and_creates_turn_span(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()

    class FakeSupervisor:
        async def ainvoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"messages": []}

    app = _application()
    session = _session(supervisor=FakeSupervisor())

    result = asyncio.run(app.chat(session, "你好", request_id="req-chat-12345678"))

    assert result == {"messages": []}
    turn = next(
        span for span in exporter.get_finished_spans() if span.name == "agent.turn"
    )
    attributes = turn.attributes or {}
    assert attributes["request_id"] == "req-chat-12345678"
    assert attributes["agent.kind"] == "chat"
    assert attributes["outcome"] == "completed"


def test_resume_creates_independent_turn_span(
    exporter: InMemorySpanExporter,
) -> None:
    exporter.clear()

    class FakeSupervisor:
        async def ainvoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"messages": []}

    app = _application()
    session = _session(supervisor=FakeSupervisor())

    result = asyncio.run(app.resume(session, approved=True, request_id="req-87654321"))

    assert result == {"messages": []}
    turn = next(
        span for span in exporter.get_finished_spans() if span.name == "agent.turn"
    )
    attributes = turn.attributes or {}
    assert attributes["request_id"] == "req-87654321"
    assert attributes["agent.kind"] == "resume"
    assert attributes["outcome"] == "completed"
