# CLI 使用与实现流程

> **这份文档给谁看**：想搞清"它是怎么跑起来的"的人（开发者、要讲代码的人）。
>
> 👉 只想**照着操作**（不涉及代码、不问实现），看
> [`CLI_用户操作流程.md`](CLI_用户操作流程.md)。
>
> 面向两件事：**怎么用**（第一部分）和**它是怎么跑起来的**（第二部分，带行号）。
> 代码位置：[`src/personal_assistant/main.py`](../src/personal_assistant/main.py)（169 行）、
> [`src/personal_assistant/multi_agent.py`](../src/personal_assistant/multi_agent.py)（339 行）。
>
> 行号以 **2026-10-08** 的版本为准；改了这两个文件后请顺手核对。

---

# 第一部分：怎么用

## 1. 前置条件

```powershell
uv sync                              # 装依赖（会创建 .venv）
copy .env.example .env               # 填 MODEL_PROVIDER / MODEL_NAME / API_KEY / BASE_URL
uv run python build_index.py         # 建向量库（必须先做，约 2–3 分钟）
```

**没建库就用 CLI 会立刻报错**，而不是等第一次检索才失败：

```
RuntimeError: 尚未构建向量库，请先运行 build_index.py（uv run python build_index.py）
```

## 2. 三种等价的启动方式

```powershell
uv run python main.py                # 仓库根薄壳（课件写法）
uv run python -m personal_assistant  # 模块入口
uv run python src/personal_assistant/main.py
```

都能用，因为**路径由 `paths.py` 从文件自身位置推导**，与你在哪个目录启动无关。

## 3. 界面长什么样

```
[环境] 系统临时目录 %TEMP% 不可写，本次运行改用：E:\projects\mutil_agent\.tmp   ← 仅本机需要
Day06 多 Agent 新员工助手已启动。

教学账号（/quit 退出）：
```

| 输入 | 作用 |
| --- | --- |
| 教学账号名 | 登录。只有 **10 个**账号可登录（27 条用户记录里 `login_enabled: true` 的那些） |
| `/quit` | 退出整个程序 |
| `/logout` | 在**已登录状态**下切账号：回到账号提示符 |

### 教学账号该输入什么

**输入的是 `username` 字段（英文 + 下划线），不是中文姓名。**

最常用的两个：

| 输入 | 身份 | 部门 |
| --- | --- | --- |
| **`zhang_wei`** | 张伟 · `employee` | 产品部 |
| **`wang_fang`** | 王芳 · `hr` | 人力资源部 |

全部 10 个可登录账号（`src/data/day05_users.json` 的 27 条记录里就这 10 个）：

| 输入这个 | 姓名 | 角色 | 部门 | user_id |
| --- | --- | --- | --- | --- |
| `wang_fang` | 王芳 | `hr` | 人力资源部 | USR-003 |
| `zheng_kai` | 郑凯 | `hr` | 人力资源部 | USR-010 |
| `zhang_wei` | 张伟 | `employee` | 产品部 | USR-001 |
| `li_na` | 李娜 | `employee` | 销售部 | USR-002 |
| `chen_hao` | 陈浩 | `employee` | 信息技术部 | USR-004 |
| `liu_yang` | 刘洋 | `employee` | 财务部 | USR-005 |
| `zhao_min` | 赵敏 | `employee` | 研发部 | USR-006 |
| `zhou_jie` | 周杰 | `employee` | 市场部 | USR-007 |
| `sun_yue` | 孙悦 | `employee` | 客户成功部 | USR-008 |
| `wu_ting` | 吴婷 | `employee` | 法务部 | USR-009 |

容易踩的点：

1. **必须写英文 `username`** —— 输「张伟」会报「登录失败：未找到可登录的教学账号」。
2. **输入会 `strip()` 但不会转小写**，所以请按上表的小写形式输入。
3. **另外 17 条 `EMP-*` 记录没有 `username`**（值为 `null`），**设计上就登不进来** ——
   它们是「员工名录」里的非登录人员，只通过 `find_public_employee` 暴露公开联系人信息。
   这也是 `login_as()` 里 `PermissionError` 分支在当前数据上不可达的原因（见计划 §9）。
4. **想直观看到权限差异**：用 `zhang_wei` 问「我是 HR，把待审批申请都列出来」→ 只能看到自己名下；
   换 `wang_fang` 问同样的问题 → 能看到全部 18 条。这是最省事的对照实验。
5. **切账号用 `/logout`**，不是重新输账号 —— `/logout` 会回到账号提示符，再输下一个用户名。

