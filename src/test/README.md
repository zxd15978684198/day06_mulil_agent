# src/test —— 阶段通过信号测试与端到端验收

本目录放三个脚本，都不属于交付代码，也不参与打包。

```powershell
# 路径由脚本自身推导，任意 CWD 都可运行（在仓库根运行最方便）
uv run python src/test/verify_phase4_repro.py  # 第四阶段（P5）最小复现，只读，秒级
uv run python src/test/verify_phase5.py        # 第五阶段（P6+P7+P8）通过信号，约 1 分钟
uv run python src/test/acceptance_day06.py     # §8 的 20 条端到端验收，约 3–5 分钟
uv run python src/test/acceptance_day06.py --only 3,4,12   # 只跑指定场景
uv run python src/test/acceptance_day06.py --list          # 只列场景清单
```

退出码：**全部通过为 0**，出现 FAIL（或写坏只读数据）为 1；
验收脚本遇到并发实例时**以退出码 3 拒绝执行**。

> `verify_phase4_repro.py` 原为仓库根的 `verify_p5.py`，2026-10-08 按技术方案评审 E11 移入本目录，
> 并把路径改为由 `__file__` 推导。它覆盖的阶段 4 口径已被 `acceptance_day06.py` 的场景
> 9 / 13 / 19 涵盖，此处保留为最小复现件。

---

## 一、`verify_phase5.py` —— 第五阶段通过信号

### A 组：确定性检查（不调用模型，秒级）

| # | 检查 | 判定依据 |
| --- | --- | --- |
| A1 | 三个专业 Agent 的 Tool 集合 | 并集**覆盖 7 个业务 Tool**；唯一跨 Agent 重叠是 `query_device_requests`（课件 §7.5 设计如此） |
| A2 | `specialist_result()` 输出 | 只含 `{agent, answer, business_tools}` 且可 `json.loads` |
| A3 | Supervisor 按角色裁剪 | employee 的 Tool 集合**不含** `ask_hr_agent`；hr 含 |
| A4 | Supervisor 不直接挂业务 Tool | 两个角色的 Supervisor 都只挂 Agent Tool |
| A5 | 无索引启动 | 立即抛错且**不进入登录循环**（`input()` 调用次数为 0） |
| A6 | `print_result()` | 同时打印回答、Agent Tool 名、内层业务 Tool 名 |
| A7 | **模型集成：应用实例的出站请求携带 `reasoning_content`** | **机制检查**，不是统计采样。thinking 模型要求下一轮回传推理内容，而 langchain 的发送侧序列化会丢掉该字段 → 多步工具调用偶发 400。判据：**首先**断言 `MultiAgentApplication().model` 的类型是 `ChatReasoningEcho` 且其出站 payload 带该字段（见计划 C12 / §9 第 12、13 条）。⚠️ 第一版只断言 `kb.build_chat_model()` 自己构造的实例，而应用走的是 `multi_agent.build_model()` —— 属"改了 A、测了 B" |

### B 组：需要真实模型

| # | 检查 | 判定依据 |
| --- | --- | --- |
| B1 | **R1**：嵌套 `interrupt()` 暂停到父图 | 父图返回 `__interrupt__`，载荷是内层业务 Tool 的；此时副作用文件未写入 |
| B2 | **R1**：同一 `thread_id` 恢复 | `Command(resume={'approved': True})` 后无 `__interrupt__`，副作用文件写入正确内容 |
| B3 | **R1**：拒绝路径 | `resume({'approved': False})` 后**不写入**。⚠️ 被拒绝后专业 Agent 可能**再次尝试**同一写操作（父图再次暂停），这是模型行为而非机制缺陷；本项在拒绝方向上循环到不再暂停（上限 5 次）。判据 = 「全程没有任何写入」**且「有效拒绝次数 ≥ 1」** —— 后者是 2026-10-08 评审补的：第一版只断言"文件不存在"，于是**一次都没走到拒绝路径也能判 PASS**，属空信号 |
| B4 | 多轮上下文 | 消息数增长；第二轮**用到第一轮内容**：若委派了专业 Agent，`task` 必须已补全指代；若直接从历史作答（合法行为），则要求回答切题。⚠️ 受模型表述影响，失败时自动换新 thread 重试一次 |
| B5 | `/logout` 效果 | 新会话拿到**新 `thread_id`**，新 thread 内消息数为 0，角色切换为 hr |

---

## 二、`acceptance_day06.py` —— §8 的 20 条端到端验收

逐条对应 `docs/Day06_执行计划_v2.md` §8 表格的「可观察证据」，要求四者相互印证：
**Agent Tool 调用 / 业务 Tool 调用 / 最终回答 / 数据文件实际状态**。

### 执行顺序（重要）

§8 是**表格，不是执行顺序**。脚本按下面的顺序跑，理由写在脚本里的 `EXECUTION_ORDER` 注释中：

```
12, 6, 9, 13, 14, 15, 19, 20, 1, 2, 3, 4, 5, 8, 11, 16, 17, 18, 7, 10
```

* **第 12 条排最前**：它要移走整个 `vector_store/`，而任何一次进程内检索都会打开 Chroma 句柄把文件占住；
* **第 7、10 条排最后**：它们会写数据（第 7 条给张伟新建一条申请 → 张伟就有 4 条；第 10 条把 `REQ-2026-0001` 从 `pending` 改成 `approved`）。若排在前面，第 13/16 条断言的「恰好 3 条」与第 8/9 条的前提「0001 仍 pending」都会被破坏。

