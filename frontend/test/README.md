# Day06 前端 · 阶段流程文档索引

本目录是「为多 Agent 员工助手加一层 Web 前端」这件事的**过程证据**：每个阶段一份流程文档，记录该阶段实际跑了什么、结果如何、偏差在哪。
执行方式：**连续执行不停顿**（原计划的"每阶段硬停等审批"被撤销），所有阶段一次跑完。

> ⚠️ **持久化升级后（2026-10）的执行说明 —— 先读这一段**
>
> 设备申请与审批的写入已从 `src/data/day05_device_requests.json` 换到 **MySQL
> `agent_service.device_requests` 表**（见 `docs/状态持久化升级计划.md`）。因此下面各流程文档里
> 凡出现 `Copy-Item .tmp/... src/data/day05_device_requests.json -Force` 的**还原步骤都已失效**：
> 它不再还原数据（那份 JSON 已不是写目标），跑完只会在库里留下脏数据。
>
> 正确做法：
>
> * **备份 / 还原**改用测试侧工具 `../../src/tests`：
>   ```
>   uv run python -c "import sys; from pathlib import Path; sys.path[:0]=['src','src/test']; import db_state; print(db_state.load_requests_backup(Path('.tmp/day05_device_requests.backup.json')))"
>   ```
>   （备份用 `dump_requests_backup`，参数同形。）
> * **基线**：**以库中实际行数为准** —— 总条数会随验收/网页联调漂移（历史值 19 → 20），
>   测试自带备份还原，**不要求你手改任何数字**；稳定的不变量是员工 `zhang_wei`（USR-001）可见 **4 条**。
> * 各文档里的**浏览器流程步骤本身仍然有效**，只有"还原"这一步换成上面这条。
>
> P0/P1/P7/P8 与本文件正文**未逐句改写**（那需要重跑一遍浏览器验证）；统一以本说明为准 ——
> 属于已知的、故意留下的文档债，记在计划 §10.5。

---

## 阶段文档

| 阶段 | 文档 | 一句话内容 |
|---|---|---|
| `P0` | [P0_流程文档.md](P0_流程文档.md) | 契约冻结 + Vite 工程骨架；`trace` 累计性实测；构建产物落 `src/static/` 并被 FastAPI 托管 |
| `P1` | [P1_流程文档.md](P1_流程文档.md) | 后端唯一改动：审批中断载荷补 `applicant_name` / `device_name`（真实 HR 审批闭环验证） |
| `P2+P3+P4` | [P2-P4_流程文档.md](P2-P4_流程文档.md) | 逻辑层三件套（API 客户端 / 会话持久化 / 轨迹切片），36 条断言全过；抓出并修掉 1 个真 bug |
| `P5` | [P5_流程文档.md](P5_流程文档.md) | 登录页 + 设计令牌（Linear 式 surface 阶梯 + 发丝边框，无阴影）；真浏览器验证登录/刷新/退出 |
| `P6` | [P6_流程文档.md](P6_流程文档.md) | 对话流 + 轨迹面板；**K1 反证**（每轮只显示本轮条目）；503 事故排查与 `N1`/`N2` 缺陷 |
| `P7` | [P7_流程文档.md](P7_流程文档.md) | 确认卡片（模板分派 / 按钮语义 / 未知 action 默认拒绝 / 防双击）；**取消支路首次实测** |
| `P8` | [P8_流程文档.md](P8_流程文档.md) | 动效接入 + 端到端验收清单逐条留证 + 已知限制汇总 |
| `P9`（追加需求） | [P9-主题_流程文档.md](P9-主题_流程文档.md) | 多主题：四套主题的令牌层、**运行时对比度审计零失败**、防闪烁（FOUC） |
| `P10`（追加需求） | [P10-三栏布局_流程文档.md](P10-三栏布局_流程文档.md) | 宽屏三栏：左「身份与能力」+ 中对话 + 右「本轮轨迹」常驻；<1280px 收回单栏 |
| `P11`（追加需求） | [P11-流式输出_流程文档.md](P11-流式输出_流程文档.md) | 接到 SSE 流做打字机：`sse.ts` / `typewriter.ts` / `streamChat`；真机 21 个递增长度值；暴露后端 chromadb 全局竞态 |

## 其它

| 文件 | 用途 |
|---|---|
| `logic-check.ts` | P2+P3+P4 的逻辑层校验脚本（用真实响应数据跑） |
| `.tmp/tw_check.cjs` | P11 的打字机 + SSE 帧解析自检（17 条，**不依赖后端**） |
| `shots/` | 各阶段真机截图 |

## 怎么跑

```powershell
# 终端 1（知识类问题目前几乎必挂，见 P11 文档 §7）
$env:TEMP='E:\projects\mutil_agent\.tmp'; $env:TMP=$env:TEMP
uv run python -m uvicorn personal_assistant.agent_api:app --host 127.0.0.1 --port 8000

# 终端 2
cd frontend; npm run dev        # → http://localhost:5173   （是 localhost，Vite 不绑 127.0.0.1）
```

```powershell
# 逻辑层校验
cd frontend; node test/logic-check.ts     # 期望：36 passed, 0 failed

# P11 打字机 / SSE 自检
cd frontend
npx tsc src/lib/typewriter.ts src/lib/sse.ts --outDir ..\.tmp\twbuild --module commonjs --target es2022 --skipLibCheck --moduleResolution node --ignoreConfig
node ..\.tmp\tw_check.cjs                 # 期望：ALL PASS (17)
```

**跑完务必还原唯一可写的数据文件**：

```powershell
Copy-Item .tmp/day05_device_requests.backup.json src/data/day05_device_requests.json -Force
# 基线：sha256 前16位 393e3009b1baf63a，19 条
```

## 三条贯穿全程的硬约束

1. **接口事实以 `frontend/CONTRACTS.md` 为准** —— 那是 P0 冻结的契约（`C1`–`C6`）与已知坑（`K1`–`K9`），后面各阶段只引用、不重述。
2. **后端改动是逐次获准后最小化的**，目前共四处，全部记录在案：
   - `business_tools.py` 的 `approve_device_request`：中断载荷补 `applicant_name` / `device_name`（P1）
   - `multi_agent.py`：三个专家的 `except Exception` 之前加 `except GraphInterrupt: raise`（否则每次人工确认都会假报一个 `tool_error`）
   - `agent_api.py`：`status_value` 的**花括号改成圆括号**（原写法是 set 字面量，`json.dumps` 必抛 `TypeError`）
   - `agent_api.py`：lifespan 第一句补 `ensure_writable_tempdir()`（Web 入口漏了这个前置条件，TEMP 不可写时一问知识问题就 RuntimeError）
   其余后端缺陷（事件循环阻塞、401 语义混同、503 无 traceback、chromadb 全局竞态）**一律只记录不改**。
3. **只读资产不许被动**：`src/knowledge/`、`src/data/` 下另外三份 JSON、以及 `src/vector_store/`。唯一可写文件是 `src/data/day05_device_requests.json`，每次验证后必须还原。
