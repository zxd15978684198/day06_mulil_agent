# 执行计划：为多 Agent 员工助手加一层 Web 前端

> **层级与档位声明**：本文档是**模块级**（= 现有 FastAPI 后端之上的一层前端）的**实现路径**文档，不是架构级设计，也不是流程规范。评估请按此尺子。

---

## 0. 起点与定位

**需求原话**（用户消息，2026-10-10）：

> 「`@src/personal_assistant/agent_api.py` 接口文件我已经写好了，再次基础之上为当前项目增加前端，用 ui-ux-pro-max 和 ui-ux-pro-max 设计动效页面，当前阶段先生成一份执行计划；执行计划的内容参考 requirement-to-path 的分析结果」

它缺三类决策：**技术栈**、**范围到哪**、**后端要不要动**（供给 L1 搜索当输入）。

### 为什么这不是一次从零开始的需求

`docs/Day06_Agent封装成WebAPI_实现路径.md` 本身就是一份 `requirement-to-path` 产物，它的 **P6 明确写了「联调页：同源、够用即止」**，并硬性要求：

> 「用原生 `fetch`，**不要**引入任何前端框架、**不要**配 CORS（同源）、**不要**为了好看花时间在样式上」

其 **`H1` 假设是「前端只用于联调，不交付成品前端」**。

**本次需求正是推翻 `H1`。** 所以本次不是"给一个没有前端的项目加前端"，而是"把一份明确声明为一次性的联调页，升级为成品前端"。这条决定了本文档的重心：**不是重复论证要不要做前端，而是把那条假设翻转后牵连到的所有契约点重新核一遍**。

---

## 1. 已确认的决策（门禁产出）

### 1.1 门禁 1 · 痛点清单

> 右两列描述的是**现状**（CLI 的体验），不是提案。

| 编号 | 现象 | 触发条件 | 现在怎么绕 | 影响 |
| --- | --- | --- | --- | --- |
| `L0-P1` | 看不见 agent 内部在做什么 | 每次提问后 | `main.py:56` 往终端打一坨「当前会话累计 Supervisor 路由证据」文本，翻屏即失 | 讲不清"这答案是哪个 agent 给的" |
| `L0-P2` | 审批确认太简陋 | 写操作触发 interrupt | 终端一行 payload + 敲 `y`/`n` | 看不清在批什么，敲错没得回头 |
| `L0-P3` | 不好演示给别人看 | 要展示时 | 终端没法投屏给别人看，也没法一人演示两个角色 | 权限差异这条主线讲不出来 |
| `L0-P4` | 重点在练前端/做作品 | — | — | 界面与动效本身即交付物 |

### 1.2 门禁 2 · 方案决策

| 维度 | 选择 | 理由 |
| --- | --- | --- |
| 技术栈 | **React + Vite + TypeScript** | 用户选定 |
| 开发期联调 | **Vite proxy**（`/api` → 后端） | 后端零改动，CORS 不用碰 |
| 组件来源 | **shadcn/ui（复制式）+ Tailwind** | 代码在仓库里、样式可改，配合设计规范落地 |
| 动效 | **framer-motion**（现名 `motion`） | 声明式，消息入场/卡片展开/滑入都能覆盖 |
| trace 形态 | **气泡下方折叠面板** | 平时安静，展开看时间线 |
| 刷新处理 | **记住会话，刷新不断** | 演示时不至于点一下刷新就重来 |
| 设计底座 | **`awesome-design-md` · `linear.app`** | 用户指定。用成熟产品的设计语言作参照，质量有保证 |
| 设计护栏 | **`ui-ux-pro-max`** | 用户指定。UX 准则、无障碍、响应式的校验清单 |
| 界面落地 | **`uicraft`** | 聊天流 / 轨迹面板 / 确认卡片是**自定义组件**，DESIGN.md 里没有，得在它的令牌上自己设计 |

### 1.3 门禁 3 · 需求规格

| 编号 | 内容 |
| --- | --- |
| `L0-S1` | 交付一个 React+Vite 前端，**构建产物由 FastAPI 托管**（`GET /` 返回 `src/static/index.html`，`/static` 挂载静态资源） |
| `L0-S2` | 范围：登录 → 对话 → 确认 → trace 折叠面板。**明确不做**：流式输出（SSE）、多会话列表、历史会话管理、独立 HR 审批台、移动端专门适配、markdown 富渲染之外的富媒体 |
| `L0-S3` | 开发期走 Vite proxy；**不改 `agent_api.py` 的 CORS** |
| `L0-S4` | 后端**唯一**改动：`approve_device_request` 的 interrupt payload 补 `applicant_name` / `device_name` |
| `L0-S5` | 会话与未决确认持久化到 localStorage，刷新可续 |
| `L0-S6` | 组件 shadcn/ui（复制式），动效 framer-motion |

---

## 2. 最终设计决策表

### 2.1 天花板条目（R 级）

#### `R1` 累计 trace 的处理口径 —— "前端拿到的 trace 到底是谁的"

