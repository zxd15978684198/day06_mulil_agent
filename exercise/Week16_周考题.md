# Week16_周考题

总分：**100分**（理论40分＋技能60分）　考试时间：**2小时**

理论题在 Excel 答题卡作答，技能题在配套 Python 文件作答。

## 一、判断题（每题1分，共10分）

填写 T（正确）或 F（错误）。

1. 一个系统调用了多个 Tool，就一定属于多 Agent 系统。F
2. 使用 `Send` 动态创建并行分支时，多个分支同时写入的聚合字段通常需要 Reducer。T
3. Handoff 只是调用一次专业 Agent 并立即把控制权交回调用者，不会影响后续对话归属。F
4. Agent Skill 可以包含 `SKILL.md`、参考资料、脚本和素材，并按需加载相关内容。T
5. MCP Tool 的描述可以帮助模型选择能力，但 Server 仍需执行参数校验、权限检查和副作用控制。T
6. `stdio` 传输中，Client 通常启动本地 Server 子进程并通过标准输入输出通信。F
7. FastAPI 可以根据 Python 类型注解和 Pydantic 模型对请求数据进行校验。T
8. `app.state` 适合保存应用级共享对象，但不应把每位用户的请求参数都混放在其中。T
9. SSE 是基于 HTTP 的服务器单向事件流，一条响应中可持续发送多个文本事件。T
10. 前端停止读取 SSE 响应后，可以推断服务端已回滚所有业务操作。F

## 二、单选题（每题1分，共20分）

每题只有一个正确选项。

**1.** 哪种情况更值得考虑拆分为多 Agent？B

A. 同一个 Agent 调用计算器和天气两个 Tool

B. 多个专业领域的工具、上下文和权限边界明显不同

C. 一个固定流程依次完成读取、转换和保存

D. 同一套权限和上下文即可完成全部任务

**2.** 必须按固定顺序执行、不需要模型决定下一步的任务，优先选择？A

A. 确定性工作流

B. 由 Supervisor 每一步都重新选择执行者

C. 将后续对话直接 Handoff 给专业 Agent

D. 让 Agent 自由循环直到自行判断结束

**3.** Supervisor 将专业 Agent 包装为 Tool 时，最准确的描述是？B

A. Supervisor 把全部控制权永久交给专业 Agent

B. Supervisor 选择并调用专业能力，之后继续掌控当前任务

C. 专业 Agent 必须和 Supervisor 使用完全相同的 State

D. 专业 Agent 的内部状态会自动暴露给调用者

**4.** Handoff 与 Agent-as-Tool 的主要区别是？A

A. Handoff 可以转移后续对话的控制权

B. Handoff 只能执行确定性的 Python 函数

C. Agent-as-Tool 由专业 Agent 接管后续全部对话

D. Handoff 完成后，原调用者一定立即收回后续对话控制权 B


**5.** 父图和子图 State 结构不同时，通常应？

A. 要求父图完全复制子图的所有内部字段

B. 使用包装 Node 明确转换输入和输出

C. 直接把父图 State 原样传入并忽略字段差异

D. 把所有字段都改成可选并取消边界检查

**6.** Web API 查询一个不存在的会话，且请求格式本身合法时，更合适返回？B

A. 200，并返回空字符串

B. 404，说明目标资源不存在

C. 422，说明 JSON 语法一定错误

D. 503，说明服务器必须停机

**7.** 哪项最适合做成 Agent Skill？B

A. 每次目标和验收方式都完全不同的一次性探索

B. 有稳定步骤、参考资料和验证标准的重复工作流

C. 只保存一个不会变化的配置常量

D. 没有稳定步骤、参考资料或检查方式的临时请求

**8.** Skill 中的 `scripts/` 目录最适合保存？C

A. 可重复执行、能够辅助处理或验证结果的脚本

B. 只供模型选择的 Tool 描述

C. 必须首先阅读的全部背景理论

D. 与工作流无关的临时下载文件

**9.** MCP 架构中，直接向用户提供 AI 交互环境的部分是？A

A. Host

B. Client

C. Server

D. Tool

**10.** MCP Server 中“可被模型选择并执行的操作”属于？A

A. Tool

B. Resource

C. Prompt

D. Elicitation

**11.** AI 应用需要读取一份由 MCP Server 提供的制度文本，更适合使用？C

A. Resource

B. Tool

C. Prompt

D. Sampling

**12.** 执行删除等高风险 MCP 操作前，Client 向用户请求确认的机制是？A

