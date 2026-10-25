"""multi_agent 的纯函数测试（不启动 Supervisor / 模型）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from personal_assistant.multi_agent import (
    _result_outcome,
    message_text,
    outer_trace,
    pending_confirmation_of,
    specialist_result,
)


def test_message_text_handles_string_and_content_blocks() -> None:
    assert message_text(AIMessage(content="hello")) == "hello"
    assert (
        message_text(
            AIMessage(
                content=[
                    {"type": "text", "text": "a"},
                    {"type": "image", "url": "x"},
                    {"type": "text", "text": "b"},
                ]
            )
        )
        == "ab"
    )


def test_specialist_result_only_returns_contract_fields() -> None:
    result = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_company_knowledge", "args": {}, "id": "1"}
                ],
            ),
            AIMessage(content="最终回答"),
        ]
    }

    payload = json.loads(specialist_result("knowledge_agent", result))

    assert payload["agent"] == "knowledge_agent"
    assert payload["answer"] == "最终回答"
    assert payload["business_tools"] == ["search_company_knowledge"]
    assert "messages" not in payload


def test_outer_trace_extracts_agent_tool_calls_and_results() -> None:
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "ask_knowledge_agent", "args": {"task": "x"}, "id": "1"}],
    )
    tool = ToolMessage(
        content='{"agent": "knowledge_agent"}',
        name="ask_knowledge_agent",
        tool_call_id="1",
    )

    trace = outer_trace({"messages": [HumanMessage(content="hi"), ai, tool]})

    assert trace[0]["type"] == "agent_tool_calls"
    assert trace[0]["calls"][0]["name"] == "ask_knowledge_agent"
    assert trace[1]["type"] == "agent_tool_result"
    assert trace[1]["name"] == "ask_knowledge_agent"


def test_pending_confirmation_of_reads_only_interrupts() -> None:
    assert pending_confirmation_of(SimpleNamespace(interrupts=[])) is None
    assert pending_confirmation_of(SimpleNamespace()) is None
    value = pending_confirmation_of(
        SimpleNamespace(interrupts=[SimpleNamespace(value={"action": "x"})])
    )
    assert value == {"action": "x"}
    wrapped = pending_confirmation_of(
        SimpleNamespace(interrupts=[SimpleNamespace(value="plain")])
    )
    assert wrapped == {"message": "plain"}


def test_result_outcome() -> None:
    assert _result_outcome({"__interrupt__": [object()]}) == "waiting_confirmation"
    rejected = ToolMessage(
        content=json.dumps({"ok": False, "error": "user_rejected"}),
        name="create_device_request",
        tool_call_id="1",
    )
    assert _result_outcome({"messages": [rejected]}) == "rejected"
    assert _result_outcome({"messages": [AIMessage(content="ok")]}) == "completed"
