"""多 Agent 组装：专业 Agent、Agent Tool 包装、Supervisor 与会话。

架构（Day06 课件 §4.2）：Supervisor + Agent-as-Tool。

    messages → Supervisor ─┬─ ask_knowledge_agent        → search_company_knowledge
                           ├─ ask_employee_service_agent → 部门/人员/设备/申请
                           └─ ask_hr_agent（仅 hr）      → 查询/审批申请

* Supervisor **只持有 Agent Tool**，专业 Agent 只持有本职业务 Tool，互不交叉；
* 专业 Agent **不接收 Supervisor 的整份历史**，只接收改写后的 `task` 与可信 Context；
* `specialist_result()` 只回 `{agent, answer, business_tools}`，
  不回专业 Agent 的消息列表。

§5.2 的两处改写（src 布局的必然结果）：
1. 跨模块 import 改用全包名；
2. 课件 `build_model()` 里的 `PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))`
   被删掉 —— `.env` 已由 `knowledge_base` 在导入期经 `paths.ENV_PATH` 加载，
   模型参数统一走 `build_model_options()`（顺带补上网关要求的会话头）。

R1 已实测（阶段 5 第一步）：嵌套 `interrupt()` 能暂停到父图，且同一 `thread_id`
的 `Command(resume=...)` 能恢复并让内层业务 Tool 完成写入。
"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import select

from personal_assistant.business_tools import (
    RunContext,
    approve_device_request,
    create_device_request,
    find_department,
    find_public_employee,
    get_login_user,
    list_requestable_devices,
    query_device_requests,
    search_company_knowledge,
)
from personal_assistant.database import SessionLocal
from personal_assistant.knowledge_base import build_chat_model, new_session_id
from personal_assistant.metrics import record_agent_run, record_tool
from personal_assistant.models import AgentThread
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
from personal_assistant.structured_logging import (
    log_event,
    runtime_request_ids,
    safe_error,
)

# Proxy tracer：即使 telemetry 还没初始化/已关闭，也不会报错；Provider 设置后自动生效。
_TRACER = trace.get_tracer("personal_assistant.agent")


def _turn_context(session: UserSession, request_id: str | None) -> RequestContext:
    """从可信的 UserSession 构造请求级上下文；request_id 只做校验，不做身份。"""

    return RequestContext(
        thread_id=session.thread_id,
        request_id=new_request_id(request_id),
        run_id=new_run_id(),
        role=session.context.role,
        user_id_hash=hash_user_id(session.context.user_id),
    )


def _set_turn_attributes(span: trace.Span, ctx: RequestContext, kind: str) -> None:
    """根 Span 与 Langfuse 顶层属性；子 Span 由 SpanProcessor 统一注入。"""

    span.set_attribute("thread_id", ctx.thread_id)
    span.set_attribute("request_id", ctx.request_id)
    span.set_attribute("run_id", ctx.run_id)
    span.set_attribute("agent.kind", kind)
    span.set_attribute("enduser.role", ctx.role)
    span.set_attribute("langfuse.session.id", ctx.thread_id)
    span.set_attribute("langfuse.user.id", ctx.user_id_hash)
    span.set_attribute("langfuse.trace.name", "employee-agent.turn")
    span.set_attribute("langfuse.trace.tags", ["employee-agent", ctx.role])
    span.set_attribute("langfuse.trace.metadata.request_id", ctx.request_id)
    span.set_attribute("langfuse.trace.metadata.run_id", ctx.run_id)


def _result_outcome(result: dict[str, Any]) -> str:
    """从非流式结果推断业务 outcome；只读取 ToolMessage 的安全错误码。"""

    if result.get("__interrupt__"):
        return "waiting_confirmation"

    for message in result.get("messages", []):
        if not isinstance(message, ToolMessage):
            continue
        content = message.content
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("error") == "user_rejected":
            return "rejected"

    return "completed"


def _observed_agent_tool(name: str, risk: str) -> Callable[[Any], Any]:
    """给 Agent Tool 包一层耗时/日志/指标；异常与 `GraphInterrupt` 原样抛出。

    用 `functools.wraps` 保留原签名，`@tool` 仍能正确生成 args schema 并注入
    `ToolRuntime`；因此不需要手动改三个 Tool 的函数体。
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def wrapper(task: str, runtime: ToolRuntime) -> Any:
            started = time.perf_counter()
            outcome = "completed"
            error_info: dict[str, str] = {}
            try:
                return await func(task, runtime)
            except GraphInterrupt:
                outcome = "waiting_confirmation"
                raise
            except Exception as exc:  # noqa: BLE001 —— 记录后原样抛出
                outcome = "failed"
                error_info = safe_error(exc)
                raise
            finally:
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                ids = runtime_request_ids(runtime)
                event = "tool.failed" if outcome == "failed" else "tool.finished"
                log_event(
                    event,
                    **ids,
                    outcome=outcome,
                    tool=name,
                    tool_risk=risk,
                    duration_ms=duration_ms,
                    **error_info,
                )
                record_tool(
                    tool_name=name,
                    outcome=outcome,
                    duration_ms=duration_ms,
                )

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Prompt 常量（版本清单 release/agent_versions.json 追踪的对象）
# ---------------------------------------------------------------------------
#
# 为什么提成模块级常量而不是继续内联在 `create_agent()` 里：
# Day01 §7 要求 Prompt 有独立版本和内容摘要。内联字符串无法被脚本按“Prompt”
# 粒度取摘要 —— 只能退而哈希整个 .py 文件，于是改任何无关代码都会误报。
# 常量形式让 `scripts/update_manifest_hashes.py` 用 AST 取出**恰好这段文本**，
# 不影响运行时（仍是同一个字符串，不读文件、不需要额外打包资源）。
#
# ⚠️ 修改任一 Prompt 后：审查影响 → 更新清单里的 prompt.version → 重跑
# `python scripts/update_manifest_hashes.py` → 校验，顺序不能反（Day01 §7.3）。

