"""请求级业务上下文：thread_id / request_id / run_id / role / user_id_hash。

为什么单独一个模块：
    Trace、日志、指标都要带同一组业务 ID，但它们分属不同层（FastAPI 路由、
    LangGraph 节点、同步业务 Tool）。把这些 ID 放进一个 frozen dataclass，
    再用 contextvars 传递，避免每个函数都加三个参数；同时不把 request_id
    塞进 `RunContext` —— 后者是登录身份，生命周期是会话级，不是请求级。

注意：
    * `request_id` 来自外部 header 时必须严格校验，不能被换行/控制字符污染日志；
    * `user_id_hash` 只用于 Langfuse/日志关联，不导出 username / display_name。
"""

from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import uuid4

# 只允许常见的请求 ID 字符，长度 8–64；不匹配就本地生成，不报错、不影响业务。
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_current: ContextVar[RequestContext | None] = ContextVar(
    "personal_assistant_request_context", default=None
)


@dataclass(frozen=True)
class RequestContext:
    """一次 HTTP 请求 / 一轮 Agent 执行的可信业务标识。"""

    thread_id: str
    request_id: str
    run_id: str
    role: str
    user_id_hash: str


def new_request_id(header_value: str | None = None) -> str:
    """接受合法的上游 request id；否则生成 `req-<uuid>`。"""

    if header_value is not None:
        candidate = header_value.strip()
        if _REQUEST_ID_RE.fullmatch(candidate):
            return candidate
    return f"req-{uuid4().hex}"


def new_run_id() -> str:
    """一轮 Agent 执行（一次 stream_chat / resume / CLI 回合）的 ID。"""

    return f"run-{uuid4().hex}"


def hash_user_id(user_id: str) -> str:
    """只导出哈希前缀，避免用户名/姓名进入 Trace 和日志。"""

    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


def bind_request_context(ctx: RequestContext) -> Token[RequestContext | None]:
    """绑定当前上下文；调用方必须在 finally 里 reset。"""

    return _current.set(ctx)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _current.reset(token)


def current_request_context() -> RequestContext | None:
    return _current.get()


def config_metadata(ctx: RequestContext) -> dict[str, str]:
    """放进 LangGraph `config["metadata"]`，供业务 Tool 侧读取。

    LangGraph 可能在线程池里执行同步 Tool，contextvars 不保证跨线程保留；
    `ToolRuntime.config` 是更可靠的兜底来源。
    """

    return {
        "thread_id": ctx.thread_id,
        "request_id": ctx.request_id,
        "run_id": ctx.run_id,
        "role": ctx.role,
        "user_id_hash": ctx.user_id_hash,
    }