A. Elicitation

B. Sampling

C. Roots

D. Logging

**13.** 查询 ID 为7的用户，更合适的 HTTP 设计是？C

A. `GET /users/7`

B. `POST /users/7/query`

C. `GET /users` 并把 ID 放在请求体中

D. `GET /users/all/7`

**14.** FastAPI 中 `user_id: int` 收到字符串 `abc` 时，通常返回？B

A. 400

B. 404

C. 422

D. 500

**15.** 多个接口都要执行相同的请求头检查，更适合使用？A

A. `Depends`

B. 在每个路由中重复调用普通检查函数

C. 为整个应用添加无差别的全局中间件

D. `lifespan`

**16.** 应用启动时创建共享资源，关闭时清理，更适合放在？A

A. `lifespan`

B. 普通业务路由

C. `BackgroundTasks`

D. `Depends`

**17.** SSE 响应的媒体类型是？C

A. `application/json`

B. `text/plain`

C. `text/event-stream`

D. `application/octet-stream`

**18.** SSE 中用于标识事件位置、为重连恢复提供依据的字段是？A

A. `id`

B. `event`

C. `retry`

D. `data`

**19.** 浏览器需要用 POST 提交 JSON 并手动读取 SSE 响应流时，课件采用？B

A. `fetch()`

B. `EventSource`

C. `WebSocket`

D. `XMLHttpRequest` 的同步模式

**20.** SSE 已经发出 HTTP 200 后，流内又发生异常，更合适的做法是？B

A. 抛出 `HTTPException(500)`，要求已发送的响应头自动撤回

B. 在流中发送明确的 `error` 事件后结束

C. 直接结束生成器，但不告诉客户端任务是否成功

D. 再返回一个普通 JSON 响应替换当前事件流


## 三、填空题（每空1分，共10分）

1. LangGraph 中，并行分支写入同一个列表字段时，用于合并结果的规则称为 ＿＿＿Reducer＿＿＿＿＿＿＿。
2. Supervisor 模式中，负责选择专业 Agent 并汇总结果的角色是 ＿＿＿＿Supervisor＿＿＿＿＿＿。
3. Agent Skill 的主入口说明文件通常命名为 ＿＿＿＿skill.md＿＿＿＿＿＿。
4. MCP 架构中三个核心角色是 Host、Client 和 ＿＿＿＿＿Server＿＿＿＿＿。
5. MCP 中适合通过 URL 连接远程 Server 的现代传输方式是 ＿＿＿＿Streamable HTTP＿＿＿＿＿＿。
6. FastAPI 默认交互式接口文档的路径是 ＿＿＿＿http://127.0.0.1:8000/docs＿＿＿＿＿＿。
7. Pydantic 请求模型通常继承 ＿＿＿＿BaseModel＿＿＿＿＿＿。
8. FastAPI 中用于保存应用级共享对象的属性是 ＿＿＿＿app.state＿＿＿＿＿＿。
9. SSE 事件之间使用一个 ＿＿＿＿＿\n\n＿＿＿＿＿ 表示前一条事件结束。
10. Python 生成器使用关键字 ＿＿＿＿yield＿＿＿＿＿＿ 逐次产生流式内容。

## 四、技能题（共60分）

两道题各30分。素材和公开检查已放在 `Week16_答题_姓名.py`。只修改指定函数，可增加辅助函数；不得修改固定素材和公开检查。

### 第1题（30分）：图书目录查询 API

#### 1.1 你要完成什么

编写一个只读的图书目录 API。调用者可以：

- 查询图书列表，并按分类、最高价格和返回数量过滤；
- 根据图书 ID 查询单本图书；
- 在请求头不正确、参数不合法或图书不存在时得到明确的 HTTP 错误。

本题不需要数据库，不需要增加、修改或删除图书。

#### 1.2 答题文件已提供什么

| 名称 | 作用 | 是否需要修改 |
| --- | --- | --- |
| `BookOut` | 定义对外返回的图书字段 | 否 |
| `BOOKS` | 保存本题使用的四条图书数据 | 否 |
| `require_client()` | 检查 `X-Client-Id` 请求头 | 否 |
| `build_book_app()` | 创建 FastAPI 应用和两个路由 | **是，这是答题位置** |

`BOOKS` 中每条原始数据的结构如下：

