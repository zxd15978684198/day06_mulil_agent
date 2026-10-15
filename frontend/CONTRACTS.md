# P0 契约冻结（Day06 前端）

冻结对象：`frontend/` 与后端 `agent_api.py` 之间的**全部接口事实**。
冻结日期：2026-10-10 · 冻结依据：脚本实测（`.tmp/live_test.txt`）+ 逐行读码。
**本文件一旦冻结，P1–P8 期间不得凭记忆改动；要改必须先改这里并说明理由。**

---

## 一、六条接口契约

### C1 · `trace` 是**线程累计**轨迹，不是本轮增量 ⭐ 已实测

`AgentReply.trace` 来自 `outer_trace(result)`，是**整个 thread** 的累计轨迹。
**实测证据**（`.tmp/live_test.txt`，同一 `session_id` 连发三轮）：

| 轮次 | 请求 | `trace.length` | 内容 |
|---|---|---|---|
| A | `你好` | **0** | `[]` |
| B | 申请一台显示器（带理由） | **1** | `[agent_tool_calls: ask_employee_service_agent]` |
| C | 确认执行 | **2** | `[agent_tool_calls: …（与 B 完全相同）, agent_tool_result: ask_employee_service_agent]` |

结论：**前缀稳定、只追加、永不收缩**。
→ 前端必须用游标切片：`trace.slice(prevLen)`，`prevLen` 取「上一轮响应的 `trace.length`」。

### C2 · `confirmation.action` 是模板分派的**唯一**依据

后端只保证 `confirmation` 对象里有 `action`（字符串）与 `candidate`（对象）。
前端**不得**根据 `candidate` 的字段形状猜 action，也不得假定 `candidate` 一定存在。

### C3 · HTTP 409 = 当前会话有未决确认

触发点：`agent_api.py` 的 `/api/chat` 守卫（`await has_pending_confirmation(session)`）——**判据是检查点里的未决中断位置**，不再是进程内的 `pending_confirmations`（那个集合已随持久化升级删除）。
语义：**必须先把确认处理掉**，不是"网络错误"，不是"重试即可"。

### C4 · HTTP 404 = 会话不存在

`get_session_or_404` 先在 `app.state.sessions`（**进程内缓存**）里找；**查不到时不再直接 404**，
而是按 `agent_threads` + 检查点调 `restore_session()` 重建会话（重建时校验 `login_enabled` /
`account_status` / `role` 三条件），**只有重建也失败才 404**。
因此**后端重启后旧 `session_id` 仍然有效**（→ K4 的前提已改变）。
除 404 外**没有任何"查询会话状态"的接口**，前端无法提前探测会话是否还活着。

### C5 · `approved` 的语义是「是否执行 agent 已决定的动作」

`approved: true` = 执行；`approved: false` = 不执行。
**不是**"这条申请批不批"。UI 文案必须写成「确认执行 / 取消本次操作」，
写「批准 / 驳回」就是把后端语义讲成谎话。

### C6 · 审批那一处 interrupt 的 payload 缺字段（= P1 要修的点）

- **创建**申请那处 interrupt 的 payload **已经齐全**：实测返回的 `candidate` 含
  `applicant_name: "张伟"`、`device_name: "24 英寸显示器"`（来自 `business_tools.py:475-477` 的 `_build_create_candidate`）。
- **审批**那处 interrupt（`business_tools.py:608` `answer = interrupt(payload)`）的 payload 需要补
  `applicant_name` / `device_name` —— 这是 `P1` 的**唯一**后端改动。

---

## 二、九个已知坑（都已在代码里定位）

| 编号 | 坑 | 位置 / 依据 |
|---|---|---|
| K1 | 累计 trace 直接 append 会指数级重复 | C1 实测；A/B/C 三轮已证 |
| K2 | `approved: false` 不是"驳回申请" | C5 |
| K3 | `base` 不按命令切换会**白屏**（资源 404） | `vite.config.ts` D3 |
| K4 | ~~后端重启后 localStorage 里的 `session_id` 变死键~~ **已修复**（持久化升级后按 `agent_threads` + 检查点 `restore_session()` 重建；仅重建失败才 404） | C4 |
| K5 | `emptyOutDir` 会清空 `src/static/`（含原 322 B 占位页） | `vite.config.ts` build 段 |
| K6 | 待确认期间 `/api/chat` 返回 409 | C3 |
| K7 | `confirmation` 可能退化成 `{"message": ...}` 而非结构化候选 | `agent_api.py:112` 的非 dict 兜底 |
| K8 | `answer` 为 `null` 的那一轮**没有助手气泡** | `agent_api.py:113-114`；实测 B 轮 `"answer": null` |
| K9 | CORS `allow_methods` 只有 `GET`/`POST` | `agent_api.py:71` |

---

## 三、构建契约（frontend 侧）

| 编号 | 决定 | 理由 |
|---|---|---|
| D1 | 源码在 `frontend/`，构建产物落 `src/static/` | `paths.py:42 STATIC_DIR = SRC_ROOT / "static"` |
| D2 | 不引入 react-router | 只有两个视图（登录 / 对话），状态机比路由简单 |
| D3 | `base` 按 `command` 切换：dev `/`，build `/static/` | FastAPI 把 `src/static` 挂在 `/static` |
| D4 | dev 下 `/api` 代理到 `127.0.0.1:8000`；前端代码只写相对路径 | 免 CORS、免硬编码主机 |
| D5 | 产物 `outDir: '../src/static'`，`emptyOutDir: true` | 构建即替换（K5 是预期行为） |
| D6 | **后端改动边界：只允许 `business_tools.py` 的 P1 一处** | 见下节待裁决项 |