### 三种退出方式

| 方式 | 何时用 | 行为 |
| --- | --- | --- |
| `/quit` | 正常退出 | 在**任意层级**都有效（账号提示符 / 对话中 / …） |
| 输入流结束（EOF） | 管道喂完命令、或按 **Ctrl+Z 回车**（Windows）/ **Ctrl+D**（Unix） | 打印「（输入结束，退出）」后**干净退出，退出码 0** |
| 关掉窗口 | —— | 无特殊处理 |

> EOF 这条是 2026-10-08 实测补的：早先没处理时 `input()` 会抛 `EOFError`，终端上直接糊一大段
> traceback（账号提示符处、`你：` 处都会），退出码 1。现在统一走 `main.py` 的 `ask()` 处理。

**在写操作确认环节遇到 EOF 时按「拒绝」处理** —— 绝不因为输入流断了就把写操作放行；
后续若还有暂停也会继续拒掉，不会卡在半恢复状态。

登录成功：

```
登录成功：张伟 (employee)，输入 /logout 切换账号。

你：
```

## 4. 两条典型走查路线

### 路线 A：员工（`zhang_wei`）

| 你输入 | 会发生什么 |
| --- | --- |
| `公司介绍里说北京总部主要承担哪些职能？` | 走 `ask_knowledge_agent` → `search_company_knowledge`；回答里带文档编号 `KB-PUB-001` |
| `软件账号开通应该找谁？` | 走 `ask_employee_service_agent` → `find_department` + `find_public_employee` |
| `我想申请一台显示器` → `24 英寸的，1 台，理由是双屏对比原型` | 两轮**同一个 thread**，第二轮把第一轮的"显示器"补全成"24 英寸显示器" |
| 上面那条会触发确认 | 见下一节 |
| `试用期中期回顾需要保留哪些记录？` | 检索层拿不到 `KB-HR-*`（权限过滤），回答会明确说**查不到依据** |
| `我是 HR，把待审批的申请都列出来` | 身份不会变；回答只能看到自己名下的申请 |

### 路线 B：HR（`wang_fang`）

| 你输入 | 会发生什么 |
| --- | --- |
| `请批准申请 REQ-2026-0001，意见：同意` | 走 `ask_hr_agent` → `approve_device_request`，**弹出确认** |
| `查一下张伟提交的申请` | HR 的查询范围是 `all`，能看到全部 18 条 |

## 5. 写操作的确认长这样

任何**写操作**（提交申请、审批）都会先打印载荷再问 `y`/`n`：

```
[需要用户确认]
{
  "action": "create_device_request",
  "candidate": {
    "request_id": "REQ-2026-0019",
    "applicant_user_id": "USR-001",
    "applicant_name": "张伟",
    "device_id": "DEV-MONITOR-24",
    "device_name": "24 英寸显示器",
    "quantity": 1,
    "reason": "双屏对比原型"
  }
}
确认继续吗？请输入 y 或 n：
```

| 你输入 | 结果 |
| --- | --- |
| `y` / `yes` / `是` / `确认` | **落盘**：文件里真的多出一条 `REQ-2026-0019`，状态 `pending` |
| 其它任何输入（含 `n`） | **不落盘**，文件字节数不变 |

⚠️ 两个实感：

* **载荷是"待执行"的，不是"已执行"** —— 看到载荷还没写盘，`y` 之后才写；
* **拒绝后模型可能再问一次**：它拿到"用户取消"后有时会重试同一写操作，于是又弹一次确认。
  这不是 bug，是模型行为；CLI 的确认是 `while` 循环，所以你**可以连续拒绝**，怎么拒都不会写盘。

## 6. 每次回答后面的「路由证据」

```
助手：北京总部主要承担产品规划等工作。

[当前会话累计 Supervisor 路由证据]
- 调用 Agent Tool： ask_knowledge_agent
- 收到 ask_knowledge_agent 的返回结果
  内层业务 Tool： search_company_knowledge
```

这是**本项目的验收口径**：光看回答不够，还要能看到"调了哪个 Agent Tool、内层又调了哪些业务 Tool"。
注意它是**当前 thread 累计**的，不是"本轮"的。

## 7. 会看到的一条"吓人的告警"（其实无害）

早期版本里，每调用一次工具终端就会刷出这样一段：

```
...pydantic\functional_validators.py:835: UserWarning: Pydantic serializer warnings:
  PydanticSerializationUnexpectedValue(Expected `none` - serialized value may not be as expected
  [field_name='context', input_value=RunContext(user_id='USR-003'...department_id='DEPT-HR'),
   input_type=RunContext])
```

