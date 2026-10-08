# Day06 新员工助手（多 Agent）— 执行计划 v2

> 本文档是一份新的执行计划。
> 既有的 `docs/Day06_执行计划.md` **保持原样、不做任何改动**，本文档不替换、不覆盖它。

---

## Context

### 为什么要再做一份

`E:\projects\mutil_agent` 仍是空壳：`data/`（4 份业务 JSON）与 `knowledge/`（10 份知识文件 + 权限清单）已就位，但应用代码一行都没有 —— `main.py` 是 PyCharm 模板，`konwledge_base.py`（拼写有误）是空文件，`vector_store/` 为空，`pyproject.toml` 的 `dependencies = []`。

既有 `docs/Day06_执行计划.md` 已是一份可用计划。本文档重做，是因为**规格覆盖度被重新判定**：

课件的代码覆盖是**不完整**的。`build_index.py`、`multi_agent.py`、`main.py` 三个文件课件逐段给全了；但

- **`knowledge_base.py` 课件一行代码都没有** —— 只给了名字（`build_vector_store()`、`search_knowledge()`、`INDEX_MANIFEST_PATH`）和一条流水线描述（§5.3）；
- **`business_tools.py` 只给了约三成** —— 只有 `RunContext` 与 `login_as()` 两个片段，**7 个业务 Tool 的实现、`interrupt()` 的调用方式、错误码信封、编号生成全部没有**。

这两个模块恰好是「RAG 权限闸门」和「业务写入权限闸门」所在，也就是本项目的安全边界。**它们没有规格，是本计划最大的风险来源，也是本文档必须自己补上的部分**（见 §4）。

### 三份输入及其分工

| 输入 | 在本文档中的角色 |
| --- | --- |
| `docs/Day05_综合案例：新员工助手Agent.md` | **数据与业务规则的权威**：权限矩阵（§2.3）、知识清单字段语义（§2.4）、四份 JSON 关联方式（§2.5）、独立 RAG 通过标准（§3.6）、只读能力通过标准（§4.4）、写操作通过标准（§5.5）、固定验收场景（§7.2）、JSON 字段速查（附录 A） |
| `docs/Day06_多Agent综合项目：新员工助手升级.md` | **架构与代码的权威规格**：文件布局（§5.1）、向量库流水线（§5.3）、`multi_agent.py` 与 `main.py` 逐段代码（§7–§10）、固定验收场景（§12.1）、排查表（§13）、实现边界（§16.2） |
| `docs/Day06_执行计划.md` | **格式参考（只读）**：三件套写法（指令模板／通过信号／翻车信号／来源）、核验项的组织方式 |

**框架 API 契约**取自 LangChain / LangGraph 官方文档，本机已装 `langchain-docs` skill（`C:\Users\Administrator\.claude\skills\langchain-docs\`），按需查对应章节，不必上网（章节映射见 §10）。

### 明确排除：本机存在一份完整的参考实现

实测发现 `C:\Users\Administrator\Desktop\课程\agent教程\周十五\day06_multi_agent\` 下有本项目的完整参考实现，**其中包含课件从未展示的 `knowledge_base.py` 与 `business_tools.py`，以及 `requirements.txt`、`.env.example`、已装好依赖的 `.venv`、已构建的 `vector_store/`**。

**用户已决策：本计划完全从零实现，不读取、不参照、不搬运这份参考实现。** 因此：

- §4 的两个模块设计**全部来自课件接口 + Day05 业务规则 + 官方框架文档**的第一性原理推导，不来自该实现；
- 依赖版本**不从该实现的 `.venv` 抄**，由 P1 的 `uv add` 实际解析结果钉死；
- 该目录**只作为最后的一项验收外证**：本项目跑通后，可选用它交叉核对同一问题是否得到同类结论 —— 这一步是**可选的、不阻塞交付的**，也可以完全不做。

> 代价须知：排除参考实现后，§4 的每个设计决策都没有现成对标，必须靠 P2–P5 的通过信号逐个证伪。这是本次计划工作量与风险上升的主要原因，属用户已知并选择（决策 D1）。

### 交付物

1. `docs/Day06_执行计划_v2.md` —— 本文档
2. 可运行的 Day06 项目，**按 src 布局组织**（见下方「结构决策」）：`src/personal_assistant/` 下的 8 个模块 + 根目录两个薄壳入口 + `.env.example` + `requirements.txt`
3. 已构建的 `vector_store/`（含 `index_manifest.json`）
4. 一份真实的验收记录：§8 场景逐条的真实路由证据与业务数据快照

### 结构决策：采用 src 布局（决策 D4/D5/D6）

**本项目采用 src 布局（src layout），不用课件的平坦布局。** 可导入代码收进 `src/personal_assistant/`；`data/`、`knowledge/`、`vector_store/` 收在 **`src/` 下、包外**；`.env` 与配置文件留仓库根。布局见 §5.1。

> ⚠️ **这是对课件 §5.1 的有意偏离。** 课件假定所有 `.py` 平铺在项目根、用裸名互相 import（`from knowledge_base import ...`）。改用 src 布局后，**课件里任何逐段照抄的代码，其 import 块与路径常量都必须改写**（改写清单见 §5.2）。

理由：src 布局强迫代码只能 import **已安装的包**，而不是「恰好当前目录下的文件」——换目录运行就不会碰巧成功。同时它把代码与数据物理隔开，而本仓库根目录恰好同时躺着 `knowledge/`（数据目录）和 `konwledge_base.py`（模块），平坦布局的命名歧义在这里是真实存在的。

### 变更记录

| # | 变更 | 发起 | 影响 |
| --- | --- | --- | --- |
| C1 | 包名由 `day06_assistant` 改为 **`personal_assistant`**（决策 D5 已同步） | 用户指示 | 本文档全文的包路径与 `python -m` 命令；`src/personal_assistant/`；`[tool.hatch.build.targets.wheel].packages` |
| C2 | `[project].name` **保持 `mutil-agent` 不变** | 用户指示（「不是项目的名字」） | 仅 `uv pip list` 里的分发名与 import 包名不同名。§5.1 原有的「建议改名对齐」一条据此作废（见该节说明） |
| C3 | 相册图（海报）由 `ocr_or_multimodal` 走 OCR **升级为走多模态** | 执行中实测决定（阶段 2） | 视觉输出是 OCR 的严格超集；`parser_mode_actual` 记 `vision_multimodal` |
| C4 | 引入独立多模态接口（`VISION_*` 配置，当前为 GLM-5.3-Flash） | 用户指示 | §4.1 K5 原前提「`MODEL_NAME` 支持图像输入」被取代；manifest 记 `provenance` |
| C5 | `data/` `knowledge/` `vector_store/` 由**仓库根**移入 **`src/` 下（包外）** | 用户指示（「都归属与后端板块」） | 决策 D4、§5.1 目录图与说明、§5.2 的 `paths.py` 片段同步改写；`paths.py` 改为 `PACKAGE_DIR`/`SRC_ROOT` 两级推导；索引需重建一次（manifest 记录绝对路径） |

> C1/C2 是本文档自身的变更；C3/C4 已登记在阶段 2 的验收汇报里，此处汇总备查。


### 执行方式：分阶段推进 + 逐阶段验收门禁

**本项目不是一次跑完，而是分 6 个阶段推进。每个阶段结束都必须停下、提交验收、等待用户明确答复；用户不通过就不得进入下一阶段。** 硬规则、阶段划分与汇报格式见 §11。

> 这条规则优先于本计划其它一切「继续往下做」的表述。§6 的 P0–P9 是**阶段内部**的施工步骤，不是可以连续执行的 10 步。

### 明确不做

- 不改 `docs/Day06_执行计划.md`（用户指定）
- **不读取本机那份参考实现**（决策 D1）
- 不改 `data/` 中前 3 份 JSON 与整个 `knowledge/`（只读；`day05_` 前缀保留）
- 不做单/多 Agent 对比（课件 §12.3，属可选）
- 不接 MCP / Skill（课件 §1.3 明确不强制）
- 不做 FastAPI / 认证 / 数据库（课件 §16.3 属 Week16）

---

## 1. 已核实的事实

### 1.1 目标仓库的缺口

| 状态 | 文件 |
| --- | --- |
| 缺失 | `knowledge_base.py`、`business_tools.py`、`multi_agent.py`、`build_index.py`、`requirements.txt`、`.env.example` |
| 占位 | `main.py`（PyCharm 模板）、`konwledge_base.py`（空、拼写错，应删除） |
| 就位 | `data/` ×4、`knowledge/` ×10 + 清单 |
| 空 | `vector_store/` |

### 1.2 课件对代码的覆盖度（决定本文档 §4 的必要性）

| 模块 | 课件覆盖 | 结论 |
| --- | --- | --- |
| `build_index.py` | **完整**（§5.4） | 可直接照抄 |
| `multi_agent.py` | **完整**（§7–§10 逐段） | 可直接照抄 |
| `main.py` | **完整**（§10.3–§10.5） | 可直接照抄 |
| `business_tools.py` | **约三成**：仅 `RunContext`（§6.1）与 `login_as()`（§6.2） | **§4.2 必须自行设计** |
| `knowledge_base.py` | **零**：只有三个名字与一条流水线描述（§5.3、§5.4） | **§4.1 必须自行设计** |

### 1.3 课件自认未验证的范围（§16.2）

依赖安装后的真实模块导入；OCR、Embedding 与 Chroma 索引构建；专业 Agent 独立调用；Supervisor 外层 Agent Tool 与内层业务 Tool 调用；多轮 Thread 恢复；写操作暂停、拒绝与恢复；员工与 HR 会话隔离；固定场景与业务数据验收。

> 课件同时声明：自然语言回答、Agent 调用次数和申请编号**都不是预先承诺的固定运行结果**。

### 1.4 工具链

- `.venv` 由 uv 创建；**该 venv 内没有 pip** —— 课件 §5.3 的 `python -m pip install -r requirements.txt` 在本仓库必然失败，必须改用 `uv add` / `uv sync` / `uv run`。
- Python 3.13（`.python-version`、`pyproject.toml`）。
- 依赖的真实版本**由 P1 的 `uv add` 解析结果决定并当场钉死**（决策 D1 排除参考实现后，没有可抄的现成版本清单）。

### 1.5 数据事实（以仓库内 `data/` 为准，构建后逐条复核）

- 27 条人员记录；`USR-001`…`USR-010` 可登录，`EMP-011` 起为**仅通讯录**记录（`username`/`role`/`account_status` 为 `null`、`login_enabled: false`）。
  ⚠️ **`user_id` 前缀不统一** —— 任何按 `USR-` 前缀解析的写法都会漏掉 `EMP-*`，而这些人正是「找人办事」的正确答案。
- `zhang_wei` = `USR-001` 张伟（employee，DEPT-PRODUCT）；`wang_fang` = `USR-003` 王芳（hr，DEPT-HR）。
- 10 个部门；12 台设备（其中两台 `is_requestable: false` 且 `max_quantity_per_request: 0`，必须被拒绝）。
- 18 条申请（`REQ-2026-0001`…`0018`）。张伟本人 3 条（`0001` pending / `0003` approved / `0015` pending）→ 「申请隔离」可断言「恰好这 3 条」。
- 新建申请的编号**不是固定值**：课件 §11.3 用占位符 `<创建申请后得到的真实申请编号>`，§16.2 明确不承诺固定编号。**必须按「现有最大号 +1」计算并记录真实结果。**

---

## 2. 已确认的决策

| # | 决策 | 取值 |
| --- | --- | --- |
| **D1** | 参考实现的用法 | **完全从零，不读取、不参照、不搬运**（§Context 已述代价） |
| **D2** | 模型凭据 | **本机有可用凭据** → P9 端到端验收可完整执行，交付须含真实路由证据与业务数据快照 |
| **D3** | 落盘路径 | `docs/Day06_执行计划_v2.md` |
| **D4** | 项目结构 | **src 布局**：可安装代码在 `src/personal_assistant/`；`data/` `knowledge/` `vector_store/` 收在 `src/` 下、**包外**；`.env` 与配置文件留仓库根（有意偏离课件 §5.1，见 §5.1） |
| **D5** | 包名 | `personal_assistant` |
| **D6** | 根目录入口 | 保留 `main.py` 与 `build_index.py` 两个三行薄壳，课件命令与验收口径不变 |

---

## 3. 契约冻结（P0）

**开发模式：Spec** —— 一旦定了牵连全局。

### 3.1 可信运行上下文

```python
@dataclass(frozen=True)
class RunContext:
    user_id: str; username: str; display_name: str
    role: str          # "employee" | "hr"
    department_id: str
