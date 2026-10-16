"""第五阶段（P6 + P7 + P8）通过信号测试。

用法（在仓库根运行）：

    uv run python src/tests/verify_phase5.py

退出码：全部通过 0，否则 1。逐条打印 PASS / FAIL / SKIP 与判定依据。

覆盖范围
--------
**A 组：确定性检查（不调用模型，秒级）**
  A1 三个专业 Agent 的 Tool 集合：并集覆盖 7 个业务 Tool，且唯一跨 Agent 重叠是
     `query_device_requests`（课件 §7.5 设计如此）
  A2 `specialist_result()` 只回 `{agent, answer, business_tools}` 且可 `json.loads`
  A3 Supervisor 按角色裁剪：employee 的 Tool 集合不含 `ask_hr_agent`，hr 含
  A4 Supervisor **不直接挂业务 Tool**（只挂 Agent Tool）
  A5 无索引启动：立即抛错、且**不进入登录循环**（`input()` 调用次数为 0）
  A6 `print_result()` 打印路由证据三要素（回答 / Agent Tool / 内层业务 Tool）

**B 组：需要真实模型的检查（R1 与多轮，约 1–3 分钟）**
  B1 R1：嵌套 `interrupt()` 能暂停到父图，载荷是内层业务 Tool 的
  B2 R1：同一 `thread_id` 的 `Command(resume={'approved': True})` 能恢复并完成写入
  B3 R1：`resume({'approved': False})` 恢复后**不写入**
  B4 同一 `thread_id` 第二轮能引用第一轮：消息数增长，且 Supervisor 把代词
     补全成可独立理解的 task
  B5 `/logout` 效果：新会话拿到**新 `thread_id`**，新 thread 里看不到旧对话

**只读保证**：全程不写业务数据；脚本开头与结尾各取一次
`device_requests` 表的行摘要（`db_state.requests_snapshot()`：内容长度 + sha256 + 行数）
做对比。B1–B3 的副作用写入 `.tmp/` 下的临时文件，结束时清理。

**B 组的模型依赖**：B1–B5 需要 `.env` 里配置好可用的 `MODEL_PROVIDER` /
`MODEL_NAME` / `API_KEY` / `BASE_URL`。若模型没有按预期调用工具，B1 会判
FAIL 并打印原始返回，便于区分「机制不成立」与「模型没照做」。
"""

from __future__ import annotations

import builtins
import io
import json
import sys
import warnings
from contextlib import redirect_stdout
from dataclasses import MISSING, dataclass, fields
from pathlib import Path
from typing import Any, Callable

# ToolRuntime 是 pydantic 模型，注入自定义 Context 会打一条无害的序列化告警
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # 让 `import db_state` / `import sync_app` 可用

from langchain.agents import create_agent  # noqa: E402
from langchain.tools import ToolRuntime, tool  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

import db_state  # noqa: E402
from sync_app import SyncApplication  # noqa: E402

import personal_assistant.main as cli  # noqa: E402
import personal_assistant.knowledge_base as kb  # noqa: E402
from personal_assistant.business_tools import RunContext  # noqa: E402
from personal_assistant.multi_agent import (  # noqa: E402
    MultiAgentApplication,
    outer_trace,
    specialist_result,
)

BUSINESS_TOOLS = [
    "approve_device_request",
    "create_device_request",
    "find_department",
    "find_public_employee",
    "list_requestable_devices",
    "query_device_requests",
    "search_company_knowledge",
]
EXPECTED_SPECIALIST_TOOLS = {
    "knowledge_agent": ["search_company_knowledge"],
    "employee_service_agent": [
        "create_device_request",
        "find_department",
        "find_public_employee",
        "list_requestable_devices",
        "query_device_requests",
    ],
    "hr_agent": ["approve_device_request", "query_device_requests"],
}
SIDE_EFFECT = REPO_ROOT / ".tmp" / "phase5_r1_side_effect.txt"

RESULTS: list[tuple[str, str, str]] = []  # (检查项, 判定, 依据)


def record(name: str, ok: bool, detail: str = "", skipped: bool = False) -> None:
    verdict = "SKIP" if skipped else ("PASS" if ok else "FAIL")
    RESULTS.append((name, verdict, detail))
    print(f"[{verdict}] {name}")
    if detail:
        for line in detail.splitlines():
            print(f"        {line}")