```python
{
    "id": 1,                       # 图书唯一编号
    "title": "Python入门",       # 书名
    "category": "programming",    # 分类
    "price": 59.0,                 # 价格
    "internal_note": "不对外展示", # 内部字段
}
```

`BookOut` 只有 `id`、`title`、`category`、`price` 四个字段。因此，正确使用 `response_model` 后，`internal_note` 不应出现在 JSON 响应中。

#### 1.3 需要实现的函数

实现：

```python
def build_book_app() -> FastAPI:
    ...
```

该函数没有参数，需要创建并返回一个 `FastAPI` 应用对象。公开检查会把返回值交给 `TestClient`，再调用下面两个接口。

#### 1.4 接口一：`GET /books`

**作用**：返回图书列表。所有参数都放在 URL 的查询字符串中，不需要请求体。

| 参数 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `category` | `str | None` | `None` | 要查询的分类名。传入 `programming` 时，只保留 `category == "programming"` 的图书；不传时不按分类过滤 |
| `max_price` | `float | None` | `None` | 可接受的最高价格，边界包含等于。传入 `60` 时保留 `price <= 60`的图书；不传时不按价格过滤；值必须大于0 |
| `limit` | `int` | `10` | 最多返回多少条，取值范围为1–20。它在所有过滤完成后再截取列表 |

处理顺序必须是：

```text
BOOKS 原始顺序
    → 按 category 过滤（如果传入）
    → 按 max_price 过滤（如果传入）
    → 取前 limit 条
    → 返回 list[BookOut]
```

如果没有图书符合条件，返回空列表 `[]`，不是404。`limit=0`、`limit=21`或 `max_price=0` 由 FastAPI 参数校验返回422。

#### 1.5 接口二：`GET /books/{book_id}`

**作用**：根据路径中的图书 ID 返回单本图书。

- `book_id` 来自路径，例如 `/books/2` 中的值是 `2`。
- `book_id` 的类型是 `int`，且必须大于等于1；`/books/0` 应由 FastAPI 返回422。
- 在 `BOOKS` 中找到相同 `id` 时，返回该字典，并由 `BookOut` 约束最终 JSON。
- ID 形式合法但数据不存在时，抛出 `HTTPException(status_code=404, detail="图书不存在")`。

#### 1.6 两个接口的共同规则

- 两个接口都使用 `Depends(require_client)`。
- `require_client()` 会读取 `X-Client-Id` 请求头。值必须是 `classroom`；缺少或值不同时返回401和 `{"detail": "无效客户端"}`。
- 使用 `response_model` 声明输出，不得返回 `internal_note`。
- 不得修改 `BOOKS` 及其中的字典。

#### 1.7 调用示例与预期结果

```python
client = TestClient(build_book_app())
headers = {"X-Client-Id": "classroom"}
response = client.get(
    "/books?category=programming&max_price=60&limit=1",
    headers=headers,
)
print(response.status_code)
# 200
print(response.json())
# [{"id": 1, "title": "Python入门", "category": "programming", "price": 59.0}]

print(client.get("/books/99", headers=headers).json())
# {"detail": "图书不存在"}

print(client.get("/books?category=missing", headers=headers).json())
# []

print(client.get("/books?limit=0", headers=headers).status_code)
# 422
```

### 第2题（30分）：SSE 事件编码与流式接口

#### 2.1 你要完成什么

请先把 Python 数据编码为规范的 SSE 事件文本，再使用 FastAPI 提供一个“在线古诗逐句展示”接口。客户端选择一首古诗后，服务器通过 SSE 逐句返回诗文，每条 `line` 事件只携带一句诗：

```text
Python 数据
    → encode_sse()
    → 符合 SSE 格式的字符串
    → 异步生成器逐条 yield
    → StreamingResponse
    → 客户端逐句收到古诗
```

不要求编写前端。公开检查会使用 `TestClient` 调用接口，并把等待时间设为0。

#### 2.2 第一问：将 Python 数据编码成 SSE 文本（10分）

```python
def encode_sse(event, data, event_id=None) -> str:
    ...
```

**函数作用**：把一个事件名和一份 Python 数据组装成一条完整的 SSE 事件字符串。

| 参数 | 含义 | 示例 |
| --- | --- | --- |
| `event` | SSE 事件名，用于区分 `progress`、`done` 等事件 | `"progress"` |
| `data` | 事件携带的 Python 数据，必须能被 `json.dumps()` 编码 | `{"percent": 50}` |
| `event_id` | 可选事件编号；是 `None` 时不输出 `id:` 行 | `2` |