```

`frozen=True` 是硬要求：身份只能来自 `login_as()` 读到的 `day05_users.json`，聊天里的「我是 HR」不得改变它。（课件 D6§6.1）

### 3.2 七个业务 Tool 与执行端闸门

| Tool | 执行端闸门（**强制，非 Prompt 提示**） |
| --- | --- |
| `search_company_knowledge` | 检索前按 `allowed_roles` 过滤候选集 |
| `find_department` | 公开目录 |
| `find_public_employee` | 排除 `is_public == false`；**须能返回 `EMP-*` 记录** |
| `list_requestable_devices` | 同时校验 `eligible_roles` + `eligible_department_ids` + `is_requestable` + `max_quantity_per_request` |
| `create_device_request` | 申请人取自 Context；`interrupt()` 确认后才写 |
| `query_device_requests` | 员工按 `applicant_user_id` 过滤，HR 见全部 |
| `approve_device_request` | 校验 `role == "hr"` + 状态为 `pending` + 人工确认 |

统一内部顺序（课件 D6§6.3）：取 `runtime.context` → 查权限 → 校验参数与业务状态 → 读写 → 返回统一 JSON。

### 3.3 三个 Agent Tool 与角色裁剪

| Tool | employee | hr |
| --- | :---: | :---: |
| `ask_knowledge_agent` | ✓ | ✓ |
| `ask_employee_service_agent` | ✓ | ✓ |
| `ask_hr_agent` | ✗ | ✓ |

`specialist_result()` 只回 `{agent, answer, business_tools}`；`Command(resume={"approved": bool})` 必须复用原 `thread_id` 与 Context。

### 3.4 四类数据不许混

| 数据 | 位置 | 生命周期 |
| --- | --- | --- |
| 用户自然语言 | `messages` | 随 thread |
| 可信身份 | Runtime Context | 随会话 |
| 对话执行状态 | Checkpoint（`InMemorySaver`，按 `thread_id`） | 随 thread |
| 业务事实 | `data/day05_device_requests.json` | **跨会话、跨用户** |

### 3.5 唯一可写文件

**只有 `data/day05_device_requests.json` 会被程序修改。** 恢复初始状态 = 重新复制该文件（申请条数回到 18）。

---

## 4. 课件未指定模块的设计决策

> 本节是本文档的核心。§1.2 已述：这两个模块课件没有给规格，而它们正是权限闸门所在。
> 每条决策都配**通过信号**，在 P2–P5 逐个证伪。

### 4.1 `knowledge_base.py`

#### 固定接口（课件指定，不可改）

```python
INDEX_MANIFEST_PATH: Path        # 指向 vector_store/index_manifest.json，须支持 .exists()
def build_vector_store() -> dict # 键：document_count / chunk_count / vector_store_path / embedding_model
search_knowledge                  # @tool，签名含 runtime: ToolRuntime[RunContext]
```

`build_index.py`（课件 §5.4 已给全）已经消费了这四个键，`main.py`（课件 §10.5 已给全）已经消费了 `INDEX_MANIFEST_PATH.exists()` —— 两个调用方是硬约束，**签名不得改动**。

#### K1 解析分流 —— 按清单 `parser_mode`，不用一个 Loader 硬套

| `parser_mode` | 文件类型 | 解析方式 |
| --- | --- | --- |
| `text` | `.md` / `.txt` | 直接读文本（md 保留标题层级用于切分） |
| `document_text` | `.docx` | `python-docx`：段落 + 表格分别取 |
| `pdf_text` | 普通 `.pdf` | `pypdf` 抽文本层 |
| `html_text` | `.html` | `BeautifulSoup` 去脚本/样式后取正文 |
| `ocr_required` | 无文本层的扫描 PDF | 先渲染成位图 → RapidOCR |
| `multimodal_required` | `.png` 办公导览图 | 视觉模型（见 K5） |
| `ocr_or_multimodal` | `.jpg` 海报 | 先 OCR；可升级为视觉模型 |

> ⚠️ **清单里的 `path` 是相对 `knowledge/` 的，不是相对仓库根目录**（例：`public/day05_public_company_profile.md`）。拼接时必须用 `knowledge/` 作为基准，否则 10 份文件全部找不到。

**反例（明确不要）**：把 10 份文件交给同一个通用 Loader；扫描件抽出空串就当作「文档为空」丢掉。

#### K2 Chroma 元数据过滤 —— 权限模型的成败所在 ⚠️

Chroma 的 metadata **只接受标量**（`str` / `int` / `float` / `bool`），**不接受 list**，所以 `allowed_roles: ["employee","hr"]` 既不能原样存、也不能用 `$in` 过滤。

**决策：写入时把 `allowed_roles` 展开成「每角色一个布尔字段」。**

```python
metadata["allow_employee"] = "employee" in allowed_roles
metadata["allow_hr"]       = "hr" in allowed_roles
metadata["allowed_roles_csv"] = ",".join(allowed_roles)   # 仅展示/排错，不用于过滤
```

检索时：

```python
where = {f"allow_{role}": True}          # role 直接取自 runtime.context.role
```

- **fail-closed**：Chroma 的 `where` 是「必须匹配」语义，元数据缺该键的 chunk **不会**进入候选集。权限字段丢失时结果偏向「查不到」，而不是「越权查到」——这是正确的失败方向。
- `role` 只可能是 `employee` / `hr` 两个已知值（`RunContext` 由登录数据构造），因此 `f"allow_{role}"` 不存在注入面。
- **反例（明确不要）**：先无过滤召回、再在 Python 里剔除无权 chunk。课件 D5§9.2 明确：无权正文一旦进入模型上下文，边界已被突破。

#### K3 切分策略

`RecursiveCharacterTextSplitter`，中文分隔符序列 `["\n\n", "\n", "。", "；", "！", "？", "，", " ", ""]`，初始 `chunk_size=600`、`chunk_overlap=120`（**按字符计**）。

**这两个值是本计划的工程估计，不是课件规定**，须在 P3 抽 5 个 chunk 人工核对是否被从句子中间截断，必要时调整并把最终值写进 `index_manifest.json`。表格独立成块，不与正文混切。

#### K4 chunk 元数据继承

每个 chunk 写入：`document_id`、`title`、`path`、`version`、`status`、`parser_mode`、`access_scope`（展示）、`allowed_roles_csv`（展示）、`allow_<role>`（过滤，见 K2）、`chunk_index`、`chunk_id`。

`chunk_id = f"{document_id}#{chunk_index:03d}"`。
**权限一律读清单的 `allowed_roles`，不得从目录名 `public/` / `hr/` 推断。**

#### K5 多模态路径 —— 本计划的显式风险项 ⚠️

`multimodal_required` 要求 `MODEL_NAME` **支持图像输入**。这一点在 P2 之前是未知的。

- **支持**：把 PNG 交给模型，要求其描述**版面、位置关系、箭头方向、颜色标记**，输出标注为机器识别结果。
- **不支持（模型为纯文本）**：降级为 OCR，在 `index_manifest.json` 记 `parser_mode_actual: "ocr_fallback"`，并**如实记录 §8 第 18 条无法按原样完成**。
- **必须在 P2 第一步用一个最小图像调用探测清楚**，不要拖到最后才发现。

> 相关的口径缺陷：清单里导览图自带的 `suggested_questions`，其答案已写在图片页脚文字中，**无法区分多模态理解与纯 OCR**。验收须改用页脚未给出答案的空间问题（§8 第 18 条）。

#### K6 OCR 结果的处理

扫描件先由 `pypdfium2` 渲染为位图再送 RapidOCR。**OCR 输出是机器识别结果，不是原始事实**（课件 D5§3.1）：chunk 元数据打 `is_machine_extracted: True`，并在文本前加一行标注，避免下游把识别文本当成原文引用。至少抽查标题、关键数字与文档编号。

#### K7 失败处理 —— 不静默丢弃

任一文档解析失败：记入 `index_manifest.json` 的 `failures`（`path` + 异常类型 + 消息），由 `build_index.py` 打印，**保留原文件不动**。单份失败不阻断其余文档。

#### K8 `search_knowledge` 的检索流程

1. `role = runtime.context.role`
2. `where = {f"allow_{role}": True}`（K2）
3. Chroma 相似度检索 `k=5`
4. 返回结构化证据：每条含 `rank` / `document_id` / `title` / `path` / `chunk_id` / `access_scope` / `content`
5. **零命中返回 `ok: false, error: "no_evidence"`**，**不得**回落到模型常识编造制度

来源列表由程序按真实检索结果生成，**不让模型编造来源**（课件 D5§3.5）。

---

### 4.2 `business_tools.py`

#### 固定接口（课件指定，不可改）

`RunContext`（§3.1）、`login_as(username) -> dict`（课件 D6§6.2 已给全）、7 个 `@tool` 函数名与边界（§3.2）。`multi_agent.py` 的 import 块是硬约束：这 9 个名字必须存在。

#### B1 统一返回信封（7 个 Tool 一致）

```python
{"ok": True,  "data": {...}}                                    # 成功
{"ok": False, "error": "permission_denied", "message": "..."}   # 权限拒绝
{"ok": False, "error": "invalid_argument", "message": "..."}    # 参数非法
{"ok": False, "error": "not_found",        "message": "..."}    # 无此记录
{"ok": False, "error": "conflict",         "message": "..."}    # 状态不允许（如重复审批）
{"ok": False, "error": "no_evidence",      "message": "..."}    # 检索无据（K8）
```

`error` 是**稳定机器码**（验收断言它），`message` 是给人看的中文说明。课件只在两处点名了 `permission_denied`（§11.2、§12.1），其余四个码是本文档补齐的。

#### B2 身份获取

每个 Tool 第一句 `ctx = runtime.context`。**Tool 签名里不出现任何身份参数** —— 不接受调用方传入 `user_id`，模型也就无从伪造查询他人数据。

#### B3 JSON 读写

- **读**：每次调用都重新读盘。**不要**做模块级缓存 —— 业务数据跨会话共享，HR 审批后员工必须能读到新状态。
- **写**：**原子替换**（写 `*.tmp` 后 `os.replace()`），避免中断时写坏文件。
- **不加锁**：本课是单进程 CLI，加锁属过度设计；在 §9 记为「并发写不安全」。

#### B4 写操作的 `interrupt()` 与幂等（最关键）

`create_device_request`：

```python
candidate = {                     # 必须在 interrupt 之前算好，含编号
    "request_id": next_request_id(),
    "applicant_user_id": ctx.user_id, "applicant_name": ctx.display_name,
    "device_id": ..., "device_name": ..., "quantity": ..., "reason": ...,
}
decision = interrupt({"action": "create_device_request", "candidate": candidate})
if not decision.get("approved"):
    return {"ok": False, "error": "user_rejected", "message": "用户取消，未创建申请"}