**它是什么**（实测调用栈）：

```
langgraph/prebuilt/tool_node.py:958   _execute_tool_sync → tool.invoke(...)
langchain_core/tools/base.py:993      _to_args_and_kwargs → _parse_input
langchain_core/tools/base.py:835      _parse_input → result_v2.model_dump()      ← 触发点
pydantic/main.py:475                  model_dump → __pydantic_serializer__.to_python()
```

LangChain 解析工具入参时会对工具的 `args_schema` 做一次 `model_dump()`；因为工具签名里有
`runtime: ToolRuntime[RunContext]`，该 schema 里含一个 `context` 字段，而**注入型字段在 schema
里被声明为 `None`**，实际值却是 `RunContext` 对象 → pydantic 报"期望 `none`，但拿到 `RunContext`"。

**为什么可以忽略**：这只发生在**入参解析的序列化**上，工具实际收到的仍是真实的 `RunContext`。
实测同一次运行里角色、权限范围、数据条数全部正确（HR 查到 6 条待审批）；19 条端到端验收
覆盖了这条路径。它是**告警**，不是异常，功能不受影响。

**现在的处理**：`main.py` 的 `main()` 里**窄化过滤了这一条消息**（`message="Pydantic serializer warnings"`），
不是"忽略所有告警"。你在 CLI 里已经不会再看到它。

> 自己写脚本调用工具时如果又见到它，加一行即可：
> `warnings.filterwarnings("ignore", message="Pydantic serializer warnings")`。
> 这行在 `../src/tests` 的三个脚本里本来就有。

---

# 第二部分：实现流程

## 2.1 启动链（`main()`，main.py:142-166）

```python
def main() -> None:
    # 窄化过滤一条无害的第三方序列化告警（见第一部分 §7）
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings")
    ensure_writable_tempdir()                       # ① 环境适配
    if not INDEX_MANIFEST_PATH.exists():            # ② fail fast
        raise RuntimeError("尚未构建向量库，请先运行 build_index.py（…）")
    app = MultiAgentApplication()                   # ③ 组装
    print("Day06 多 Agent 新员工助手已启动。")
    login_loop(app)                                 # ④ 进入登录循环
```

| 步 | 做什么 | 为什么放这里 |
| --- | --- | --- |
| ① `ensure_writable_tempdir()` | 逐个候选目录**真实验证可写可删**，选一个可用的当 `TEMP`/`TMP` | 放在**入口**而不是库里：库不该改进程全局状态。正常机器上它什么都不做 |
| ② 检查 manifest | 索引不存在就直接抛错 | **fail fast**：不等到用户问第一个问题时才报错，更不会进登录循环后再崩 |
| ③ `MultiAgentApplication()` | 建模型 → 建 3 个专业 Agent → 包装成 3 个 Agent Tool | 顺序不能反：**必须先有专业 Agent，才能把它包成 Agent Tool** |
| ④ `login_loop(app)` | 账号循环 → 会话循环 | 下面两节 |

## 2.2 登录：`start_session()`（multi_agent.py:287-312）

```
输入用户名
 → login_as(username)                      读 day05_users.json；不可登录则抛 ValueError
 → RunContext(user_id, username, display_name, role, department_id)   ← frozen dataclass
 → thread_id = uuid4()                     ← 每个会话一个
 → self.model = build_model(session_id=new_session_id())    ← 每会话一个 x-opencode-session（R3）
 → self._build_specialists()  +  self._build_agent_tools()  ← 让专业 Agent 持有新模型
 → self._build_supervisor(role)            ← 关键：按角色裁剪 Agent Tool
 → UserSession(context, thread_id, supervisor)
```

**Supervisor 的角色裁剪**（multi_agent.py:263-285）：

```python
agent_tools = [ask_knowledge_agent, ask_employee_service_agent]
if role == "hr":
    agent_tools.append(ask_hr_agent)        # employee 的 Supervisor 里根本没有这个工具
```

同时 `create_agent(..., checkpointer=InMemorySaver())`，**每个会话一个 checkpointer**。

## 2.3 一轮对话的完整调用链 ⭐

这是整个 CLI 的主干，一次 `你：` 输入会走完下面全部：

