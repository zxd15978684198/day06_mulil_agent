"""结构化日志契约：JSON、白名单、trace 关联、安全错误。"""

from __future__ import annotations

import io
import json
import logging

from personal_assistant import structured_logging as sl
from personal_assistant.structured_logging import (
    log_event,
    runtime_request_ids,
    safe_error,
)


class _FakeRuntime:
    def __init__(self, metadata: dict[str, str]) -> None:
        self.config = {"metadata": metadata}


def test_log_event_is_json_and_filters_unknown_attrs() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    sl.logger.addHandler(handler)
    try:
        log_event(
            "agent.finished",
            thread_id="thread-1",
            request_id="req-12345678",
            run_id="run-1",
            outcome="completed",
            duration_ms=12.3,
            tool="search_company_knowledge",
            # 下面两个都不在白名单里：一个敏感、一个未知。
            prompt="SENSITIVE-PROMPT",
            arbitrary="drop-me",
        )
    finally:
        sl.logger.removeHandler(handler)

    line = stream.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)

    assert payload["event"] == "agent.finished"
    assert payload["thread_id"] == "thread-1"
    assert payload["tool"] == "search_company_knowledge"
    assert payload["duration_ms"] == 12.3
    assert payload["attrs_dropped"] == 2
    assert "prompt" not in payload
    assert "SENSITIVE-PROMPT" not in line


def test_safe_error_strips_newlines_and_truncates() -> None:
    result = safe_error(ValueError("line1\nline2 " + "x" * 500))

    assert result["error_type"] == "ValueError"
    assert "\n" not in result["error_message_safe"]
    assert len(result["error_message_safe"]) <= 200


def test_runtime_request_ids_prefers_config_metadata() -> None:
    runtime = _FakeRuntime(
        {
            "thread_id": "thread-1",
            "request_id": "req-12345678",
            "run_id": "run-1",
        }
    )

    assert runtime_request_ids(runtime) == {
        "thread_id": "thread-1",
        "request_id": "req-12345678",
        "run_id": "run-1",
    }


def test_runtime_request_ids_without_metadata_returns_empty() -> None:
    assert runtime_request_ids(object()) == {
        "thread_id": "",
        "request_id": "",
        "run_id": "",
    }
