"""状态持久化升级的验收（计划 §9.1 的 V3–V7）。

与 `acceptance_day06.py` 的关系：那份验的是 Day06 的业务行为（19 个场景），
本份验的是**本次升级新增的能力**，两不重叠。

覆盖项：
* `V3` 四张业务表行数与基线一致
* `V4` 重启后普通对话仍有历史（换一份新连接、应用实例不共享内存）
* `V5` 重启后未决确认仍可完成，且不能重复提交
* `V6` 员工查不到他人申请、HR 能查到全部（权限闸门仍在 Tool 层）
* `V7` 生产代码里不再出现内存 Saver 与 JSON 写路径

`V4`／`V5` 必须**真的重启**：先关掉 SQLite 检查点连接，再用新连接新实例读回来。
一个进程内"看起来还在"是内存态，不算持久化 —— 这正是本次升级要消灭的假象。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # 让 `import db_state` 可用

import db_state  # noqa: E402
from langchain.tools import ToolRuntime  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402

from personal_assistant import business_tools as bt  # noqa: E402
from personal_assistant.knowledge_base import ensure_writable_tempdir  # noqa: E402
from personal_assistant.multi_agent import MultiAgentApplication  # noqa: E402
from personal_assistant.paths import RUNTIME_DIR  # noqa: E402

BASELINE = {"departments": 10, "users": 27, "devices": 12, "device_requests": 19}
RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print("       " + detail.replace("\n", "\n       "))


def runtime_for(username: str) -> ToolRuntime:
    """按用户名造一个可信 Context 的 ToolRuntime（与 acceptance_day06 同法）。"""

    user = db_state.login_user(username)
    context = bt.RunContext(
        user_id=user["user_id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
        department_id=user["department_id"],
    )
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


async def _unused() -> None:
    pass


def call(tool_obj: Any, payload: dict) -> dict:
    """调一个业务 Tool；`runtime` 按 acceptance_day06 的同一约定放进 payload。"""

    import json

    return json.loads(tool_obj.invoke(payload))


def check_v3() -> None:
    counts = db_state.table_counts()
    ok = all(counts[k] == v for k, v in BASELINE.items())
    record("V3 四张业务表行数与基线一致", ok, f"实测 {counts} / 基线 {BASELINE}")


def check_v7() -> None:
    """生产代码里不许再出现内存 Saver 与 JSON 写入路径。

    扫描刻意走 **AST** 而不是逐行正则：`InMemorySaver`、`device_requests.json` 这些
    字样在注释与文档字符串里出现是**说明历史**（"以前是这么写的"），把它们判违规
    会让检查变成"谁也别提旧实现"。真正要拦的是**代码里的引用**。
    """

    import ast

    banned_names = {
        "InMemorySaver",
        "DEVICE_REQUESTS_PATH",
        "_save_requests",
        "_next_request_id",
        "_load_document",
        "_load_users",
        "_load_devices",
        "_load_requests",
        "login_as",
    }
    hits: list[str] = []

    for path in sorted((REPO_ROOT / "src" / "personal_assistant").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                body = getattr(node, "body", [])
                first = body[0] if body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))

        for node in ast.walk(tree):
            rel = path.relative_to(REPO_ROOT)
            if isinstance(node, ast.Name) and node.id in banned_names:
                hits.append(f"{rel}:{node.lineno}: 代码引用了 `{node.id}`")
            elif isinstance(node, ast.Attribute) and node.attr in banned_names:
                hits.append(f"{rel}:{node.lineno}: 代码引用了 `.{node.attr}`")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and "device_requests.json" in node.value
            ):
                hits.append(
                    f"{rel}:{node.lineno}: 代码里的字符串仍指向 `device_requests.json`"
                )

    record(
        "V7 无内存 Saver 与 JSON 写路径",
        not hits,
        "\n".join(hits)
        if hits
        else "AST 扫描 src/personal_assistant/**/*.py：0 处代码引用（注释/文档字符串不计）",
    )


def check_v6() -> None:
    """员工只能看到自己的申请；HR 能看到全部。"""

    mine = call(bt.query_device_requests, {"runtime": runtime_for("zhang_wei")})
    all_of_hr = call(bt.query_device_requests, {"runtime": runtime_for("wang_fang")})
    employee_rows = (mine.get("data") or {}).get("requests", [])
    hr_rows = (all_of_hr.get("data") or {}).get("requests", [])
    leaked = [r for r in employee_rows if r.get("applicant_user_id") != "USR-001"]
    applicants = {r.get("applicant_user_id") for r in hr_rows}
    ok = (
        bool(employee_rows)
        and not leaked
        and len(hr_rows) > len(employee_rows)
        and len(applicants) > 1
    )
    record(
        "V6 权限闸门：员工只见本人 / HR 见全部",
        ok,
        f"员工可见 {len(employee_rows)} 条（越权 {len(leaked)} 条）/ "
        f"HR 可见 {len(hr_rows)} 条、涉及 {len(applicants)} 个申请人",
    )


async def check_v4() -> None:
    """重启后普通对话仍有历史。"""

    sqlite_path = Path(tempfile.mkdtemp(prefix="v4-")) / "checkpoints.sqlite3"

    async with AsyncSqliteSaver.from_conn_string(str(sqlite_path)) as cp1:
        app1 = MultiAgentApplication(checkpointer=cp1)
        session1 = app1.start_session("zhang_wei")
        thread_id = session1.thread_id
        result = await app1.chat(session1, "公司介绍里说北京总部主要承担哪些职能？")
        before = len(result.get("messages", []))

    # ——— 重启：新连接、新实例，进程内存里什么都没有 ———
    async with AsyncSqliteSaver.from_conn_string(str(sqlite_path)) as cp2:
        app2 = MultiAgentApplication(checkpointer=cp2)
        restored = app2.restore_session(thread_id)
        if restored is None:
            record(
                "V4 重启后普通对话仍有历史",
                False,
                "restore_session 返回 None（线程索引没落库？）",
            )
            return
        snapshot = await restored.supervisor.aget_state(app2._config(restored))
        after = len(snapshot.values.get("messages", []))
        same_thread = restored.thread_id == thread_id
        # 索引也验一次：同一账号再登录应当复用同一个 thread_id
        again = app2.start_session("zhang_wei", restore=True)
        reused = again.thread_id == thread_id

    ok = same_thread and after == before and after > 0 and reused
    record(
        "V4 重启后普通对话仍有历史",
        ok,
        f"thread_id 一致={same_thread} / 消息数 重启前 {before} → 重启后 {after} / "
        f"agent_threads 复用同一线程={reused} / sqlite={sqlite_path.parent.name}",
    )


async def check_v5() -> None:
    """重启后未决确认仍可完成，且不能重复提交。"""

    sqlite_path = Path(tempfile.mkdtemp(prefix="v5-")) / "checkpoints.sqlite3"
    # 验收会把申请表的条数改掉（这正是要验的"确认后新增 1 条"），跑完必须还原，
    # 否则每跑一次基线就漂一次，V3 会自己把自己跑红。
    backup_path = REPO_ROOT / ".tmp" / "acceptance_persistence_v5_backup.json"
    db_state.dump_requests_backup(backup_path)
    baseline = db_state.requests_snapshot()[2]

    try:
        async with AsyncSqliteSaver.from_conn_string(str(sqlite_path)) as cp1:
            app1 = MultiAgentApplication(checkpointer=cp1)
            session1 = app1.start_session("zhang_wei")
            thread_id = session1.thread_id
            await app1.chat(
                session1, "请帮我申请一台 24 英寸显示器，数量 1，理由是双屏对比原型。"
            )
            pending_before = await app1.has_pending_confirmation(session1)
            after_chat = db_state.requests_snapshot()[2]

        async with AsyncSqliteSaver.from_conn_string(str(sqlite_path)) as cp2:
            app2 = MultiAgentApplication(checkpointer=cp2)
            restored = app2.restore_session(thread_id)
            if restored is None:
                record(
                    "V5 重启后未决确认可完成且不可重复提交",
                    False,
                    "restore_session 返回 None",
                )
                return
            pending_after = await app2.has_pending_confirmation(restored)
            await app2.resume(restored, approved=True)
            after_resume = db_state.requests_snapshot()[2]
            still_pending = await app2.has_pending_confirmation(restored)

            duplicate_blocked = False
            try:
                await app2.resume(restored, approved=True)
                # 没有抛错也不许再写一条：条数必须保持不变
                duplicate_blocked = db_state.requests_snapshot()[2] == after_resume
            except Exception:  # noqa: BLE001 —— 抛错同样是"拒绝了重复提交"
                duplicate_blocked = True
            after_duplicate = db_state.requests_snapshot()[2]

        checks = {
            "对话后停在确认上": pending_before,
            "确认前没有写库": after_chat == baseline,
            "重启后仍是未决": pending_after,
            "确认后新增 1 条": after_resume == baseline + 1,
            "确认后不再未决": not still_pending,
            "重复提交不再新增": duplicate_blocked and after_duplicate == after_resume,
        }
        record(
            "V5 重启后未决确认可完成且不可重复提交",
            all(checks.values()),
            f"申请表条数 {baseline} →（对话后）{after_chat} →（确认后）{after_resume} →（重复提交后）{after_duplicate}\n"
            + "\n".join(f"{k}: {v}" for k, v in checks.items()),
        )
    finally:
        restored_rows = db_state.load_requests_backup(backup_path)
        print(f"       [清理] 申请表已从备份还原为 {restored_rows} 条")


async def main() -> int:
    # 与两个入口脚本一致：本机 %TEMP% 对子进程不可写时，chromadb 打不开向量库。
    # 这一步同时是"测试也必须走入口同一套环境适配"的提醒。
    ensure_writable_tempdir()

    print("=" * 72)
    print("状态持久化升级验收（V3–V7）")
    print("=" * 72)
    check_v3()
    check_v7()
    check_v6()
    await check_v4()
    await check_v5()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("-" * 72)
    print(f"结果：{passed}/{len(RESULTS)} 通过")
    for name, ok, _ in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    raise SystemExit(asyncio.run(main()))
