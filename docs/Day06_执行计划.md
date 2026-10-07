# Day06 多 Agent 新员工助手 — 执行计划


## Context

`E:\projects\mutil_agent` 目前是一个**空壳脚手架**：`data/`（4 份业务 JSON）和 `knowledge/`（10 份知识文件 + 权限清单）已就位，`docs/` 里是 Day05/Day06 两份课件，但**应用代码一行都没有**——`main.py` 仍是 PyCharm 的 `print_hi('PyCharm')` 模板，`konwledge_base.py`（拼写有误）是空文件，`vector_store/` 为空，`pyproject.toml` 的 `dependencies = []`，`.venv` 里装好的第三方包为 0，git 上没有任何提交。

目标是按 `docs/Day06_多Agent综合项目：新员工助手升级.md` 的规格，把 Day06 项目从零建成可运行状态：教学登录 → 权限 RAG → Supervisor + 三个专业 Agent → 设备申请与 HR 审批闭环。

### 本计划与 skill 默认流程的差异（已与用户确认）

`docs/Day06_*.md` **不是模糊需求，而是一份写到代码级的规格**（§5.1 文件布局、§7–§10 逐段代码、§12.1 十一条验收场景）。且项目核心是「星桥科技有限公司」的课程私有业务（教学登录、固定权限矩阵、课程私有 JSON 结构），GitHub 上不存在整块开源对标。因此：

| skill 默认步骤 | 本计划做法 | 理由 |
| --- | --- | --- |
| L0 三道门禁逐道 STOP | **并入本计划，一次审批** | 课件已给出全部答案，逐道停只是仪式 |
| L1 漏斗七步找整块对标 | **只做定向核验**（§4） | 无整块对标；核验的是课件自己承认没跑过的点 |
| L2 读对标仓库源码 | **不适用** | 对标对象是框架 API 契约，来源是 LangChain/LangGraph 官方文档 |
| L3 分步路径 + 三件套 | **保留**（§5） | 是让计划可施工而非待办清单的关键 |

课件 §16.2 自己声明：依赖导入、OCR、索引构建、专业 Agent 调用、嵌套暂停恢复、会话隔离、场景验收**全部未经验证**。本计划把「验证这些」列为显式施工步骤，而不是当作已知成立。

### 范围

**只建 Day06。** Day05 单 Agent 基线的代码不属于本仓库；`data/` 与 `knowledge/` 里 `day05_*` 命名的文件是 Day06 直接复用的资料副本，**保留命名不改**。课件 §12.3 的单/多 Agent 对比列为可选扩展，不阻塞交付。

---

## 1. 已核实的环境与数据事实

以下为本次实测所得，非引用课件：

### 1.1 工具链

| 事实 | 值 | 影响 |
| --- | --- | --- |
| 虚拟环境由 `uv 0.11.30` 创建 | `.venv/pyvenv.cfg` 含 `uv = 0.11.30` | 必须用 `uv` 管理依赖 |
| **`.venv` 内没有 pip** | `No module named pip` | 课件 §5.3 的 `python -m pip install -r requirements.txt` **在本仓库必然失败**，改用 `uv add` / `uv sync` / `uv run` |
| 已装第三方包 | **0 个** | 从零开始 |
| Python | 3.13.3 | 满足 `requires-python = ">=3.13"` |

### 1.2 知识文件（10 份，正文真实非占位）

| 需特别注意的 | 事实 |
| --- | --- |
| `day05_public_expense_guide_scanned.pdf` | **748 KB**，清单标 `contains_text_layer: false` → OCR 是硬需求 |
| `day05_public_office_map.png` | 125 KB，真实楼层图；**页脚已用文字写出答案**（见 §4 R4） |
| `day05_public_security_poster.jpg` | 526 KB，`ocr_or_multimodal` |
| docx ×2 / pdf ×2 / md、txt、html ×3 | 正文完整可检索 |

### 1.3 业务数据

