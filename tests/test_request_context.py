"""请求级业务上下文的单元测试（不依赖数据库 / 模型 / 网络）。"""

from personal_assistant.request_context import (
    RequestContext,
    bind_request_context,
    config_metadata,
    current_request_context,
    hash_user_id,
    new_request_id,
    new_run_id,
    reset_request_context,
)


def test_request_id_accepts_valid_external_id() -> None:
    assert new_request_id("abc-123_XYZ") == "abc-123_XYZ"


def test_request_id_rejects_short_and_control_characters() -> None:
    assert new_request_id("short").startswith("req-")
    assert new_request_id("bad\nid").startswith("req-")
    assert new_request_id("bad id with spaces").startswith("req-")
    assert new_request_id(None).startswith("req-")


def test_run_id_is_unique_and_prefixed() -> None:
    first = new_run_id()
    second = new_run_id()
    assert first.startswith("run-")
    assert first != second


def test_hash_user_id_is_stable_and_short() -> None:
    assert hash_user_id("USR-001") == hash_user_id("USR-001")
    assert len(hash_user_id("USR-001")) == 12
    assert hash_user_id("USR-001") != hash_user_id("USR-002")


def test_bind_and_reset_context() -> None:
    ctx = RequestContext(
        thread_id="thread-1",
        request_id="req-12345678",
        run_id="run-1",
        role="employee",
        user_id_hash="abc123def456",
    )
    token = bind_request_context(ctx)
    try:
        assert current_request_context() == ctx
        assert config_metadata(ctx) == {
            "thread_id": "thread-1",
            "request_id": "req-12345678",
            "run_id": "run-1",
            "role": "employee",
            "user_id_hash": "abc123def456",
        }
    finally:
        reset_request_context(token)

    assert current_request_context() is None
