"""命令行入口：登录循环、多轮对话、人工确认与路由证据打印。

课件 §10.3–§10.5 的实现，按 §5.2 改写两处 import（`knowledge_base` /
`multi_agent` → 全包名），并在启动时做一次环境适配（本机 `%TEMP%` 对子进程
不可写，chromadb 需要可写的临时目录；正常机器上该调用是空操作）。

固定字符串（提示语、`/quit`、`/logout`、确认输入集）照课件原样，验收会断言它们。
"""

from __future__ import annotations

import json

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
        print("\n[需要用户确认]")
        print(
            json.dumps(
                interrupts[0].value,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        answer = input("确认继续吗？请输入 y 或 n：").strip().lower()
        approved = answer in {"y", "yes", "是", "确认"}

        # 复用原 session，也就是复用原 thread_id 和 Context。
        result = app.resume(session, approved=approved)
    return result


def login_loop(app: MultiAgentApplication) -> None:
    while True:
        username = input("\n教学账号（/quit 退出）：").strip()
        if username == "/quit":
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
            user_text = input("\n你：").strip()
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