def tools_of(agent: Any) -> list[str]:
    """取出已编译 Agent 的 tools 节点里的工具名（逐层回退，避免绑定方式变化）。"""
    candidates = [agent.nodes["tools"]]
    node = agent.nodes["tools"]
    for _ in range(3):
        node = getattr(node, "bound", None)
        if node is None:
            break
        candidates.append(node)
    for candidate in candidates:
        by_name = getattr(candidate, "tools_by_name", None)
        if by_name:
            return sorted(by_name)
    raise RuntimeError(f"取不到工具集合：{[type(c).__name__ for c in candidates]}")


def digest() -> tuple[int, str, int]:
    """申请表的库版摘要：``(内容长度, sha256[:16], 行数)``。

    旧版读 `day05_device_requests.json` 的字节数与 sha256；数据源换成
    `agent_service.device_requests` 表之后，对应物是 `db_state.requests_snapshot()`。
    元组从 2 位变 3 位（多出行数），但判定逻辑只看整体相等，所以比较与打印都不用改。
    """
    return db_state.requests_snapshot()


@dataclass(frozen=True)
class Ctx:
    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


def runtime_with(context: Any) -> ToolRuntime:
    kwargs: dict[str, object] = {}
    for f in fields(ToolRuntime):
        if f.name == "context":
            kwargs["context"] = context
        elif f.name == "state":
            kwargs["state"] = {}
        elif f.name == "tools":
            kwargs["tools"] = []
        elif f.default is MISSING and f.default_factory is MISSING:  # type: ignore[misc]
            kwargs[f.name] = None
    return ToolRuntime(**kwargs)  # type: ignore[arg-type]


# ==========================================================================
# A 组：确定性检查
# ==========================================================================


def check_a1(app: SyncApplication) -> None:
    actual = {
        "knowledge_agent": tools_of(app.knowledge_agent),
        "employee_service_agent": tools_of(app.employee_service_agent),
        "hr_agent": tools_of(app.hr_agent),
    }
    union = sorted({t for tools in actual.values() for t in tools})
    overlap = sorted(t for t in union if sum(t in tools for tools in actual.values()) > 1)
    ok = (
        actual == {k: sorted(v) for k, v in EXPECTED_SPECIALIST_TOOLS.items()}
        and union == BUSINESS_TOOLS
        and overlap == ["query_device_requests"]
    )
    record(
        "A1 三个专业 Agent 的 Tool 集合（并集覆盖 7 个）",
        ok,
        "\n".join(f"{k:24} {v}" for k, v in actual.items())
        + f"\n并集覆盖 7 个: {union == BUSINESS_TOOLS}"
        + f"\n唯一跨 Agent 重叠: {overlap}",
    )


def check_a2() -> None:
    fake = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "find_department", "args": {}, "id": "1"}]),
            AIMessage(content="信息技术部可以处理软件账号问题。"),
        ]
    }
    raw = specialist_result("employee_service_agent", fake)
    try:
        payload = json.loads(raw)
        ok = sorted(payload) == ["agent", "answer", "business_tools"]
        detail = f"输出 {raw}"
    except json.JSONDecodeError as exc:
        ok, detail = False, f"json.loads 失败：{exc}"
    record("A2 specialist_result 只回三个字段且可 json.loads", ok, detail)


def check_a3(app: SyncApplication) -> None:
    employee_tools = tools_of(app._build_supervisor("employee"))
    hr_tools = tools_of(app._build_supervisor("hr"))
    ok = (
        "ask_hr_agent" not in employee_tools
        and "ask_hr_agent" in hr_tools
        and set(employee_tools) <= set(hr_tools)
    )
    record(
        "A3 Supervisor 按角色裁剪（employee 不含 ask_hr_agent）",
        ok,
        f"employee: {employee_tools}\nhr      : {hr_tools}",
    )


def check_a4(app: SyncApplication) -> None:
    for role in ("employee", "hr"):
        tools = tools_of(app._build_supervisor(role))
        leaked = sorted(set(tools) & set(BUSINESS_TOOLS))
        if leaked:
            record(f"A4 Supervisor({role}) 不直接挂业务 Tool", False, f"越界: {leaked}")
            return
    record("A4 Supervisor 不直接挂业务 Tool", True, "两个角色的 Supervisor 都只挂 Agent Tool")