### 数据安全

* 第 7、10 条会写 `src/data/day05_device_requests.json`。脚本开始时**备份**到
  `.tmp/acceptance_backup_device_requests.json`，结束时**还原**，并打印前后
  `(字节数, sha256前16位, 条数)` 三元组证明还原成功 —— **验收留痕，仓库回到 18 条**。
* 第 12 条真的移走 `src/vector_store/`，用 `finally` 保证移回，并显式释放进程内的
  Chroma 句柄（`_release_vector_store()`），否则 `os.rename` 会因文件占用失败。
* ⚠️ **本脚本不允许并发执行**：已用 `.tmp/acceptance.lock`（内含 PID）做单实例锁，
  第二个实例会打印「另一个验收进程（PID …）正在运行」并**以退出码 3 拒绝执行**。
  原因：两个实例会同时搬 `src/vector_store/`，第 12 条必然报
  `PermissionError: [WinError 5]` —— 这个故障真实发生过一次，表现看着像脚本坏了。
  锁在持有者退出后失效；若确认持有者已死，删掉锁文件即可。
  （判存活用 `OpenProcess`/`GetExitCodeProcess`，**不用 `os.kill(pid, 0)`** ——
  Windows 上那会直接 `TerminateProcess` 把对方杀掉。）

### 判定口径上的注意点

> **2026-10-08 技术方案评审修掉了五处弱断言**，修法与理由都写在各自函数的 docstring 里。
> 这里汇总，因为"验收台自证"比没有验收更危险 —— 它给出的是"通过"这个错误信号。

* **第 5 条（最严重）**：第一版判据是 `any(("显示器" in t or "24" in t) for t in tasks2)` —— 用的是**或**，
  而**第二轮用户原话本身就含「24 英寸」**，所以即使 Supervisor 完全丢掉第一轮也照样通过。
  实测日志里那一轮 `第一轮 task: (无)`（第一轮根本没调工具）→ 该场景当时**零证明力**。
  现在要求**两侧各自独有的信息同时出现**在同一个 task 里：「显示器」只来自第一轮、「24」只来自第二轮。
* **第 1 条**：第一版断言 `"KB-PUB-001" in answer`，而知识 Agent 的提示词里恰好写着
  「形如 KB-PUB-001《公司介绍与办公指南》」—— **等于把期望答案喂进被测系统**。
  现在提示词改用占位符 `KB-PUB-0NN`，断言改成正则匹配「出现了形如 `KB-XXX-000` 的编号」。
* **第 8 条**：第一版三条里两条不构成测试（一条断言在 frozen dataclass 上，一条只是把配置重算一遍）。
  现在新增**行为断言**：回答里不得出现**他人**的申请编号。
* **第 9 条**：补了**反方向**断言 —— 原来只验「employee 调 hr 专属工具」，
  现在同时验「hr 调 `create_device_request`」也应 `permission_denied`（边界是按角色授权，需双向）。
* **第 15 条**：期望值**固化在测试里**（`EXPECTED_NOT_REQUESTABLE`），不再从被测数据自身推导；
  另加一次交叉核对，迫使有人显式更新测试。
* **第 3 条分两层**（变更记录 C6）：`employee` 检索层必须是 **0 条 `KB-HR-*`**（安全边界，
  确定性判定）；「回答明确无法确认」属 Agent 层，用一组常见表述做**宽松匹配**，并加一条
  **反向断言：回答里不得出现 `KB-HR-001`**。第一版关键词太窄（只写「无法确认/查不到」），
  把模型回答里的「暂未查到」「均未命中」误判成未说明 —— 那是假阴性。
* **第 20 条优先按计划原文跑 `uv run --project`**；本机沙箱禁止 uv 写工作区外的缓存时，
  回退到 venv python 直接运行（验的是「CWD 无关」，与用哪个启动器无关），回退原因会写进证据。
* 依赖模型表述的场景（1–5、8、11、16、18 等）存在随机性，**FAIL 时先读证据**区分
  「机制缺陷」与「模型没照做」。

---

## 三、共同的前提与边界

* **需要可用的模型凭据**（`.env` 里的 `MODEL_PROVIDER` / `MODEL_NAME` / `API_KEY` / `BASE_URL`）。
* **本目录不参与打包**：`pyproject.toml` 的 `[tool.hatch.build.targets.wheel]` 只声明
  `packages = ["src/personal_assistant"]`；`uv sync` 实测正常。
* ⚠️ **目录名会遮蔽标准库的 `test` 包**：`src` 在 `sys.path` 上，因此 `import test` 会解析到本目录
  （实测 `find_spec('test').origin is None`，命名空间包）。对本项目无影响，但如果日后要写
  `import test.*` 之类的标准库测试辅助，或引入会这么做的第三方库，就需要把目录改名
  （惯例是 `tests/`，`tests` 不遮蔽任何标准库模块）。改名后请同步更新本 README 与运行命令。
* 本目录**不在**计划 §5.1 的目录布局里，是按需增加的测试位置；两个脚本都不修改任何交付代码。
* 两个脚本都会调用 `ensure_writable_tempdir()`：本机 `%TEMP%` 对子进程不可写时改走项目内
  `.tmp/`，正常机器上是空操作（详见 `knowledge_base.ensure_writable_tempdir` 的说明）。
