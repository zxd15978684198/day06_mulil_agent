wo# 星桥科技 · 新员工助手（多 Agent）

> Week15 / Day06 教学项目。基于 **LangChain 1.4 + LangGraph 1.2**，用
> **Supervisor + Agent-as-Tool** 架构做一个新员工助手：既能按角色查公司制度知识库，
> 也能完成「设备申请 → HR 审批」的完整业务闭环，写操作前必须人工确认。
>
> 交付三种形态：**CLI**、**FastAPI 后端**、**React 单页前端**（由同一个 FastAPI 托管）。

一句话看清它是什么：

```
                        ┌─ CLI（终端登录循环）─────────────────┐
员工/HR ──► 三种入口 ────┼─ Web（React SPA + SSE 流式输出）─────┤──► Supervisor（只持 Agent Tool）
                        └─ HTTP API（/docs 可直接调）─────────┘        ├─ ask_knowledge_agent        ──► search_company_knowledge（按角色过滤的向量检索）
                                                                      ├─ ask_employee_service_agent ──► 查部门 / 找联系人 / 查设备 / 建设备申请 / 查自己的申请
                                                                      └─ ask_hr_agent（仅 hr 可见）  ──► 查全部申请 / 批准或拒绝
```

---

## 目录

- [1. 交付状态](#1-交付状态)
- [2. 三种运行形态](#2-三种运行形态)
- [3. 架构](#3-架构)
- [4. 目录结构](#4-目录结构)
- [5. 快速开始](#5-快速开始)
- [6. Web API 契约](#6-web-api-契约)
- [7. 交互说明](#7-交互说明)
- [8. 权限模型（三层）](#8-权限模型三层)
- [9. 测试与验收](#9-测试与验收)
- [10. 数据与知识契约](#10-数据与知识契约)
- [11. 依赖](#11-依赖)
- [12. 已知限制](#12-已知限制)
- [13. 排查手册](#13-排查手册)
- [14. 文档索引](#14-文档索引)

---

## 1. 交付状态

| 项 | 状态 |
| --- | --- |
| 后端 6 个施工阶段（P0–P9） | 全部执行完毕 |
| 阶段通过信号 `tests` | **12/12 PASS**（A1–A7 确定性 + B1–B5 真实模型）——项目记录 |
| §8 端到端验收 `tests` | **20/20 PASS**——项目记录，⚠️ **见下方数据基线警告，现已失效** |
| 前端 `P0`–`P11`（含三档追加需求） | 全部执行完毕，阶段证据见 [`frontend/test/`](frontend/test/README.md) |
| 索引 | 10 份资料 / 36 chunk / 解析失败 0 |
| 业务数据 | 设备申请（真源 = MySQL `agent_service.device_requests` 表；条数随验收/网页测试漂移，**以库中实际为准**） |

**这不是「课件代码照抄」**：目录布局改成了 src 布局，路径解析、权限过滤、切分参数、
模型构造等处都有对课件的有意偏离，**每一条都登记在
[`docs/plans/Day06_执行计划_v2.md`](docs/plans/Day06_执行计划_v2.md) 的「变更记录 C1–C12」**；
前端对 `frontend/` 与后端接口的每一条约定都冻结在
[`frontend/CONTRACTS.md`](frontend/CONTRACTS.md)（`C1`–`C9` 契约 / `K1`–`K11` 坑 / `D1`–`D6` 构建契约）。

### 数据基线：以库为真源（跑验收前必读）

写入目标是 **MySQL `agent_service.device_requests` 表**；`src/data/*.json` 已退为历史基线、运行期不再读写。

* **不需要为了跑测试手工删任何数据。** `acceptance_day06.py` 开始时自己备份
  （`db_state.dump_requests_backup()`）、结束时自己还原（`load_requests_backup()`），并打印前后
  `(内容长度, sha256前16位, 行数)` 三元组；`verify_phase5.py` / `verify_phase4_repro.py` 是**只读**的，
  用同一摘要前后比对自证。
* **不要在任何文档或断言里写死总条数** —— 它会在每次验收/网页联调后漂移（历史值：19 → 20）。
  稳定的不变量是**按用户过滤后的条数**：`USR-001`（`zhang_wei`）名下 **4 条**
  （`0001`/`0003`/`0015`/`0019`）。场景 13/16 的断言已按这个不变量写死（`acceptance_day06.py` 的 s13/s16），
  按编号逐个核对，多一条少一条都会 FAIL。
* 历史遗留：`README` 与 `frontend/CONTRACTS.md` 曾各自登记 18 条 / 19 条的 **JSON** 基线并互相冲突；
  **该冲突随「JSON 不再是写目标」一并失效**——两份数字只用于历史比对，不再是验收前置条件。

---

## 2. 三种运行形态

| 形态 | 入口 | 适用 |
| --- | --- | --- |
| **CLI** | `uv run python main.py` | 课件主线、看路由证据最直观 |
| **Web（开发）** | FastAPI `:8000` + Vite `:5173` | 改前端代码，HMR 生效 |
| **Web（生产）** | 只跑 FastAPI `:8000` | 前端已构建进 `src/static/`，单端口 |

三者**共用同一套 `MultiAgentApplication`**，也共用同一份业务数据。命令见 §5。

---

## 3. 架构

### 3.1 为什么是 Agent-as-Tool

Supervisor **只**持有 Agent Tool，不直接持有任何业务 Tool；每个专业 Agent 只持有本职业务
Tool。好处是：Supervisor 的上下文里不出现业务细节，专业 Agent 之间也不会互相串工具。

### 3.2 四个数据平面（**刻意不合并**）

| 平面 | 装什么 | 机制 |
| --- | --- | --- |
| `messages` | 用户自然语言 | LangGraph state |
| `RunContext` | **可信**的 `user_id` / `role` / `department_id` | frozen dataclass，由应用注入，**聊天内容改不了它** |
| Checkpointer | 每个 thread 的消息历史与中断位置 | `AsyncSqliteSaver`（位置由 `CHECKPOINT_DB` 决定，默认 `runtime/checkpoints.sqlite3`），按 `thread_id` 索引，**跨重启保留**；应用启动时开一次、被所有 Supervisor 共享 |
| 业务数据 | 申请编号、状态 | MySQL 库 `agent_service`（SQLAlchemy ORM；账号 `agent_app` 只有 SELECT/INSERT/UPDATE/DELETE）。`src/data/*.json` 已退为**历史基线**，运行期不再读写 |

切账号 = 新 `RunContext` + 新 Supervisor + 新 `thread_id`（**对话历史不跨账号**），
但业务数据是共享的 —— 所以 HR 仍能查到员工刚提交的申请。

### 3.3 人工确认闭环

写操作（提交申请、审批）在业务 Tool 内部调用 LangGraph 的 `interrupt()` 暂停：

```
Supervisor ─► Agent Tool ─► 专业 Agent ─► 业务 Tool ─► interrupt(载荷)
                                                            │  一路冒泡到父图
CLI：打印载荷并问 y/n ─► Command(resume={"approved": True/False}) ─► 同一 thread_id 恢复
Web：ConfirmationCard ─► POST /api/confirmation ────────────────────┘
```

* **必须复用原 `thread_id` 与 Context**，否则恢复不了；
* `approved=False` 时**不落盘**（`verify_phase5.py` 的 B3 专门验这点）；
* 拒绝后模型有时会**重试**同一写操作 → 会再次暂停。这是模型行为，CLI 的
  `handle_interrupts()` 是 `while` 循环，会再问一次。

### 3.4 Web 层（`agent_api.py` + `frontend/`）

```
浏览器（React SPA，src/static/ 由 FastAPI 托管在 /static）
   │  POST /api/sessions       登录        → { session_id, display_name, role }
   │  POST /api/chat/stream    SSE 对话    → status/text_delta/tool_*/confirmation/done/error
   │  POST /api/confirmation   人工确认    → AgentReply（含 trace）
   ▼
FastAPI（agent_api.py）
   ├─ lifespan：检查索引存在 → 否则**启动即失败**；同时开**共享** `AsyncSqliteSaver`（退出时 `engine.dispose()`）
   ├─ app.state.agent ：全进程**一个** MultiAgentApplication（复用 embedding 模型，不每请求重建）
   └─ app.state.sessions / active_streams ：**进程内缓存**（重启即空，但**会话不再依赖它**）
       └─ 缓存未命中 → 按 `agent_threads` + 检查点 `restore_session()` 重建；待确认状态**读检查点**（原 `pending_confirmations` 已删除）
```

三个关键设计（详见 [`frontend/CONTRACTS.md`](frontend/CONTRACTS.md)）：

* **`trace` 是线程累计、不是本轮增量** —— 前缀稳定、只追加、永不收缩。前端必须用游标切片
  `trace.slice(prevLen)`，直接 `append` 会指数级重复（契约 `C1` / 坑 `K1`）。
* **`approved` 的语义是「是否执行 agent 已决定的动作」**，不是「这条申请批不批」。
  所以 UI 文案是「确认执行 / 取消本次操作」，写成「批准 / 驳回」就是把后端语义讲成谎话（`C5`）。
* **走 SSE 的轮次拿不到完整 trace** —— 流里没有 `trace` 事件（`C8`），正常轮次的右栏只能用
  agent 级事件拼一个简版（`LiveTraceRail`）；完整轨迹只在 `/api/confirmation` 的响应里。
  前端**已经预留**了 `trace` 事件处理（`frontend/src/lib/api.ts:262-263`），后端只要在 `done`
  之前补发一个即可生效，不必改前端。

---

## 4. 目录结构

```
mutil_agent/
├── README.md                     ← 本文件
├── pyproject.toml / uv.lock      ← 依赖（发行名 mutil-agent，import 包名 personal_assistant）
├── requirements.txt              ← 直接依赖钉子（本仓库用 uv，不要用 pip -r）
├── .env.example                  ← 配置模板；复制成 .env 后填真实密钥
├── main.py / build_index.py      ← 3 行薄壳，保证 `uv run python main.py` 仍可用
├── docs/                         ← 课件 + 计划 + CLI 文档 + Web/前端文档（见 §14）
├── frontend/                     ← React 单页应用源码（Vite）
│   ├── CONTRACTS.md              ← ⭐ 接口事实的唯一权威：C1–C9 / K1–K11 / D1–D6
│   ├── vite.config.ts            ← dev 代理 /api→:8000；build 产物流向 ../src/static
│   ├── tsconfig*.json / .oxlintrc.json / components.json
│   │                             ← TS 工程引用、lint 规则、shadcn 解析配置
│   ├── public/favicon.svg
│   ├── README.md                 ← ⚠️ 未改动的 Vite 模板 README，不是本项目文档
│   ├── src/
│   │   ├── main.tsx / App.tsx    ← 挂载点；登录 ↔ 对话的二态状态机（无 react-router）
│   │   ├── index.css             ← Tailwind 4 + 四套主题令牌
│   │   ├── components/           ← LoginView / ChatView / SessionPanel / TracePanel /
│   │   │                            LiveTraceRail / MessageBubble / ConfirmationCard /
│   │   │                            PanelSection / ThemeSwitcher
│   │   └── lib/                  ← api.ts（HTTP）/ sse.ts（SSE 帧解析）/ typewriter.ts（打字机）
│   │                                session.ts / history.ts / trace.ts（游标切片）
│   │                                theme.ts / layout.ts（侧栏与快捷键）/ utils.ts
│   └── test/                     ← P0–P11 阶段流程文档 + shots/ 真机截图 + logic-check.ts
└── src/
    ├── personal_assistant/       ← 可安装代码（唯一进 wheel 的目录）
    │   ├── paths.py              ← 唯一的路径来源 + 布局 fail-fast 断言
    │   ├── knowledge_base.py     ← 解析/OCR/多模态 → 切分 → 建库 → 按角色过滤的检索；模型构造
    │   ├── business_tools.py     ← RunContext / 权限表 / login_as / 7 个业务 Tool
    │   ├── multi_agent.py        ← 3 个专业 Agent + Agent Tool + Supervisor + MultiAgentApplication
    │   ├── main.py               ← CLI：登录循环、中断确认、路由证据打印
    │   ├── build_index.py        ← 建库入口
    │   ├── agent_api.py          ← ⭐ FastAPI 入口：3 条业务路由 + SSE + 静态托管
    │   ├── schemas.py            ← 请求/响应 Pydantic 模型（LoginRequest/ChatRequest/…）
    │   └── __main__.py           ← 支持 `python -m personal_assistant`
    ├── data/                     ← 4 份业务 JSON（**历史基线，运行期不再读写**；真源是 MySQL `agent_service`）
    ├── runtime/                  ← `checkpoints.sqlite3`（会话检查点，`CHECKPOINT_DB` 指定；已 gitignore）
    ├── knowledge/                ← 10 份知识文件 + day05_knowledge_manifest.json
    ├── vector_store/             ← Chroma 索引 + index_manifest.json（可用 build_index.py 重建）
    ├── static/                   ← ⭐ 前端**构建产物**（index.html + assets/），FastAPI 挂在 /static
    └── test/                     ← 三个测试脚本 + README（不参与打包）
```

> ⚠️ `tests` 会遮蔽标准库的 `test` 包（`src` 在 `sys.path` 上）。对本项目无影响，
> 但如果日后要 `import test.*`，需把目录改名（惯例 `tests/`）。

---

## 5. 快速开始

前置：Windows / Linux 均可，**Python 3.13**，装了 [uv](https://docs.astral.sh/uv/) 与 **Node.js**（前端）。
**本仓库的 `.venv` 由 uv 创建、内部没有 pip** —— 请一律用 `uv run`，不要用 `pip install -r`。

```bash
# 1) 安装依赖（会创建 .venv）
uv sync

# 2) 配置密钥
copy .env.example .env          # Windows；Linux 用 cp
#   然后填 MODEL_PROVIDER / MODEL_NAME / API_KEY / BASE_URL
#   多模态（导览图、海报）另填 VISION_*，留空则回落用聊天模型

# 3) 建向量库（必须先做；约 2–3 分钟，首次会下载 embedding 模型）
uv run python build_index.py
```

### 5.1 跑 CLI

```bash
uv run python main.py
#   等价写法（证明 src 布局与 CWD 无关）：
uv run python -m personal_assistant
```

### 5.2 跑 Web（开发形态）

```bash
# 终端 1 —— 后端 :8000
uv run python -m uvicorn personal_assistant.agent_api:app --host 127.0.0.1 --port 8000

# 终端 2 —— 前端 :5173
cd frontend && npm install && npm run dev      # → http://localhost:5173
```

* **用 `localhost:5173`，不要用 `127.0.0.1:5173`** —— Vite 默认不绑 `127.0.0.1`；
* frontend 的 `/api` 已代理到 `127.0.0.1:8000`（`vite.config.ts:26-30`），前端代码里只写相对路径
  `/api/...`，因此**不触发 CORS**；
* 本机 `%TEMP%` 对子进程不可写时，先设 `$env:TEMP`/`$env:TMP` 指向项目内 `.tmp/`（见 §12.3）。

### 5.3 跑 Web（生产形态，单端口）

```bash
cd frontend && npm run build      # 产物落到 ../src/static/，资源前缀 /static/
# 浏览器直接开 http://127.0.0.1:8000/ ，不经过 Vite
```

⚠️ `build.outDir: '../src/static'` + `emptyOutDir: true` —— **每次 build 会清空 `src/static/`**（契约 `K5`，是预期行为）。

### 5.4 接口自测

FastAPI 自带 `/docs`（Swagger UI），三条业务路由都能直接调；`/` 返回前端 `index.html`。

### 5.5 环境变量（`.env`）

| 变量 | 说明 |
| --- | --- |
| `MODEL_PROVIDER` / `MODEL_NAME` | 聊天模型。**注意**：本项目用 `ChatDeepSeek` 客户端（见 §12.1），`MODEL_PROVIDER` 目前只用于**配置校验**，不决定客户端类 |
| `API_KEY` / `BASE_URL` | OpenAI 兼容端点。若网关注册会话，客户端会自动带 `x-opencode-session`（每个会话一个） |
| `VISION_MODEL_PROVIDER` / `VISION_MODEL_NAME` | 多模态接口（导览图、海报）。**两个都不填**时回落到聊天模型，`index_manifest.json` 记 `config_source=vision_fallback` |
| `VISION_API_KEY` / `VISION_BASE_URL` | 留空则分别回落用 `API_KEY` / `BASE_URL` |
| `EMBEDDING_MODEL` | Hugging Face 模型名，默认 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，**首次建库会下载** |
| `HF_ENDPOINT` | 可选。huggingface.co 不可达时改镜像，如 `https://hf-mirror.com` |
| `STREAM_TIMEOUT_SECONDS` | 可选，SSE 流的服务端硬超时，默认 **90** 秒（见 §12.2） |

**教学账号**（`src/data/day05_users.json` 里 27 人、**10 人可登录**）：

| 用户名 | 角色 | 部门 |
| --- | --- | --- |
| `zhang_wei` | `employee` | 产品部 |
| `wang_fang` | `hr` | 人力资源部 |

> ⚠️ **输入的是英文 `username`，不是中文姓名** —— 输「张伟」会报
> 「登录失败：未找到可登录的教学账号」。
> 全部 10 个可登录账号（`wang_fang` / `zheng_kai` / `zhang_wei` / `li_na` / `chen_hao` /
> `liu_yang` / `zhao_min` / `zhou_jie` / `sun_yue` / `wu_ting`）与踩坑说明见
> [`docs/指导文档/CLI_使用与实现流程.md`](docs/指导文档/CLI_使用与实现流程.md) §3；
> 另外 17 条 `EMP-*` 记录没有 `username`，**设计上就登不进来**。

---

## 6. Web API 契约

以 `src/personal_assistant/agent_api.py` 的实现为准。**实际只有 3 条业务路由**：

| 方法 | 路径 | 请求 | 响应 | 说明 |
| --- | --- | --- | --- | --- |
| `POST` | `/api/sessions` | `LoginRequest` | `LoginResponse` | 登录。`session_id` 就是 LangGraph 的 `thread_id`；用户不存在返回 **401** |
| `POST` | `/api/chat/stream` | `ChatRequest` | **SSE 流** | 对话主链路。404 会话不存在、409 有待确认操作、409 上一条流未结束 |
| `POST` | `/api/confirmation` | `ConfirmRequest` | `AgentReply` | 人工确认。404 会话不存在、409 无待确认、503 agent 失败 |
| `GET` | `/` | — | `src/static/index.html` | 前端入口 |
| `GET` | `/static/*` | — | 静态资源 | 构建产物 |
| `GET` | `/docs` | — | Swagger UI | 自动生成 |

**SSE 事件表**（帧格式 `event:<name>\ndata:<json>\n\n`，注意 `data:` 后**没有空格**）：

| `event` | `data` | 时机 |
| --- | --- | --- |
| `status` | `{"message":"Agent 已经开始处理"}` | 流一建立就发 |
| `text_delta` | `{"text":"…"}` | 逐 token；兜底路径整段一条 |
| `tool_start` / `tool_end` | `{"name":"knowledge_agent","label":"知识 Agent"}` | 三个专家 |
| `tool_error` | `{"name":…,"label":…,"message":"…"}` | 专家内部异常 |
| `confirmation` | interrupt 载荷（含 `action` / `candidate`） | 写操作暂停 |
| `done` | `{"status":"completed"｜"waiting_confirmation"}` | 流收尾 |
| `error` | `{"message":"…"}` | 超时或 agent 失败，之后流关闭 |

**`AgentReply`**（`/api/confirmation` 的响应，`schemas.py`）：

```json
{
  "answer": "…或 null（被 interrupt 暂停时）",
  "needs_confirmation": false,
  "confirmation": null,
  "trace": [ … ]
}
```

### 6.1 与计划文档的差异（**已知，未修**）

| 计划里写的 | 实现里是 | 影响 |
| --- | --- | --- |
| `GET /api/health` → `{"status":"ok"}` | **不存在** | `docs/plans/Day06_Agent封装成WebAPI_实现路径.md` 的验收 #1、#12 无法按原口径执行 |
| `POST /api/confirm` | `POST /api/confirmation` | 命名漂移 |
| `POST /api/chat` | 已**整段注释掉**（`agent_api.py:157-175`），改走 `POST /api/chat/stream` | 老文档里的 curl 示例会 404 |
| `uv run python -m uvicorn webapp:app` | 模块名是 `personal_assistant.agent_api` | 按旧名启动会起不来 |
| CORS 允许 `http://127.0.0.1:12367` | 前端 dev 跑在 **5173** | 走 Vite 代理时同源、不受影响；但**直连 8000 的跨源请求会被拒**（`agent_api.py:88-89`） |

---

## 7. 交互说明

### 7.1 CLI

启动后进入登录循环，提示符是「教学账号（/quit 退出）：」。

| 输入 | 作用 |
| --- | --- |
| 用户名 | 登录（仅 10 个可登录账号；失败会提示"未找到可登录的教学账号"） |
| `/logout` | 切账号：**新 `thread_id`、新 `RunContext`、新 Supervisor**，旧对话不可见 |
| `/quit` | 退出 |
| 普通文本 | 交给 Supervisor；回答后打印**本次会话累计的路由证据**（调了哪个 Agent Tool、内层调了哪些业务 Tool） |

写操作会先打印确认载荷再问 `y`/`n`：

```
[需要用户确认]
  action: create_device_request
  candidate: {"request_id": "REQ-2026-00NN", "device_id": "DEV-MONITOR-24", ...}
是否执行？(y/n):
```

`n` → 不落盘，文件字节数不变；`y` → 落盘并返回真实记录。

### 7.2 Web UI

三栏：左「身份与能力」+ 中对话 + 右「本轮轨迹」。**两侧栏各自独立显隐、手动切换、刷新后保持，
与视口宽度无关** —— `ChatView.tsx:61-63` 明确写了「这些 `xl:` 门槛已全部去掉」。
四套主题（`indigo` 默认 / `midnight` / `graphite` / `daylight`），登录页与顶栏都可切。

| 操作 | 效果 |
| --- | --- |
| 点教学账号 | 登录，`session_id` 落 localStorage |
| 发消息 | 走 SSE，回答逐字打出；右栏实时显示 agent 步骤 |
| 写操作 | 弹出确认卡片（按 `action` 分派模板）；**待确认期间输入框禁用** |
| 刷新页面 | 账号、消息列表、未决确认卡片都恢复 |
| 后端重启后刷新 | 会话**不再失效**——后端按 `agent_threads` + 检查点 `restore_session()` 重建（消息列表、未决确认卡片都还在）。只有重建也失败时才回到 **404** → 清会话回登录页，**不静默重登** |
| `Ctrl` / `⌘` + `B` | 折叠 / 展开**左栏**（沿用 VS Code 语义）。右栏**故意不给快捷键**，只在边缘按钮上切换（`frontend/src/lib/layout.ts:9-10,18`） |

**localStorage 键**（`frontend/src/lib/`）：

| 键 | 内容 |
| --- | --- |
| `day06.employee-assistant.v1` | 会话（`session_id` / 身份 / `traceCursor` / `pending`） |
| `day06.employee-assistant.history.<sessionId>` | 该会话的消息历史（有上限，避免撑爆） |
| `day06.employee-assistant.theme` | 主题 id |
| `day06.employee-assistant.sidebar-<left｜right>-hidden` | 左右栏折叠状态（`'1'` / `'0'`） |

> ⚠️ **侧边栏宽度不可拖拽调整** —— 不是 bug，是没实现。左右栏都是二值状态
> （`w-64` / `w-80` ↔ `w-0`）+ 宽度过渡动画，内层宽度硬编码以保证收起时内容不变形
> （`frontend/src/components/ChatView.tsx:352-436`）。全前端没有任何 splitter 或拖拽处理。

---

## 8. 权限模型（三层）

**Agent Tool 可见性 ≠ 权限。** 真正的边界是第二层：

| 层 | 在哪 | 做什么 | 只解决什么 |
| --- | --- | --- | --- |
| ① Agent Tool 裁剪 | `multi_agent._build_supervisor(role)` | employee 的 Supervisor **不含** `ask_hr_agent` | 减少误路由 |
| ② 执行端闸门 | 每个业务 Tool 内部重读 `runtime.context.role` | `approve_device_request` 对 employee 返回 `permission_denied` | **真正的保护** |
| ③ 检索期过滤 | `search_knowledge()` 在候选集阶段按 `allowed_roles` 过滤 | employee 检索 `KB-HR-*` **恒为 0 条** | 不让越权文本进模型上下文 |

另外三条硬约束：

* **身份只来自登录数据**：聊天里说"我是 HR"不会改变 `RunContext`（`frozen=True`）；
* **知识在检索期过滤，不是检索后再剔除** —— 一旦越权文本进了模型上下文，边界已经跨过；
* **Agent Tool 外层不得包 `try/except`** —— 那会吞掉 `interrupt()`，人工确认就废了
  （Web 版额外踩过一次：`multi_agent.py` 三个专家的 `except Exception` 之前必须加
  `except GraphInterrupt: raise`，否则每次人工确认都会假报一个 `tool_error`）。

> Web 层的 `session_id` **就是钥匙**：没有密码、没有 token，拿到 `session_id` 即可冒充。
> 这是教学项目的刻意取舍，不要部署到公网。

---

## 9. 测试与验收

退出码 **0 = 全通过**。

### 9.1 后端两个脚本（`tests`）

```bash
# 阶段通过信号：12 项（A1–A7 确定性 + B1–B5 需真实模型），约 1 分钟
uv run python -u tests/verify_phase5.py

# §8 端到端验收：20 条场景，约 3–5 分钟
uv run python -u tests/acceptance_day06.py
uv run python -u tests/acceptance_day06.py --only 6,9,12,13,14,15,19,20   # 只跑确定性场景
uv run python -u tests/acceptance_day06.py --list                        # 列场景清单

# 第四阶段最小复现（只读，秒级）
uv run python -u tests/verify_phase4_repro.py
```

* 逐条要求**四者相互印证**：Agent Tool 调用 / 业务 Tool 调用 / 最终回答 / **数据文件实际状态**；
* **会写数据**的第 7、10 条：开始前备份、结束后还原，并打印 `(字节数, sha256前16位, 条数)` 自证；
* **第 12 条真的移走 `src/vector_store/`**，用 `finally` 保证移回；
* ⚠️ **不允许并发执行**：`.tmp/acceptance.lock` 单实例锁，第二个实例**以退出码 3 拒绝**；
* ⚠️ 依赖模型表述的场景有随机性 —— **FAIL 时先读证据**，区分"机制缺陷"与"模型没照做"。

### 9.2 前端两个自检（`frontend/`）

```bash
cd frontend && node tests/logic-check.ts     # P2+P3+P4 逻辑层，记录为 36 passed / 0 failed

# P11 打字机 + SSE 帧解析（17 条，不依赖后端）
npx tsc src/lib/typewriter.ts src/lib/sse.ts --outDir ..\.tmp\twbuild --module commonjs \
  --target es2022 --skipLibCheck --moduleResolution node --ignoreConfig
node ..\.tmp\tw_check.cjs
```

阶段级证据（每阶段跑了什么、偏差在哪、真机截图）见 [`frontend/test/`](frontend/test/README.md)。

> ⚠️ 前端**没有测试框架**：`package.json` 里没有 `test` script、也没有 vitest。上面两个脚本是
> **手工执行**的校验件，且 `logic-check.ts` 不在 `tsc -b` 的类型检查范围内（见 §12.3）。

### 9.3 数据还原（**跑完务必做**）

写操作落在 MySQL 的 `device_requests` 表——**运行期不再写 `src/data/*.json`**。两个测试套件的基线目前**不一致**（见 §1）：

* `acceptance_day06.py` 结束时**自动还原**（`db_state.load_requests_backup()`），并打印还原前后的 `(内容长度, sha256前16位, 行数)`；
* `verify_phase5.py` / `verify_phase4_repro.py` 只读，用同一个摘要前后比对自证（`digest()`）。

**还原后请核对行数与摘要**（**以库中实际行数为准**——总条数会随验收/网页测试漂移，历史值 19 → 20；
稳定的不变量是 `USR-001` 名下 4 条）；对不上说明还原失败。需要手工回灌时：

```powershell
uv run python -c "import sys; sys.path[:0]=['src','tests']; import db_state; print(db_state.load_requests_backup('.tmp/day05_device_requests.backup.json'))"
```

---

## 10. 数据与知识契约

* **ID 是稳定的连接键**：`USR-` / `DEPT-` / `DEV-` / `REQ-`。名字要回原文件解析，不要冗余存储。
* 申请状态恰好三种：`pending` / `approved` / `rejected`。**已完成的申请不能再次审批**
  （重复审批返回 `conflict`）。"批准"只表示**已审批**，不代表已发设备。
* **运行期只有 `device_requests` 表会被写**（条数以库中实际为准，见 §1 的基线说明）：
  `src/data/day05_device_requests.json` 是历史基线，**不再被读写**（`README` 里凡以它为准的说法都只用于历史比对）：

  | 申请人 | 申请编号 | 状态 |
  | --- | --- | --- |
  | 张伟 USR-001 | `REQ-2026-0001` | pending |
  | 张伟 USR-001 | `REQ-2026-0003` | approved |
  | 张伟 USR-001 | `REQ-2026-0015` | pending |
  | 张伟 USR-001 | `REQ-2026-0019` | approved ← 前端联调遗留，与 CLI 验收冲突 |

  其余三份 JSON 与 `src/knowledge/` 全体**只读**。要复位就从 Day05 重新复制该文件。
* 12 台设备里 **2 台不可申请**（`DEV-DESK-STAND`、`DEV-ERGONOMIC-CHAIR`），
  `list_requestable_devices` 不返回它们。
* 非公开员工（`EMP-026` 宋妍、`EMP-027` 魏然）**永不出现**在 `find_public_employee` 结果里；
  返回字段是白名单：`user_id` / `display_name` / `job_title` / `department_id` /
  `office_location` / `office_contact` / `expertise`（**不含** `username`、`role`、`account_status`）。
* **`parser_mode` 决定解析路径**：`text` / `document_text` / `pdf_text` / `html_text` 正常解析；
  无文本层的扫描 PDF 走 OCR；PNG 导览图走多模态。OCR/多模态产物是**机器识别文本**，
  chunk 里会带「本段为机器识别结果，请勿作为原文引用」标注，**不要当原文**。
* chunk 从源文档继承 `document_id`、标题、路径、版本、状态与 `allowed_roles`。

---

## 11. 依赖

**Python 3.13** + `uv`；**Node.js** + npm（仅前端）。直接依赖钉在
[`requirements.txt`](requirements.txt)，完整传递依赖见 `uv.lock`。

| 分类 | 包 |
| --- | --- |
| Agent 编排 | `langchain` 1.4.3、`langgraph` 1.2.14 |
| 模型接入 | `langchain-openai` 1.6.7、`langchain-deepseek` 1.1.1（见 §12.1） |
| Web 层 | `fastapi[standard]`（含 uvicorn）—— ⚠️ 早期脚手架留下的声明，**现已被 `agent_api.py` 真正使用** |
| 向量库 | `langchain-chroma` 1.1.0、`chromadb` 1.5.9、`langchain-huggingface` 1.2.2、`sentence-transformers` 6.1.0 |
| 文本切分 | `langchain-text-splitters` 1.1.3（langchain 1.x 不再内置，**额外加的**） |
| 文档解析 | `pypdf`、`pypdfium2`、`python-docx`、`beautifulsoup4`、`rapidocr-onnxruntime`、`pillow` |
| 配置 | `python-dotenv` 1.2.4 |
| 可观测性 | `opentelemetry-api/sdk` 1.45.1、`opentelemetry-exporter-otlp-proto-http` 1.45.1、`opentelemetry-instrumentation-fastapi/httpx/sqlalchemy` 0.66b1、`openinference-instrumentation-langchain` 0.1.80 |

### 11.1 可观测性（可选，默认关闭）

应用侧埋点代码在 `src/personal_assistant/`：

- `telemetry.py`：Trace / Metrics 初始化、OTLP 导出、FastAPI/HTTPX/SQLAlchemy/LangChain 插桩；
- `request_context.py`：`thread_id / request_id / run_id` 与 Langfuse 属性；
- `structured_logging.py`：stdout JSON 日志（不写文件、不用 OTel Logs SDK）；
- `metrics.py`：成功率、耗时、RAG、Tool、Token 指标。

默认不配置 `OTEL_EXPORTER_OTLP_ENDPOINT` 时**完全 no-op**，不影响本地开发和测试。
需要观测时按 [`docs/指导文档/运行手册.md`](docs/指导文档/运行手册.md) 启动：

```text
应用 ──OTLP──► Collector ──┬─► Langfuse Cloud EU（Trace）
                            └─► :8889 /metrics ◄── Prometheus
应用 stdout JSON ──► Grafana Alloy ──► Loki
```

关键环境变量（完整见 `.env.example`）：

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=none
OPENINFERENCE_HIDE_INPUTS=true
OPENINFERENCE_HIDE_OUTPUTS=true
```

本地只想在终端看 Trace：`OTEL_TRACES_EXPORTER=console`。
测试默认 `OTEL_SDK_DISABLED=true`，不会向 Collector 发数据。

**前端**：React 19、Vite 8、TypeScript 6、Tailwind CSS 4、`motion`、`react-markdown` + `remark-gfm`
（`frontend/package.json`）。**刻意不引入 react-router** —— 只有登录/对话两个视图，
"是否已登录"本身就是全部路由状态（契约 `D2`）。另有 `lucide-react` 与
`class-variance-authority` 两个**死依赖**（零引用，见 §12.3）。

---

## 12. 已知限制

### 12.1 `reasoning_content`：thinking 模型与网关的兼容性（已修，但有前提）

链路：模型是 thinking 模型（难题实测产出 1.9 万字符推理内容、6091 推理 token）→
网关要求下一轮**原样回传**该字段，否则 400
`The reasoning_content in the thinking mode must be passed back to the API` →
而 `langchain_openai` 的发送侧序列化**只白名单复制 4 个 `additional_kwargs` 键**、
从不带该字段 → 「模型 → tool_call → tool 结果 → 再调模型」**偶发 400（实测 5–12%）**。

**修法**：`knowledge_base.ChatReasoningEcho`（继承 `ChatDeepSeek`，覆写
`_get_request_payload` 回填该字段），**且 `multi_agent.build_model()` 必须委托
`build_chat_model()`** —— 这一条曾经踩坑：修复只改到后者，应用仍走
`init_chat_model(... "openai")` → `ChatOpenAI`，等于没修。

* 该定制**针对本网关的约定**：换到不要求回传的网关时无害；**换 thinking 模型时必须重新验证**；
* 备用方案（该定制失效时）：`build_model_options()` 加 `reasoning_effort="none"` 关掉 thinking
  —— 代价是放弃推理能力，且它会**连带关闭多模态路径的 thinking**（两个路径共用该函数）；
* **不要用"跑几次都通过"来证明它消失**：以 12.5% 失败率计，连跑 8 次全过的概率约 34%。
  所以验收用的是**机制断言**（A7 直接看出站请求体），不是统计采样。

### 12.2 Web 层未修缺陷（**已在案，刻意不改**）

| 缺陷 | 表现 | 依据 |
| --- | --- | --- |
| **chromadb 全局被毒化后永久失效** | 一旦某次知识问答失败（如撞上超时），**该进程之后所有**知识问答都在 `_open_vector_store()` 抛 `KeyError`，只能重启后端 | 契约 `K11`；前端联调时实测 |
| **SSE 硬超时 90 秒** | 首次知识问答要冷启动嵌入模型（实测约 **27 秒**），叠加三次模型调用后冷进程下会逼近甚至超过 90 秒 → 发 `error` 并关流，前端表现为"回答中断" | 契约 `K10` |
| **流里没有 `trace` 事件** | 走 SSE 的正常轮次拿不到完整轨迹，右栏只能显示简版 | 契约 `C8` |
| **事件循环阻塞** | `/api/confirmation` 是 `async def` 但内部同步调 `agent.resume()`，会阻塞整个事件循环几十秒（期间所有并发请求排队）。修它只需把 `async def` 改成 `def`，但越过了 P0 冻结的后端改动边界 | 契约 §四.1，**待裁决** |
| **401 语义混同** | 登录接口把所有异常都兜成 401「此用户不存在」，模型/配置错误也报这个 | `agent_api.py:117-119` |
| **503 无 traceback** | agent 调用失败只回一句"稍后重试"，排查时看不到真因 | `agent_api.py:323-327` |

### 12.3 其余须知

| 限制 | 影响 |
| --- | --- |
| `no_evidence` 分支在非空索引上**不可达** | 检索对任何查询都返回 k 条最近邻；员工问 HR 专属问题时拿到的是 5 条**弱相关公开 chunk**，"回答无法确认"靠提示词约束。**索引为空会直接报错**（不会静默返回 0 条） |
| 索引内容**不可复现** | 导览图/海报的文字由视觉模型生成，重建后 chunk 数会浮动（实测 35/36）；`document_count` 恒为 10 |
| `EMBEDDING_MODEL` **首次下载未验证** | 本机命中了机器级 HF 缓存；网络不可达时能否建库未取证 |
| `login_as()` 的 `PermissionError` 分支**不可达** | 现有数据里没有"用户名匹配但不可登录"的记录 |
| 多中断只确认第一个 | `handle_interrupts()` 用 `interrupts[0]`（课件实现如此）；`len(interrupts) > 1` 时会打印显式告警 |
| `reason` 字段是间接注入通道 | 用户输入落盘后又被 HR Agent 读进上下文（有人工确认兜底，未验证可利用性） |
| 权限收紧后重建的回归用例缺失 | 没有测试验证「改小某文档的 `allowed_roles` → 重建 → 旧角色检索确实为 0」；需要真的改数据并重建索引（约 3 分钟） |
| Web 会话**不再依赖**进程内存 | 会话状态落在检查点（`runtime/checkpoints.sqlite3`）+ `agent_threads`，后端重启后旧 `session_id` 仍可用（契约 `C4`）；仍未变的限制是——除 404/自动重建外没有"查询会话状态"的接口，前端无法**提前**探测 |
| 侧边栏宽度**不可拖拽** | 见 §7.2；二值折叠，无 splitter |
| `approve_device_request` 的前端渲染**从未端到端实测** | 要走到它需要「HR + 一条 pending 申请」；`frontend/test/P7_流程文档.md:140` 自述这是"唯一没有端到端实测的分支" |
| 前端**没有测试框架** | `package.json` 无 `test` script、未引入 vitest；`test/logic-check.ts` 也不在类型检查范围内（`tsconfig.app.json` 只 `include: ["src"]`），只能手工 `node` 跑 |
| `lucide-react` / `class-variance-authority` 是**死依赖** | 声明在 `package.json`，但 `frontend/src/` 全目录**零引用**；`components.json` 里的 `@/components/ui` 别名与 `iconLibrary: lucide` 同样落空（无该目录） |
| `frontend/test/P10-三栏布局_流程文档.md` 描述的是**第一版**布局 | 它写「≥1280px 显示、窄屏收回单栏」并称「没有做侧栏折叠按钮」，与现行代码（手动折叠 + 持久化、`xl:` 门槛已移除）**不符**，且没有对应的新阶段文档。**以代码为准** |

### 12.4 本机环境适配（正常机器上是空操作）

* **`%TEMP%` 对子进程不可写** → `ensure_writable_tempdir()` 会改用项目内 `.tmp/`
  （逐个候选**真实验证可写可删**，全不行就在启动时立刻失败并列出原因）。
  chromadb 的报错长这样：`(code: 14) unable to open database file`。
* **`main.py` / `build_index.py` / `agent_api.py` 的 lifespan 都调了这一句** —— Web 入口曾经漏掉，
  导致 TEMP 不可写时"一问知识问题就 RuntimeError"。

---

## 13. 排查手册

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `尚未构建向量库，请先运行 build_index.py` | 索引不存在 | `uv run python build_index.py` |
| 后端启动即失败、报上面那句 | `lifespan` 的索引检查（预期行为，fail fast） | 同上 |
| `向量库为空（collection 里没有任何 chunk）` | 索引目录被清空但 manifest 还在 | 重建索引 |
| `(code: 14) unable to open database file` | 临时目录不可写 | 用 `uv run` 启动（会做适配），或把 `TEMP`/`TMP` 指向可写目录 |
| `请在 .env 中配置 MODEL_PROVIDER 和 MODEL_NAME` | `.env` 缺失或不全 | 从 `.env.example` 复制并填写 |
| `400 … MissingSessionID` | 网关要求会话头 | 本项目已自动携带；自写脚本调用模型时注意 |
| `400 … reasoning_content must be passed back` | 模型客户端没回传推理内容 | 已修；若复现，检查是不是绕过了 `build_model()` 直接用了 `ChatOpenAI` |
| 满屏 `UserWarning: Pydantic serializer warnings … [field_name='context', input_type=RunContext]` | **无害噪音**：LangChain 解析工具入参时对 `args_schema` 做 `model_dump()`（`langchain_core/tools/base.py` 的 `_parse_input`），而带 `runtime: ToolRuntime[...]` 的工具其 schema 把注入的 `context` 声明为 `None`，实际值是 `RunContext` → pydantic 报"期望 none"。**工具实际收到的仍是真实 RunContext，权限判定全部正常** | CLI 已在 `main()` 里**窄化过滤这一条**（不是忽略所有告警）；自写脚本可加 `warnings.filterwarnings("ignore", message="Pydantic serializer warnings")` |
| `ModuleNotFoundError: No module named 'langchain'` | 用了系统 Python 而不是本项目 `.venv` | 一律走 `uv run` |
| 多步工具调用偶发失败但重跑就好 | 见 §12.1 | 读 A7 是否 PASS |
| 验收脚本报"另一个验收进程正在运行"（退出码 3） | 有另一个实例在跑 | 等它结束；确认进程已死可删 `.tmp/acceptance.lock` |
| **CLI 验收场景 13/16 FAIL**（张伟条数 ≠ 3） | 旧断言按 18 条基线写死 3 条 | **已在持久化升级中修好**：断言改为「恰好 4 条（含本地增量 `REQ-2026-0019`）」并按编号逐个核对 —— **不需要再删任何数据** |
| 前端 `localhost:5173` 打不开、换 `127.0.0.1:5173` 也不行 | Vite 只绑 `localhost` | 用 `http://localhost:5173` |
| 前端请求报 CORS | 绕过了 Vite 代理直连 `:8000` | 走 5173，或把前端源加进 `agent_api.py` 的 `allow_origins` |
| 知识问答"回答中断" | SSE 撞上 90 秒硬超时（`K10`） | 调大 `STREAM_TIMEOUT_SECONDS`，或先热身一次让嵌入模型进内存 |
| 之后**所有**知识问答都失败、报 `KeyError: '...\\src\\vector_store'` | chromadb 进程级全局被毒化（`K11`） | **只能重启后端**；这是后端缺陷 |
| `npm run build` 后 `src/static/` 里旧文件没了 | `emptyOutDir: true`（契约 `K5`，预期行为） | 别往 `src/static/` 放需要保留的东西 |

---

## 14. 文档索引

### 项目与计划

| 文件 | 用途 |
| --- | --- |
| [`docs/plans/Day06_执行计划_v2.md`](docs/plans/Day06_执行计划_v2.md) | **本项目的执行计划与工程记录**：§4 课件未给全模块的设计决策、§5 目录布局、§8 的 20 条验收口径、§9 已知限制（14 条）、**变更记录 C1–C12**（含对课件的有意偏离与理由） |
| [`docs/plans/Day06_Agent封装成WebAPI_实现路径.md`](docs/plans/Day06_Agent封装成WebAPI_实现路径.md) | 后端 Web 化的实现路径与验收口径（⚠️ 部分口径与实现有差异，见 §6.1） |
| [`docs/plans/Day06_前端执行计划.md`](docs/plans/Day06_前端执行计划.md) | 前端的分步实现路径（`P0`–`P8`）、契约与边界、验收清单、已知限制 |

### 接口契约（**改前端前必读**）

| 文件 | 用途 |
| --- | --- |
| [`frontend/CONTRACTS.md`](frontend/CONTRACTS.md) | ⭐ **接口事实的唯一权威**：`C1`–`C9` 契约（含实测量化证据）、`K1`–`K11` 已知坑、`D1`–`D6` 构建契约、待裁决项 |
| [`frontend/test/README.md`](frontend/test/README.md) | 前端 `P0`–`P11` 各阶段流程文档索引 + 三条贯穿全程的硬约束 + 跑法 |

### 使用说明

| 文件 | 用途 |
| --- | --- |
| [`docs/指导文档/CLI_用户操作流程.md`](docs/指导文档/CLI_用户操作流程.md) | **CLI 用户视角**：五分钟上手、登录账号、能问什么（按身份）、写操作确认、切账号退出、常见问题、一分钟自检 |
| [`docs/指导文档/CLI_使用与实现流程.md`](docs/指导文档/CLI_使用与实现流程.md) | **CLI 技术视角**：一次 `你：` 输入在代码里走过的**完整调用链（带行号）**、中断与恢复、路由证据来源、关键设计点与常见告警解释 |
| [`tests`](tests/README.md) | 三个测试脚本的运行方式、执行顺序理由、数据安全、判定口径注意点（含五处弱断言的修法） |
| [`frontend/test/`](frontend/test/README.md) | 前端各阶段流程文档 + `shots/` 真机截图 |

### 课件（上游规格）

| 文件 | 用途 |
| --- | --- |
| [`docs/参考文档/Day06_多Agent综合项目：新员工助手升级.md`](docs/参考文档/Day06_多Agent综合项目：新员工助手升级.md) | 课件：架构与代码的权威规格（§5.1 布局、§5.3 向量库流水线、§6 Tool 边界、§7–§10 逐段代码、§12.1 验收场景） |
| [`docs/参考文档/Day05_综合案例：新员工助手Agent.md`](docs/参考文档/Day05_综合案例：新员工助手Agent.md) | 课件（单 Agent 基线）：§2.3 权限矩阵、§2.4 知识字段语义、§2.5 四份 JSON 关联、**附录 A JSON 字段速查** |
| [`docs/plans/Day06_执行计划.md`](docs/plans/Day06_执行计划.md) | 上一版执行计划（被 `_v2` 取代，保留作对照） |

---

## 附：一份最小可复现的验收流程

```bash
uv sync
uv run python build_index.py

# 后端验收（⚠️ 先处理 §1 的数据基线冲突）
uv run python -u tests/verify_phase5.py        # 期望 12/12，exit 0
uv run python -u tests/acceptance_day06.py     # 期望 20/20，exit 0

# CLI 手测
uv run python main.py                             # zhang_wei 登录，试一句：
                                                  #   公司介绍里说北京总部主要承担哪些职能？
                                                  # 再试 /logout → wang_fang → 批准 REQ-2026-0001（会问 y/n）

# Web 手测
uv run python -m uvicorn personal_assistant.agent_api:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev                        # → http://localhost:5173
```

跑完验收后，`device_requests` 表会被脚本**自动还原**。
**还原后请核对行数与摘要，确认与验收前一致**；对不上说明还原失败。
（总条数会随验收/网页测试漂移，别把它当基线；稳定的是 `USR-001` 名下 4 条。）
（`src/data/*.json` 已不是写目标，它的 sha256 基线只用于**历史**比对。）