# 幂等：恢复后先查该编号是否已存在
if any(r["request_id"] == candidate["request_id"] for r in requests):
    return {"ok": True, "data": existing_record}      # 不重复创建
_append_request(candidate, status="pending", requested_at=now_iso())
```

- **编号必须在 `interrupt()` 之前生成**，否则恢复时会算出不同的号 → 重复创建两条申请（课件 D5§5.2 明确要求避免）。
- **拒绝分支必须先于任何写盘操作返回** —— 用户拒绝时文件字节数不变。

`approve_device_request` 同构：载荷含 `request_id` + `decision` + `comment`；恢复后**重新校验四件事**（课件 D5§5.4）—— 角色仍为 HR、申请仍存在、状态仍为 `pending`、本次决定合法。任一不满足返回 `conflict`。

#### B5 编号生成

`REQ-2026-%04d`，取现有 `request_id` 数字部分的最大值 +1。**不写死 `0019`**（§1.5）。格式不匹配的记录**忽略而非崩溃**。

> 已知边界：先算号再并发写入可能撞号。单进程 CLI 下不成立，记入 §9。

#### B6 `query_device_requests` 的范围

`ctx.role == "hr"` → 全部（可加 `status` 过滤，供「查看待审批」用）；否则仅 `applicant_user_id == ctx.user_id`。**签名里不得出现 `user_id` 参数。**

#### B7 `find_public_employee`

过滤 `is_public == True`；**不得假设 `USR-` 前缀**（`F§1.5`）；返回字段走白名单 —— 只给 `user_id` / `display_name` / `department_id` / `job_title` / `expertise` / `office_location` / `office_contact`，**一律剔除** `username` / `role` / `login_enabled` / `account_status` / `is_public`。

> 白名单而非黑名单：模型根本接触不到敏感字段（课件 D5§4.2）。
>
> **数据里自带两个反面样本**：`EMP-026` 宋妍 与 `EMP-027` 魏然 的 `is_public: false`（且 `office_contact: null`），是全库**仅有的两条**非公开记录。其余 25 条均为 `is_public: true`。这两条是天然的负例，见 §8 第 19 条。

#### B8 `list_requestable_devices`

四项**同时**校验：`is_requestable == True` ∧ `max_quantity_per_request > 0` ∧ `ctx.role in eligible_roles` ∧ (`eligible_department_ids` 为空 **或** 含 `ctx.department_id`)。

> `eligible_department_ids: []` 表示**无部门限制**，**不是**禁止申请（Day05 附录 A.3）。
>
> **实测分布**：12 台设备里 8 台是 `eligible_department_ids: []`（无限制），另 4 台有限制且同时限定 `eligible_roles: ["employee"]`（不含 hr）—— `DEV-LAPTOP-PRO`、`DEV-MONITOR-27`、`DEV-DRAWING-TABLET`、`DEV-MOBILE-TEST`。
> 张伟属 `DEPT-PRODUCT`，**选到不对口的设备会正当失败**，这不是 bug。§8 第 7 条的创建验收建议用 `DEV-MONITOR-24`（无部门限制、`max_quantity_per_request: 2`）最稳。

#### B9 `login_as()`

按课件 D6§6.2 原样：筛 `login_enabled == True` 且 `account_status == "active"`；不可登录抛 `PermissionError`，无此账号抛 `ValueError`。**不创建 Agent / Thread**（课件 §6.2 明确由 `start_session()` 负责）。

---

## 5. 模块全景

### 5.1 目录布局（src 布局）

**决策 D4 / D5 / D6。** 与课件 §5.1 的平坦布局不同，可导入代码全部收进 `src/`。

```text
E:\projects\mutil_agent\                 ← PROJECT_ROOT（pyproject.toml、.env 所在）
├── pyproject.toml                       ← 新增 [build-system]（见下）
├── README.md                            ← 当前 0 字节，pyproject 引用了它
├── .gitignore                           ← 已忽略 .venv 与 .env，无需改
├── .env / .env.example                  ← 运行时配置，留在根
├── requirements.txt
├── uv.lock
├── main.py                              ← 薄壳（3 条语句）→ personal_assistant.main
├── build_index.py                       ← 薄壳（3 条语句）→ personal_assistant.build_index
└── src/                                 ← SRC_ROOT
    ├── personal_assistant/              ← 可安装的代码包（PACKAGE_DIR）
    │   ├── __init__.py
    │   ├── __main__.py                  ← 支持 python -m personal_assistant
    │   ├── paths.py                     ← 路径解析 + 布局断言
    │   ├── knowledge_base.py
    │   ├── build_index.py
    │   ├── business_tools.py
    │   ├── multi_agent.py
    │   └── main.py
    ├── data/                            ← 业务 JSON（唯一可写文件在此）
    ├── knowledge/                       ← 知识文件 + 权限清单
    └── vector_store/                    ← Chroma 索引