def check_a5() -> None:
    calls: list[str] = []
    original_input = builtins.input
    original_path = cli.INDEX_MANIFEST_PATH
    cli.INDEX_MANIFEST_PATH = REPO_ROOT / "src" / "vector_store" / "__不存在的清单__.json"
    builtins.input = lambda prompt="": (calls.append(prompt), "/quit")[1]
    try:
        with redirect_stdout(io.StringIO()):
            cli.main()
        ok, detail = False, "未抛错（应当立即报错）"
    except RuntimeError as exc:
        ok = "请先运行 build_index.py" in str(exc) and not calls
        detail = f"{exc}\n进入登录循环（input 次数）: {len(calls)}"
    finally:
        cli.INDEX_MANIFEST_PATH = original_path
        builtins.input = original_input
    record("A5 无索引启动立即报错且不进入登录循环", ok, detail)


def check_a6() -> None:
    fake_result = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "ask_knowledge_agent", "args": {"task": "公司介绍"}, "id": "1"}],
            ),
            ToolMessage(
                content=json.dumps(
                    {"agent": "knowledge_agent", "answer": "…", "business_tools": ["search_company_knowledge"]},
                    ensure_ascii=False,
                ),
                name="ask_knowledge_agent",
                tool_call_id="1",
            ),
            AIMessage(content="北京总部主要承担产品规划等工作。"),
        ]
    }
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        cli.print_result(fake_result)
    printed = buffer.getvalue()
    ok = (
        "当前会话累计 Supervisor 路由证据" in printed
        and "ask_knowledge_agent" in printed
        and "search_company_knowledge" in printed
        and "北京总部主要承担产品规划等工作。" in printed
    )
    record("A6 print_result 打印回答 + Agent Tool + 内层业务 Tool", ok, printed.strip())


def check_a7() -> None:
    """A7 模型集成：**应用实际使用的那个模型**必须回传 `reasoning_content`。

    这是**机制检查**，不是"跑 N 次看有没有报错"。背景（阶段 6 实测）：模型是 thinking
    模型（难题上产出上万字符推理内容、数千推理 token），网关要求下一轮把这些内容原样
    回传，否则返回 400「The `reasoning_content` in the thinking mode must be passed
    back to the API」；而 langchain 的发送侧序列化只白名单复制 4 个 additional_kwargs
    键，字段会在发送时丢失 —— 于是「模型 → tool_call → tool 结果 → 再调模型」这条链
    会偶发 400。该故障率约 5–12%，跑 8 次全过的运气概率就有三成，**所以不能靠统计采样**。

    ⚠️ 判据修正（P0-1，评审提出）：第一版只断言 `kb.build_chat_model()` **自己构造的**实例
    —— 而应用走的是 `multi_agent.build_model()`。当时那条链拿到的是 `ChatOpenAI`，
    于是出现了"改了 A、测了 B"：修复没接到应用上，验收却报 PASS。
    现在**首先**断言 `MultiAgentApplication().model`（应用真实入口）的类型与出站 payload。
    """
    marker = "上一轮推理内容-机制检查"
    messages = [
        HumanMessage(content="你好"),
        AIMessage(content="我先想想。", additional_kwargs={"reasoning_content": marker}),
        HumanMessage(content="继续"),
    ]

    def carried_by(model: Any) -> tuple[bool, list[list[str]]]:
        payload = model._get_request_payload(messages)  # type: ignore[attr-defined]
        assistant_items = [m for m in payload.get("messages", []) if m.get("role") == "assistant"]
        hit = [m for m in assistant_items if m.get("reasoning_content") == marker]
        return len(hit) == 1, [sorted(m) for m in assistant_items]

    try:
        app_model = MultiAgentApplication(checkpointer=InMemorySaver()).model  # 应用真实入口
        app_ok, app_fields = carried_by(app_model)
        kb_model, name, source = kb.build_chat_model()
        kb_ok, _kb_fields = carried_by(kb_model)
        checks = {
            "应用实例类型 == ChatReasoningEcho": type(app_model).__name__ == "ChatReasoningEcho",
            "应用实例的出站请求带 reasoning_content": app_ok,
            "独立构造的实例也带（两条构造路径一致）": kb_ok,
        }
        detail = (
            f"应用实例: {type(app_model).__name__}\n"
            f"kb.build_chat_model(): {type(kb_model).__name__} | name={name} | source={source}\n"
            f"应用实例出站 assistant 消息字段: {app_fields}\n"
            + "\n".join(f"{k}: {v}" for k, v in checks.items())
        )
        ok = all(checks.values())
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    record("A7 模型集成：应用实例的出站请求携带 reasoning_content", ok, detail)