- **27 人**：`USR-001`…`USR-010` 为可登录账号，`EMP-011` 起为**仅通讯录**记录（`username`/`role`/`account_status` 为 `null`，`login_enabled: false`）。
  ⚠️ **`user_id` 前缀不统一**——可登录用 `USR-`，通讯录用 `EMP-`。任何按 `USR-` 前缀解析 `user_id` 的写法都会漏掉 `EMP-*`，而这些人（如 `EMP-012` 林峰「账号管理员」）正是「找人办事」的正确答案。
- 关键账号：`zhang_wei` = **USR-001 张伟**（employee，DEPT-PRODUCT）；`wang_fang` = **USR-003 王芳**（hr，DEPT-HR）。
- **10 个部门**，职责字段驱动「找人办事」（例：`DEPT-IT` 职责含「软件账号」）。
- **12 台设备**：其中 `DEV-DESK-STAND`、`DEV-ERGONOMIC-CHAIR` 为 `is_requestable: false` + `max_quantity_per_request: 0`，必须被拒绝。`eligible_department_ids: []` 表示**无部门限制**，不是禁止。
- **18 条申请**（`REQ-2026-0001`…`0018`）：pending 6 条、approved 8 条、rejected 4 条。
  - 张伟（USR-001）本人有 3 条：`0001`(pending)、`0003`(approved)、`0015`(pending) → 「申请隔离」验收可直接断言「恰好这 3 条」。
  - 新建申请的编号必须是 **`REQ-2026-0019`**（现有最大号 +1）。

---

## 2. 契约冻结（P0）

**开发模式：Spec** — 一旦定了牵连全局。

### 2.1 可信运行上下文

```python
@dataclass(frozen=True)
class RunContext:
    user_id: str; username: str; display_name: str
    role: str          # "employee" | "hr"
    department_id: str
```

`frozen=True` 是硬要求：身份只能来自 `login_as()` 读到的 `day05_users.json`，不能来自聊天内容。

### 2.2 七个业务 Tool 与执行端闸门

| Tool | 权限闸门（**执行端强制，非 Prompt 提示**） |
| --- | --- |
| `search_company_knowledge` | 检索前按 `allowed_roles` 过滤候选集 |
| `find_department` | 公开目录 |
| `find_public_employee` | 排除 `is_public == false`；**须能返回 `EMP-*` 记录** |
| `list_requestable_devices` | 同时校验 `eligible_roles` + `eligible_department_ids` + `is_requestable` |
| `create_device_request` | 申请人取自 Context；`interrupt()` 确认后才写；校验 `max_quantity_per_request` |
| `query_device_requests` | 员工按 `applicant_user_id` 过滤，HR 见全部 |
| `approve_device_request` | 校验 `role == "hr"` + 状态为 `pending` + 人工确认 |

### 2.3 四类数据不许混

| 数据 | 位置 | 生命周期 |
| --- | --- | --- |
| 用户自然语言 | `messages` | 随 thread |
| 可信身份 | Runtime Context | 随会话 |
| 对话执行状态 | Checkpoint（`InMemorySaver`，按 `thread_id`） | 随 thread |
| 业务事实 | `data/day05_device_requests.json` | **跨会话、跨用户** |

### 2.4 唯一可写文件

**只有 `data/day05_device_requests.json` 会被程序修改。** 其余 3 份 JSON 与整个 `knowledge/` 只读。恢复初始申请 = 重新从 Day05 复制该文件。

---

## 3. 模块全景

```
knowledge/*.{md,txt,html,docx,pdf,png,jpg}
        │
        ▼
┌─────────────────────────────┐
│ knowledge_base.py           │  解析 → OCR/多模态 → 切分(继承 allowed_roles)
│  build_vector_store()       │  → Embedding → Chroma 持久化
│  search_knowledge(role,…)   │  检索时按角色过滤
│  INDEX_MANIFEST_PATH        │
└──────────────┬──────────────┘        build_index.py ──► vector_store/
               │
data/*.json ──►┌┴────────────────────┐
(users/depts/  │ business_tools.py    │
 devices)      │ RunContext/login_as  │
               │ + 7 个业务 Tool       │
               └─────────┬────────────┘
                         │
               ┌─────────┴────────────┐
               │ multi_agent.py       │
               │ 3 专业 Agent          │
               │   ↑ Agent Tool 包装   │
               │ Supervisor(按角色裁剪) │
               │ UserSession/chat/resume│
               └─────────┬────────────┘
                         ▼
                    main.py (CLI)
```

