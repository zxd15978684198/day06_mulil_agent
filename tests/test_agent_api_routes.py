"""agent_api 的 lifespan、线程列表/创建和错误分支。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from personal_assistant import agent_api as api
from personal_assistant.dependencies import CurrentUser


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.rows = rows or []
        self.added: list[object] = []

    def __enter__(self) -> _FakeDb:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def scalars(self, _statement: object) -> _Rows:
        return _Rows(self.rows)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None


class _Factory:
    def __init__(self, db: _FakeDb) -> None:
        self._db = db

    def __call__(self) -> _FakeDb:
        return self._db

    def begin(self) -> _FakeDb:
        return self._db


class _AsyncCtx:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> bool:
        return False


def _current_user() -> CurrentUser:
    return CurrentUser(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
    )


def _request(agent: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                agent=agent,
                sessions={},
                active_streams=set(),
            )
        ),
        headers={},
        is_disconnected=_never_disconnected,
    )


async def _never_disconnected() -> bool:
    return False


def test_lifespan_initializes_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    manifest = tmp_path / "index_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    disposed: list[bool] = []
    shutdown: list[bool] = []

    monkeypatch.setattr(api, "ensure_writable_tempdir", lambda: None)
    monkeypatch.setattr(api, "_warm_up_vector_store_in_background", lambda: None)
    monkeypatch.setattr(api, "INDEX_MANIFEST_PATH", manifest)
    monkeypatch.setattr(api, "checkpoint_path", lambda: tmp_path / "checkpoint.sqlite3")
    monkeypatch.setattr(
        api.AsyncSqliteSaver,
        "from_conn_string",
        lambda *_args, **_kwargs: _AsyncCtx(),
    )
    monkeypatch.setattr(
        api,
        "MultiAgentApplication",
        lambda checkpointer: SimpleNamespace(checkpointer=checkpointer),
    )
    monkeypatch.setattr(
        api,
        "engine",
        SimpleNamespace(dispose=lambda: disposed.append(True)),
    )
    monkeypatch.setattr(api, "shutdown_telemetry", lambda: shutdown.append(True))
    monkeypatch.setattr(
        api.threading,
        "Thread",
        lambda *args, **kwargs: SimpleNamespace(start=lambda: None),
    )

    app = SimpleNamespace(state=SimpleNamespace())

    async def run() -> None:
        async with api.lifespan(app):
            assert app.state.agent is not None
            assert app.state.sessions == {}
            assert app.state.active_streams == set()

    asyncio.run(run())

    assert disposed == [True]
    assert shutdown == [True]
    assert app.state.sessions == {}


def test_list_sessions_and_create_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    created = datetime.now(UTC)
    db = _FakeDb([SimpleNamespace(thread_id="T-1", created_at=created)])
    monkeypatch.setattr(api, "SessionLocal", _Factory(db))

    threads = api.list_sessions(_current_user())

    assert threads[0].thread_id == "T-1"

    monkeypatch.setattr(
        api,
        "AgentThread",
        lambda **kwargs: SimpleNamespace(
            thread_id=kwargs["thread_id"], created_at=created
        ),
    )
    response = api.create_thread(_current_user())
    assert response.thread_id
    assert db.added


def test_index_route_returns_static_file() -> None:
    response = asyncio.run(api.index())
    assert isinstance(response, FileResponse)


def test_stream_chat_rejects_pending_confirmation() -> None:
    class _Agent:
        async def has_pending_confirmation(self, session: object) -> bool:
            return True

    session = SimpleNamespace(
        thread_id="T-1",
        context=SimpleNamespace(role="employee", user_id="USR-001"),
    )
    payload = SimpleNamespace(message="hello")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.stream_chat(payload, _request(_Agent()), session))  # type: ignore[arg-type]
    assert exc.value.status_code == 409


def test_stream_agent_events_disconnect_timeout_and_failure() -> None:
    class _DisconnectAgent:
        async def stream_chat(self, *args: object, **kwargs: object):
            yield {"event": "text_delta", "data": {"text": "hi"}}

    async def disconnected() -> bool:
        return True

    request = _request(_DisconnectAgent())
    request.is_disconnected = disconnected
    session = SimpleNamespace(thread_id="T-1")
    payload = SimpleNamespace(message="hello")

    async def run_disconnect() -> list[str]:
        return [
            item
            async for item in api.stream_agent_events(request, session, payload)  # type: ignore[arg-type]
        ]

    events = asyncio.run(run_disconnect())
    assert any("event:status" in item for item in events)
    assert not any("event:done" in item for item in events)

    class _TimeoutAgent:
        async def stream_chat(self, *args: object, **kwargs: object):
            raise TimeoutError
            yield  # pragma: no cover

        async def has_pending_confirmation(self, session: object) -> bool:
            return False

    timeout_events = asyncio.run(
        _collect(api.stream_agent_events(_request(_TimeoutAgent()), session, payload))  # type: ignore[arg-type]
    )
    assert any("event:error" in item for item in timeout_events)

    class _FailingAgent:
        async def stream_chat(self, *args: object, **kwargs: object):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            _collect(
                api.stream_agent_events(_request(_FailingAgent()), session, payload)
            )  # type: ignore[arg-type]
        )


async def _collect(iterator) -> list[str]:
    return [item async for item in iterator]


def test_confirmation_action_errors() -> None:
    class _NoPending:
        async def has_pending_confirmation(self, session: object) -> bool:
            return False

    session = SimpleNamespace(
        thread_id="T-1",
        context=SimpleNamespace(role="employee", user_id="USR-001"),
    )
    payload = SimpleNamespace(approved=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.confirmation_action(payload, _request(_NoPending()), session))  # type: ignore[arg-type]
    assert exc.value.status_code == 409

    class _Failing:
        async def has_pending_confirmation(self, session: object) -> bool:
            return True

        async def resume(self, *args: object, **kwargs: object) -> dict:
            raise RuntimeError("resume failed")

    with pytest.raises(HTTPException) as exc2:
        asyncio.run(api.confirmation_action(payload, _request(_Failing()), session))  # type: ignore[arg-type]
    assert exc2.value.status_code == 503
