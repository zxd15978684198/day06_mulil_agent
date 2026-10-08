r"""P5 通过信号复现脚本（阶段 4 验收用）。

用法：在仓库根 E:\projects\mutil_agent 下运行
    uv run python verify_p5.py

只读检查，不修改任何数据文件（会比对申请文件的字节数与 sha256 来证明这一点）。
"""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from dataclasses import MISSING, dataclass, fields

# ToolRuntime 是 pydantic 模型，注入自定义 Context 会打一条无害的序列化告警，屏蔽掉
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

sys.path.insert(0, "src")  # 从仓库根运行时也能找到包

from langchain.tools import ToolRuntime  # noqa: E402

import personal_assistant.business_tools as bt  # noqa: E402

REQUESTS = bt.DEVICE_REQUESTS_PATH


@dataclass(frozen=True)
class Ctx:
    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


def runtime_for(username: str) -> ToolRuntime:
    """按教学账号构造一个可信 Runtime Context（与 Agent 注入的等价）。"""
    u = bt.login_as(username)
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


def digest() -> tuple[int, str]:
    raw = REQUESTS.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()[:16]


ZHANG = runtime_for("zhang_wei")
WANG = runtime_for("wang_fang")

print("=" * 70)
print("① employee 直接调审批 -> permission_denied，且申请文件字节不变")
print("=" * 70)
before = digest()
print(f"   调用前: 字节数={before[0]} sha256={before[1]}")
result = call(
    bt.approve_device_request,
    {"request_id": "REQ-2026-0001", "decision": "approved", "runtime": ZHANG},
)
print("   返回  :", json.dumps(result, ensure_ascii=False))
after = digest()
print(f"   调用后: 字节数={after[0]} sha256={after[1]}")
print("   字节不变:", before == after, "| error == permission_denied:",
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
print("③ 张伟（employee）查申请：恰好本人 3 条")
print("=" * 70)
res = call(bt.query_device_requests, {"runtime": ZHANG})
data = res["data"]
print(f"   scope={data['scope']} count={data['count']}")
for item in data["requests"]:
    print(f"     {item['request_id']}  {item['device_id']:16} status={item['status']}")
res_hr = call(bt.query_device_requests, {"runtime": WANG})
print(f"   HR scope={res_hr['data']['scope']} count={res_hr['data']['count']}（应为全部 18 条）")

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
print("最终：申请文件字节数/摘要 =", digest(), "（应与 ① 的调用前完全一致）")