**步骤拼装关系**：P1 环境 → P2–P4 知识层 → P5 业务层 → P6–P8 编排层 → P9 端到端验收。
**P2–P4 与 P5 互不依赖，可并行**；P6 依赖 P5 的 Tool 与 P4 的检索入口。

---

## 4. 定向核验项（用户指定：不做整块对标，只核验课件自认没跑过的点）

### R1 嵌套 `interrupt()` 与 Checkpointer 继承 —— 最高风险

课件 §8.3 称「Agent Tool 调用的专业 Agent 继承父级 Checkpointer，并在一次调用中使用 `interrupt()`」，同时自认「正式授课前仍需记录实际安装版本并完成真实暂停、恢复验证」。

**若此机制不成立，设备申请与审批的人工确认流程整体作废。**

- 核验方式：装好依赖后写最小复现（Supervisor → Agent Tool → 专业 Agent → 业务 Tool 内 `interrupt()` → 父图 `Command(resume=...)`），**实跑一次**。
- **处置预案**（课件 §13 也提到）：把确认提到 Supervisor 外层固定节点——专业 Agent 只返回「待确认载荷」，由 Supervisor 侧的 `interrupt()` 负责暂停与恢复。此方案不依赖嵌套继承，代价是确认逻辑上移一层。

> ⏳ 两个 Explore agent 正在核验中，结论回来后落定 P7 的写法。

### R2 API 签名与依赖版本

课件样例用 `langchain.agents.create_agent` / `langchain.tools.ToolRuntime` / `context_schema=` / `langgraph.checkpoint.memory.InMemorySaver`，但 `pyproject.toml` 无任何依赖与版本约束。须逐一确认 import 路径与参数真实存在，并**钉死版本**（课件 §16.2 承认用的是「版本范围」，未记录实际版本）。

> ⏳ 核验中（含 `requirements` 清单与版本 pin）。

### R3 Chroma 对 `list[str]` 元数据的过滤

权限模型成败系于此：chunk 的 `allowed_roles` 是**列表**，检索必须按当前角色过滤。若 Chroma 不支持对数组字段做 `$in`/`$contains`，须改写元数据形态（如拆成布尔字段 `allow_employee` / `allow_hr`）。

> ⏳ 核验中。

### R4 导览图的「多模态」验收是假验收（本次新发现）

`day05_public_office_map.png` 的页脚原文写着：**「蓝色箭头表示从电梯到会议室 A 的推荐路线。打印区在茶水区东侧。」**

而清单给出的两个 `suggested_questions` 恰恰是「从电梯出来怎样到达会议室 A？」「打印区位于茶水区的哪个方向？」——**答案被图内文字直接写出来了**。因此课件 Day05 §3.6 要求的「能够回答至少一个需要理解位置或路线的问题，**而不只是抄出图片文字**」，用现有题目**无法区分**多模态理解与纯 OCR。

- 处置：验收时改用**页脚未给出答案**的空间问题，例如「会议室 B 位于打印区的哪一侧？」「从西侧出口进来，去信息技术部要先经过哪里？」——这类问题只能靠版面关系回答。
- 同时这也意味着：**纯 OCR 路径可能通过现有清单题目**，不能据此宣称多模态能力已验证。

---

## 5. 分步实现路径

> 模式标注依据 `l3-mode-map.md`（契约/顺序用 Spec，纯逻辑用 TDD，真实环境用场景测试）。
> 来源列取值：`课件§n` = Day06 课件章节；`F<n>` = §1 实测事实；`R<n>` = §4 风险项。

### P0 契约冻结