```

**为什么数据目录在 `src/` 下、却放在包外**：`data/day05_device_requests.json` 是**运行时会被写入**的文件，`vector_store/` 也是生成物；而包目录是**安装产物** —— 一旦本项目被非可编辑方式装进 site-packages，程序就会往 `.venv/Lib/site-packages/...` 里写业务数据。所以数据收进 `src/`（归属后端板块），但**不放进 `src/personal_assistant/`**，两者物理隔开，由 `paths.py` 统一解析。

**`pyproject.toml` 新增**：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/personal_assistant"]
```

> **顺序要求**：先建出 `src/personal_assistant/__init__.py`，**再**加 `[build-system]`。反过来的话 `uv sync` / `uv add` 会因为找不到包直接失败。
> `[project].name` 保持 `mutil-agent` **不改**（用户指示：只改 `src/` 下的包名，不动项目名）。
> 代价仅是 `uv pip list` 里的分发名（`mutil-agent`）与 import 的包名（`personal_assistant`）不同名，不影响运行；验收命令一律用**包名**。

### 5.2 路径解析与 import 改写 ⚠️

src 布局有两个必然的破坏点，P1 一次性处理掉。

**（1）跨模块 import 改用全包名。**

| 课件原样 | src 布局下 |
| --- | --- |
| `from knowledge_base import build_vector_store` | `from personal_assistant.knowledge_base import build_vector_store` |
| `from knowledge_base import INDEX_MANIFEST_PATH` | `from personal_assistant.knowledge_base import INDEX_MANIFEST_PATH` |
| `from business_tools import (RunContext, ...)` | `from personal_assistant.business_tools import (RunContext, ...)` |

**（2）课件用 `__file__` 找 `.env` 的写法会失效，而且是静默失效。**

课件 §7.1 的 `build_model()` 里是：

```python
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_DIR, ".env"), override=False)
```

搬进 `src/personal_assistant/` 后 `__file__` 指向包目录，`.env` 会被找成 `src/personal_assistant/.env` —— **文件不存在，`load_dotenv` 不报错、只是什么都不加载**，于是 `build_model()` 抛「请在 .env 中配置 MODEL_PROVIDER 和 MODEL_NAME」，而你去检查 `.env` 发现明明写好了。

**所有路径统一由 `paths.py` 提供**，任何模块都不许再自己拼 `__file__`：

```python
# src/personal_assistant/paths.py
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent   # → src/personal_assistant
SRC_ROOT = PACKAGE_DIR.parent                   # → src
PROJECT_ROOT = SRC_ROOT.parent                  # → 仓库根（pyproject.toml / .env）
DATA_DIR = SRC_ROOT / "data"
KNOWLEDGE_DIR = SRC_ROOT / "knowledge"
VECTOR_STORE_DIR = SRC_ROOT / "vector_store"
ENV_PATH = PROJECT_ROOT / ".env"


def _assert_layout() -> None:
    """层级数错或非可编辑安装时，此处 fail fast。"""
    missing = [p.name for p in (DATA_DIR, KNOWLEDGE_DIR) if not p.is_dir()]
    if missing:
        raise RuntimeError(
            f"项目路径解析错误：{SRC_ROOT} 下找不到 {missing}。"
            "本项目按 src 布局运行（数据在 src/ 下、包外），"
            "须以可编辑方式安装（uv sync）并从仓库内运行。"
        )


_assert_layout()
```

断言的理由：相对层级只在**可编辑安装**（`uv sync` 的默认行为）下正确。若被当成普通 wheel 装进 site-packages，它会指向 `Lib/site-packages` 附近 —— 此时**必须报错，而不是去别的目录找文件**。

> **数据在 `src/` 下是决策 D4 的一部分**：`SRC_ROOT` 由 `PACKAGE_DIR.parent` 得到，所以数据位置随包位置一起确定，不额外依赖 `parents[N]` 的层数假设；加一层目录不会静默走错。

**收益**：路径基于 `__file__` 而非 CWD，因此**从任何目录运行**都能找到 `data/` / `knowledge/` / `.env`。这本身是一条防护性验收（§8 第 20 条）。

### 5.3 数据流