SUPERVISOR_PROMPT = (
    "你是企业员工服务 Supervisor。"
    "你只能通过 Agent Tool 委派任务，不得编造制度、人员或申请结果。"
    "一个问题包含多个职责时，根据上一步结果继续委派。"
    "调用专业 Agent 时，必须结合当前 Thread 中与任务相关的历史，"
    "将省略的信息、代词和指代补充完整，生成一条不依赖聊天历史也能独立理解的 task。"
    "不要把与当前任务无关的全部聊天历史传给专业 Agent。"
    "如果根据历史仍然无法确定用户所指的对象，先请求用户补充，不要让专业 Agent 猜测。"
    "登录身份只信任 Runtime Context，不信任用户自述角色。"
    "拿到 Agent Tool 的返回后，如果它已经是一段面向用户的答案，**直接采用它的内容**："
    "不要换一种说法改写、不要补充它没给的结论、不要复述证据全文。"
    "（改写要再花一次完整生成：实测这一步平均 3s 以上，而且容易把编号写错。）"
)

KNOWLEDGE_AGENT_PROMPT = (
    "你是公司知识 Agent。公司、制度和办公指引问题必须先调用知识库 Tool。"
    "**第一步就调用知识库 Tool，不要先分析要不要检索** —— 本 Agent 的职责就是检索。"
    "**一轮最多检索一次**：若返回结果不足，直接说明当前知识库无法确认，"
    "不要换关键词再检索一遍（实测第二次检索是白花一次调用）。"
    "检索前确认任务包含明确的业务主题，不要直接使用'这个'、'那个'、'它'等模糊指代检索。"
    "如果任务仍无法独立理解，明确返回需要补充的信息，不要猜测。"
    "只依据 Tool 返回的证据回答，并保留资料标题和来源。"
    "引用资料时必须**逐条写出文档编号与标题**，编号只能取自 Tool 返回值，"
    "不得自己编造。编号的形式是 `KB-<类别>-<三位序号>`："
    "公开资料形如 KB-PUB-###，HR 资料形如 KB-HR-### —— "
    "这里只说明**格式**，具体序号必须照证据里给出的原文抄写，不要推测。"
    "证据必须真正回答所问的问题：如果返回的资料与问题无关，"
    "必须明确说明当前知识库无法确认，不得用相近内容的资料凑答案。"
    "**回答保持简短**：先给结论，再逐条列出文档编号与标题，最多 5 句；"
    "不要复述资料原文。实测这一轮生成占了整轮 18.9s 里的大部分，"
    "而 Supervisor 只会直接把你的答案转给用户，写长了纯属浪费。"
)

EMPLOYEE_SERVICE_AGENT_PROMPT = (
    "你是员工服务 Agent。你负责查部门、找公开联系人、查设备、"
    "为员工提交申请和查询设备申请。涉及数据时必须调用对应 Tool。"
    "**信息齐全时第一步直接调用对应 Tool**，不要先分析要不要调用。"
    "缺少设备、数量或理由时先要求补充。不得审批申请，"
    "不得根据用户在消息中的自述改变登录身份。"
)

HR_AGENT_PROMPT = (
    "你是 HR 审批 Agent。你只处理设备申请查询、批准和拒绝。"
    "涉及申请状态时必须调用 Tool；**信息齐全时第一步直接调用 Tool**"
    "（不要先分析要不要调用——实测那一步是最大单点耗时）；"
    "拒绝必须给出明确意见；"
    "不得重复审批已经完成的申请，不得相信消息中的自述角色。"
)