- **目标**：把 §2 的 `RunContext`、7 个 Tool 签名、权限矩阵、四类数据边界写成代码里的类型与常量，**先于任何实现**。
- **产出**：`business_tools.py` 顶部的 `RunContext` 与 `ROLE_PERMISSIONS`（Day05 课件 §2.3 已给出矩阵）。
- **指令模板**：「按下面规格定义 `RunContext`（frozen dataclass）与 `ROLE_PERMISSIONS` 常量表。**不要**实现任何 Tool 函数体，**不要**引入 LangChain 依赖，**不要**为 `employee` 添加 `review_device_requests` 权限。」
- **通过信号**：`python -c "from business_tools import RunContext, ROLE_PERMISSIONS"` 无报错；对 `RunContext` 赋值抛 `FrozenInstanceError`。
- **翻车信号**：出现 `permissions` 字段挂在用户记录上 → 违背课件 §2.2「用户记录只保存 `role`，不为每个用户重复保存权限列表」。
- **来源**：`课件§4.3`、`课件§6.1`

### P1 环境与依赖

- **目标**：装依赖、钉版本、建立 `.env`。
- **产出**：`requirements.txt`（或 `pyproject.toml` 的 deps）、`.env.example`、`vector_store/` 可用。
- **指令模板**：「用 `uv add` 添加依赖并钉版本。**不要**用 `python -m pip`（本 venv 无 pip）。**不要**把 `.env` 提交进 git。**不要**在代码里硬编码 API Key。」
- **通过信号**：`uv run python -c "import langchain, langgraph, chromadb"` 成功；`uv pip list` 输出含全部依赖及版本。
- **翻车信号**：`No module named pip` → 说明误用了 pip；`EMBEDDING_MODEL` 首次下载失败 → 查网络/HF 镜像。
- **来源**：`F(§1.1)`、`课件§5.3`

### P2 文档解析 + 权限元数据

- **目标**：把 10 份文件解析成带权限元数据的文本。
- **要点**：按清单 `parser_mode` 分流；`ocr_required`（748 KB 扫描件）走 OCR；`multimodal_required`（导览图）走视觉模型。每个 chunk **必须继承** `document_id`、`title`、`path`、`version`、`status`、`allowed_roles`。
- **指令模板**：「按 `parser_mode` 实现五种解析路径。**不要**用同一个 Loader 硬套所有格式。**不要**在解析失败时静默丢弃文件——保留错误与原文件名。**不要**从目录名或文件名推断权限，一律读清单的 `allowed_roles`。」
- **通过信号**：打印每条文件的「文档数 / chunk 数 / 解析方式」；扫描件 OCR 结果非空且含标题；导览图返回空间描述而非仅文字。
- **翻车信号**：扫描件返回空字符串 → OCR 未生效（课件 §3.1 明说不要把「没有文字」误判为「文档为空」）；`allowed_roles` 缺失 → 权限会静默放开。
- **来源**：`课件§3.1`、`课件§3.2`、`F(§1.2)`

### P3 向量库构建

- **目标**：Embedding + Chroma 持久化 + 索引清单。
- **产出**：`build_index.py`、`vector_store/`（含 `index_manifest.json`）。
- **指令模板**：「实现 `build_vector_store()` 并让 `build_index.py` 打印真实统计。**不要**把统计数字写成常量——必须来自本次运行。**不要**在索引里丢失 `allowed_roles` 元数据。」
- **通过信号**：`uv run python build_index.py` 打印文档数/chunk 数/索引目录/Embedding 模型；`vector_store/index_manifest.json` 存在。
- **翻车信号**：数字与源文件数不符；Chroma 目录为空但脚本报成功。
- **来源**：`课件§5.3`、`课件§5.4`

### P4 权限检索

- **目标**：`search_knowledge(role, query)` —— **检索阶段**就按角色过滤。
- **指令模板**：「实现按 `allowed_roles` 过滤的检索。**不要**先召回再让模型判断权限——课件 §9.2 明确：无权正文一旦进入模型上下文，边界已被突破。**不要**让模型决定检索范围。」
- **通过信号**：同一问题「试用期中期回顾需要保留哪些记录？」，`role=employee` 返回**零条 HR 证据**并明确说明无法确认；`role=hr` 返回 `KB-HR-001` 证据与来源。
- **翻车信号**：employee 角色召回到 `KB-HR-*` → 权限闸门失效（这是安全边界缺陷，最高优先级）。
- **来源**：`课件§9.2`、`R3`、`课件§12.1`