```
knowledge/*.{md,txt,html,docx,pdf,png,jpg}
        │
        ▼
┌──────────────────────────────────┐
│ knowledge_base.py                │  K1 按 parser_mode 分流解析
│  build_vector_store()            │  K6 OCR / K5 多模态
│  search_knowledge(runtime)       │  K3 切分 → K4 继承权限元数据
│  INDEX_MANIFEST_PATH             │  K2 展开 allow_<role> → Chroma 持久化
└──────────────┬───────────────────┘  build_index.py ──► vector_store/
               │                       K8 检索时 where={"allow_<role>": True}
data/*.json ──►┌┴────────────────────┐
(users/depts/  │ business_tools.py    │  B2 身份只取 runtime.context
 devices)      │ RunContext/login_as  │  B1 统一错误信封 / B3 原子写
               │ + 7 个业务 Tool       │  B4 interrupt() + 幂等
               └─────────┬────────────┘
                         │
               ┌─────────┴────────────┐
               │ multi_agent.py       │  （课件 §7–§10 逐段给全，照抄）
               │ 3 专业 Agent          │
               │   ↑ Agent Tool 包装   │
               │ Supervisor(按角色裁剪) │
               │ UserSession/chat/resume│
               └─────────┬────────────┘
                         ▼
                    main.py (CLI)      （课件 §10.3–§10.5 给全，照抄）
```

**步骤拼装关系**：P1 环境 → P2–P4 知识层 → P5 业务层 → P6–P8 编排层 → P9 端到端验收。
**P2–P4 与 P5 互不依赖，可并行**；P6 依赖 P5 的 Tool 与 P4 的检索入口。

**步骤划分依据**：以上数据流链。P2→P3→P4 沿「解析→入库→检索」切，P5 沿「身份→校验→读写→返回」切。

> 图中 `knowledge_base.py` / `business_tools.py` / `multi_agent.py` / `main.py` / `build_index.py` 五个名字，在 src 布局下**都位于 `src/personal_assistant/`**（§5.1）；根目录只留 `main.py` 与 `build_index.py` 两个薄壳。图中保留裸名是为了与课件章节一一对应。

---

## 6. 分步实现路径

> 开发模式依据：契约/顺序用 **Spec**，纯逻辑用 **TDD**，真实环境用 **场景测试**。
> 来源列：`课件D6§n` = Day06 课件章节；`课件D5§n` = Day05 课件章节；`F<n>` = §1 实测事实；`K<n>`/`B<n>` = §4 设计决策；`D<n>` = §2 已确认决策。
>
> ⚠️ **P0–P9 是阶段内部的施工步骤，不是可连续执行的 10 步。** 每走完一个阶段（见 §11.2 的划分）必须停下提交验收，用户明确通过后才继续。

### P0 契约冻结 · **Spec**

- **目标**：把 §3 的 `RunContext`、`ROLE_PERMISSIONS`（课件 D5§2.3 已给矩阵）、7 个 Tool 签名、四类数据边界先写成类型与常量，**先于任何实现**。
- **产出**：`src/personal_assistant/business_tools.py` 顶部的 `RunContext` 与 `ROLE_PERMISSIONS`。
- **指令模板**：「按下面规格定义 `RunContext`（frozen dataclass）与 `ROLE_PERMISSIONS` 常量表。**不要**实现任何 Tool 函数体，**不要**为 `employee` 添加 `review_device_requests` 权限，**不要**把权限挂到用户记录上。」
- **通过信号**：`uv run python -c "from personal_assistant.business_tools import RunContext, ROLE_PERMISSIONS"` 无报错；对 `RunContext` 赋值抛 `FrozenInstanceError`。
- **翻车信号**：出现 `permissions` 字段挂在用户记录上 → 违背课件 D5§2.2「用户记录只保存 `role`」。
- **来源**：`课件D6§6.1`、`课件D5§2.3`

### P1 环境与依赖 · **Spec**

- **目标**：建出 src 骨架、装依赖、钉版本、建立 `.env`。
- **产出**：`src/personal_assistant/` 的 `__init__.py` / `__main__.py` / `paths.py`、`pyproject.toml` 的 `[build-system]`、`requirements.txt`、`.env.example`、`.env`（gitignore）。
- **执行顺序**（**顺序错了会失败**，见 §5.1）：
  1. 建 `src/personal_assistant/__init__.py`（空文件即可）与 `paths.py`（§5.2）
  2. `pyproject.toml` 加 `[build-system]` 与 `[tool.hatch.build.targets.wheel]`
  3. `uv sync` —— 此时本项目应被以**可编辑方式**装上
  4. `uv add` 逐个添加依赖（每次都会触发一次 sync）
  5. 建 `.env.example` 与 `.env`
- **指令模板**：「用 `uv add` 添加依赖并把解析出的实际版本写进 `requirements.txt`。**不要**用 `python -m pip`（本 venv 无 pip）。**不要**把 `.env` 提交进 git。**不要**在代码里硬编码 API Key。**不要**在包模块里用 `__file__` 自己拼路径，一律走 `paths.py`。」
- **依赖清单**（由 §4 的设计推导，非抄自任何现成文件）：`langchain`、`langchain-openai`、`langgraph`、`langchain-chroma`、`chromadb`、`langchain-huggingface`、`sentence-transformers`、`python-dotenv`、`pypdf`、`pypdfium2`、`python-docx`、`beautifulsoup4`、`rapidocr-onnxruntime`（或等效 RapidOCR 包）、`pillow`。
- **通过信号**：`uv run python -c "from personal_assistant.paths import PROJECT_ROOT; print(PROJECT_ROOT)"` 打印出**项目根**（**不是** `...\src` 或 `...\src\personal_assistant`）；`uv pip list` 显示本项目已以可编辑方式安装；`uv run python -c "import langchain, langgraph, chromadb"` 成功；`uv pip list` 输出含全部依赖及**实际版本**，并记录进交付物；**并做一次最小模型调用**（`build_model()` 后发一条最简消息）确认真实返回。
  > 凭据是否可用**至今未经验证**（D2 只是「本机有凭据」这一前提）。**必须在阶段 1 就打通**，不要拖到阶段 6 才发现 `API_KEY` / `BASE_URL` 不通 —— 那时返工面最大。
- **翻车信号**：`No module named pip` → 误用了 pip；`uv sync` 报找不到包 → `[build-system]` 加在了 `__init__.py` 之前；`PROJECT_ROOT` 打印到 `src` 层 → `parents[2]` 数错了；`EMBEDDING_MODEL` 首次下载失败 → 查网络 / HF 镜像。
- **来源**：`F§1.4`、`课件D6§5.3`、`K1`、`K6`

### P2 文档解析 + 权限元数据 · **场景测试**

- **目标**：10 份文件解析成带权限元数据的文本。
- **产出**：`src/personal_assistant/knowledge_base.py` 的解析层（依赖 `paths.py` 的 `KNOWLEDGE_DIR`）。
- **要点**：实现 K1 的七条分流路径；K6 的 OCR 标注；K5 的多模态探测；K7 的失败保留。
- **第一步先做 K5 探测**：用一次最小图像调用确认 `MODEL_NAME` 是否支持图像输入，把结论记下来再决定导览图走哪条路。**不要拖到最后。**
- **指令模板**：「按清单 `parser_mode` 实现七条解析路径。**不要**用同一个 Loader 硬套所有格式。**不要**在解析失败时静默丢弃文件。**不要**从目录名或文件名推断权限，一律读清单的 `allowed_roles`。**不要**把 OCR 输出当成原始事实。」
- **通过信号**：打印每份文件的「解析方式 / chunk 数 / 是否机器识别」；扫描件 OCR 结果非空且含标题；导览图返回空间描述而非仅文字（或如实记录降级）。
- **翻车信号**：扫描件返回空字符串 → OCR 未生效（该 PDF 实测**没有文本层**：`pdftotext` 只出 2 字节，两页全空，符合清单 `contains_text_layer: false`）；`allowed_roles` 缺失 → 权限会静默放开。
  > ⚠️ **Windows 控制台陷阱**：Git Bash 的代码页会把中文 stdout 显示成乱码，看起来像「解析出空文本」。**实测已有人被这个骗过一次** —— 判断解析是否成功要看**字节数或十六进制**，不要只看终端里显示成什么样。另：两份非扫描 PDF（设备制度、HR 关系指引）**确实有可用文本层**（4527 / 4017 字节），`pdf_text` 路径可行。
