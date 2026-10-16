"""把异步的 `MultiAgentApplication.chat` / `resume` 包成同步调用。

为什么需要它：持久化升级把这两个方法改成了 `async`（`AsyncSqliteSaver` 只有异步
接口），而三个既有测试文件是同步写的、共二十多处调用点。逐个把它们改成 async 会
牵动这些文件的主流程与断言结构，风险大于收益；这里只加一层薄适配，调用点在字面上
不用动。

**关键：全程共用一个长期存活的事件循环，而不是每次 `asyncio.run()`。**
首版用 `asyncio.run()`，每次新建/销毁一个循环，理由是"这些测试的检查点是
`InMemorySaver`、没有跨循环的连接状态" —— **这条假设被实测推翻**：模型客户端的
HTTP 连接池是在第一次 `chat()` 里、绑在**那一个**循环上建立的；循环一关，池里的
连接就属于一个已经死掉的循环，第二次调用新建的循环再去用它，收尾时抛
`RuntimeError: Event loop is closed`。`acceptance_day06.py` 的 20 条断言里有 5 条
因此失败（`[13] [5] [16] [7] [10]`），全是"同一进程内连续多轮调用"的场景。
所以现在改成：一个进程一个循环，创建后不再关闭，所有同步调用都在它上面
`run_until_complete`。

边界：本薄壳只给同步测试用。**真正的持久化验收不在这些文件里** —— 它在
`acceptance_persistence.py`，那里全程跑在同一个事件循环内，并且真的关掉再打开
SQLite 连接来验证"重启后还在"。
"""

from __future__ import annotations

import asyncio
from typing import Any

from personal_assistant.multi_agent import MultiAgentApplication


class SyncApplication:
    """只代理 `chat` / `resume` 的薄壳，其余属性照原样透传。"""

    def __init__(
        self,
        app: MultiAgentApplication,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._app = app
        self._loop = loop or asyncio.new_event_loop()
        # 让库内部任何 asyncio.get_event_loop() 拿到的都是这一个循环
        asyncio.set_event_loop(self._loop)

    def __getattr__(self, name: str) -> Any:
        # 透传 `model`、`_build_supervisor`、`start_session` 等一切同步成员
        return getattr(self._app, name)

    def _run(self, coro: Any) -> Any:
        if self._loop.is_closed():
            raise RuntimeError("SyncApplication 的事件循环已关闭 —— 不要手动 close 它")
        if self._loop.is_running():
            raise RuntimeError("不能在已运行的事件循环里调用 SyncApplication（它是给同步测试用的薄壳）")
        return self._loop.run_until_complete(coro)

    def chat(self, session: Any, user_text: str) -> dict[str, Any]:
        return self._run(self._app.chat(session, user_text))

    def resume(self, session: Any, approved: bool) -> dict[str, Any]:
        return self._run(self._app.resume(session, approved=approved))

    def close(self) -> None:
        """收尾关掉循环。可选：不调也不会出错（进程退出时回收）。"""
        if not self._loop.is_closed():
            self._loop.close()
