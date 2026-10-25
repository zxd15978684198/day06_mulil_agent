"""结构化 JSON 日志：只写 stdout，不写文件、不走 OTel Logs SDK。

采集链路（见 `docs/plans/可观测性升级计划.md`）：

    应用 stdout JSON ──► Grafana Alloy ──► Loki

设计约束：

* **不依赖 LoggingInstrumentor**：`%(message)s` 会把注入的 LogRecord 属性丢掉；
  这里在 `log_event()` 里主动读取当前 Span，把 `trace_id/span_id` 写进 JSON；
* **白名单**：调用方只允许传固定字段，未知字段丢弃并记 `attrs_dropped`；
* **不记录原文**：用户消息、Prompt、回答、检索片段、工具入参都不在允许列表里；
* **观测失败不影响业务**：序列化/写日志异常只降级到 debug，不向调用方抛出。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

from personal_assistant import __version__
from personal_assistant.request_context import current_request_context
from personal_assistant.telemetry import current_trace_ids

logger = logging.getLogger("agent.events")
_configured = False

# 只允许低敏感、低基数的字段；不要在这里加 message / prompt / answer / args。
_ALLOWED_ATTRS = frozenset(
    {
        "agent",
        "agent_kind",
        "action",
        "approved",
        "count",
        "duration_ms",
        "error_message_safe",
        "error_type",
        "hit_count",
        "model",
        "role",
        "status_code",
        "timeout_seconds",
        "token_usage_available",
        "tool",
        "tool_risk",
    }
)


def configure_logging() -> None:
    """配置 `agent.events`：stdout、纯 JSON、不向 root 传播。"""

    global _configured
    if _configured:
        return
    _configured = True

    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def _service_name() -> str:
    return (os.getenv("OTEL_SERVICE_NAME") or "employee-agent").strip()


def _environment() -> str:
    return (os.getenv("DEPLOYMENT_ENV") or "development").strip()


def safe_error(exc: BaseException) -> dict[str, str]:
    """只返回类型名和截断后的消息；完整堆栈留给 stderr/日志代理。"""

    message = " ".join(str(exc).split())[:200]
    return {
        "error_type": type(exc).__name__,
        "error_message_safe": message,
    }


def runtime_request_ids(runtime: Any) -> dict[str, str]:
    """从 ToolRuntime.config 或 contextvars 取三个业务 ID。

    同步 Tool 可能在线程池里执行，contextvars 不保证保留；LangGraph 的
    `config["metadata"]` 是更可靠的来源。两者都没有时返回空串。
    """

    config = getattr(runtime, "config", None)
    metadata = config.get("metadata") if isinstance(config, dict) else None
    if isinstance(metadata, dict) and metadata.get("thread_id"):
        return {
            "thread_id": str(metadata.get("thread_id", "")),
            "request_id": str(metadata.get("request_id", "")),
            "run_id": str(metadata.get("run_id", "")),
        }

    ctx = current_request_context()
    if ctx is not None:
        return {
            "thread_id": ctx.thread_id,
            "request_id": ctx.request_id,
            "run_id": ctx.run_id,
        }

    return {"thread_id": "", "request_id": "", "run_id": ""}


def log_event(
    event: str,
    *,
    thread_id: str,
    request_id: str,
    run_id: str,
    outcome: str | None = None,
    **attrs: object,
) -> None:
    """写一行 JSON。字段过滤后，未知字段只记数量，不写内容。"""

    trace_id, span_id = current_trace_ids()
    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": "INFO",
        "service": _service_name(),
        "service_version": __version__,
        "env": _environment(),
        "event": event,
        "thread_id": thread_id,
        "request_id": request_id,
        "run_id": run_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "outcome": outcome,
    }

    dropped = 0
    for key, value in attrs.items():
        if key in _ALLOWED_ATTRS:
            payload[key] = value
        else:
            dropped += 1
    if dropped:
        payload["attrs_dropped"] = dropped

    try:
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 —— 观测失败不能影响业务
        logging.getLogger(__name__).debug("log_event 写入失败", exc_info=True)