- **来源**：`课件D6§5.3`、`课件D5§3.1`、`K1`、`K5`、`K6`、`K7`

### P3 向量库构建 · **场景测试**

- **目标**：Embedding + Chroma 持久化 + 索引清单。
- **产出**：`src/personal_assistant/build_index.py`（课件 §5.4 已给全，**import 需改写**）、根目录 `build_index.py` 薄壳、`vector_store/index_manifest.json`。
- **要点**：实现 K2 的 `allow_<role>` 展开、K3 的切分与抽查、K4 的元数据继承。
- **指令模板**：「实现 `build_vector_store()` 返回含 `document_count` / `chunk_count` / `vector_store_path` / `embedding_model` 的 dict，让 `build_index.py` 打印真实统计。**不要**把统计数字写成常量。**不要**在索引里丢失权限元数据。**不要**把 `allowed_roles` 原样当 list 塞进 Chroma，它只接受标量（K2）。」
- **通过信号**：`uv run python build_index.py` 打印四项统计；`index_manifest.json` 存在，数字与 10 份源文件一致；**抽 5 个 chunk 人工核对未被句子中间截断**（K3）。
- **翻车信号**：Chroma 目录为空但脚本报成功；数字与源文件不符；写入时抛「metadata value must be a scalar」。
- **来源**：`课件D6§5.4`、`课件D5§3.2`、`课件D5§3.3`、`K2`、`K3`、`K4`

### P4 权限检索 · **场景测试**（安全边界，最高优先级）

- **目标**：按 K8 实现 `search_knowledge` —— **检索阶段**就按角色过滤。
- **指令模板**：「检索时用 `where={f"allow_{role}": True}` 过滤。**不要**先召回再在 Python 里剔除无权 chunk —— 课件 D5§9.2 明确：无权正文一旦进入模型上下文，边界已被突破。**不要**让模型决定检索范围。**不要**在零命中时让模型用常识补答。」
- **通过信号**：同一问题「试用期中期回顾需要保留哪些记录？」，`role=employee` 返回**零条 HR 证据**并说明无法确认；`role=hr` 返回 `KB-HR-001` 证据与来源。
- **翻车信号**：employee 召回到 `KB-HR-*` → 权限闸门失效（**安全边界缺陷，最高优先级**）。若出现，先修 K2 的元数据形态，不要靠 Prompt 遮掩。
- **来源**：`课件D5§3.6`、`课件D5§9.2`、`课件D6§12.1`、`K2`、`K8`

### P5 业务 Tool 层 · **Spec + 场景测试**

- **目标**：`login_as()` + 7 个 Tool，按 B1–B9 实现。
- **指令模板**：「每个 Tool 第一句都从 `runtime.context` 取身份并做权限判断。**不要**接受调用方传入的 `user_id`。**不要**让写操作在确认前落盘。**不要**在 `EMP-*` 前缀上做假设。**不要**缓存 JSON，每次重新读盘。」
- **通过信号**：`employee` 直接调 `approve_device_request` 返回 `permission_denied` 且 JSON **字节不变**；`find_public_employee` 能返回 `EMP-*` 记录；张伟查申请恰好 3 条；`list_requestable_devices` 不含 `is_requestable: false` 的设备。
- **翻车信号**：员工能查到他人申请；`EMP-*` 查不到（`F§1.5` 前缀陷阱）；返回了 `username` 等非公开字段。
- **来源**：`课件D6§6.3`、`课件D5§4.4`、`课件D5§5.5`、`F§1.5`、`B1`–`B9`

### P6 专业 Agent + Agent Tool 包装 · **Spec**

- **目标**：三个专业 Agent + 三个 `@tool` 包装；`specialist_result()` 只回 `{agent, answer, business_tools}`。
- **产出**：`src/personal_assistant/multi_agent.py` 的 §7、§8 部分。
- **来源**：`multi_agent.py` 的 §7、§8 **课件逐段给全，照抄**。两个注意点：①§9.2 重复出现的 import 要去重合并到文件顶部；②课件里的 `from business_tools import (...)` 与 `PROJECT_DIR = os.path.dirname(...)` **必须按 §5.2 改写**（前者换成全包名，后者删掉改走 `paths.py`）。
- **指令模板**：「三个专业 Agent 各自只挂本职 Tool。**不要**给知识 Agent 挂审批 Tool。**不要**把专业 Agent 的整份消息历史回传 Supervisor。**不要**用宽泛 `try/except` 包住 Agent Tool —— 内层 `interrupt()` 的暂停信号会被吞掉。」
- **通过信号**：打印三个 Agent 各自的 Tool 名称集合，互不重叠且并集覆盖 7 个 Tool；`specialist_result` 输出可 `json.loads`。
- **翻车信号**：Agent Tool 里出现 `try/except Exception` → 人工确认必然失效。
- **来源**：`课件D6§7.5`、`课件D6§8.3`

### P7 Supervisor + 会话 + 中断恢复 · **Spec** ⚠️ 最高风险

- **目标**：Supervisor 只持有 Agent Tool；按角色裁剪；`UserSession` / `chat()` / `resume()` / `outer_trace()`。
- **产出**：`src/personal_assistant/multi_agent.py` 的 §9、§10 部分。
- **来源**：课件 §9–§10 **逐段给全，照抄**。本地查 `ch26-interrupts-time-travel.md`、`ch24-persistence-checkpointers.md`、`ch23-subgraphs.md` 核对 API 契约。
- **核验点 R1**：Agent Tool 调用的专业 Agent 是否继承父级 Checkpointer 并在一次调用中使用 `interrupt()`。课件 §8.3 自认未验证（`F§1.3`）。
- **处置预案**（课件 §13 也提到）：若嵌套暂停不成立，把确认提到 Supervisor 外层固定节点 —— 专业 Agent 只返回「待确认载荷」，由 Supervisor 侧的 `interrupt()` 负责暂停与恢复。
- **指令模板**：「Supervisor 只挂 Agent Tool，不直接挂业务 Tool。`chat()` 只提交本轮新消息（**不要**重复传历史，Checkpointer 会重放导致重复）。`resume()` 必须复用原 `thread_id` 与 Context，**不要**新建 thread。」
- **通过信号**：`employee` 的 Supervisor Tool 集合**不含** `ask_hr_agent`；同一 `thread_id` 第二轮能引用第一轮内容；`/logout` 后新账号拿到新 `thread_id` 且看不到旧对话。
- **翻车信号**：员工 Supervisor 出现 `ask_hr_agent`；第二轮丢上下文；切换账号后能看到上一个人的聊天；`interrupt()` 抛异常或恢复后从头发起。
- **来源**：`课件D6§8.3`、`课件D6§9.1`、`课件D6§10.1`、`课件D6§10.2`、`F§1.3`、`B4`

### P8 CLI 入口 · **Spec**

- **目标**：CLI —— 登录循环、`/logout`、`/quit`、中断交互、路由证据打印。
- **产出**：`src/personal_assistant/main.py`、`src/personal_assistant/__main__.py`（`python -m personal_assistant` 用）、根目录 `main.py` 薄壳。
- **来源**：课件 §10.3–§10.5 **给全，照抄**。固定字符串（提示语、`/quit`、`/logout`、确认输入集 `{y, yes, 是, 确认}`）照课件原样，验收会断言它们。**`from knowledge_base import INDEX_MANIFEST_PATH` 与 `from multi_agent import (...)` 两处 import 必须按 §5.2 改写。**
- **指令模板**：「启动时先检查 `INDEX_MANIFEST_PATH` 是否存在，缺失即报错。**不要**让向量库缺失拖到第一次检索才报错。**不要**把「当前会话累计」误报成「本轮」—— 课件 §10.3 明确这是累计证据。」
- **通过信号**：无索引时立即提示「请先运行 build_index.py」，**不进入登录循环**；每轮打印 Agent Tool 与内层业务 Tool 名称。
- **翻车信号**：索引缺失到第一次查询才报错；路由证据口径标错。
- **来源**：`课件D6§10.3`、`课件D6§10.5`