# ==========================================================================
# B 组：R1 最小复现（真实模型）
# ==========================================================================


def build_r1_stack() -> tuple[Any, Any, Any]:
    """按 §11.4 搭一套最小链路：Supervisor → Agent Tool → 专业 Agent → 含 interrupt 的业务 Tool。"""

    @tool
    def write_note(note: str, runtime: ToolRuntime) -> str:
        """把一条备注写入文件（写入前需要人工确认）。"""
        decision = interrupt({"action": "write_note", "candidate": {"note": note}})
        if not isinstance(decision, dict) or not decision.get("approved"):
            return "user_rejected：用户取消，未写入"
        SIDE_EFFECT.write_text(note, encoding="utf-8")
        return f"written：已写入 {note}"

    model = kb.build_chat_model()[0]

    specialist = create_agent(
        model=model,
        tools=[write_note],
        context_schema=RunContext,
        system_prompt=(
            "你是备注 Agent。用户要求写备注时，你必须调用 write_note 工具，"
            "参数取用户给出的内容，不要编造内容，也不要只口头答应。"
        ),
    )

    @tool
    def ask_note_agent(task: str, runtime: ToolRuntime) -> str:
        """把写备注的任务交给备注 Agent。task 必须是完整、可独立理解的指令。"""
        result = specialist.invoke(
            {"messages": [{"role": "user", "content": task}]},
            context=runtime.context,
        )
        return specialist_result("note_agent", result)

    supervisor = create_agent(
        model=model,
        tools=[ask_note_agent],
        context_schema=RunContext,
        checkpointer=InMemorySaver(),
        system_prompt=(
            "你是备注 Supervisor。用户要求写备注时，你必须调用 ask_note_agent 工具，"
            "把任务补全成一条可独立理解的指令（包含要写的具体内容）。"
            "不要自己写文件，也不要编造内容。"
        ),
    )
    return supervisor, model, write_note