### P5 业务 Tool 层

- **目标**：`login_as()` + 7 个 Tool，统一「取 Context → 查权限 → 校验参数 → 读写 → 返回 JSON」顺序。
- **指令模板**：「每个 Tool 第一句都从 `runtime.context` 取身份并做权限判断。**不要**接受调用方传入的 `user_id`。**不要**让写操作在确认前落盘。」
- **通过信号**：`employee` 身份直接调 `approve_device_request` 返回 `permission_denied` 且 `day05_device_requests.json` 字节不变；`find_public_employee` 能返回 `EMP-012` 林峰；张伟查申请恰好 3 条。
- **翻车信号**：员工能查到他人申请；`EMP-*` 记录查不到（→ §1.3 的前缀陷阱）；`list_requestable_devices` 返回升降桌。
- **来源**：`F(§1.3)`、`课件§6.3`、`课件§5.4`

### P6 专业 Agent + Agent Tool 包装

- **目标**：三个专业 Agent（各带本职 Tool）+ 三个 `@tool` 包装；`specialist_result()` 只回传 `{agent, answer, business_tools}`。
- **指令模板**：「三个专业 Agent 各自只挂本职 Tool。**不要**给知识 Agent 挂审批 Tool。**不要**把专业 Agent 的整份消息历史回传 Supervisor。**不要**用宽泛 `try/except` 包住 Agent Tool——内层 `interrupt()` 的暂停信号会被当成异常吞掉。」
- **通过信号**：打印三个 Agent 各自的 Tool 名称集合，互不重叠且覆盖 7 个 Tool；`specialist_result` 输出可 `json.loads`。
- **翻车信号**：Agent Tool 里出现 `try/except Exception` → 人工确认必然失效。
- **来源**：`课件§7.5`、`课件§8.3`、`R1`

### P7 Supervisor + 会话 + 中断恢复 ⚠️ 写法取决于 R1

- **目标**：Supervisor 只持有 Agent Tool；按角色裁剪；`UserSession` / `chat()` / `resume()`。
- **R1 成立时**：按课件 §9–§10 原样实现，`interrupt()` 留在业务 Tool 内，`resume()` 用父图 `Command(resume=...)`。
- **R1 不成立时**：改用 §4 R1 预案——专业 Agent 返回「待确认载荷」，`interrupt()` 移到 Supervisor 外层节点。
- **指令模板**：「Supervisor 只挂 Agent Tool，不直接挂业务 Tool。`chat()` 只提交本轮新消息（**不要**重复传历史，Checkpointer 会重放导致重复）。`resume()` 必须复用原 `thread_id` 与 Context，**不要**新建 thread。」
- **通过信号**：`employee` 的 Supervisor Tool 集合**不含** `ask_hr_agent`；`hr` 的含；同一 `thread_id` 第二轮能引用第一轮内容；`/logout` 后新账号拿到新 `thread_id` 且看不到旧对话。
- **翻车信号**：员工 Supervisor 出现 `ask_hr_agent`；第二轮丢失第一轮上下文；切换账号后能看到上一个人的聊天。
- **来源**：`R1`、`课件§9.1`、`课件§10.1`

### P8 CLI 入口

- **目标**：`main.py` —— 登录循环、`/logout`、`/quit`、中断交互、路由证据打印。
- **指令模板**：「启动时先检查 `INDEX_MANIFEST_PATH` 是否存在，缺失即报错。**不要**让向量库缺失拖到第一次检索才报错。」
- **通过信号**：无索引时立即提示「请先运行 build_index.py」；每轮打印 Agent Tool 与内层业务 Tool 名称。
- **翻车信号**：路由证据把「当前会话累计」误报成「本轮」——课件 §10.3 明确这是累计证据。
- **来源**：`课件§10.3`、`课件§10.5`

### P9 端到端验收

见 §6。**模式：场景测试**（需真实环境）。

---

## 6. 验收

每条都给第三方可复现的证据，不接受「看起来对」。