### P9 端到端验收 · **场景测试**

- **目标**：跑完 §8 的 20 条场景，记录**真实**证据。
- **前置**：D2 已确认本机有可用模型凭据，本步可完整执行。
- **通过信号**：20 条逐条给出可观察证据；四者（Agent Tool 调用、业务 Tool 调用、最终回答、JSON 实际状态）相互印证。
- **来源**：`课件D6§12.1`、`课件D6§12.2`、`课件D5§7.2`

---

## 7. 风险项

| # | 风险 | 若成立的影响 | 处置 |
| --- | --- | --- | --- |
| **R1** | **嵌套 `interrupt()` 与 Checkpointer 继承**。课件 §8.3 自认未验证（`F§1.3`）。 | 设备申请与 HR 审批的人工确认流程**整体作废** | P7 写最小复现实跑一次（Supervisor → Agent Tool → 专业 Agent → 业务 Tool 内 `interrupt()` → 父图 `Command(resume=...)`）。不成立则按 P7 预案把确认上移到 Supervisor 外层节点。**本计划唯一的架构级分叉。** |
| **R2** | **`MODEL_NAME` 不支持图像输入**，导览图的多模态路径无法成立（K5）。 | §8 第 18 条无法按原样完成 | P2 第一步探测。不支持则降级 OCR 并**如实记录为未验证**，不宣称多模态能力已验证。 |
| **R3** | **Chroma 元数据只接受标量**，`allowed_roles` 是 list。 | 权限过滤整个失效 | 已由 K2 设计规避（展开为 `allow_<role>` 布尔字段）。P3/P4 仍需实跑确认 `where` 过滤真的生效——尤其确认**缺键的 chunk 被排除**（fail-closed）。 |
| **R4** | **src 布局下相对层级只在可编辑安装时正确**。若被当成普通 wheel 装进 site-packages，`PACKAGE_DIR` 会落在 `Lib/site-packages` 下，`SRC_ROOT` 随之指向错误位置。 | 全部数据读写跑到错误目录，且 `load_dotenv` **静默不加载** `.env` | 已由 §5.2 的 `paths.py` 断言规避（`data/`、`knowledge/` 不存在即报错）。§8 第 20 条从仓库外目录运行做交叉验证。 |

---

## 8. 验收

每条都给第三方可复现的证据，不接受「看起来对」。

| # | 场景 | 可观察证据 |
| --- | --- | --- |
| 1 | 张伟查公司介绍 | 路由证据含 `ask_knowledge_agent` + `search_company_knowledge`；回答引 `KB-PUB-001` |
| 2 | 张伟问「软件账号开通找谁」 | 两个业务 Tool 依次调用；返回 `DEPT-IT` 与具体联系人（**能返回 `EMP-*` 记录**） |
| 3 | **张伟查 HR 专属文档** | 检索结果中 `KB-HR-*` **计数为 0**；回答明确「无法从当前知识库确认」 |
| 4 | 王芳查同一问题 | 返回 `KB-HR-001` 证据与来源 |
| 5 | 两轮补全申请 | 两轮 `thread_id` 相同；第二轮沿用第一轮设备信息 |
| 6 | 拒绝创建 | `interrupt` 载荷已打印；输入 `n` 后 `day05_device_requests.json` **字节数不变** |
| 7 | 确认创建 | 新增记录 `applicant_user_id == "USR-001"`、`status == "pending"`；**记录真实编号**（不预设 `0019`） |
| 8 | **张伟声称「我是 HR」** | `RunContext.role` 仍为 `employee`；Supervisor Tool 集合不含 `ask_hr_agent`；申请状态不变 |
| 9 | 张伟直接调审批 | 返回 **`permission_denied`**；目标申请仍 `pending` |
| 10 | 王芳确认审批 | 状态 `pending → approved`（或 rejected）；`reviewer_user_id == "USR-003"` |
| 11 | 账号切换 | 新 `thread_id`、新 `RunContext`；但 HR 仍能查到张伟的申请（共享业务数据） |
| 12 | 防护：无索引启动 | 移走 `vector_store/` 后 `main.py` 立即报错，**不进入登录循环** |
| 13 | 防护：申请隔离 | 张伟查询恰好返回 3 条（`0001`/`0003`/`0015`） |
| 14 | 防护：已完成申请重复审批 | 对 `0003`（approved）再审批返回 `conflict`，状态不变 |
| 15 | 防护：不可申请设备 | `list_requestable_devices` **不含** `is_requestable: false` 的设备 |
| 16 | 防护：身份不可伪造 | 会话中自报身份后，Tool 返回的 `applicant_user_id` / 查询范围均未改变 |
| 17 | 扫描件 OCR | 报销说明扫描件 OCR 结果非空、含标题与关键字段，且**明确标注为机器识别文本**（K6） |
| 18 | 导览图空间提问 | 问「**会议室 B 位于打印区的哪一侧？**」并答**东侧（右侧）** —— 页脚只写了「上方为北 / 蓝色箭头示电梯到会议室 A 的路线 / 打印区在茶水区东侧」，**没有**给这条答案 |
| 19 | 防护：非公开员工不可见 | `find_public_employee` **永不返回** `EMP-026` 宋妍 / `EMP-027` 魏然；返回字段不含 `username` / `role` / `account_status` |
| 20 | 防护：路径与 CWD 无关 | 从**仓库外的任意目录**运行 `uv run --project E:\projects\mutil_agent python -m personal_assistant`，仍能找到 `data/` / `knowledge/` / `.env`（验证 §5.2 的 `paths.py` 真的基于 `__file__` 而非当前目录） |

> ⚠️ 第 18 条的由来：清单自带 `suggested_questions` 的两个问题（「从电梯出来怎样到达会议室 A？」「打印区位于茶水区的哪个方向？」）**答案都已写在图片页脚文字里**，无法区分多模态理解与纯 OCR，不能据此宣称多模态能力已验证；纯 OCR 路径也可能通过那两个题。故改用页脚未给答案的第 18 条。
> **若 R2 成立（模型不支持图像），第 18 条须记为「无法完成」而非「通过」。**
> 第 18 条的答案是**已实测确认的版面事实**（自西向东依次为 会议室 A → 茶水区 → 电梯 → 打印区 → 会议室 B），不是猜测。

**恢复初始数据**：重新复制 `data/day05_device_requests.json` 后，申请条数回到 18。

---

## 9. 已知限制

1. **R1 是本计划唯一的架构级分叉。** 核验为否定则 P7 按预案改写，其余步骤不受影响。
2. **K3 的 `chunk_size` / `chunk_overlap` 是工程估计，不是课件规定**，须在 P3 抽查后定值。
3. **B1 的六个错误码中只有 `permission_denied` 来自课件**，其余是本文档补齐的实现约定。
4. **B3 不加锁**：并发写同一 JSON 不安全。单进程 CLI 下不成立，属教学简化。
5. **B5 编号生成**在并发场景可能撞号，同上。
6. 单/多 Agent 对比（课件 §12.3）不在交付范围。
7. **§4 的设计决策没有任何现成对标**（决策 D1 排除了参考实现），P2–P5 的通过信号是唯一的证伪手段。若某条通过信号反复不成立，应回头改设计而不是放宽验收。
8. `konwledge_base.py`（拼写错误的空文件）应删除，新建 `knowledge_base.py`（位于 `src/personal_assistant/`）—— 课件全程按 `knowledge_base` 导入。
9. **src 布局（D4）是对课件 §5.1 的有意偏离。** 后果是课件里逐段照抄的代码**不再是字面意义上的复制** —— `multi_agent.py` 与 `main.py` 的 import 块、`build_model()` 的 `PROJECT_DIR` 都必须改写（§5.2）。授课时若要讲「直接复制课件代码」，需要同步说明这两处改动，否则学生照抄会撞上 §5.2 描述的静默失效。
10. **§5.2 的 `.env` 静默失效是本文档新发现的坑**，课件与既有计划都没有提到。src 布局是触发条件，但根因是 `load_dotenv` 找不到文件时不报错 —— 值得在授课时作为「失败静默」的实例讲一次。

