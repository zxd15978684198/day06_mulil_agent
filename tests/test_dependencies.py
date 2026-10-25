"""鉴权依赖的单元测试：用假 Session 代替 MySQL。"""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException

from personal_assistant import dependencies
from personal_assistant.dependencies import CurrentUser


class _FakeSession:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def scalar(self, _statement: object) -> object | None:
        return self._value


def _user(**overrides: object) -> object:
    values = {
        "user_id": "USR-001",
        "username": "zhang_wei",
        "display_name": "张伟",
        "role": "employee",
        "department_id": "DEPT-001",
        "login_enabled": True,
        "account_status": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_get_current_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies, "decode_access_token", lambda token: "USR-001")
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: _FakeSession(_user()))

    current = dependencies.get_current_user("any-token")

    assert current == CurrentUser(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
    )


def test_get_current_user_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(_token: str) -> str:
        raise jwt.InvalidTokenError("bad")

    monkeypatch.setattr(dependencies, "decode_access_token", _raise)

    with pytest.raises(HTTPException) as exc:
        dependencies.get_current_user("bad-token")

    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"login_enabled": False},
        {"account_status": "disabled"},
        {"username": None},
        {"role": "guest"},
    ],
)
def test_get_current_user_rejects_inactive_or_invalid_account(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    monkeypatch.setattr(dependencies, "decode_access_token", lambda token: "USR-001")
    monkeypatch.setattr(
        dependencies, "SessionLocal", lambda: _FakeSession(_user(**overrides))
    )

    with pytest.raises(HTTPException) as exc:
        dependencies.get_current_user("token")

    assert exc.value.status_code == 401


def test_get_owned_runtime_session_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = object()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                agent=SimpleNamespace(
                    supervisors={"employee": supervisor},
                )
            )
        )
    )
    monkeypatch.setattr(
        dependencies,
        "SessionLocal",
        lambda: _FakeSession(SimpleNamespace(thread_id="T-001")),
    )
    current = CurrentUser(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
    )

    session = dependencies.get_owned_runtime_session(request, "T-001", current)

    assert session.thread_id == "T-001"
    assert session.supervisor is supervisor
    assert session.context.user_id == "USR-001"


def test_get_owned_runtime_session_rejects_unknown_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(agent=SimpleNamespace()))
    )
    monkeypatch.setattr(dependencies, "SessionLocal", lambda: _FakeSession(None))
    current = CurrentUser(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
    )

    with pytest.raises(HTTPException) as exc:
        dependencies.get_owned_runtime_session(request, "missing", current)

    assert exc.value.status_code == 404