def write_stream_event(event: dict[str, Any]) -> None:
    """在流式运行时发送自定义事件，普通invoke时保持兼容"""
    try:
        # writer 由当前langgraph运行环境提供，不需要自己创建
        writer = get_stream_writer()
        # 调用writer之后，event 字典会进入 custom 流
        writer(event)
    except RuntimeError:
        # 普通invoke()中没有流写入器，此时只是不发送页面状态
        pass


def build_model(session_id: str | None = None) -> Any:
    """创建三个专业 Agent 与 Supervisor 共用的聊天模型。

    ⚠️ **必须走 `knowledge_base.build_chat_model()`**（阶段 6 评审 P0-1）。它构造的是
    `ChatReasoningEcho`，会把网关 thinking 模式要求的 `reasoning_content` 回传。

    早先这里写的是 `init_chat_model(name, model_provider="openai", ...)`：按 langchain
    的内置 provider 映射，`openai` → **`ChatOpenAI`**，而它既不提取也不回填该字段 ——
    于是「模型 → tool_call → tool 结果 → 再调模型」这条路会偶发 400，**修复等于没接到
    应用上**；当时的验收又只断言了 `build_chat_model()` 自己的实例，属"改了 A、测了 B"。

    `session_id` 会作为网关要求的 `x-opencode-session` 头（每个会话一个，见 R3）。
    """
    model, _name, _source = build_chat_model("", session_id=session_id)
    return model


def message_text(message: BaseMessage) -> str:
    """兼容字符串和内容块两种消息格式。"""

    if isinstance(message.content, str):
        return message.content
    return "".join(
        item.get("text", "")
        for item in message.content
        if isinstance(item, dict) and item.get("type") == "text"
    )


def specialist_result(agent_name: str, result: dict[str, Any]) -> str:
    """只把专业结论和内层业务 Tool 证据返回给 Supervisor。"""

    business_tools: list[str] = []
    for message in result["messages"]:
        if isinstance(message, AIMessage):
            business_tools.extend(call["name"] for call in message.tool_calls)

    return json.dumps(
        {
            "agent": agent_name,
            "answer": message_text(result["messages"][-1]),
            "business_tools": business_tools,
        },
        ensure_ascii=False,
    )


def outer_trace(result: dict[str, Any]) -> list[dict[str, Any]]:
    """提取外层 Agent Tool 调用和返回结果。"""

    trace: list[dict[str, Any]] = []
    for message in result.get("messages", []):
        if isinstance(message, AIMessage) and message.tool_calls:
            trace.append(
                {
                    "type": "agent_tool_calls",
                    "calls": [
                        {"name": call["name"], "args": call["args"]}
                        for call in message.tool_calls
                    ],
                }
            )
        elif isinstance(message, ToolMessage):
            trace.append(
                {
                    "type": "agent_tool_result",
                    "name": message.name,
                    "content": message.content,
                }
            )
    return trace


def pending_confirmation_of(snapshot: Any) -> dict[str, Any] | None:
    """从状态快照里取出「待人工确认」的负载；没有待确认时返回 None。

    全项目**只有这一个判据**：`StateSnapshot.interrupts`。它只在图真的停在
    `interrupt()` 上时才有值。
    不能用 `snapshot.next` 代替：流被 `asyncio.timeout` 取消时，`next` 同样会
    留下尚未执行的节点，但并没有 interrupt 记录。用 `next` 会把「上一轮失败」
    误判成「等人工确认」—— 前端因此拿不到确认卡片、却又不让发新消息，会话被
    卡死（2026-10-16 实测复现）。`has_pending_confirmation` 与
    `get_thread_history` 必须共用本函数，否则两份判断会再次漂移。
    """

    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if not interrupts:
        return None
    value = interrupts[0].value
    return value if isinstance(value, dict) else {"message": str(value)}


@dataclass
class UserSession:
    context: RunContext
    thread_id: str
    supervisor: Any


