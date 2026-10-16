r"""P5 通过信号复现脚本（阶段 4 验收用）。

用法（在仓库根运行，或任意目录 —— 路径由脚本自身推导）：
    uv run python src/tests/verify_phase4_repro.py

只读检查，不修改任何业务数据（会比对 `device_requests` 表的行摘要 —— 内容长度 +
sha256 + 行数 —— 来证明这一点）。

> 2026-10-08 从仓库根移入 `src/tests/`（技术方案评审 E11）：它原本散在根目录，与本目录下
> 的脚本重复、容易被误认为主入口。功能与阶段 4 验收口径一致，覆盖范围已被
> `acceptance_day06.py` 的场景 9（employee 调审批 → permission_denied）、
> 场景 13（张伟恰好 3 条）、场景 19（非公开员工不可见）涵盖，此处保留为**最小复现件**。
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import MISSING, dataclass, fields
from pathlib import Path

# ToolRuntime 是 pydantic 模型，注入自定义 Context 会打一条无害的序列化告警，屏蔽掉
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

# 按脚本自身位置推导仓库根，这样在任何 CWD 下都能跑
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # 让 `import db_state` 可用

from langchain.tools import ToolRuntime  # noqa: E402

import db_state  # noqa: E402
import personal_assistant.business_tools as bt  # noqa: E402


@dataclass(frozen=True)
class Ctx:
    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


def runtime_for(username: str) -> ToolRuntime:
    """按教学账号构造一个可信 Runtime Context（与 Agent 注入的等价）。"""
    u = db_state.login_user(username)
    ctx = Ctx(u["user_id"], u["username"], u["display_name"], u["role"], u["department_id"])
    kwargs: dict[str, object] = {}
    for f in fields(ToolRuntime):
        if f.name == "context":
            kwargs["context"] = ctx
        elif f.name == "state":
            kwargs["state"] = {}
        elif f.name == "tools":
            kwargs["tools"] = []
        elif f.default is MISSING and f.default_factory is MISSING:  # type: ignore[misc]
            kwargs[f.name] = None
    return ToolRuntime(**kwargs)  # type: ignore[arg-type]


def call(tool_obj, payload: dict) -> dict:
    return json.loads(tool_obj.invoke(payload))


def digest() -> tuple[int, str, int]:
    """申请表的库版摘要：``(内容长度, sha256[:16], 行数)``。

    旧版读 `day05_device_requests.json` 的字节数与 sha256；数据源换成
    `agent_service.device_requests` 表之后，对应物是 `db_state.requests_snapshot()`。
    """
    return db_state.requests_snapshot()


ZHANG = runtime_for("zhang_wei")
WANG = runtime_for("wang_fang")

print("=" * 70)
print("① employee 直接调审批 -> permission_denied，且申请表内容不变")
print("=" * 70)
before = digest()
print(f"   调用前: 内容长度={before[0]} sha256={before[1]} 行数={before[2]}")
result = call(
    bt.approve_device_request,
    {"request_id": "REQ-2026-0001", "decision": "approved", "runtime": ZHANG},
)
print("   返回  :", json.dumps(result, ensure_ascii=False))
after = digest()
print(f"   调用后: 内容长度={after[0]} sha256={after[1]} 行数={after[2]}")
print("   表内容不变:", before == after, "| error == permission_denied:",
      result.get("error") == "permission_denied")

print()
print("=" * 70)
print("② find_public_employee：能返回 EMP-*，非公开人员永不出现，字段受白名单约束")
print("=" * 70)
for query in ("宋妍", "魏然", "信息技术部", "DEPT-IT", "账号管理员"):
    res = call(bt.find_public_employee, {"query": query, "runtime": ZHANG})
    data = res.get("data") or {}
    ids = [e["user_id"] for e in data.get("employees", [])]
    print(f"   {query:10} -> count={data.get('count', 0):2}  ids={ids}  error={res.get('error')}")
res = call(bt.find_public_employee, {"query": "信息技术部", "runtime": ZHANG})
one = res["data"]["employees"][0]
print("   返回字段:", sorted(one))
print("   越界字段（应为空）:", sorted(set(one) - set(bt.PUBLIC_EMPLOYEE_FIELDS)) or "无")

print()
print("=" * 70)
print("③ 张伟（employee）查申请：只应看到本人的申请（不写条数——条数会随数据变化而漂移，逐条核对 user_id 才是不变量）")
print("=" * 70)
res = call(bt.query_device_requests, {"runtime": ZHANG})
data = res["data"]
print(f"   scope={data['scope']} count={data['count']}")
for item in data["requests"]:
    print(f"     {item['request_id']}  {item['device_id']:16} status={item['status']}")
res_hr = call(bt.query_device_requests, {"runtime": WANG})
print(f"   HR scope={res_hr['data']['scope']} count={res_hr['data']['count']}（HR 应看到全部申请，不按人过滤——同样不写死条数）")

print()
print("=" * 70)
print("④ list_requestable_devices：不含 is_requestable=false 的设备")
print("=" * 70)
res = call(bt.list_requestable_devices, {"runtime": ZHANG})
ids = [d["device_id"] for d in res["data"]["devices"]]
print(f"   张伟可申请 {len(ids)} 台: {ids}")
print("   含 DEV-DESK-STAND / DEV-ERGONOMIC-CHAIR:",
      any(x in ids for x in ("DEV-DESK-STAND", "DEV-ERGONOMIC-CHAIR")), "（应为 False）")
res_hr = call(bt.list_requestable_devices, {"runtime": WANG})
print(f"   HR 可申请 {len(res_hr['data']['devices'])} 台（限部门设备因 roles=['employee'] 被排除）")

print()
print("=" * 70)
print("⑤ 附加防护")
print("=" * 70)
print("   find_department('软件账号') ->",
      call(bt.find_department, {"query": "软件账号", "runtime": ZHANG})["data"]["departments"][0]["department_id"])
print("   对已 approved 的 0003 再审批 ->",
      call(bt.approve_device_request, {"request_id": "REQ-2026-0003", "decision": "approved", "runtime": WANG}).get("error"))
print("   不存在设备 ->",
      call(bt.create_device_request, {"device_id": "DEV-NOPE", "quantity": 1, "reason": "x", "runtime": ZHANG}).get("error"))
print("   不可申请设备 ->",
      call(bt.create_device_request, {"device_id": "DEV-DESK-STAND", "quantity": 1, "reason": "x", "runtime": ZHANG}).get("message"))
print("   数量超限 ->",
      call(bt.create_device_request, {"device_id": "DEV-MONITOR-24", "quantity": 9, "reason": "x", "runtime": ZHANG}).get("message"))
print("   部门不对口（李娜 DEPT-SALES 申请 DEV-LAPTOP-PRO）->",
      call(bt.create_device_request,
           {"device_id": "DEV-LAPTOP-PRO", "quantity": 1, "reason": "x", "runtime": runtime_for("li_na")}).get("message"))

# 身份缺失必须 fail-closed：构造一个 context=None 的 runtime
missing_kwargs: dict[str, object] = {}
for f in fields(ToolRuntime):
    if f.name == "state":
        missing_kwargs["state"] = {}
    elif f.name == "tools":
        missing_kwargs["tools"] = []
    elif f.default is MISSING and f.default_factory is MISSING:  # type: ignore[misc]
        missing_kwargs[f.name] = None
NO_IDENTITY = ToolRuntime(**missing_kwargs)  # type: ignore[arg-type]
print("   身份缺失时 query_device_requests ->",
      call(bt.query_device_requests, {"runtime": NO_IDENTITY}).get("error"))
print("   身份缺失时 create_device_request ->",
      call(bt.create_device_request,
           {"device_id": "DEV-MONITOR-24", "quantity": 1, "reason": "x", "runtime": NO_IDENTITY}).get("error"))

print()
print("最终：申请表内容长度/摘要/行数 =", digest(), "（应与 ① 的调用前完全一致）")