def run_r1_checks() -> None:
    context = RunContext(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-PRODUCT",
    )
    if SIDE_EFFECT.exists():
        SIDE_EFFECT.unlink()

    supervisor, _model, _tool = build_r1_stack()
    task = "请写一条备注，内容就四个字：会议改期"

    # ---- B1：暂停是否传播到父图 ----
    config = {"configurable": {"thread_id": "phase5-r1-approve"}}
    try:
        first = supervisor.invoke(
            {"messages": [{"role": "user", "content": task}]},
            config=config,
            context=context,
        )
        interrupts = first.get("__interrupt__")
        if not interrupts:
            record(
                "B1 R1：嵌套 interrupt 能暂停到父图",
                False,
                "父图没有返回 __interrupt__ —— 可能机制不成立，或模型没有调用工具。\n"
                + f"最后一条消息: {[getattr(m, 'content', '') for m in first.get('messages', [])][-1:]!s:.400}",
            )
            return
        payload = getattr(interrupts[0], "value", interrupts[0])
        ok = (
            isinstance(payload, dict)
            and payload.get("action") == "write_note"
            and not SIDE_EFFECT.exists()
        )
        record(
            "B1 R1：嵌套 interrupt 能暂停到父图",
            ok,
            f"暂停载荷: {json.dumps(payload, ensure_ascii=False, default=str)}\n"
            f"暂停阶段副作用文件存在: {SIDE_EFFECT.exists()}（应为 False）",
        )
    except Exception as exc:  # noqa: BLE001
        record("B1 R1：嵌套 interrupt 能暂停到父图", False, f"{type(exc).__name__}: {exc}")
        return

    # ---- B2：批准后恢复并写入 ----
    try:
        resumed = supervisor.invoke(Command(resume={"approved": True}), config=config, context=context)
        written = SIDE_EFFECT.read_text(encoding="utf-8") if SIDE_EFFECT.exists() else None
        ok = resumed.get("__interrupt__") is None and written == "会议改期"
        record(
            "B2 R1：同一 thread_id 恢复后完成写入",
            ok,
            f"恢复后 __interrupt__: {resumed.get('__interrupt__')}\n副作用文件内容: {written!r}",
        )
    except Exception as exc:  # noqa: BLE001
        record("B2 R1：同一 thread_id 恢复后完成写入", False, f"{type(exc).__name__}: {exc}")

    # ---- B3：拒绝后不写入 ----
    # 注意：被拒绝后，专业 Agent 可能**再次尝试**同一个写操作，于是父图再次暂停。
    # 这是模型行为，不是机制缺陷；所以这里在拒绝方向上循环到不再暂停（有上限），
    # 断言的核心只有一条：**全程没有任何写入**。
    if SIDE_EFFECT.exists():
        SIDE_EFFECT.unlink()
    config2 = {"configurable": {"thread_id": "phase5-r1-reject"}}
    max_rejects = 5
    try:
        result = supervisor.invoke(
            {"messages": [{"role": "user", "content": "请写一条备注，内容两个字：取消"}]},
            config=config2,
            context=context,
        )
        if not result.get("__interrupt__"):
            record("B3 R1：拒绝后不写入", False, "第一次调用没有暂停，无法验证拒绝路径")
        else:
            rejects = 0
            while result.get("__interrupt__") and rejects < max_rejects:
                result = supervisor.invoke(
                    Command(resume={"approved": False}), config=config2, context=context
                )
                rejects += 1
            still_paused = bool(result.get("__interrupt__"))
            # ⚠️ 判据修正（P0-2，评审提出）：第一版只断言 `not SIDE_EFFECT.exists()`，
            # 于是「一次都没走到拒绝路径」也能判 PASS —— 那是空信号。既然要验的是
            # "拒绝后不写入"，就必须**真的拒绝过至少一次**。
            ok = (not SIDE_EFFECT.exists()) and rejects >= 1
            record(
                "B3 R1：拒绝后不写入",
                ok,
                f"连续拒绝 {rejects} 次（上限 {max_rejects}）后仍暂停: {still_paused}\n"
                f"有效拒绝次数 >= 1（必须真的走到该路径）: {rejects >= 1}\n"
                f"副作用文件存在: {SIDE_EFFECT.exists()}（应为 False）\n"
                f"备注：拒绝后模型重试同一写操作属正常行为，CLI 的 handle_interrupts() "
                f"是 while 循环，会再次询问用户",
            )
    except Exception as exc:  # noqa: BLE001
        record("B3 R1：拒绝后不写入", False, f"{type(exc).__name__}: {exc}")


# ==========================================================================
# B 组：多轮与账号切换
# ==========================================================================


def _b4_attempt(app: SyncApplication) -> tuple[bool, str, Any]:
    """跑一次两轮对话并给出判定。返回 (是否通过, 证据, 会话)。"""
    session = app.start_session("zhang_wei")
    question1 = "公司介绍里说北京总部主要承担哪些职能？"
    question2 = "那上海那边呢？"

    first = app.chat(session, question1)
    second = app.chat(session, question2)

    def agent_tasks(result: dict) -> list[str]:
        return [
            call["args"].get("task", "")
            for event in outer_trace(result)
            if event["type"] == "agent_tool_calls"
            for call in event["calls"]
        ]

    # outer_trace 返回的是**当前 thread 的累计**消息，所以要按第一轮的长度切出第二轮
    tasks_round1 = agent_tasks(first)
    tasks_round2 = agent_tasks(second)[len(tasks_round1) :]

    answers = [
        m.content
        for m in second["messages"]
        if isinstance(m, AIMessage) and not m.tool_calls and isinstance(m.content, str)
    ]
    last_answer = answers[-1] if answers else ""

    grew = len(second["messages"]) > len(first["messages"])
    answer_ok = ("上海" in last_answer) or ("研发中心" in last_answer)

    # 第二轮委派时才要求 task 已把指代补全；直接从历史作答是合法行为
    delegated = bool(tasks_round2)
    resolved = (
        any(("上海" in t or "研发中心" in t) and "那边" not in t for t in tasks_round2)
        if delegated
        else True
    )
    ok = grew and answer_ok and resolved
    detail = (
        f"消息数 {len(first['messages'])} -> {len(second['messages'])}（增长 {grew}）\n"
        f"第二轮是否委派专业 Agent: {delegated}"
        + ("（直接从历史作答，也说明历史被用到了）" if not delegated else "") + "\n"
        f"第二轮委派的 task: {tasks_round2[-1] if tasks_round2 else '(无)'}\n"
        f"task 指代已补全: {resolved}\n"
        f"回答提到上海/研发中心: {answer_ok}\n"
        f"第二轮回答前 120 字: {last_answer[:120]}"
    )
    return ok, detail, session