- **要什么**：让每一轮的轨迹面板只显示**这一轮**的调用，而不是从会话开天辟地以来的全部。
- **备选**：① 前端切片 diff ② 每轮全量重绘（把所有历史 trace 都渲染一遍）③ 改后端让 `outer_trace` 只返回增量。
- **权衡**：②会让第 N 轮的界面里出现 N 份重复条目，直接用不了；③要动 `multi_agent.py` 与 CLI 的既有行为，且 LangGraph 返回的本就是全量 state，改成增量等于在服务端做一次反向 diff —— 复杂度搬了个家，还破坏了 CLI 现有输出。
- **推荐**：**①**。`result["messages"]` 是 append-only 的，因此 `outer_trace` 的输出是**前缀稳定**的增长列表，前端记住上次长度、`slice(上次长度)` 即得本轮新增。
- **放弃的代价**：放弃"前端零状态"的简单模型 —— 前端必须为每个会话维护一个 `traceCursor`，且刷新恢复时要**同时恢复 cursor**，否则会重复渲染。

#### `R2` 确认按钮的语义口径 —— "拒绝"到底拒绝了什么

- **要什么**：让按钮文案如实描述后端会发生什么。
- **现状事实**（`[代码可读]`）：`business_tools.py` 两处 `interrupt()` 的恢复协议都只有 `{"approved": bool}`：
  - `create_device_request`：`approved:false` → 返回 `user_rejected`「用户取消，未创建申请」，**一个字节都不写**；
  - `approve_device_request`：payload 里自带 `decision`（agent 已决定批/驳），`approved:false` → 「用户取消，未修改申请状态」。
- **关键判断**：后端的 `approved` 语义是「**是否执行 agent 已经决定好的动作**」，**不是**「这条设备申请批不批」。HR 场景下，"拒绝"会让用户以为在拒绝那条申请，实际只是"这次不执行"。
- **对标印证**：`repo/langchain-ai/agent-chat-ui:src/components/thread/agent-inbox/types.ts#DecisionType` 定义的是 `"approve" | "edit" | "reject"` 三态，`Decision` 里 `reject` 是一个**独立决定**（可带 `message`）。它那套语义映射到我们的后端是错的 —— **照抄会把 UI 变成谎言**。
- **推荐**：按钮文案定为「**确认执行**」/「**取消本次操作**」，且卡片必须**先展示 agent 打算做什么**（`action` + 关键参数），再给按钮。
- **放弃的代价**：放弃 accept/edit/respond 三态编辑能力 —— 用户不能改完参数再提交，只能取消后重新对话。

#### `R3` 会话失效的处置 —— "localStorage 里那个 session_id 过期了怎么办"

- **要什么**：选了「刷新不断」之后，必须有明确的失效出口，否则会卡在一个永远报错的页面上。
- **现状事实**（`[代码可读]`）：会话存在 `app.state.sessions`（进程内存），key 是 `thread_id`；`agent_api.py` 的 `get_session_or_404` 在查不到时返回 **404**。**后端重启即全部会话消失。**
- **备选**：① 收到 404 → 清 localStorage → 回登录页并提示 ② 静默用旧 username 重新登录 ③ 不做处理，让用户手动刷新。
- **权衡**：②会**静默换一个新会话**，用户看着还在对话、实际历史全丢了 —— 比 ①更糟；③就是卡死。
- **推荐**：**①**。且必须在**第一次** 404 就清理，不做重试。
- **放弃的代价**：放弃"无感续期"。用户会看到一次"会话已失效，请重新登录"。

### 2.2 打包默认项（D 级，无异议即通过）

| 编号 | 决策 | 意图（要什么） |
| --- | --- | --- |
| `D1` | 前端源码放仓库根 `frontend/`，构建产物输出到 `src/static/` | 要"源码与产物分离"，且产物落在后端已有的挂载点里 |
| `D2` | **不引入 react-router**，登录页/对话页用条件渲染切换 | 要避开"SPA 子路由被 FastAPI 404"这一整类部署坑 |
| `D3` | Vite `base` 按 command 切换：dev 用 `/`，build 用 `/static/` | 要 dev 时能直接开 `http://127.0.0.1:5173`，同时 build 后资源路径对得上 `/static` 挂载 |
| `D4` | Vite proxy target `http://127.0.0.1:8000` | 沿用 WebAPI 文档里的端口约定（见 `H1`） |
| `D5` | TypeScript | 后端返回的是宽松 `dict[str, Any]`，前端需要自己的窄类型兜住 |
| `D6` | 后端改动只碰 `business_tools.py` 的一处 payload，不动 `agent_api.py` | 要"接口文件已冻结"这条约束成立 |

---

## 3. 对标结论

L1 走了两轮（`search_code` 反查 + `search_repositories` 直搜），L2 对主候选做了代码级读取。

**设计底座的来源另算一路**：界面风格不取自上述 GitHub 候选，而取自 `awesome-design-md`（来源 [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)，MIT）中的 `references/linear.app/DESIGN.md`。**用法是取其令牌层，不取其组件层** —— 该文件是从营销官网分析而来，`Components` 一节里 `pricing-card` / `cta-banner` / `testimonial-card` / `customer-logo-tile` / `footer` 全部用不上；真正要用的是颜色令牌、Elevation 五级阶梯、圆角刻度、`button-*` / `text-input` / `status-badge` / `top-nav` 这些基础件。其中 `linear.app` 的一条设计原则直接对应本项目的难点：*"depth is carried by surface ladder + hairline borders; the brand resists drop shadows on dark almost entirely"* —— 对话气泡、轨迹面板、确认卡片三层容器同时出现在深色底上时，靠 `surface-1/2/3` 阶梯 + 1px 发丝边框分层，而不是阴影。

