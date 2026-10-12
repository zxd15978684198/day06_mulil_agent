"""命令行入口：登录循环、多轮对话、人工确认与路由证据打印。

课件 §10.3–§10.5 的实现，按 §5.2 改写两处 import（`knowledge_base` /
`multi_agent` → 全包名），并在启动时做一次环境适配（本机 `%TEMP%` 对子进程
不可写，chromadb 需要可写的临时目录；正常机器上该调用是空操作）。

固定字符串（提示语、`/quit`、`/logout`、确认输入集）照课件原样，验收会断言它们。
"""

from __future__ import annotations

import json
import warnings

from langchain_core.messages import AIMessage

from personal_assistant.knowledge_base import (
    INDEX_MANIFEST_PATH,
    ensure_writable_tempdir,
)
from personal_assistant.multi_agent import (
    MultiAgentApplication,
    UserSession,
    message_text,
    outer_trace,
)


def ask(prompt: str) -> str | None:
    """读一行输入并 strip；**输入流结束（EOF）时返回 None 表示应当退出**。

    为什么需要：不处理时 `input()` 会抛 `EOFError`，终端上直接糊一大段 traceback。
    实测触发场景：① 用管道喂命令、输入喂完后；② 用户按 Ctrl+Z 回车（Windows）/
    Ctrl+D（Unix）。交互式 CLI 遇到这两种情况应当干净退出。
    """
    try:
        return input(prompt).strip()
    except EOFError:
        print("\n（输入结束，退出）")
        return None


def print_result(result: dict) -> None:
    """打印最终回答和可观察的 Supervisor 路由证据。"""

    answers = [
        message_text(message)
        for message in result.get("messages", [])
        if isinstance(message, AIMessage) and not message.tool_calls
    ]
    if answers and answers[-1]:
        print(f"\n助手：{answers[-1]}")

    trace = outer_trace(result)
    if trace:
        print("\n[当前会话累计 Supervisor 路由证据]")
        for event in trace:
            if event["type"] == "agent_tool_calls":
                names = [call["name"] for call in event["calls"]]
                print("- 调用 Agent Tool：", "、".join(names))
            else:
                print(f"- 收到 {event['name']} 的返回结果")
                if isinstance(event["content"], str):
                    try:
                        payload = json.loads(event["content"])
                    except json.JSONDecodeError:
                        payload = {}
                    business_tools = payload.get("business_tools", [])
                    if business_tools:
                        print("  内层业务 Tool：", "、".join(business_tools))


def handle_interrupts(
    app: MultiAgentApplication, session: UserSession, result: dict
) -> dict:
    """显示确认内容，并用同一 Thread 恢复暂停的执行。"""

    while interrupts := result.get("__interrupt__", ()):
        # R2（技术方案评审提出，2026-10-08）：一轮里若同时产生多个暂停，本实现与课件一致，
        # **只确认第一个**（`interrupts[0]`），其余仍挂在图上等下一轮 resume。
        # 目前正常流程（一次只写一条）不会触发；这里加一条显式告警，避免将来"以为都处理了"。
        if len(interrupts) > 1:
            print(
                f"\n[警告] 本轮同时有 {len(interrupts)} 个待确认操作，"
                f"本次只处理第 1 个，其余会在此后继续询问。"
            )
        print("\n[需要用户确认]")
        print(
            json.dumps(
                interrupts[0].value,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        answer = ask("确认继续吗？请输入 y 或 n：")
        # EOF 时按"拒绝"处理（保守：绝不因为输入流断了就把写操作放行），
        # 并在循环里继续把后续暂停也拒掉，避免卡在半恢复状态。
        approved = bool(answer) and answer in {"y", "yes", "是", "确认"}

        # 复用原 session，也就是复用原 thread_id 和 Context。
        result = app.resume(session, approved=approved)
    return result


def login_loop(app: MultiAgentApplication) -> None:
    while True:
        username = ask("\n教学账号（/quit 退出）：")
        if username is None or username == "/quit":
            return

        try:
            session = app.start_session(username)
        except (ValueError, PermissionError) as exc:
            print(f"登录失败：{exc}")
            continue

        print(
            f"登录成功：{session.context.display_name} "
            f"({session.context.role})，输入 /logout 切换账号。"
        )
        while True:
            user_text = ask("\n你：")
            if user_text is None:
                return  # 输入流结束（EOF）→ 干净退出，而不是抛 traceback
            if not user_text:
                continue
            if user_text == "/quit":
                return
            if user_text == "/logout":
                break

            try:
                # 固定主流程：运行一轮 -> 处理确认 -> 打印结果。
                result = app.chat(session, user_text)
                result = handle_interrupts(app, session, result)
                print_result(result)
            except Exception as exc:  # noqa: BLE001 —— 单轮失败不退出登录循环
                print(f"本轮执行失败：{type(exc).__name__}: {exc}")


def main() -> None:
    # 过滤一条**无害**的第三方告警（不加这行时，每调用一次带注入参数的工具就打一条）：
    # LangChain 解析工具入参时会对 args_schema 做一次 `model_dump()`
    # （langchain_core/tools/base.py 的 _parse_input），而带 `runtime: ToolRuntime[...]`
    # 的工具，其 schema 把注入的 context 声明为 None；实际值却是 RunContext 对象 ——
    # pydantic 于是发出 PydanticSerializationUnexpectedValue（期望 none，拿到 RunContext）。
    #
    # 为什么可以忽略：这只发生在**入参解析的序列化**上，工具实际收到的仍是真实的
    # RunContext（角色与权限判定全部正常，19 条端到端验收覆盖了这条路径）。
    # 这里**只过滤这一条消息**，不是"忽略所有告警"。
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

    # 环境适配放在入口：库本身不改进程全局状态（正常机器上是空操作）。
    ensure_writable_tempdir()

    # 没有向量库时立即提示，不等到第一次 RAG 查询才报错。
    if not INDEX_MANIFEST_PATH.exists():
        raise RuntimeError(
            "尚未构建向量库，请先运行 build_index.py（uv run python build_index.py）"
        )

    app = MultiAgentApplication()
    print("Day06 多 Agent 新员工助手已启动。")
    login_loop(app)


if __name__ == "__main__":
    main()