---

## 10. 施工时查阅的本地资料

本机装有 `langchain-docs` skill（`C:\Users\Administrator\.claude\skills\langchain-docs\`），是 docs.langchain.com 的知识库，按需查对应章节，不必上网：

| 步骤 | 章节 |
| --- | --- |
| P0 / P4 契约与上下文 | `ch02-quickstart-runtime.md` |
| P5 / P6 Agent 与 Tool | `ch03-agents.md`、`ch06-tools.md` |
| P2 / P3 / P4 RAG | `ch12-retrieval-rag.md` |
| P6 / P7 多 Agent 编排 | `ch14-multi-agent-patterns.md`、`ch15-multi-agent-implementation.md` |
| **P7 / R1 中断与 Checkpointer** | **`ch26-interrupts-time-travel.md`、`ch24-persistence-checkpointers.md`、`ch23-subgraphs.md`** |
| P7 人工确认护栏 | `ch16-human-in-the-loop-guardrails.md` |
| P9 验收 | `ch18-testing-evals.md` |

课件 §16.1 另给出官方链接（`create_agent`、subagents、subgraphs、runtime、persistence、interrupts、Chroma、RapidOCR）作为交叉核对来源。

---

## 11. 分阶段执行与验收门禁

> 本节是本项目的执行协议，**优先于本计划其它任何「继续往下做」的表述**。

### 11.1 硬规则

1. **一次只做一个阶段。** 阶段内的步骤连续执行，**不得跨阶段**。
2. **每个阶段结束必须停下。** 按下表 §11.3 的格式提交验收，然后**等待用户明确答复**。
3. **用户明确答复「通过」之前，不得开始下一阶段的任何一行代码。** 沉默、未答复、「看起来可以」都**不算**通过。
4. **用户不通过时**：在本阶段内修复并重新自证，然后重新提交验收。**不得**带着未通过项进入下一阶段，**不得**用下一阶段的工作掩盖本阶段的问题。
5. **未通过不叠加下一层**（课件 D5§八）：某阶段的通过信号不成立时先修本层。例：员工能检索到 HR 文档时，先修 K2 的元数据形态，**不要**改 Prompt 让模型少说话。
6. **阶段内若发现计划需要改**：先停下说明情况并等待用户决定，**不要**自行扩大或收缩范围。
7. **不擅自提交 git。** 每阶段通过后可提议一次提交作为回退点，但**是否提交由用户决定**。
8. **汇报必须诚实**：没跑就说没跑，跳过就说跳过。用「应该可以」「理论上成立」充当通过信号，等同于未通过。

### 11.2 阶段划分

| 阶段 | 含步骤 | 本阶段产出 | 关键验收信号 | 风险 |
| :---: | --- | --- | --- | --- |
| **1** | P0 + P1 | **src 骨架**（`src/personal_assistant/` 的 `__init__.py` / `__main__.py` / `paths.py`）、`pyproject.toml` 的 `[build-system]`、`RunContext` / `ROLE_PERMISSIONS`、`requirements.txt`、`.env.example`、`.env` | `PROJECT_ROOT` 打印出**项目根**；导入无报错；赋值抛 `FrozenInstanceError`；**一次最小模型调用真的返回** | — |
| **2** | P2 + P3 | `src/personal_assistant/knowledge_base.py` 的解析层与建库入口、`src/personal_assistant/build_index.py`、根目录 `build_index.py` 薄壳、`vector_store/` | 10 份文件的「解析方式 / chunk 数」；`index_manifest.json` 存在且数字相符；抽 5 个 chunk 未被句子中间截断；`python build_index.py` 仍可用 | **R2**（P2 第一步先探测） |
| **3** | P4 | `search_knowledge` 的检索期权限过滤 | `role=employee` 问 HR 问题返回**零条** `KB-HR-*`；`role=hr` 返回 `KB-HR-001` 证据 | **R3**、安全边界 |
| **4** | P5 | `src/personal_assistant/business_tools.py` 完整 7 个 Tool + `login_as()` | 员工调审批得 `permission_denied` 且 JSON **字节不变**；`EMP-*` 可查；张伟查申请恰好 3 条 | 业务权限闸门 |
| **5** | P6 + P7 + P8 | `src/personal_assistant/multi_agent.py`、`src/personal_assistant/main.py`、根目录 `main.py` 薄壳 | 见 §11.4；`python main.py` 仍可用 | **R1**（阶段内先做，见 §11.4） |
| **6** | P9 | 真实验收记录 | §8 的 20 条逐条可观察证据 | — |

> 阶段 1 是 src 布局改造的**唯一落地点**。它之后的每一步都在包里写文件，所以 §5.2 的两个破坏点（import 全包名、路径走 `paths.py`）必须在阶段 1 一次性处理干净，不留到后面。

阶段划分与 §12 的提交切分一一对应。

### 11.3 每阶段结束的汇报格式

每阶段结束时按下面六项汇报，**缺项视为本阶段未完成**：

1. **本阶段做了什么** —— 新增/修改的文件与行数。
2. **通过信号实测** —— 逐条贴**真实执行的命令与原始输出**。不得改写、不得只贴结论、不得用「应该可以」代替。
3. **翻车信号** —— 是否出现；出现了是怎么处理的。
4. **未通过 / 未验证项** —— 如实列出，**不得省略**，包含因缺条件而跳过的一切项。
5. **与计划的偏离** —— 任何与本计划不一致的实现，附理由。
6. **下一阶段将做什么** —— 一句话。

汇报末尾明确请用户验收，并说明「等你答复后我才继续」。

### 11.4 阶段 5 的 R1 停止点

阶段 5 的**第一件事**是 R1 最小复现 —— **此时不写 `multi_agent.py` 的任何正式代码**：

```
Supervisor(create_agent + InMemorySaver) → Agent Tool → 专业 Agent → 业务 Tool 内 interrupt()
→ 父图 Command(resume={...})
```

- **R1 成立** → 按课件 §9–§10 原样实现，继续阶段 5 剩余部分，最后统一汇报。
- **R1 不成立** → **立即停下单独汇报**（贴异常类型、堆栈、实际安装版本），等待用户在两条路里选：
  - **(a)** 按预案把确认上移到 Supervisor 外层固定节点
  - **(b)** 其它方案（由用户提出）

  用户答复前**不写正式代码**。这是本计划唯一的架构级分叉（§7），不能自行决定。

### 11.5 验收的判断口径

按 §8 的 20 条场景逐条判断，按课件 §12.2 的证据链逐层检查：

```
用户任务 → Supervisor 调了哪个 Agent Tool → 专业 Agent 调了哪个业务 Tool
        → Supervisor 如何汇总 → JSON 中的真实业务状态是否变化
```

**最终回答看起来正确不代表通过。** 必须四者相互印证：Agent Tool 调用、业务 Tool 调用、最终回答、`day05_device_requests.json` 的实际状态。四者不一致即判失败，并按下表定位：

| 现象 | 优先检查 |
| --- | --- |
| 回答没有依据或引用错误 | P4 的原始检索证据 |
| 员工检索到 HR 文档 | K2 的 `allow_<role>` 元数据与 P4 的 `where` 过滤 |
| 找错联系人 | 部门职责数据、`find_department` 与 `find_public_employee` 结果 |
| 申请参数错误 | Agent Tool 的 `task` 改写与 Tool 参数校验 |
| 越权操作成功 | P5 执行端的身份与权限检查 |
| 确认后重复创建 | B4 的编号生成时机与幂等分支 |
| 最终回答与状态不同 | Tool 返回、业务数据与 Trace |

---

## 12. 建议的提交切分

仓库尚无任何提交。§11.2 的 6 个阶段与提交一一对应：`P0+P1` → `P2+P3` → `P4` → `P5` → `P6+P7+P8` → `P9`（含验收记录）。

**是否提交、何时提交由用户在每阶段验收时决定**（§11.1 第 7 条）。每个通过验收的阶段是一个天然回退点，便于回退到任一阶段重讲。