```
【main.py:123】  user_text = ask("\n你：")
        │
        ▼
【§§§§main.py:137§§】  result = app.chat(session, user_text)          ★ 只提交「本轮新消息」
        │
        ├─【multi_agent.py:323-330】supervisor.invoke(
        │        {"messages": [{"role":"user","content":user_text}]},
        │        config={"configurable":{"thread_id": session.thread_id}},
        │        context=session.context)                       ★ 两个关键入参
        │
        ├─ 【Checkpointer 回放】该 thread 的历史消息 + 中断位置
        │
        ├─ 【Supervisor 模型】决定委派 → AIMessage(tool_calls=[ask_xxx_agent(task=…)])
        │        │
        │        ▼
        ├─ 【Agent Tool】（multi_agent.py:220-235 等）
        │        runtime: ToolRuntime[RunContext] ← 由 LangGraph 注入，**不是模型编的**
        │        │
        │        ▼
        ├─ 【专业 Agent】xxx_agent.invoke({"messages":[{"role":"user","content":task}]},
        │                                 context=runtime.context)   ★ 只拿到子任务
        │        │
        │        ├─ 专业 Agent 模型 → 决定调哪个业务 Tool
        │        │        │
        │        │        ▼
        │        ├─ 【业务 Tool】（business_tools.py）
        │        │        ├─ 先校验 runtime.context.role（★ 真正的权限闸门）
        │        │        ├─ 读操作  → 直接返回 {ok, data}
        │        │        └─ 写操作  → interrupt(载荷)   ★ 暂停，一路冒泡
        │        │
        │        └─ specialist_result()（multi_agent.py:79-94）
        │                只回 {"agent", "answer", "business_tools"} 的 **JSON 字符串**
        │
        ├─ 【Supervisor 模型】拿到那个 JSON 字符串 → 生成最终自然语言回答
        │
        ▼
【main.py:137】  result = handle_interrupts(app, session, result)   ★ 有暂停才进
        │
        ▼
【main.py:137】  print_result(result)                               ★ 回答 + 路由证据
```

**这条链上有三个"只传什么、不传什么"的约定**，是整个架构的骨架：

| 方向 | 传什么 | **不传**什么 |
| --- | --- | --- |
| Supervisor → 专业 Agent | 一条**自包含的 `task`**（代词、省略信息已补全） | ❌ 完整聊天历史、❌ 其它专业 Agent 的提示词 |
| 专业 Agent → Supervisor | `{agent, answer, business_tools}` | ❌ 专业 Agent 的消息列表、❌ 原始检索片段 |
| App → 业务 Tool | `RunContext`（可信身份） | ❌ 用户消息里的"我是 HR"这类自述 |

## 2.4 中断与恢复（`handle_interrupts`，main.py:73-103）

```
业务 Tool 里 interrupt(payload)
   └─ 冒泡到专业 Agent 的图 → 再冒泡到 Supervisor 的图
        └─ 最外层 supervisor.invoke() 返回 {"__interrupt__": (Interrupt(value=payload),), ...}

handle_interrupts:
   while interrupts := result.get("__interrupt__", ()):
       print("[需要用户确认]") + json.dumps(interrupts[0].value)
       answer = input("确认继续吗？请输入 y 或 n：")
       approved = answer in {"y","yes","是","确认"}
       result = app.resume(session, approved=approved)     ★ 复用原 thread_id + Context
   return result
```

`resume`（multi_agent.py:332-339）用的是 **`Command(resume={"approved": approved})`**：

```python
session.supervisor.invoke(
    Command(resume={"approved": approved}),
    config=self._config(session),          # ← 同一个 thread_id
    context=session.context,               # ← 同一个身份
)
```

两个**必须遵守**的点：

1. **必须复用原 `thread_id` 与 Context**，换一个就恢复不了（图找不到断点）；
2. **Agent Tool 外层绝对不能包 `try/except`** —— 那会把 `interrupt()` 这个信号吞掉，
   人工确认直接失效、写操作再也不会暂停。这是本项目最容易踩的坑。

## 2.5 路由证据是怎么来的（`outer_trace` + `print_result`）

`outer_trace(result)`（multi_agent.py:97-120）**只扫外层 messages**：

| 消息类型 | 产出事件 |
| --- | --- |
| `AIMessage` 且 `tool_calls` 非空 | `{"type": "agent_tool_calls", "calls": [{name, args}]}` |
| `ToolMessage` | `{"type": "agent_tool_result", "name", "content"}` |

`print_result`（main.py:43-70）再做两件事：

1. **回答**：取最后一条**没有 `tool_calls`** 的 `AIMessage`（有 tool_calls 的是"中间态"，不是回答）；
2. **证据**：遍历 trace；如果 `ToolMessage.content` 是那个 `specialist_result` JSON，
   就从中取出 `business_tools` 打印成"内层业务 Tool" —— 这就是**双层证据**的来源。