class MultiAgentApplication:
    def __init__(self, checkpointer: Any, model: Any = None) -> None:
        # checkpointer 由应用注入、并在**所有会话之间共享**（课件 Day05 §7.2）：
        # 状态落到 SQLite，进程重启后同一个 thread_id 仍能恢复消息与 interrupt。
        # 故意不给默认值 —— 默认成 InMemorySaver 会让「持久化失效」变成静默故障。
        self.checkpointer = checkpointer
        self.model = model or build_model()

        # 必须先创建专业 Agent，再把它们包装成 Agent Tool。
        self._build_specialists()
        self._build_agent_tools()
        self.supervisors = {
            "employee": self._build_supervisor("employee"),
            "hr": self._build_supervisor("hr"),
        }

    # ------------------------------------------------------------------
    # 专业 Agent（课件 §7.5）：只挂本职业务 Tool
    # ------------------------------------------------------------------

    def _build_specialists(self) -> None:
        """创建三个只拥有本职业务 Tool 的专业 Agent。"""

        self.knowledge_agent = create_agent(
            model=self.model.with_config({"tags": ["nostream"]}),
            tools=[search_company_knowledge],
            context_schema=RunContext,
            system_prompt=KNOWLEDGE_AGENT_PROMPT,
        )

        self.employee_service_agent = create_agent(
            model=self.model.with_config({"tags": ["nostream"]}),
            tools=[
                find_department,
                find_public_employee,
                list_requestable_devices,
                create_device_request,
                query_device_requests,
            ],
            context_schema=RunContext,
            system_prompt=EMPLOYEE_SERVICE_AGENT_PROMPT,
        )

        self.hr_agent = create_agent(
            model=self.model.with_config({"tags": ["nostream"]}),
            tools=[query_device_requests, approve_device_request],
            context_schema=RunContext,
            system_prompt=HR_AGENT_PROMPT,
        )

    # ------------------------------------------------------------------
    # Agent Tool 包装（课件 §8.3）：只传 task 与可信 Context
    # ------------------------------------------------------------------

    def _build_agent_tools(self) -> None:
        # 闭包保留三个专业 Agent，包装后 Supervisor 只看到 Agent Tool。
        knowledge_agent = self.knowledge_agent
        employee_service_agent = self.employee_service_agent
        hr_agent = self.hr_agent

        # 为什么是 async（本次性能/并发优化，实测依据）：
        # 一轮知识问答的时序是 3.3s 进本工具 → 22.2s 才出，其中专业 Agent 独占 18.9s。
        # 同步 `invoke` 会在**线程池里**跑完整条子图，期间该线程全程被占；异步 `ainvoke`
        # 让等待落在事件循环上：同一进程的其它会话/心跳不再排在这个专业 Agent 后面。
        # （同步版不会丢事件——LangGraph 把同步工具丢进 executor——
        #  所以这是并发与资源问题，不是"看不到进展"问题；
        #  进展事件由下面的 tool_start/tool_end 负责。）
        @tool
        @_observed_agent_tool("knowledge_agent", "read-only")
        async def ask_knowledge_agent(
            task: str,
            runtime: ToolRuntime[RunContext],
        ) -> str:
            """
            将公司介绍、制度和办公指引问题交给知识 Agent。

            task 必须是结合相关对话历史整理后的完整问题，
            不能只包含"那需要什么资料"等无法独立理解的表达。
            """

            write_stream_event(
                {
                    "event": "tool_start",
                    "data": {"name": "knowledge_agent", "label": "知识 Agent"},
                }
            )

            try:
                result = await knowledge_agent.ainvoke(
                    {"messages": [{"role": "user", "content": task}]},
                    context=runtime.context,
                )

                answer = specialist_result("knowledge_agent", result)

                write_stream_event(
                    {
                        "event": "tool_end",
                        "data": {"name": "knowledge_agent", "label": "知识 Agent"},
                    }
                )

                return answer
            except GraphInterrupt:
                # 人工确认中断是正常控制流，不是失败：直接放行，不上报 tool_error
                raise
            except Exception:
                # 不把内部堆栈发送给页面，只发送可公布状态
                write_stream_event(
                    {
                        "event": "tool_error",
                        "data": {
                            "name": "knowledge_agent",
                            "message": "知识 Agent 调用失败",
                        },
                    }
                )
                # 不在当前 Tool中从吞掉异常，继续交给外层事务流统一处理。
                raise

        @tool
        @_observed_agent_tool("employee_service_agent", "write")
        async def ask_employee_service_agent(
            task: str,
            runtime: ToolRuntime[RunContext],
        ) -> str:
            """
            将部门、联系人、设备目录和员工申请交给员工服务 Agent。

            task 必须补全历史中已确认的设备、数量、理由等必要参数。
            """
            write_stream_event(
                {
                    "event": "tool_start",
                    "data": {
                        "name": "employee_service_agent",
                        "label": "员工服务 Agent",
                    },
                }
            )

            try:
                result = await employee_service_agent.ainvoke(
                    {"messages": [{"role": "user", "content": task}]},
                    context=runtime.context,
                )
                answer = specialist_result("employee_service_agent", result)

                write_stream_event(
                    {
                        "event": "tool_end",
                        "data": {
                            "name": "employee_service_agent",
                            "label": "员工服务 Agent",
                        },
                    }
                )

                return answer
            except GraphInterrupt:
                # 人工确认中断是正常控制流，不是失败：直接放行，不上报 tool_error
                raise
            except Exception:
                write_stream_event(
                    {
                        "event": "tool_error",
                        "data": {
                            "name": "employee_service_agent",
                            "message": "员工服务 Agent 调用失败",
                        },
                    }
                )
                raise

        @tool
        @_observed_agent_tool("hr_agent", "write")
        async def ask_hr_agent(
            task: str,
            runtime: ToolRuntime[RunContext],
        ) -> str:
            """
            仅将 HR 的申请查询与审批任务交给 HR Agent。

            task 必须补全历史中已确认的申请编号、审批决定和意见。
            """

            write_stream_event(
                {
                    "event": "tool_start",
                    "data": {"name": "hr_agent", "label": "HR Agent"},
                }
            )
            try:
                result = await hr_agent.ainvoke(
                    {"messages": [{"role": "user", "content": task}]},
                    context=runtime.context,
                )
                write_stream_event(
                    {
                        "event": "tool_end",
                        "data": {"name": "hr_agent", "label": "HR Agent"},
                    }
                )
                answer = specialist_result("hr_agent", result)
                return answer
            except GraphInterrupt:
                # 人工确认中断是正常控制流，不是失败：直接放行，不上报 tool_error
                raise
            except Exception:
                write_stream_event(
                    {
                        "event": "tool_error",
                        "data": {"name": "hr_agent", "message": "HR Agent 调用失败"},
                    }
                )
                raise

        # 保存为实例属性，创建 Supervisor 时使用。
        self.ask_knowledge_agent = ask_knowledge_agent
        self.ask_employee_service_agent = ask_employee_service_agent
        self.ask_hr_agent = ask_hr_agent

    # ------------------------------------------------------------------
    # Supervisor 与会话（课件 §9）
    # ------------------------------------------------------------------

    def _build_supervisor(self, role: str) -> Any:
        """根据教学登录角色构建当前会话的 Supervisor。"""

        agent_tools = [self.ask_knowledge_agent, self.ask_employee_service_agent]
        if role == "hr":
            agent_tools.append(self.ask_hr_agent)

        return create_agent(
            model=self.model,
            tools=agent_tools,
            context_schema=RunContext,
            checkpointer=self.checkpointer,
            system_prompt=SUPERVISOR_PROMPT,
        )

    def start_session(self, username: str, *, restore: bool = False) -> UserSession:
        """登录成功后创建独立的多 Agent 会话。

        `restore=True` 时先查 `agent_threads`（课件 §8.2 的线程索引）：该账号最近用过
        的 `thread_id` 仍存在就复用它 —— 这正是「进程重启后仍有历史」的入口；
        查不到才新建一个并登记。`U7` 的答复是 CLI 也纳入，所以这个开关默认关、
        由调用方按场景打开（HTTP 侧与 CLI 都开）。
        """

        # 登录是一次性读：开一个短命 Session，查完立刻归还连接
        # （课件 §5.3：查询函数接收外部 Session，不跨业务操作持有它）。
        with SessionLocal() as db:
            login_user = get_login_user(db, username)
            context = RunContext(
                user_id=login_user.user_id,
                username=str(login_user.username or ""),
                display_name=login_user.display_name,
                role=str(login_user.role or ""),
                department_id=login_user.department_id,
            )

            # 线程索引（课件 §8.2）：`agent_threads` 是「用户 → 最近线程」的落点。
            # 跨重启恢复靠它把同一个 user_id 找回原线程，而不是每次登录都新建 uuid4
            # —— 否则检查点写得再对也没有人认领。
            thread_id = None
            if restore:
                thread_id = db.scalar(
                    select(AgentThread.thread_id)
                    .where(AgentThread.user_id == login_user.user_id)
                    .order_by(
                        AgentThread.created_at.desc(), AgentThread.thread_id.desc()
                    )
                    .limit(1)
                )
            if thread_id is None:
                thread_id = str(uuid4())
                db.add(AgentThread(thread_id=thread_id, user_id=login_user.user_id))
                db.commit()

        # R3（评审提出）：网关按会话做路由与 prompt 缓存，`x-opencode-session` 必须
        # **每个会话一个**。模型对象在 __init__ 里建过一次，这里用新的会话 ID 重建，
        # 并同步重建持有它的 3 个专业 Agent 与 Agent Tool —— 课件要求的是「同一会话内
        # 三个 Agent 复用同一个模型对象」，不是「整个进程共用一个」。
        self.model = build_model(session_id=new_session_id())
        self._build_specialists()
        self._build_agent_tools()

        return UserSession(
            context=context,
            thread_id=thread_id,
            supervisor=self._build_supervisor(context.role),
        )

    # def restore_session(self, thread_id: str) -> UserSession | None:
    #     """按 `thread_id` 重建会话（进程重启后的恢复入口，课件 §8.3）。
    #
    #     内存里的 `app.state.sessions` 是**缓存**、不是真源：真源是 `agent_threads`
    #     （`thread_id → user_id`）加 `users`（身份）。缓存丢失时用它把可信身份重新
    #     拼出来，同一个 `thread_id` 继续读写同一份检查点，因此历史与未决确认都还在。
    #     账号被停用、角色不合法或记录已删除时返回 `None`（`U6`：不允许越权恢复）。
    #     """
    #
    #     with SessionLocal() as db:
    #         row = db.scalar(
    #             select(AgentThread).where(AgentThread.thread_id == thread_id)
    #         )
    #         if row is None:
    #             return None
    #         user = db.scalar(select(User).where(User.user_id == row.user_id))
    #         if (
    #             user is None
    #             or not user.login_enabled
    #             or user.account_status != "active"
    #             or user.role not in {"employee", "hr"}
    #         ):
    #             return None
    #         context = RunContext(
    #             user_id=user.user_id,
    #             username=str(user.username or ""),
    #             display_name=user.display_name,
    #             role=str(user.role or ""),
    #             department_id=user.department_id,
    #         )
    #
    #     # 与 start_session 一致地重建模型与工具链：网关按会话做路由与缓存，
    #     # `session_id` 必须是新的（课件 §7.6）。身份与 thread_id 则保持原样。
    #     self.model = build_model(session_id=new_session_id())
    #     self._build_specialists()
    #     self._build_agent_tools()
    #
    #     return UserSession(
    #         context=context,
    #         thread_id=thread_id,
    #         supervisor=self._build_supervisor(context.role),
    #     )

    async def has_pending_confirmation(self, session: UserSession) -> bool:
        """本轮是否停在人工确认上 —— 读**检查点**，不读进程内集合（计划 §7 `R4`）。

        进程重启后内存集合必然为空、而检查点里的 interrupt 还在；"待确认"存成两份
        正是状态漂移的根因，所以这里只认检查点，并且与 `get_thread_history` 共用
        `pending_confirmation_of()` 这一个判据。
        """

        snapshot = await session.supervisor.aget_state(self._config(session))
        return pending_confirmation_of(snapshot) is not None

    # ------------------------------------------------------------------
    # 多轮对话与人工确认恢复（课件 §10.1、§10.2）
    # ------------------------------------------------------------------

    def _config(self, session: UserSession) -> dict[str, Any]:
        """把当前会话的 thread_id 转成 LangGraph 需要的配置。

        如果当前协程/线程绑定了 RequestContext，把三个业务 ID 放进
        `config["metadata"]`：同步 Tool 在线程池里执行时 contextvars 可能丢失，
        `ToolRuntime.config` 是更可靠的兜底来源。
        """

        config: dict[str, Any] = {"configurable": {"thread_id": session.thread_id}}
        ctx = current_request_context()
        if ctx is not None:
            config["metadata"] = config_metadata(ctx)
        return config

    async def get_thread_history(
        self, session: UserSession
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """_config(session) 使用当前 session.thread_id 定位最新状态快照"""
        snapshot = await session.supervisor.aget_state(self._config(session))

        display_messages: list[dict[str, str]] = []

        # 空Thread 没有messages，有数据时按照原顺序过滤信息
        for message in (snapshot.values or {}).get("messages", []):
            role: str | None = None
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage) and not message.tool_calls:
                role = "assistant"

            if role is None:
                continue
            content = message_text(message).strip()
            if content:
                display_messages.append({"role": role, "content": content})

        return display_messages, pending_confirmation_of(snapshot)

    async def chat(
        self,
        session: UserSession,
        user_text: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """在同一 Thread 中只提交本轮新增消息（非流式入口）。

        这条路径供 CLI 与既有测试使用；Web 走 `stream_chat`。两者共用同一套
        RequestContext、`agent.turn` Span、JSON 日志和 Metrics，区别只是这里
        不向外发 SSE 事件，直接返回 LangGraph 的最终结果。

        AsyncSqliteSaver 只有异步接口，所以必须是 `ainvoke`，不能用同步 `invoke`。
        """

        ctx = _turn_context(session, request_id)
        token = bind_request_context(ctx)
        span = _TRACER.start_span("agent.turn")
        _set_turn_attributes(span, ctx, "chat")
        started = time.perf_counter()
        outcome = "completed"
        error_info: dict[str, str] = {}

        try:
            with trace.use_span(
                span,
                end_on_exit=False,
                record_exception=False,
                set_status_on_exception=False,
            ):
                log_event(
                    "agent.started",
                    thread_id=ctx.thread_id,
                    request_id=ctx.request_id,
                    run_id=ctx.run_id,
                    agent_kind="chat",
                    role=ctx.role,
                )
                result = cast(
                    dict[str, Any],
                    await session.supervisor.ainvoke(
                        {"messages": [{"role": "user", "content": user_text}]},
                        config=self._config(session),
                        context=session.context,
                    ),
                )
                outcome = _result_outcome(result)
                return result
        except asyncio.CancelledError:
            outcome = "disconnected"
            raise
        except GraphInterrupt:
            # 人工确认是正常控制流，不是失败。
            outcome = "waiting_confirmation"
            raise
        except Exception as exc:  # noqa: BLE001 —— 记录后必须原样抛出
            outcome = "failed"
            error_info = safe_error(exc)
            span.set_attribute("error.type", error_info["error_type"])
            span.set_attribute("error.message", error_info["error_message_safe"])
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute("outcome", outcome)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            with trace.use_span(span, end_on_exit=False):
                log_event(
                    "agent.finished",
                    thread_id=ctx.thread_id,
                    request_id=ctx.request_id,
                    run_id=ctx.run_id,
                    outcome=outcome,
                    agent_kind="chat",
                    role=ctx.role,
                    duration_ms=duration_ms,
                    **error_info,
                )
            record_agent_run(
                outcome=outcome,
                kind="chat",
                role=ctx.role,
                duration_ms=duration_ms,
            )
            span.end()
            reset_request_context(token)

    async def resume(
        self,
        session: UserSession,
        approved: bool,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """使用同一 Thread 和 Context 恢复最近一次人工确认（同 chat 走异步接口）。

        恢复执行是独立的一轮：新的 request_id / run_id / agent.turn Span。
        """

        ctx = _turn_context(session, request_id)
        token = bind_request_context(ctx)
        span = _TRACER.start_span("agent.turn")
        _set_turn_attributes(span, ctx, "resume")
        started = time.perf_counter()
        outcome = "completed"
        error_info: dict[str, str] = {}
        try:
            with trace.use_span(
                span,
                end_on_exit=False,
                record_exception=False,
                set_status_on_exception=False,
            ):
                log_event(
                    "agent.started",
                    thread_id=ctx.thread_id,
                    request_id=ctx.request_id,
                    run_id=ctx.run_id,
                    agent_kind="resume",
                    role=ctx.role,
                )
                return cast(
                    dict[str, Any],
                    await session.supervisor.ainvoke(
                        Command(resume={"approved": approved}),
                        config=self._config(session),
                        context=session.context,
                    ),
                )
        except asyncio.CancelledError:
            outcome = "disconnected"
            raise
        except GraphInterrupt:
            # 人工确认是正常控制流，不是失败。
            outcome = "waiting_confirmation"
            raise
        except Exception as exc:  # noqa: BLE001 —— 记录后必须原样抛出
            outcome = "failed"
            error_info = safe_error(exc)
            span.set_attribute("error.type", error_info["error_type"])
            span.set_attribute("error.message", error_info["error_message_safe"])
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute("outcome", outcome)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            with trace.use_span(span, end_on_exit=False):
                log_event(
                    "agent.finished",
                    thread_id=ctx.thread_id,
                    request_id=ctx.request_id,
                    run_id=ctx.run_id,
                    outcome=outcome,
                    agent_kind="resume",
                    role=ctx.role,
                    duration_ms=duration_ms,
                    **error_info,
                )
            record_agent_run(
                outcome=outcome,
                kind="resume",
                role=ctx.role,
                duration_ms=duration_ms,
            )
            span.end()
            reset_request_context(token)

    async def stream_chat(
        self,
        session: UserSession,
        user_text: str,
        *,
        request_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """在 agent.turn Span 内运行流式对话，并绑定请求上下文。

        为什么包一层而不是直接改原方法：原方法里全是 `yield`，给整段缩进既
        容易改错行，也会把埋点逻辑和业务流混在一起。包装层只负责 Span 生命周期、
        上下文绑定和 outcome，业务逻辑保持在 `_stream_chat_impl`。
        """

        ctx = _turn_context(session, request_id)
        token = bind_request_context(ctx)
        span = _TRACER.start_span("agent.turn")
        _set_turn_attributes(span, ctx, "chat")
        started = time.perf_counter()
        outcome = "completed"
        error_info: dict[str, str] = {}

        try:
            with trace.use_span(
                span,
                end_on_exit=False,
                record_exception=False,
                set_status_on_exception=False,
            ):
                log_event(
                    "agent.started",
                    thread_id=ctx.thread_id,
                    request_id=ctx.request_id,
                    run_id=ctx.run_id,
                    agent_kind="chat",
                    role=ctx.role,
                )
                async for event in self._stream_chat_impl(session, user_text):
                    if event.get("event") == "confirmation":
                        outcome = "waiting_confirmation"
                    yield event
        except GeneratorExit:
            # 客户端断开 / 上层提前 return 时，异步生成器被关闭。
            outcome = "disconnected"
            raise
        except asyncio.CancelledError:
            outcome = "disconnected"
            raise
        except GraphInterrupt:
            outcome = "waiting_confirmation"
            raise
        except Exception as exc:  # noqa: BLE001 —— 记录后必须原样抛出
            outcome = "failed"
            error_info = safe_error(exc)
            span.set_attribute("error.type", error_info["error_type"])
            span.set_attribute("error.message", error_info["error_message_safe"])
            span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            span.set_attribute("outcome", outcome)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            with trace.use_span(span, end_on_exit=False):
                log_event(
                    "agent.finished",
                    thread_id=ctx.thread_id,
                    request_id=ctx.request_id,
                    run_id=ctx.run_id,
                    outcome=outcome,
                    agent_kind="chat",
                    role=ctx.role,
                    duration_ms=duration_ms,
                    **error_info,
                )
            record_agent_run(
                outcome=outcome,
                kind="chat",
                role=ctx.role,
                duration_ms=duration_ms,
            )
            span.end()
            reset_request_context(token)

    async def _stream_chat_impl(
        self, session: UserSession, user_text: str
    ) -> AsyncIterator[dict[str, Any]]:
        """把langgraph的模型文本，Agent Tool 状态和确认信息逐步向外发送"""

        # interrupts保存最近一次人工确认信息，初始状态表示没有中断。
        interrupts = ()
        # sent_text 用于判断是否已经发送过文本，防止兜底回答重复现实
        sent_text = False
        # final_answer 保存 updates 中出现的完整回答
        final_answer = ""
        # turn_messages 攒本轮 updates 里出现过的消息，用来在流末尾生成轨迹增量。
        # 只攒 updates 分支的，因为 messages 分支收到的是逐 token 分片。
        turn_messages: list[Any] = []

        async for part in session.supervisor.astream(
            # 只提交本轮消息，历史消息由当前的 thread_id 对应的 Checkpointer 恢复
            {"messages": [{"role": "user", "content": user_text}]},
            config=self._config(session),
            context=session.context,
            stream_mode=["messages", "custom", "updates"],
            version="v2",
        ):
            # type表示StreamPart的来源，这里只处理模型消息
            if part["type"] == "messages":
                # messages模式下的data是(token,metatdata)二元组
                # 变量前的下划线表示当前暂时不使用metadata
                message, _metadata = part["data"]
                # 只流**模型自己产出**的文本。
                # messages 模式除了模型 token，还会把工具节点写回状态的消息
                # （ToolMessage）也当作一条 message 送过来，而 Agent Tool 的返回值
                # 是 specialist_result() 的 json.dumps：
                #   {"agent": "knowledge_agent", "answer": "...",
                #    "business_tools": [...]}
                # 那是给 Supervisor 解析用的机器层数据（人看的那份在同一份 JSON 的
                # answer 字段里，由 Supervisor 重写后再输出）。不过滤的话，用户会在
                # 正文前面先看到一段裸 JSON —— 实测就是这样。
                # 注意 AIMessageChunk 是 AIMessage 的子类，逐 token 的分片不会被误杀。
                if not isinstance(message, AIMessage):
                    continue
                text = message_text(message)
                if text:
                    sent_text = True
                    yield {
                        "event": "text_delta",
                        "data": {"text": text},
                    }
            elif part["type"] == "custom":
                # writer_stream_event() 写入的 tool_start,tool_end 等事件从这里到达
                yield part["data"]

            elif part["type"] == "updates":
                # data 是本次节点更新的字典；暂停时会额外包含__interrupt__
                interrupts = part["data"].get("__interrupt__", interrupts)
                # 某些模型只在节点结束时返回完整信息，保存最终回答作为兜底

                for update in part["data"].values():
                    if not isinstance(update, dict):
                        continue
                    for message in update.get("messages", []):
                        # 攒起来给末尾的 trace 事件用（见下方说明）
                        turn_messages.append(message)
                        # 没有 tool_calls 的 AIMessage 才是可展示的回答，
                        # 不是调用 Tool 的指令
                        if isinstance(message, AIMessage) and not message.tool_calls:
                            text = message_text(message)
                            if text:
                                final_answer = text

        # 没有收到逐段文本时，至少把最终完整回答发送给页面
        if not sent_text and final_answer:
            yield {"event": "text_delta", "data": {"text": final_answer}}

        # 本轮的轨迹增量发给页面。
        # 背景：轨迹原先只由 /api/confirmation 的 AgentReply 带回来，于是**普通问答轮**
        # 的轨迹只活在浏览器的临时状态里 —— 刷新一次就没了，右栏还会误报成
        # "本轮 Supervisor 直接回答了，没有转给任何专家"。这里在 done 之前补一条
        # trace 事件，前端 StreamHandlers.onTrace 用游标切片后落库。
        # 中断轮刻意不发：那条路的 trace 由 /api/confirmation 一次性给全（含
        # agent_tool_result），分两段反而会把同一轮拆开、让右栏的专家/工具汇总变残。
        if not interrupts:
            yield {
                "event": "trace",
                "data": {"trace": outer_trace({"messages": turn_messages})},
            }

        if interrupts:
            # interrupt 的 value 是暂停时交给用户确认的业务数据
            value = interrupts[0].value
            confirmation = value if isinstance(value, dict) else {"message": str(value)}
            yield {"event": "confirmation", "data": confirmation}