| 仓库 | 规模/活跃度 | 类型 | 为什么参考 | 为什么不全抄 |
| --- | --- | --- | --- | --- |
| [langchain-ai/agent-chat-ui](https://github.com/langchain-ai/agent-chat-ui) | 3208★ · MIT · pushed 2026-10-06 | 📐 参考实现 | 同为 LangGraph，**interrupt 确认 UI 的交互设计可直接对照**。`repo/langchain-ai/agent-chat-ui:src/components/thread/messages/generic-interrupt.tsx#GenericInterruptView` 的通用兜底渲染值得抄：JSON 超过 4 行或 500 字符即折叠、字符串超 100 字符截断、**URL 不截断以保持可点击**；动效用 `AnimatePresence mode="wait"` + `initial={{opacity:0, y:20}}` 0.2s、容器 `height:auto` 0.3s、按钮 `whileHover/whileTap` 0.98–1.02 | ① 它是 **Next.js App Router**，我们选了 Vite SPA，路由与数据获取模型不同；② 它的确认交互建立在 `HITLRequest`（`action_requests` + `review_configs.allowed_decisions`）与 `Decision = approve \| reject \| edit` 之上（见 `#DecisionType`），而我们的恢复协议**只有一个 `approved: bool`** —— 照抄它的三态会让文案撒谎（见 `R2`）；③ 它绑 LangGraph Platform 的 `/threads` 协议，采用它等于推翻上一份文档的 `R2` 决策（自研路由 ↔ 平台协议） |
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) | 12467★ · MIT · pushed 2026-10-10 | 📐 参考实现库 | React 组件化拆消息流 / tool UI 的分层思路；`packages/react-streamdown` 这类可复用子包的组织方式值得借鉴 | pnpm + turbo 的 monorepo（仓库 178MB），本质是一整套 runtime —— 要把我们这 3 个接口适配进它的 model 层。对课程项目是**净负担**：多一层抽象换不来我们要的东西 |
| [OvidijusParsiunas/deep-chat](https://github.com/OvidijusParsiunas/deep-chat) | 3729★ · MIT · pushed 2026-10-09 | 📐 参考实现库（**仅元数据级，未读码**） | 可嵌入式聊天组件的"深度定制 vs 开箱即用"取舍策 | 同上，且它是 web-component 优先，与我们选的 Tailwind 设计系统不融合 |
| [Jakubantalik/thinking-orbs](https://github.com/Jakubantalik/thinking-orbs) | 3624★ · MIT · pushed 2026-08-16 | 📐 动效参考（**仅元数据级，未读码**） | 专门做 AI UI 的思考中指示器，动效节奏参数可借鉴 | 独立视觉风格，`P8` 再决定是否深读 |
| [ai-forever/giga_agent](https://github.com/ai-forever/giga_agent) | 207★ · MIT · pushed 2026-10-05 | 📐 参考 | 同为"Python 后端 + React/langgraph-sdk 前端"的完整产品，前端目录组织可对照 | 它是编排器产品，前端与自己的后端强耦合 |

**排除了什么**：`iOfficeAI/AionUi`（33408★）与 `GaiZhenbiao/ChuanhuChatGPT`（15272★）是**平台型产品**（Electron 桌面端 / Gradio GUI），`flyerhq/flutter_chat_ui` 技术栈不匹配（Dart），均按 L1 结果分类规则排除。

**本次对标带来的具体改动（能数出 2 条）**：

1. **确认卡片的载荷渲染策略**改成"结构化优先 + 通用兜底"两段式 —— 原本只打算按 `action` 写两个模板；读了对标后补一条：**未知 `action` 走通用 key/value 表格 + 折叠**，避免后端将来加工具时前端直接白屏。（依据 `#GenericInterruptView`）
2. **折叠阈值采用具体数值而非凭感觉** —— JSON > 4 行或 > 500 字符折叠、字符串 > 100 字符截断、URL 不截断。原计划里这一块写的是"长内容折叠"，没有可施工的判据。

---

## 4. 契约与边界

### 4.1 契约（每条配可执行断言 + 违约处置）

| 编号 | 契约 | 入库前断言 | 违约处置 |
| --- | --- | --- | --- |
| `C1` | `AgentReply.trace` 是**当前会话累计**的轨迹，不是本轮增量 | 同一会话连发两轮，第二轮 `trace.length` ≥ 第一轮；且第一轮的内容是第二轮的**前缀** | 断言失败即 `R1` 的前提被推翻 → 停下来重新判定切片策略，**不许**直接 append |
| `C2` | `confirmation.action` 是卡片模板分派的**唯一依据**；取值目前只有 `create_device_request` / `approve_device_request` | 两处 `interrupt()` 的 payload 首字段均为 `action`（`business_tools.py` 已成立） | 未知 `action` → 通用兜底渲染，**不报错、不白屏** |
| `C3` | HTTP **409** 表示"本会话有未决确认"，不代表请求本身有错 | 待确认期间直接 POST `/api/chat` 必须得到 409 | 前端把它当"输入框该禁用"的信号，**不弹错误提示** |
| `C4` | HTTP **404** 表示会话已不存在 | 后端重启后带旧 `session_id` 请求必须得 404 | 清 localStorage、回登录页、提示一次 |
| `C5` | `approved: bool` 的语义是"是否执行 agent 已决定的动作" | 两处工具在 `approved:false` 时均返回 `user_rejected` 且不写盘 | 文案必须用「确认执行/取消本次操作」，**禁止**用「批准/拒绝」（`R2`） |
| `C6` | `approve_device_request` 的 payload 必须含 `applicant_name` 与 `device_name` | 与 `create_device_request` 的 payload 字段对齐 | `P1` 完成前，`P7` 的 HR 卡片不得开工 |

### 4.2 已知坑（正文原位引用）

- `K1` **累计 trace 直接 append 会指数级重复** —— 见 `R1`。这是本次最大的正确性风险，也是 `P4` 单独成步的原因。
- `K2` **`approved:false` 不是"驳回申请"** —— 见 `R2`。
- `K3` **build 后白屏**：`base` 不按 command 切换时，dev 正常、build 出来的 `index.html` 会去请求 `/assets/...` 而不是 `/static/assets/...`。翻车信号：Network 面板里 JS 全 404。见 `D3`。
- `K4` **后端重启后 localStorage 里的 `session_id` 变成死键** —— 见 `R3`。
- `K5` **`emptyOutDir: true` 会删掉 `src/static/index.html`**（那个 322 字节的占位页）。这是**预期行为**，但执行前要确认 `src/static/` 下没有别的东西。
- `K6` **待确认期间 `/api/chat` 返回 409** —— 见 `C3`。前端不禁用输入框的话，用户会看到莫名其妙的报错。
- `K7` **`confirmation` 可能退化成 `{"message": "..."}`**：`agent_api.py:112` 对非 dict 的 interrupt payload 会包装成 `{"message": str(value)}`。当前两个工具都是 dict，但前端要能兜住。
- `K8` **`answer` 为 `null` 的那一轮没有助手气泡**：`agent_api.py:113` 在 interrupt 时把 `answer` 设为 `None`。确认卡片是**占据气泡位置**渲染的，不是浮层。
- `K9` **`allow_methods` 只有 GET/POST**（`agent_api.py:71`）—— 前端只能用这两个方法，别指望 PUT/DELETE。

---

## 5. 模块全景

**一句话定义**：一个由 FastAPI 托管的单页 React 应用，把已有三个 HTTP 接口包装成"登录 → 对话 → 结构化确认 → 轨迹检视"四件事可看的界面。

```
flowchart TD
  subgraph 输入
    A[用户点选教学账号]
  end
  subgraph 核心
    B[LoginView] --> C[useChatSession<br/>session_id + localStorage]
    C --> D[ChatView 消息流]
    D --> E[traceCursor 切片<br/>本轮新增轨迹]
    E --> F[TracePanel 折叠面板]
    D --> G{needs_confirmation?}
    G --> H[ConfirmationCard<br/>按 action 分派]
  end
  subgraph 输出
    H --> I[POST /api/confirmation]
    D --> J[POST /api/chat]
  end
  subgraph 消费方
    J --> K[FastAPI agent_api]
    I --> K
  end
```

**做什么 / 不做什么**：

| 做 | 不做 |
| --- | --- |
| 登录与身份常驻显示 | 密码、注册、用户管理 |
| 对话流 + 发送/等待状态 | 流式逐字输出、停止生成 |
| 结构化确认卡片（两种 action） | 参数在线编辑后提交 |
| 累计 trace 的按轮切片与折叠展示 | 完整调用链的图可视化、耗时统计 |
| 会话与未决确认的刷新恢复 | 多会话列表 / 历史会话管理 |

**步骤拼装关系**：`P0` 定契约与骨架 → `P1` 补齐后端 payload（`C6`）→ `P2` API 客户端 + `P3` 会话持久化 + `P4` trace 切片（三个可独立 TDD 的纯逻辑层）→ `P5` 登录页与设计规范 → `P6` 对话流与轨迹面板 → `P7` 确认卡片 → `P8` 动效与端到端验收。

**步骤划分依据**：本需求的数据流链是 `身份 → session_id → 持久化 → 发送 → 累计 trace 切片 → 按 action 分派卡片 → 确认/取消 → 结果回填轨迹`。`P2/P3/P4` 是按这条链上**三个互不依赖、可单独验证的纯逻辑段**切出来的；`P5–P7` 按**视图**切；`P8` 是横切的动效与验收层。

---

## 6. 分步实现路径

**配套 skill 映射**（三层分工，不重叠）：

| skill | 角色 | 用在哪几步 |
| --- | --- | --- |
| `awesome-design-md` | **底座** —— 提供颜色令牌、Elevation 阶梯、圆角刻度、基础件规则 | `P5` 读取并落成 CSS 变量；`P6`/`P7` 消费这些变量 |
| `ui-ux-pro-max` | **护栏** —— UX 准则（119 条）、无障碍（对比度 / 焦点可见 / 键盘可达）、响应式、中文排版校验 | `P5`/`P6`/`P7` 每步做完过一遍，只做校验与微调 |
| `uicraft` | **落地** —— 界面打磨、动效、空状态、UX 文案、上线前检查 | `P5`/`P6`/`P7`/`P8` |
| （无） | 纯脚手架与 TS 纯函数，无对应 skill | `P0`/`P1`/`P2`/`P3`/`P4` |

> **分工边界**：`awesome-design-md` 出令牌，`ui-ux-pro-max` 只做校验、**不另立第二套令牌**；`uicraft` 做落地，**不引入第二套设计系统**。三者若给出冲突建议，以「令牌来自 `awesome-design-md`、无障碍来自 `ui-ux-pro-max`」为准。

### P0 契约冻结与工程骨架

**开发模式**：Spec

**执行流程**
1. **先跑一次实测**验证 `C1`：起后端，同一会话连发两轮，打印两次响应的 `trace.length`。**这一步不做完不许往下走** —— 整个 `R1` 押在它上面。
2. 在 `frontend/` 初始化 Vite + React + TS 工程，接入 Tailwind 与 shadcn/ui（复制式）。
3. 写死 `vite.config.ts`：`base` 按 command 切换（`D3`）、`build.outDir: '../src/static'`、`emptyOutDir: true`、`server.proxy['/api'] → http://127.0.0.1:8000`（`D4`）。
4. 冻结本文件 §4.1 的六条契约与 `R1/R2/R3` 三条决策编号，后续所有代码注释引用编号。

**提示词模板**
> 在 `frontend/` 初始化一个 Vite + React + TypeScript 工程，接入 Tailwind CSS 与 shadcn/ui（复制式初始化，不要引入 antd/MUI 这类整体组件库）。`vite.config.ts` 里：base 按 command 切换（dev 为 `/`，build 为 `/static/`），build.outDir 指向 `../src/static` 并开启 emptyOutDir，dev server 把 `/api` 代理到 `http://127.0.0.1:8000`。**不要**引入 react-router，**不要**配置任何 CORS 相关的东西，**不要**动 `src/personal_assistant/` 下的任何文件。

**通过信号**：`npm run dev` 起来后，浏览器开 `http://127.0.0.1:5173` 能看到 React 默认页；`npm run build` 后 `src/static/` 下出现 `index.html` 与 `assets/`，且该 `index.html` 里的资源路径以 `/static/` 开头。

**翻车信号**：build 产物里的资源路径是 `/assets/` 开头 → `base` 没按 command 切（`K3`），立刻改 `vite.config.ts`，**不要**去改后端的挂载点。

**来源**：`L0-S1` `L0-S3` `D1` `D3` `D4` `C1` `K3` `K5`

---

### P1 补齐审批 payload 契约

**开发模式**：Spec

**执行流程**
1. 改 `src/personal_assistant/business_tools.py` 中 `approve_device_request` 的 `payload`（约 599–607 行），补上 `applicant_name` 与 `device_name`，取值方式对齐 `create_device_request` 的 `_build_create_candidate`（那里用的是 `_field(context, "display_name")` 与 `device.get("name")`）。
2. 名字来源必须是**读盘查出来的**（`_load_users()` / `_load_devices()`），不是从会话 context 推的 —— 因为被审批人通常不是当前登录人。

**提示词模板**
> 修改 `src/personal_assistant/business_tools.py` 里 `approve_device_request` 传给 `interrupt()` 的 payload，增加 `applicant_name` 与 `device_name` 两个键，取值方式对齐同文件里 `_build_create_candidate` 的写法（申请人名字从用户表查，设备名从设备表查）。**不要**改动 `create_device_request`，**不要**改 `interrupt` 的调用位置与恢复协议，**不要**改 `agent_api.py`。

**通过信号**：以 `wang_fang` 登录，对话触发一次审批，响应里 `confirmation.applicant_name` 与 `confirmation.device_name` 是中文名而不是 `None`。

**翻车信号**：`applicant_name` 显示成当前登录 HR 自己的名字 → 名字取错了对象（错用了 `runtime.context`），回上一步改成按 `applicant_user_id` 查表。

**来源**：`L0-S4` `C6` `D6` `repo/langchain-ai/agent-chat-ui:src/components/thread/agent-inbox/types.ts#ActionRequest`

---

### P2 API 客户端与错误映射

**开发模式**：TDD

**执行流程**
1. 定义三个接口的 TS 类型：`LoginResponse` / `AgentReply` / `Confirmation`（联合类型，按 `action` 判别）。
2. 实现 `lib/api.ts`：三个函数 + 统一错误类型 `ApiError { status, kind }`，把 401/404/409/503 映射成四种语义（`C3` `C4`）。
3. 先写映射函数的测试用例（纯函数，可穷举），再接 `fetch`。

**提示词模板**
> 写 `frontend/src/lib/api.ts` 与 `errors.ts`。对外暴露 `login(username)` / `chat(sessionId, message)` / `confirm(sessionId, approved)` 三个函数，返回后端声明的类型。把 HTTP 401/404/409/503 映射成 `ApiError.kind` 的四个取值：`user_not_found` / `session_expired` / `confirm_pending` / `backend_down`。**不要**在这里做任何 UI 或状态管理，**不要**自动重试（409 和 404 重试都是错的），**不要**吞掉未知错误。

**通过信号**：单测覆盖四种状态码的映射；制造一次真实 409（待确认时再发一条消息）时 `kind` 是 `confirm_pending`。

**翻车信号**：401 和 404 被合并成同一个 `kind` → 登录失败和会话过期是两件事，必须分开。

**来源**：`C3` `C4` `K6` `K9` `L0-S2`

---

### P3 会话持久化与刷新恢复

**开发模式**：TDD

**执行流程**
1. `lib/session.ts`：读写 `{ sessionId, displayName, role, traceCursor, pendingConfirmation }`。
2. 定义失效清理路径：任何请求收到 `session_expired` → 清空并回登录态（`R3`）。
3. 往返测试 + 清理测试。

**提示词模板**
> 写 `frontend/src/lib/session.ts`，把登录结果与未决确认持久化到 localStorage。暴露 `save/load/clear`。收到 `session_expired` 时必须**一次性清干净**（含 traceCursor 与 pendingConfirmation），不能只删 sessionId。**不要**在加载时自动重新登录，**不要**做版本迁移，**不要**加密。

**通过信号**：对话进行到一半刷新页面，仍显示原账号与原消息列表；重启后端再刷新，自动清空并回到登录页且提示一次。

**翻车信号**：刷新后消息列表空了但账号还在 → 消息列表没被持久化（它必须一起存，后端不提供历史查询接口）。

**来源**：`R3` `K4` `L0-S5` `L0-P3`

---

### P4 累计 trace 的按轮切片

**开发模式**：TDD

**执行流程**
1. `lib/trace.ts` 导出一个纯函数：给定「累计 trace 数组」与「上次的 cursor」，返回「本轮新增」与「新的 cursor」。
2. 按 `C1` 写测试：前缀稳定性、interrupt 前后两次响应的衔接（同一逻辑轮里 trace 会长两次）、cursor 丢失时的降级。
3. **本轮逻辑轮的边界不由 cursor 单独决定** —— 一个用户轮次可能横跨 `chat` + `confirmation` 两次响应，两次新增必须**追加到同一个面板**里。

**提示词模板**
> 写 `frontend/src/lib/trace.ts`，导出一个纯函数，输入是后端返回的累计 trace 数组和上次的长度 cursor，输出本轮新增条目和新的 cursor。要求：① cursor 大于数组长度时（服务端变了）安全降级为返回全部；② 只做切片，**不要**在这里格式化、**不要**过滤条目类型、**不要**依赖 React。配套写单测，用例必须包含"同一轮里 trace 连续增长两次"这一种。

**通过信号**：连发三轮对话，第一轮面板显示 2 条、第二轮的**新**面板显示 2 条（不是 4 条）、第三轮显示 2 条（不是 6 条）；总条数与最后一次响应的 `trace.length` 相等。

**翻车信号**：第二轮面板出现第一轮的内容 → 直接 append 了（`K1`）。**这是本计划最该被守住的一条**。

**来源**：`R1` `C1` `K1` `L0-P1`

---

### P5 登录页与设计规范落地

**开发模式**：场景测试

**执行流程**
1. 读 `awesome-design-md` 的 `references/linear.app/DESIGN.md`，把**令牌层**抄进 `src/styles/tokens.css` 的 CSS 变量：颜色（`canvas` / `surface-1..3` / `hairline` / `hairline-strong` / `ink` / `ink-muted` / `ink-subtle` / `ink-tertiary` / `primary` / `primary-hover` / `primary-focus`）、Elevation 五级阶梯、圆角刻度、字体栈。shadcn 的主题变量指向同一套值，**不另立第二套**。
2. 用 `ui-ux-pro-max` 过一遍中文场景的 UX 准则与无障碍：正文/次要文本在 `canvas` 上的对比度是否达标、焦点环是否可见、中文字距行高、禁用态（`ink-tertiary`）是否够辨识。**只做校验与微调，不改令牌取值**。
3. 用 `uicraft` 打磨登录页视觉与文案。
4. `LoginView`：角色分组展示教学账号（`zhang_wei` / `wang_fang` 等），点选即登录。
5. 失败态：401 → 行内提示"此用户不存在或不可登录"。

**提示词模板**
> 登录页的设计令牌来自 `awesome-design-md` 的 `linear.app/DESIGN.md`：把它的颜色令牌、Elevation 五级阶梯、圆角刻度、字体栈抄进 `src/styles/tokens.css` 的 CSS 变量，shadcn 的主题变量指向同一套值。**不要**自己发明色板，**不要**引入第二套设计令牌。然后用 `ui-ux-pro-max` 校验中文场景的对比度、焦点可见性与字距行高，用 `uicraft` 打磨视觉与文案。登录页需要：账号分组（员工 / HR）、点选登录、加载态、401 的行内错误提示。**不要**做密码输入框，**不要**做注册。

**通过信号**：`zhang_wei` 与 `wang_fang` 都能登录且顶栏显示中文名与角色；故意传一个不存在的账号能看到行内错误而不是控制台报错。

**翻车信号**：shadcn 组件的颜色和自定义部分对不上 → 主题变量接了两套，回上一步统一。

**来源**：`L0-S6` `L0-P4` `D2`

---

### P6 对话流与轨迹折叠面板

**开发模式**：场景测试

**执行流程**
1. 用 `awesome-design-md` 的 Elevation 五级阶梯决定三层容器怎么分层：对话区在 `canvas`、消息气泡在 `surface-1`、轨迹面板在 `surface-2`，靠 1px `hairline` 边框分隔，**不用阴影**。`ChatView` + `MessageList` + `Composer`：用户气泡、助手气泡、等待态，输入框用 `text-input` 的焦点环（`primary-focus` 2px 50%）。
2. 把 `P4` 的切片接到每个轮次上，`TracePanel` 默认折叠成一行摘要（"调用了 N 个 Agent Tool"），展开是时间线。
3. 待确认期间禁用 `Composer`（`C3`/`K6`）。

**提示词模板**
> 实现对话视图：消息列表、输入框、发送、等待态。每一条助手回答下方挂一个默认折叠的轨迹面板，显示本轮（不是累计）的 Agent Tool 调用与内层业务 Tool 名字；摘要行形如"调用了 2 个 Agent Tool"，展开后按时间顺序列出调用与结果。待确认期间输入框必须禁用并显示原因。**不要**做流式输出，**不要**做 markdown 之外的富文本渲染，**不要**在轨迹面板里显示原始 JSON 字符串（要格式化）。

**通过信号**：以 `zhang_wei` 问"年假怎么规定的"，回答带 `KB-*` 编号，面板摘要显示 1 个 Agent Tool，展开能看到 `ask_knowledge_agent` 与其内部业务工具名；连问三轮，每轮面板只含本轮内容。

**翻车信号**：面板里出现上一轮的工具名 → `P4` 的 cursor 没在轮次边界更新。

**来源**：`L0-P1` `L0-S2` `C3` `K6` `D2`

---

### P7 确认卡片

**开发模式**：Spec + 场景测试

**执行流程**
1. 卡片用 `surface-2` + `hairline-strong` 边框（比消息气泡抬一级），状态用 `status-badge` 胶囊。用 `uicraft` 打磨按钮层级与 UX 文案，用 `ui-ux-pro-max` 校验键盘可达性（确认卡片必须能 Tab 到、「确认执行」必须是默认焦点）。
2. 按 `action` 分派两个模板：`create_device_request`（申请人 / 设备 / 数量 / 理由）与 `approve_device_request`（申请编号 / 申请人 / 设备 / 数量 / 决定 / 意见）。
3. 按钮文案按 `R2` 定为「确认执行」/「取消本次操作」，并在卡片上显式写出"这将会写入 `day05_device_requests.json`"。
4. 未知 `action` 与 `{"message": ...}` 形态走通用兜底（`C2` `K7`），折叠阈值采用第 3 节抄来的数值。
5. 卡片**占据助手气泡位置**渲染（`K8`），不是浮层。

**提示词模板**
> 实现确认卡片组件，按 `confirmation.action` 分派模板。两个已知 action 各一个结构化模板；未知 action 和 `{"message": ...}` 形态走通用 key/value 表格 + 折叠（JSON 超 4 行或 500 字符折叠、字符串超 100 字符截断、URL 保持可点击）。按钮文案必须是「确认执行」和「取消本次操作」，**不要**写「批准」「拒绝」「同意」——因为这里的语义是"是否执行 agent 已经决定好的动作"，不是"这条申请批不批"。卡片要占据助手气泡的位置，**不要**做成居中模态弹窗。

**通过信号**：申请设备时卡片显示中文设备名与真实理由；HR 审批时卡片显示申请人中文名（`P1` 生效）。点「取消本次操作」后，`src/data/day05_device_requests.json` 的**字节数不变**。

**翻车信号**：HR 卡片上出现"拒绝"字样导致演示时被理解成"驳回申请" → `R2` 被违反，改文案。

**来源**：`R2` `C2` `C5` `C6` `K2` `K7` `K8` `L0-P2` `repo/langchain-ai/agent-chat-ui:src/components/thread/messages/generic-interrupt.tsx#GenericInterruptView`

---

### P8 动效层与端到端验收

**开发模式**：场景测试

**执行流程**
1. 用 `uicraft` 统一起草动效层，再用 framer-motion 实现四类动效：消息入场、轨迹面板展开/收起、确认卡片滑入、审批结果反馈。参数先照抄第 3 节记录的节奏（0.2s 入场 / 0.3s 容器高度 / `whileTap` 0.98），再按 `linear.app` 令牌里的动效时长微调。
2. **必须处理 `prefers-reduced-motion`** —— 系统开了减弱动效时全部降级为无动画。
3. 跑第 7 节全部验收场景。

**提示词模板**
> 给已有界面加动效层，统一用 framer-motion：消息逐条入场、轨迹面板展开收起、确认卡片滑入、操作成功/取消的反馈。参数参考：入场 opacity+y 20→0 用 0.2s，容器高度用 0.3s，按钮按下 scale 0.98。**必须**尊重 `prefers-reduced-motion`，开启时全部降级为无动画。**不要**用动效掩盖加载延迟（该转圈就转圈），**不要**做视差滚动或装饰性动画。

**通过信号**：第 7 节 8 个场景全过；系统开启"减弱动态效果"后界面仍可用且无动画。

**翻车信号**：动效让消息列表在快速连发时抖动或错位 → 布局动画和列表重排冲突，改回只对新增项做入场动画。

**来源**：`L0-P4` `L0-S6` `repo/langchain-ai/agent-chat-ui:src/components/thread/messages/generic-interrupt.tsx#GenericInterruptView`

---

## 7. 验收清单

**主场景**

| # | 场景 | 可观察证据 |
| --- | --- | --- |
| 1 | 知识问答带权限差异 | `zhang_wei` 问年假 → 回答含 `KB-HR-*` 编号；浏览 `data/day05_device_requests.json` 确认未变 |
| 2 | 写操作确认后落盘 | `zhang_wei` 申请设备 → 卡片显示中文设备名 → 点「确认执行」→ `grep -c '"status": "pending"' src/data/day05_device_requests.json` **+1** |
| 3 | 写操作取消不落盘 | 再申请一次 → 点「取消本次操作」→ 该文件 `ls -l` 的**字节数与 mtime 均不变** |
| 4 | HR 审批带中文名 | `wang_fang` 登录 → 审批一条 → 卡片显示 `applicant_name`（非 `USR-` 裸 ID）→ 确认后文件里该条 `status` 变 `approved` |
| 5 | 轨迹按轮切片 | 连问三轮 → 三个面板的条目数分别为本轮新增，三者之和 = 末次响应 `trace.length` |
| 6 | 刷新不断 | 对话中途刷新 → 账号、消息列表、未决确认卡片都还在 |
| 7 | 会话失效出口 | 重启后端后刷新 → 自动清空并回登录页，**不卡死、不静默重登** |
| 8 | 待确认期禁用输入 | 有未决确认时输入框禁用且给出原因；绕过 UI 直接 `curl` POST `/api/chat` 得 **409** |

**防护性验收**（对"不该发生的事"断言）

| # | 断言 |
| --- | --- |
| P-1 | 取消任何一个写操作后，`day05_device_requests.json` 字节数不变 |
| P-2 | 任意一轮的轨迹面板里不出现属于其他轮次的条目 |
| P-3 | 未知 `action` 的确认载荷不导致白屏（用 `curl` 构造一次验证） |
| P-4 | `data/` 下另外三个 JSON 与 `knowledge/` 全程未被修改（`git status` 对此无输出） |
| P-5 | 前端只在 `allow_methods` 声明的 GET/POST 内发请求（Network 面板核对） |

---

## 8. 已知限制与假设

### 8.1 `[假设]`（必须显式列出）

| 编号 | 假设 | 错了会怎样 |
| --- | --- | --- |
| `H1` | 后端跑在 `http://127.0.0.1:8000` | `D4` 的 proxy target 要改一行；如果后端实际就跑在 `12367`，则应改为同源直连并删掉 proxy |
| `H2` | 单人单会话演示足够，不做多标签页并发保护 | 若需多标签页，`P3` 要加 `storage` 事件同步 |
| `H3` | `agent_api.py` 的 CORS 白名单（`12367`）在 Vite proxy 方案下是死代码，保留不动 | 无影响；若要清理，属于可选的额外改动 |

### 8.2 `[推断]`（附验证方法）

| 编号 | 推断 | 验证方法 |
| --- | --- | --- |
| `I1` | 多次 `start_session` 不会污染已有会话 —— 读码显示 `_build_agent_tools` 每次重建闭包、`_build_supervisor` 在重建**之后**才执行，因此旧会话的 supervisor 仍持有创建时的那套 agent | `P0` 第 1 步顺带验证：先登 `zhang_wei` 问一句，再登 `wang_fang`，回第一个浏览器标签继续追问，看历史是否还在 |
| `I2` | 会话内存不释放（`app.state.sessions` 与已废弃会话的 agent 闭包都驻留） | 长跑演示后观察进程内存；课程场景可忽略 |

### 8.3 什么情况下**不该**用这套设计（反向边界）

同时满足「单人演示 + 三接口够用 + 不需要流式」时，这套前端是划算的。**缺两条以上就该换路**：

- **要实时逐字输出** → 后端得先上 SSE（WebAPI 文档 §9.3 已列为未做项），前端数据模型要重做；
- **要给别人部署使用** → `12367` 的 CORS、内存态 session、无鉴权（`session_id` 即钥匙）都得先解决；
- **要做成长期维护的产品** → 该上 `assistant-ui` 那类成熟 runtime，而不是手搓消息流；
- **只有一台机器、只想看接口通不通** → 现有的 322 字节占位页已经够了。

### 8.4 未解项

- `agent_api.py` 没有「查询当前会话状态」的接口，前端无法在发请求前知道会话是否还有效，只能靠第一次 404 发现。本次接受这个限制（`R3` 的出口已覆盖），不新增后端接口。

---

## 9. 执行前检查

```bash
# 后端（终端 1）
uv run python -m uvicorn personal_assistant.agent_api:app --port 8000

# 前端（终端 2）
cd frontend && npm install && npm run dev     # → http://127.0.0.1:5173

# 生产形态验证
npm run build                                  # 产物落到 src/static/
# 浏览器直接开 http://127.0.0.1:8000/ ，不经过 Vite
```

**注意**：`npm run build` 会**删除并替换** `src/static/index.html`（当前是 322 字节的占位页，`K5`）。执行 `P0` 前先确认 `src/static/` 下没有其他需要保留的文件。