---

## 四、待裁决项（P0 停点时需要一句话）

1. **`agent_api.py:158` 的 `async def confirmation_action`**：它内部同步调用
   `agent.resume()`，会把整个事件循环阻塞几十秒（期间所有并发请求全部排队）。
   修它只需把 `async def` 改成 `def`（一行），但**碰了 `agent_api.py`，与 D6「只动 business_tools.py」冲突**。
   选项：(a) 纳入允许清单一起修；(b) 不改，记为本项目已知限制。
2. **数据文件基线**：`src/data/day05_device_requests.json` 当前 19 条、8420 B、git 状态为 ` M`（既有脏状态）。
   现已备份到 `.tmp/day05_device_requests.backup.json`（sha256 一致）。
   需要确认：P5–P8 联调期间每轮跑完是否都要还原到这份基线。

---

## 五、本阶段实测复现方式

```powershell
# 后端（另开一个进程）
uv run python -m uvicorn personal_assistant.agent_api:app --host 127.0.0.1 --port 8000
# 前端
cd frontend; npm run dev        # http://127.0.0.1:5173
```
端到端脚本（含备份/还原）：`.tmp/live_test.ps1` → 结果 `.tmp/live_test.txt`。

---

## 六、流式接口契约（P11 新增 · 2026-10-12 实测）

### C7 · 对话改走 `POST /api/chat/stream`（SSE），`POST /api/chat` 已 404 ⭐ 已实测

`agent_api.py` 的 `@app.post("/api/chat")`（原 149–167 行）被**整段注释掉**，OpenAPI 里也没有它。
实测 `GET /openapi.json` 只有三条路由：`/api/sessions`、`/api/chat/stream`、`/api/confirmation`。
→ 前端主链路**必须**走流式；`lib/api.ts` 里旧的 `chat()` 已删除，改用 `streamChat()`。

帧格式 `event:<name>\ndata:<json>\n\n` —— 注意 **`data:` 后没有空格**（`sse_event()` 在 `agent_api.py`）。

| `event` | `data` | 出处 |
|---|---|---|
| `status` | `{"message":"Agent 已经开始处理"}` | `agent_api.py:232`，流一建立就发 |
| `text_delta` | `{"text":"…"}` | 正常路径逐 token；兜底路径整段一条 |
| `tool_start` | `{"name":"knowledge_agent","label":"知识 Agent"}` | 三个专家：`knowledge_agent` / `employee_service_agent` / `hr_agent` |
| `tool_end` | 同 `tool_start` | |
| `tool_error` | `{"name":…,"label":…,"message":"… Agent 调用失败"}` | 专家内部异常（interrupt 误报已修） |
| `confirmation` | interrupt 载荷（形状规则同 C2 / K7） | `multi_agent.py:500` |
| `done` | `{"status":"completed" \| "waiting_confirmation"}` | `agent_api.py:250-256` |
| `error` | `{"message":"…"}` | 超时 / agent 失败，之后流即关闭 |

### C8 · 流里**没有** `trace` 事件 ⭐ 已实测

`trace` 只由 `/api/confirmation` 返回的 `AgentReply` 提供。
→ 走流的正常轮次，右栏**拿不到完整轨迹**，只能用流里的 agent 级事件拼一个简版
（`LiveTraceRail` 的 `steps`）。要保住完整轨迹得让后端在 `done` 之前补一个 `trace` 事件 —— **待裁决**。

### C9 · 流的收尾只能靠事件表达，**改不了 HTTP 状态码**

响应头在第一个字节就发出去了。流建立之后的失败（超时、模型报错）只能是流里的一条 `error` 事件，
所以前端必须**同时**接 `onStreamError` 和函数返回值，只 `try/catch` 会漏。
HTTP 层错误（401/404/409/503）仍照旧抛 `ApiError`，四态语义不变。

### K10 · `STREAM_TIMEOUT_SECONDS` 服务端硬超时，默认 90 秒

`asyncio.timeout(int(os.getenv("STREAM_TIMEOUT_SECONDS", 90)))`。
首次知识问答要冷启动嵌入模型（实测约 **27 秒**），再叠加 supervisor / 专家 / 汇总三次模型调用，
冷进程下会逼近甚至超过 90 秒；一超时就发 `error` 并关闭流（前端表现为"回答中断"）。

### K11 · chromadb 的进程级全局被毒化后**永久失效**（既有缺陷 `N2`）

```
File "chromadb/api/shared_system_client.py", line 49, in _create_system_if_not_exists
    return cls._identifier_to_system[identifier]
KeyError: 'E:\\projects\\mutil_agent\\src\\vector_store'
```

实测：一旦某次知识问答失败（例如撞上 K10 超时），**该进程之后所有**知识问答都会在
`_open_vector_store()` 处这样失败，只能重启后端。**这是后端缺陷，前端无法规避。**