def check_b4(app: SyncApplication) -> Any:
    """多轮上下文。

    ⚠️ 这条依赖**模型行为**（是否把代词补全、回答是否切题），因此会偶发不通过。
    失败时自动换一条新 thread 重试一次；两次都失败才判 FAIL，并在证据里同时
    打印两次的原始 task 与回答，便于区分「机制不成立」与「模型没照做」。
    """
    attempts: list[str] = []
    session = None
    for index in (1, 2):
        ok, detail, session = _b4_attempt(app)
        attempts.append(f"--- 第 {index} 次尝试 ---\n{detail}")
        if ok:
            suffix = "（第 2 次尝试才通过：模型行为有随机性）" if index == 2 else ""
            record("B4 同一 thread_id 第二轮能引用第一轮" + suffix, True, detail)
            return session
    record("B4 同一 thread_id 第二轮能引用第一轮", False, "\n".join(attempts))
    return session


def check_b5(app: SyncApplication, old_session: Any) -> None:
    new_session = app.start_session("wang_fang")
    fresh_state = new_session.supervisor.get_state(
        {"configurable": {"thread_id": new_session.thread_id}}
    )
    fresh_messages = fresh_state.values.get("messages", []) if fresh_state.values else []
    old_state = old_session.supervisor.get_state(
        {"configurable": {"thread_id": old_session.thread_id}}
    )
    old_messages = old_state.values.get("messages", []) if old_state.values else []
    ok = (
        new_session.thread_id != old_session.thread_id
        and new_session.context.role == "hr"
        and len(fresh_messages) == 0
        and len(old_messages) > 0
    )
    record(
        "B5 /logout 后新会话拿到新 thread_id 且看不到旧对话",
        ok,
        f"旧 thread_id: {old_session.thread_id}（消息 {len(old_messages)} 条）\n"
        f"新 thread_id: {new_session.thread_id}（消息 {len(fresh_messages)} 条，应为 0）\n"
        f"新角色: {new_session.context.role}",
    )


# ==========================================================================
# 主流程
# ==========================================================================


def main() -> int:
    kb.ensure_writable_tempdir()
    before = digest()
    print("=" * 78)
    print("第五阶段通过信号测试 —— A 组：确定性检查")
    print("=" * 78)
    # 用例只需要内存检查点（`InMemorySaver`），但 `chat`/`resume` 是 async，
    # 本文件是同步写的 —— 用 `SyncApplication` 薄壳把这两个方法包成同步，
    # 下面所有 `app.chat(...)` 调用点字面上不用动。
    app = SyncApplication(MultiAgentApplication(checkpointer=InMemorySaver()))
    check_a1(app)
    check_a2()
    check_a3(app)
    check_a4(app)
    check_a5()
    check_a6()
    check_a7()

    print()
    print("=" * 78)
    print("第五阶段通过信号测试 —— B 组：需要真实模型")
    print("=" * 78)
    run_r1_checks()
    session = check_b4(app)
    check_b5(app, session)

    if SIDE_EFFECT.exists():
        SIDE_EFFECT.unlink()

    after = digest()
    print()
    print("=" * 78)
    print("汇总")
    print("=" * 78)
    for name, verdict, _detail in RESULTS:
        print(f"  {verdict:4}  {name}")
    failed = [name for name, verdict, _ in RESULTS if verdict == "FAIL"]
    skipped = [name for name, verdict, _ in RESULTS if verdict == "SKIP"]
    print()
    print(f"共 {len(RESULTS)} 项："
          f"PASS {sum(1 for _, v, _ in RESULTS if v == 'PASS')}，"
          f"FAIL {len(failed)}，SKIP {len(skipped)}")
    print(f"申请表内容长度/摘要/行数 {before} -> {after} | 只读: {before == after}")
    if before != after:
        print("!! 测试过程中改动了 device_requests 表，这是缺陷")
    return 1 if (failed or before != after) else 0


if __name__ == "__main__":
    raise SystemExit(main())
