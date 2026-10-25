"""agent_api 的纯函数/路由测试：用假 agent 代替 MySQL 和模型。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage

from personal_assistant import agent_api as api
from personal_assistant.dependencies import CurrentUser


class _FakeSession:
    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _request(
    *,
    agent: object | None = None,
    sessions: dict[str, object] | None = None,
    active_streams: set[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                agent=agent,
                sessions=sessions or {},
                active_streams=active_streams if active_streams is not None else set(),
            )
        ),
        headers={},
        is_disconnected=_never_disconnected,
    )


async def _never_disconnected() -> bool:
    return False


def _session(thread_id: str = "T-1") -> SimpleNamespace:
    return SimpleNamespace(
        thread_id=thread_id,
        context=SimpleNamespace(role="employee", user_id="USR-001"),
    )


def test_sse_event_format() -> None:
    text = api.sse_event("text_delta", {"text": "你好"}, event_id="1", retry_ms=3000)

    assert "id:1" in text
    assert "event:text_delta" in text
    assert "retry:3000" in text
    assert 'data:{"text": "你好"}' in text


def test_format_agent_result_answer_and_interrupt() -> None:
    normal = api.format_agent_result(
        None,  # type: ignore[arg-type]
        "T-1",
        {"messages": [AIMessage(content="最终回答")]},
    )
    assert normal.answer == "最终回答"
    assert normal.needs_confirmation is False

    paused = api.format_agent_result(
        None,  # type: ignore[arg-type]
        "T-1",
        {"__interrupt__": [SimpleNamespace(value={"action": "create"})]},
    )
    assert paused.answer is None
    assert paused.needs_confirmation is True
    assert paused.confirmation == {"action": "create"}


def test_get_session_or_404() -> None:
    existing = object()
    request = _request(sessions={"T-1": existing})

    assert api.get_session_or_404(request, "T-1") is existing

    with pytest.raises(HTTPException) as exc:
        api.get_session_or_404(request, "missing")
    assert exc.value.status_code == 404


def test_login_for_access_token_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(user_id="USR-001")
    monkeypatch.setattr(api, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(api, "authenticate_user", lambda db, username, password: user)

    response = api.login_for_access_token(
        SimpleNamespace(username="zhang_wei", password="123456")
    )

    assert response.token_type == "bearer"
    assert response.access_token

    monkeypatch.setattr(api, "authenticate_user", lambda db, username, password: None)
    with pytest.raises(HTTPException) as exc:
        api.login_for_access_token(
            SimpleNamespace(username="zhang_wei", password="wrong")
        )
    assert exc.value.status_code == 401


def test_read_current_user() -> None:
    current = CurrentUser(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
    )
    response = api.read_current_user(current)
    assert response.user_id == "USR-001"


def test_list_thread_messages() -> None:
    class _Agent:
        async def get_thread_history(self, session: object) -> tuple[list, None]:
            return [{"role": "user", "content": "hi"}], None

    request = _request(agent=_Agent())
    session = SimpleNamespace(thread_id="T-1")

    response = asyncio.run(api.list_thread_messages(request, session))  # type: ignore[arg-type]

    assert response.messages[0].content == "hi"
    assert response.needs_confirmation is False


def test_stream_agent_events_normal_and_disconnect() -> None:
    class _Agent:
        async def stream_chat(
            self, session: object, message: str, request_id: str | None = None
        ):
            yield {"event": "text_delta", "data": {"text": "hi"}}

        async def has_pending_confirmation(self, session: object) -> bool:
            return False

    request = _request(agent=_Agent())
    session = _session()
    payload = SimpleNamespace(message="hello")

    async def run() -> list[str]:
        return [
            event
            async for event in api.stream_agent_events(request, session, payload)  # type: ignore[arg-type]
        ]

    events = asyncio.run(run())

    assert any("event:status" in event for event in events)
    assert any("event:text_delta" in event for event in events)
    assert any("event:done" in event for event in events)


def test_stream_chat_route_conflicts_and_success() -> None:
    class _Agent:
        async def has_pending_confirmation(self, session: object) -> bool:
            return False

    session = _session()
    payload = SimpleNamespace(message="hello")

    busy = _request(agent=_Agent(), active_streams={"T-1"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.stream_chat(payload, busy, session))  # type: ignore[arg-type]
    assert exc.value.status_code == 409

    request = _request(agent=_Agent())
    response = asyncio.run(api.stream_chat(payload, request, session))  # type: ignore[arg-type]
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"


def test_confirmation_action_success() -> None:
    class _Agent:
        async def has_pending_confirmation(self, session: object) -> bool:
            return True

        async def resume(
            self,
            session: object,
            approved: bool,
            request_id: str | None = None,
        ) -> dict:
            return {"messages": [AIMessage(content="已处理")]}

    request = _request(agent=_Agent())
    session = _session()
    payload = SimpleNamespace(approved=True)

    response = asyncio.run(
        api.confirmation_action(payload, request, session)  # type: ignore[arg-type]
    )

    assert response.answer == "已处理"
    assert response.needs_confirmation is False
