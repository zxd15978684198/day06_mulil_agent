"""CLI 入口的纯函数/流程测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from personal_assistant import main as cli


def test_ask_returns_none_on_eof(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    assert cli.ask("你：") is None
    assert "输入结束" in capsys.readouterr().out


def test_print_result_prints_answer_and_trace(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "ask_knowledge_agent", "args": {}, "id": "1"}],
            ),
            ToolMessage(
                content='{"business_tools": ["search_company_knowledge"]}',
                name="ask_knowledge_agent",
                tool_call_id="1",
            ),
            AIMessage(content="最终回答"),
        ]
    }

    cli.print_result(result)

    output = capsys.readouterr().out
    assert "最终回答" in output
    assert "ask_knowledge_agent" in output
    assert "search_company_knowledge" in output


def test_handle_interrupts_reuses_session_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _App:
        def __init__(self) -> None:
            self.calls: list[tuple[object, bool]] = []

        async def resume(self, session: object, *, approved: bool) -> dict:
            self.calls.append((session, approved))
            return {"messages": [AIMessage(content="done")]}

    app = _App()
    session = SimpleNamespace(thread_id="T-1")
    result = {"__interrupt__": [SimpleNamespace(value={"action": "create"})]}
    monkeypatch.setattr(cli, "ask", lambda prompt: "n")

    resumed = asyncio.run(cli.handle_interrupts(app, session, result))

    assert app.calls == [(session, False)]
    assert resumed["messages"][-1].content == "done"
