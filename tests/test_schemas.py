"""请求/响应模型的校验测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from personal_assistant.schemas import (
    AgentReply,
    ChatRequest,
    ConfirmRequest,
    CurrentUserResponse,
    HistoryMessage,
    ThreadHistoryResponse,
    ThreadResponse,
    TokenResponse,
)


def test_chat_request_strips_and_validates_length() -> None:
    assert ChatRequest(message="  hello  ").message == "hello"

    with pytest.raises(ValidationError):
        ChatRequest(message="")
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 2001)


def test_confirm_request_requires_bool() -> None:
    assert ConfirmRequest(approved=True).approved is True
    with pytest.raises(ValidationError):
        ConfirmRequest(approved="maybe")  # type: ignore[arg-type]


def test_history_message_role_is_literal() -> None:
    assert HistoryMessage(role="user", content="hi").role == "user"
    assert HistoryMessage(role="assistant", content="hi").role == "assistant"
    with pytest.raises(ValidationError):
        HistoryMessage(role="tool", content="x")  # type: ignore[arg-type]


def test_reply_and_history_defaults_are_independent() -> None:
    first = AgentReply()
    second = AgentReply()
    first.trace.append({"type": "x"})
    assert second.trace == []

    history = ThreadHistoryResponse()
    assert history.messages == []
    assert history.needs_confirmation is False
    assert history.confirmation is None


def test_token_thread_and_user_models() -> None:
    assert TokenResponse(access_token="abc").token_type == "bearer"
    thread = ThreadResponse(thread_id="t-1", created_at=datetime.now(UTC))
    assert thread.thread_id == "t-1"
    user = CurrentUserResponse(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
    )
    assert user.role == "employee"
