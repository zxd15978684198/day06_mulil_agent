# src/test —— 阶段通过信号测试

## 运行

```powershell
# 在仓库根 E:\projects\mutil_agent 下
uv run python src/test/verify_phase5.py
```

退出码：**全部通过为 0**，出现 FAIL 或写坏了只读数据则为 1。

## verify_phase5.py 覆盖什么

对应 Day06 执行计划 v2 的**第五阶段（P6 + P7 + P8）通过信号**。

### A 组：确定性检查（不调用模型，秒级）

| # | 检查 | 判定依据 |
| --- | --- | --- |
| A1 | 三个专业 Agent 的 Tool 集合 | 并集**覆盖 7 个业务 Tool**；唯一跨 Agent 重叠是 `query_device_requests`（课件 §7.5 设计如此） |
| A2 | `specialist_result()` 输出 | 只含 `{agent, answer, business_tools}` 且可 `json.loads` |
| A3 | Supervisor 按角色裁剪 | employee 的 Tool 集合**不含** `ask_hr_agent`；hr 含 |
| A4 | Supervisor 不直接挂业务 Tool | 两个角色的 Supervisor 都只挂 Agent Tool |
| A5 | 无索引启动 | 立即抛错且**不进入登录循环**（`input()` 调用次数为 0） |
| A6 | `print_result()` | 同时打印回答、Agent Tool 名、内层业务 Tool 名 |

### B 组：需要真实模型（约 1–3 分钟）

| # | 检查 | 判定依据 |
| --- | --- | --- |
| B1 | **R1**：嵌套 `interrupt()` 暂停到父图 | 父图返回 `__interrupt__`，载荷是内层业务 Tool 的；此时副作用文件未写入 |
| B2 | **R1**：同一 `thread_id` 恢复 | `Command(resume={'approved': True})` 后无 `__interrupt__`，副作用文件写入正确内容 |
| B3 | **R1**：拒绝路径 | `resume({'approved': False})` 后**不写入**。⚠️ 被拒绝后专业 Agent 可能**再次尝试**同一写操作（父图再次暂停），这是模型行为而非机制缺陷；本项会在拒绝方向上循环到不再暂停（上限 5 次），只断言「全程没有任何写入」，并报告重试了几次 |
| B4 | 多轮上下文 | 同一 `thread_id` 消息数增长；第二轮**用到第一轮内容**：若它委派了专业 Agent，则 `task` 必须已把「那上海那边呢？」的指代补全；若它直接从历史作答（合法行为），则要求回答确实切题。⚠️ 仍受模型表述影响，失败时自动换新 thread 重试一次 |
| B5 | `/logout` 效果 | 新会话拿到**新 `thread_id`**，新 thread 内消息数为 0，角色切换为 hr |

## 前提与边界

* **B 组需要可用的模型凭据**（`.env` 里的 `MODEL_PROVIDER` / `MODEL_NAME` / `API_KEY` / `BASE_URL`）。若模型没有按预期调用工具，B1 会判 FAIL 并打印原始返回，用来区分「机制不成立」与「模型没照做」。
* **B4 依赖模型行为，会偶发不通过**：它要求 Supervisor 把「那上海那边呢？」补全成含明确对象的 `task`，且回答切题。失败时会自动换新 thread 重试一次，两次都失败才判 FAIL，并打印两次的原始 `task` 与回答。**看到 B4 FAIL 时先读证据，不要直接当成机制缺陷。**
* **只读保证**：全程不写 `src/data/`；脚本开头与结尾各取一次 `day05_device_requests.json` 的字节数与 sha256 对比。B1–B3 的副作用写在 `.tmp/phase5_r1_side_effect.txt`，结束时删除。
* **本目录不参与打包**：`pyproject.toml` 的 `[tool.hatch.build.targets.wheel]` 只声明 `packages = ["src/personal_assistant"]`；`uv sync` 实测正常。
* ⚠️ **目录名会遮蔽标准库的 `test` 包**：`src` 在 `sys.path` 上，因此 `import test` 会解析到本目录
  （实测 `find_spec('test').origin is None`，命名空间包）。对本项目无影响，但如果日后要写
  `import test.*` 之类的标准库测试辅助，或引入会这么做的第三方库，就需要把目录改名
  （惯例是 `tests/`，`tests` 不遮蔽任何标准库模块）。改名后请同步更新本 README 与运行命令。
* 这个目录**不在**计划 §5.1 的目录布局里，是按需增加的测试位置；`verify_phase5.py` 不修改任何交付代码。