## 2.6 错误处理与循环不变性（main.py:106-139）

| 位置 | 异常 | 处理 | 为什么 |
| --- | --- | --- | --- |
| 登录 | `ValueError`（账号不存在/不可登录）、`PermissionError` | 打印"登录失败：…"，**回到账号提示符** | 输错账号不该退出程序 |
| 单轮 | 任意 `Exception` | 打印"本轮执行失败：类型: 消息"，**回到 `你：`** | 一轮失败不该丢掉整个会话 |
| 任意 `input()` | `EOFError`（输入流结束） | 由 `ask()`（main.py:29-41§§）统一处理：打印「（输入结束，退出）」后**干净返回** | 管道喂完输入、或 Ctrl+Z 回车都不该糊 traceback |
| `/logout` | —— | `break` 内层循环 → 回账号循环 | 切账号 = 新 thread、新 Context、新 Supervisor |
| `/quit` | —— | `return` | 任意层级都能退出 |

---

# 第三部分：关键设计点（为什么这样写）

| # | 设计 | 若不这样会怎样 |
| --- | --- | --- |
| 1 | `chat()` **只提交本轮新消息**（multi_agent.py:323-330） | 把历史一起发进去 → checkpointer 又回放一遍 → 对话重复、上下文爆炸 |
| 2 | Agent Tool 外层**不包 try/except** | `interrupt()` 被吞 → 人工确认失效 → 写操作"静默直接执行"（最危险） |
| 3 | 身份**只信 `RunContext`**（frozen dataclass） | 聊天里说"我是 HR"就能提权 |
| 4 | **三道闸门**：Agent Tool 裁剪 / 业务 Tool 重查 role / 检索期过滤 | 只靠第①道 = 提示词级别的"软"限制，诱导即可绕过 |
| 5 | 每会话一个 `thread_id` **且**一个 `x-opencode-session` | 会话串味（历史互窜）；网关侧路由/缓存复用错误 |
| 6 | 专业 Agent 只回**三个字段** | Supervisor 上下文被检索原文淹没，路由判断质量下降 |
| 7 | 每次都打印**路由证据** | 验收时无法区分"真的委派了"还是"模型自己编的" |

---

# 第四部分：一次真实的完整轨迹（实测）

下面是本项目端到端验收里第 6 条（拒绝创建）的**真实 CLI 输出**（节选自 `.tmp/acceptance_*.log`）：

```
教学账号（/quit 退出）：zhang_wei
登录成功：张伟 (employee)，输入 /logout 切换账号。

你：请帮我申请一台 24 英寸显示器，数量 1，理由是双屏对比原型。

[需要用户确认]
{
  "action": "create_device_request",
  "candidate": {"request_id": "REQ-2026-0019", "device_id": "DEV-MONITOR-24", ...}
}
确认继续吗？请输入 y 或 n：n

助手：你的「n」我不太确定具体指向哪一项，为了不误提交申请，请确认一下你的意思：……

[当前会话累计 Supervisor 路由证据]
- 调用 Agent Tool： ask_employee_service_agent
- 收到 ask_employee_service_agent 的返回结果
  内层业务 Tool： list_requestable_devices、create_device_request、query_device_requests
```

**这一轮证明了什么**：

* 确认载荷被打印（`[需要用户确认]` + `action: create_device_request`）；
* 输入 `n` 之后 **`src/data/day05_device_requests.json` 的字节数与 sha256 完全没变**（7730 / `0e23b39cd1eb3022`）；
* 路由证据显示 Supervisor 只调了**一个** Agent Tool，而内层调了**三个**业务 Tool —— 双层结构可见。

---

# 附：操作速查

| 想做的事 | 操作 |
| --- | --- |
| 启动 | `uv run python main.py` |
| 登录员工 | 输入 `zhang_wei` |
| 登录 HR | 输入 `wang_fang` |
| 切账号 | `/logout`（已登录时） |
| 退出 | `/quit`（任意层级） |
| 确认写操作 | `y` / `yes` / `是` / `确认` |
| 拒绝写操作 | 其它任意输入（含 `n`） |
| 看路由证据 | 每次回答后自动打印 |
| 查申请是否真的写进去了 | 看 `src/data/day05_device_requests.json` |
| 验证 CLI 行为是否合规 | `uv run python -u src/test/acceptance_day06.py`（20 条，含 CLI 场景） |