| # | 场景 | 可观察证据 |
| --- | --- | --- |
| 1 | 张伟查公司介绍 | 路由证据含 `ask_knowledge_agent` + `search_company_knowledge`；回答引 `KB-PUB-001` |
| 2 | 张伟问「软件账号开通找谁」 | 两个业务 Tool 依次调用；返回 `DEPT-IT` + 林峰/陈浩；**能返回 `EMP-012`** |
| 3 | **张伟查 HR 专属文档** | 检索结果中 `KB-HR-*` **计数为 0**；回答明确「无法从当前知识库确认」 |
| 4 | 王芳查同一问题 | 返回 `KB-HR-001` 证据与来源 |
| 5 | 两轮补全申请 | 两轮 `thread_id` 相同；第二轮沿用第一轮设备信息 |
| 6 | 拒绝创建 | `interrupt` 载荷已打印；输入 `n` 后 `day05_device_requests.json` **字节数不变** |
| 7 | 确认创建 | 新记录编号 **`REQ-2026-0019`**；`applicant_user_id == "USR-001"`；`status == "pending"` |
| 8 | **张伟声称「我是 HR」** | `RunContext.role` 仍为 `employee`；Supervisor Tool 集合不含 `ask_hr_agent`；申请状态不变 |
| 9 | 张伟直接调审批 | 返回 **`permission_denied`**；目标申请仍 `pending` |
| 10 | 王芳确认审批 | 状态 `pending → approved`；`reviewer_user_id == "USR-003"` |
| 11 | 账号切换 | 新 `thread_id`；新 `RunContext`；但 HR 能查到张伟的申请（共享业务数据） |
| 12 | **导览图多模态**（R4 修正） | 回答**页脚未写出**的空间问题（如「会议室 B 在打印区哪一侧」），非抄图内文字 |
| 13 | 防护：无索引启动 | 删除 `vector_store/` 后 `main.py` 立即报错，不进入登录循环 |
| 14 | 防护：申请隔离 | 张伟查询恰好返回 3 条（`0001`/`0003`/`0015`） |

**恢复初始数据**：重新复制 `day05_device_requests.json` 后，`REQ` 最大号回到 `0018`。

---

## 7. 已知限制

- **R1 若核验为否定**，P7 按预案改写（确认上移到 Supervisor 层），其余步骤不受影响。这是本计划唯一的架构级分叉。
- **R4**：现有清单题目无法区分多模态与 OCR，本计划已改用页脚未给答案的题目；课件 Day05 §3.6 的原始验收标准按此修正。
- 单/多 Agent 对比（课件 §12.3）不在交付范围。
- 课件 §16.2 列的未验证项，将在 P1–P9 中逐项真正跑通，不再沿用课件的「未验证」声明。
- `konwledge_base.py`（拼写错误的空文件）应删除，新建 `knowledge_base.py`——课件全程按 `knowledge_base` 导入。

---

## 8. 施工时查阅的本地资料

已确认本机装有 `langchain-docs` skill（`C:\Users\Administrator\.claude\skills\langchain-docs\`），是 docs.langchain.com 的完整知识库。按需查对应章节，不必上网：

| 步骤 | 章节 |
| --- | --- |
| P0/P4 契约与上下文 | `ch02-quickstart-runtime.md` |
| P5/P6 Agent 与 Tool | `ch03-agents.md`、`ch06-tools.md` |
| P2/P3/P4 RAG | `ch12-retrieval-rag.md` |
| P6/P7 多 Agent 编排 | `ch14-multi-agent-patterns.md`、`ch15-multi-agent-implementation.md` |
| **P7 / R1 中断与 Checkpointer** | **`ch26-interrupts-time-travel.md`、`ch24-persistence-checkpointers.md`、`ch23-subgraphs.md`** |
| P7 人工确认护栏 | `ch16-human-in-the-loop-guardrails.md` |
| P9 验收 | `ch18-testing-evals.md` |

---

## 9. 建议的提交切分

仓库尚无任何提交。建议按 `P0+P1` → `P2+P3` → `P4` → `P5` → `P6+P7+P8` → `P9`（含验收记录）分 5–6 次提交，每个可运行节点一次，便于课件作者回退到任一阶段授课。