**返回值**：一个 `str`，内容是完整 SSE 事件。该函数不返回字典，也不直接发送网络响应。

**处理步骤**：

1. 先确认 `event` 是字符串，再执行 `strip()`。
2. 清理后的事件名为空，或含 `\r` / `\n` 时，抛出 `ValueError("无效的事件名")`。
3. 使用 `json.dumps(data, ensure_ascii=False, separators=(",", ":"))` 将 `data` 转为紧凑 JSON。
4. `event_id` 不是 `None` 时输出 `id: ...` 行，否则省略。
5. 行顺序固定为 `id`（如有）、`event`、`data`。
6. 行之间使用 `\n`，整条事件以 `\n\n` 结束。

```python
print(encode_sse(" progress ", {"percent": 50}, event_id=2))
# id: 2
# event: progress
# data: {"percent":50}
# 末尾还有一个空行
```

对应的实际返回字符串为：

```python
'id: 2\nevent: progress\ndata: {"percent":50}\n\n'
```

#### 2.3 第二问：实现逐句返回古诗的 SSE 接口（20分）

```python
def build_poem_app() -> FastAPI:
    ...
```

**函数作用**：创建并返回一个 FastAPI 应用。客户端传入古诗编号后，应用先发送古诗基本信息，再逐句发送正文，最后发送完成事件。

答题文件已经提供固定的 `POEMS` 字典，结构如下，学生不得修改：

```python
POEMS = {
    "jingyesi": {
        "title": "静夜思",
        "author": "李白",
        "lines": ["床前明月光，", "疑是地上霜。", "举头望明月，", "低头思故乡。"],
    },
    "dengguanquelou": {
        "title": "登鹳雀楼",
        "author": "王之涣",
        "lines": ["白日依山尽，", "黄河入海流。", "欲穷千里目，", "更上一层楼。"],
    },
}
```

请在函数中完成以下内容：

1. 创建 `FastAPI()` 应用，并定义 `GET /poems/{poem_id}/stream` 接口。
2. 路径参数 `poem_id` 的类型为 `str`，表示 `POEMS` 中的古诗编号。
3. 查询参数 `interval_ms` 的类型为 `int`，默认值为500，取值范围为0～2000，表示相邻两句诗之间等待多少毫秒；超出范围时由 FastAPI 返回422。
4. 在返回 `StreamingResponse` 之前检查 `poem_id`。编号不存在时抛出 `HTTPException(status_code=404, detail="古诗不存在")`。
5. 在路由函数内部定义异步生成器 `poem_stream()`，并用 `yield encode_sse(...)` 依次产生事件。必须复用第一问的 `encode_sse()`，不要重新拼接 SSE 字符串。
6. 使用 `await asyncio.sleep(interval_ms / 1000)` 控制相邻两条 `line` 事件的间隔；最后一句之后不再等待。`interval_ms=0` 时仍须正常返回全部事件。
7. 事件的顺序、名称、ID 和数据固定如下：

| 顺序    | 事件名        | 事件 ID             | `data` 数据                                                         |
| ----- | ---------- | ----------------- | ----------------------------------------------------------------- |
| 第1条   | `metadata` | `0`               | `{"poem_id": poem_id, "title": 标题, "author": 作者, "total": 诗句总数}`  |
| 每句诗1条 | `line`     | 从1开始的序号 `line_no` | `{"poem_id": poem_id, "line_no": line_no, "text": 当前诗句}`          |
| 最后1条  | `done`     | `诗句总数 + 1`        | `{"poem_id": poem_id, "status": "completed", "sent_lines": 诗句总数}` |

8. 路由返回：

```python
StreamingResponse(
    poem_stream(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache"},
)
```

例如，请求：

```python
GET /poems/jingyesi/stream?interval_ms=0
```

应返回状态码200，响应头 `Content-Type` 以 `text/event-stream` 开头，响应正文按顺序包含1条 `metadata`、4条 `line` 和1条 `done` 事件。其中4条 `line` 事件分别返回《静夜思》的4句诗，每条事件只能包含一句。

请求不存在的古诗，如 `/poems/not-found/stream`，应返回404和 `{"detail":"古诗不存在"}`。请求 `interval_ms=-1` 或 `interval_ms=2001` 时应返回422。

> 公开检查只验证部分可观察结果。即使显示“公开检查通过”，仍需确认代码满足异步生成器、逐句等待、复用编码函数等全部题目要求。
