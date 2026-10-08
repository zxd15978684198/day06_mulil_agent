"""教学登录、可信运行上下文与七个业务 Tool。

本模块是项目的**业务权限闸门**：所有身份判断都在这里执行，且都在**执行端**
（不是靠 Prompt 提示）。

* ``RunContext`` 由 ``login_as()`` 从 ``data/day05_users.json`` 构造，由应用注入；
* ``ROLE_PERMISSIONS`` 是课件 Day05 §2.3 的角色权限矩阵；
* 每个 Tool 第一句取 ``runtime.context``，再判权限，再校验参数与业务状态；
* 写操作（创建 / 审批）在落盘前调用 ``interrupt()`` 等人工确认，确认前不改文件。

设计依据（Day06 执行计划 v2 §4.2）：B1 统一信封、B2 身份只取 context、
B3 每次重新读盘 + 原子写、B4 interrupt 与幂等、B5 编号生成、B6 查询范围、
B7 字段白名单、B8 设备四项校验、B9 login_as。

唯一可写文件：``data/day05_device_requests.json``（其余三份 JSON 与整个
``knowledge/`` 只读）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from personal_assistant.paths import DATA_DIR

# §4.2 硬约束：multi_agent.py 从本模块导入 9 个名字。检索 Tool 的实现与 Chroma
# 访问都在 knowledge_base，这里只做名字导出（工具名已由
# @tool("search_company_knowledge") 固定，函数名保持 knowledge_base.search_knowledge）。
from personal_assistant.knowledge_base import search_knowledge as search_company_knowledge

USERS_PATH = DATA_DIR / "day05_users.json"
DEPARTMENTS_PATH = DATA_DIR / "day05_departments.json"
DEVICES_PATH = DATA_DIR / "day05_devices.json"
DEVICE_REQUESTS_PATH = DATA_DIR / "day05_device_requests.json"

REQUEST_ID_PREFIX = "REQ-2026-"
VALID_REQUEST_STATUSES = ("pending", "approved", "rejected")
VALID_REVIEW_DECISIONS = ("approved", "rejected")

# B7：找人只给这些字段（白名单，而不是把敏感字段挑出来删）
PUBLIC_EMPLOYEE_FIELDS = (
    "user_id",
    "display_name",
    "department_id",
    "job_title",
    "expertise",
    "office_location",
    "office_contact",
)


@dataclass(frozen=True)
class RunContext:
    """由教学登录创建、由应用注入的可信运行上下文。"""

    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


# 课件 Day05 §2.3 的权限矩阵。用户记录只保存 role，不为每个用户重复保存权限列表。
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "employee": {
        "read_public_knowledge",  # 检索公司内公开知识文档
        "read_public_directory",  # 查询部门和公开员工目录
        "read_device_catalog",  # 查询可申请的设备
        "create_device_request",  # 创建设备申请
        "read_own_device_requests",  # 查看本人提交的申请
    },
    "hr": {
        "read_public_knowledge",  # 检索公司内公开知识文档
        "read_hr_knowledge",  # 检索 HR 专属文档
        "read_public_directory",  # 查询部门和公开员工目录
        "read_device_catalog",  # 查询设备目录
        "read_all_device_requests",  # 查看全部申请，其中也包括 HR 本人的申请
        "review_device_requests",  # 批准或拒绝设备申请
    },
}

__all__ = [
    "RunContext",
    "ROLE_PERMISSIONS",
    "login_as",
    "search_company_knowledge",
    "find_department",
    "find_public_employee",
    "list_requestable_devices",
    "create_device_request",
    "query_device_requests",
    "approve_device_request",
]


# --------------------------------------------------------------------------
# B1 统一返回信封（error 是稳定机器码，message 是给人看的中文说明）
# --------------------------------------------------------------------------


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _err(code: str, message: str) -> str:
    return json.dumps({"ok": False, "error": code, "message": message}, ensure_ascii=False)


# --------------------------------------------------------------------------
# B3 JSON 读写：每次重新读盘（不做模块级缓存），写入用原子替换
# --------------------------------------------------------------------------


def _load_document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_users() -> list[dict[str, Any]]:
    return _load_document(USERS_PATH)["users"]


def _load_departments() -> list[dict[str, Any]]:
    return _load_document(DEPARTMENTS_PATH)["departments"]


def _load_devices() -> list[dict[str, Any]]:
    return _load_document(DEVICES_PATH)["devices"]


def _load_requests() -> list[dict[str, Any]]:
    return _load_document(DEVICE_REQUESTS_PATH)["requests"]


def _save_requests(requests: list[dict[str, Any]]) -> None:
    """原子替换写入：先写 .tmp，再 os.replace，避免中断时写坏文件。"""
    document = _load_document(DEVICE_REQUESTS_PATH)
    document["requests"] = requests
    temporary = DEVICE_REQUESTS_PATH.with_name(DEVICE_REQUESTS_PATH.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, DEVICE_REQUESTS_PATH)


# --------------------------------------------------------------------------
# B2 身份与权限：身份只来自 Runtime Context，Tool 签名里没有身份参数
# --------------------------------------------------------------------------


def _context_of(runtime: ToolRuntime) -> Any:
    return getattr(runtime, "context", None)


def _field(context: Any, name: str) -> str:
    """从 Context 取字段，兼容 dataclass（RunContext）与 mapping 两种注入形式。"""
    if isinstance(context, dict):
        return str(context.get(name) or "").strip()
    return str(getattr(context, name, "") or "").strip()


def _role_of(runtime: ToolRuntime) -> str:
    return _field(_context_of(runtime), "role")


def _user_id_of(runtime: ToolRuntime) -> str:
    return _field(_context_of(runtime), "user_id")


def _require_identity(runtime: ToolRuntime) -> str | None:
    """身份取不到时必须拒绝 —— 否则会静默产出「申请人未知」的记录。"""
    if not _user_id_of(runtime) or not _role_of(runtime):
        return _err("permission_denied", "运行上下文缺少可信身份，拒绝执行")
    return None


def _require(runtime: ToolRuntime, permission: str) -> str | None:
    """有权限返回 None；否则返回 permission_denied 的信封。"""
    missing = _require_identity(runtime)
    if missing:
        return missing
    role = _role_of(runtime)
    if permission not in ROLE_PERMISSIONS.get(role, set()):
        return _err(
            "permission_denied",
            f"当前角色 {role or '(未知)'} 没有 {permission} 权限",
        )
    return None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# B9 教学登录（课件 D6§6.2 原样）
# --------------------------------------------------------------------------


def login_as(username: str) -> dict[str, Any]:
    """使用预先登记的教学账号登录，不接受聊天中的身份声明。"""

    normalized = username.strip()
    for user in _load_users():
        if user.get("username") != normalized:
            continue
        if not user.get("login_enabled") or user.get("account_status") != "active":
            raise PermissionError("该教学账号当前不可登录")
        return user
    raise ValueError("未找到可登录的教学账号")


# --------------------------------------------------------------------------
# 内部查找与校验
# --------------------------------------------------------------------------


def _find_device(devices: list[dict[str, Any]], device_id: str) -> dict[str, Any] | None:
    return next((d for d in devices if d.get("device_id") == device_id), None)


def _find_user(users: list[dict[str, Any]], user_id: str | None) -> dict[str, Any] | None:
    return next((u for u in users if u.get("user_id") == user_id), None)


def _device_is_requestable(device: dict[str, Any], role: str, department_id: str) -> str | None:
    """B8：四项**同时**校验。返回 None 表示可以申请，否则返回拒绝原因。"""
    if not device.get("is_requestable"):
        return "该设备当前不开放申请"
    if int(device.get("max_quantity_per_request") or 0) <= 0:
        return "该设备单次申请数量上限为 0，无法申请"
    eligible_roles = device.get("eligible_roles") or []
    if role not in eligible_roles:
        return f"当前角色 {role} 不在该设备的可申请角色内"
    eligible_departments = device.get("eligible_department_ids") or []
    # 空列表表示**无部门限制**，不是禁止申请（Day05 附录 A.3）
    if eligible_departments and department_id not in eligible_departments:
        return f"当前部门 {department_id} 不在该设备的可申请部门内"
    return None


def _next_request_id(requests: list[dict[str, Any]]) -> str:
    """B5：取现有编号数字部分的最大值 +1；格式不匹配的记录忽略而非崩溃。"""
    numbers: list[int] = []
    for record in requests:
        request_id = str(record.get("request_id", ""))
        if not request_id.startswith(REQUEST_ID_PREFIX):
            continue
        tail = request_id[len(REQUEST_ID_PREFIX) :]
        if tail.isdigit():
            numbers.append(int(tail))
    return f"{REQUEST_ID_PREFIX}{max(numbers, default=0) + 1:04d}"


def _device_brief(device: dict[str, Any] | None, device_id: str) -> dict[str, Any]:
    if device is None:
        return {"device_id": device_id, "device_name": None}
    return {
        "device_id": device_id,
        "device_name": device.get("name"),
        "category": device.get("category"),
    }


def _request_view(
    record: dict[str, Any],
    users: list[dict[str, Any]],
    devices: list[dict[str, Any]],
) -> dict[str, Any]:
    """按稳定编号回到源文件解析姓名与设备名，不依赖冗余字段。"""
    applicant = _find_user(users, record.get("applicant_user_id"))
    reviewer = _find_user(users, record.get("reviewer_user_id"))
    device = _find_device(devices, str(record.get("device_id", "")))
    return {
        "request_id": record.get("request_id"),
        "status": record.get("status"),
        "applicant_user_id": record.get("applicant_user_id"),
        "applicant_name": (applicant or {}).get("display_name"),
        "device_id": record.get("device_id"),
        "device_name": (device or {}).get("name"),
        "quantity": record.get("quantity"),
        "reason": record.get("reason"),
        "requested_at": record.get("requested_at"),
        "reviewer_user_id": record.get("reviewer_user_id"),
        "reviewer_name": (reviewer or {}).get("display_name"),
        "reviewed_at": record.get("reviewed_at"),
        "review_comment": record.get("review_comment"),
    }


# --------------------------------------------------------------------------
# 只读 Tool
# --------------------------------------------------------------------------


@tool
def find_department(query: str, runtime: ToolRuntime) -> str:
    """按职责或名称查询公司部门（例如"软件账号""报销""招聘"找对应部门）。"""
    denied = _require(runtime, "read_public_directory")
    if denied:
        return denied

    keyword = (query or "").strip()
    if not keyword:
        return _err("invalid_argument", "query 不能为空")

    matched: list[dict[str, Any]] = []
    for department in _load_departments():
        haystack = [
            str(department.get("name", "")),
            str(department.get("department_id", "")),
            *[str(item) for item in department.get("responsibilities") or []],
        ]
        if any(keyword in field for field in haystack):
            matched.append(
                {
                    "department_id": department.get("department_id"),
                    "name": department.get("name"),
                    "responsibilities": department.get("responsibilities"),
                    "office_location": department.get("office_location"),
                    "public_contact": department.get("public_contact"),
                }
            )

    if not matched:
        return _err("not_found", f"没有找到与 {keyword!r} 相关的部门")
    return _ok({"query": keyword, "count": len(matched), "departments": matched})


@tool
def find_public_employee(query: str, runtime: ToolRuntime) -> str:
    """按姓名、岗位或负责事项查询**公开**的同事联系方式（用于找人办事）。"""
    denied = _require(runtime, "read_public_directory")
    if denied:
        return denied

    keyword = (query or "").strip()
    if not keyword:
        return _err("invalid_argument", "query 不能为空")

    # 部门名称也参与匹配：调用方（模型）很可能传「信息技术部」而不是「DEPT-IT」，
    # 只匹配编号会让「软件账号开通找谁」这条链路断在第二步。
    department_names = {
        d.get("department_id"): str(d.get("name", "")) for d in _load_departments()
    }

    matched: list[dict[str, Any]] = []
    for user in _load_users():
        # B7：排除 is_public == false；且不假设 USR- 前缀（数据里有 EMP-* 记录）
        if not user.get("is_public"):
            continue
        haystack = [
            str(user.get("display_name", "")),
            str(user.get("job_title", "")),
            str(user.get("department_id", "")),
            department_names.get(user.get("department_id"), ""),
            str(user.get("user_id", "")),
            *[str(item) for item in user.get("expertise") or []],
        ]
        if any(keyword in field for field in haystack):
            matched.append({field: user.get(field) for field in PUBLIC_EMPLOYEE_FIELDS})

    if not matched:
        return _err("not_found", f"没有找到与 {keyword!r} 相关的公开同事")
    return _ok({"query": keyword, "count": len(matched), "employees": matched})


@tool
def list_requestable_devices(runtime: ToolRuntime) -> str:
    """列出**当前登录人**可以申请的设备及其数量上限与申请要求。"""
    denied = _require(runtime, "read_device_catalog")
    if denied:
        return denied

    role = _role_of(runtime)
    department_id = _field(_context_of(runtime), "department_id")

    available: list[dict[str, Any]] = []
    for device in _load_devices():
        if _device_is_requestable(device, role, department_id) is not None:
            continue
        available.append(
            {
                "device_id": device.get("device_id"),
                "name": device.get("name"),
                "category": device.get("category"),
                "description": device.get("description"),
                "max_quantity_per_request": device.get("max_quantity_per_request"),
                "request_requirements": device.get("request_requirements"),
            }
        )

    return _ok(
        {
            "role": role,
            "department_id": department_id,
            "count": len(available),
            "devices": available,
        }
    )


@tool
def query_device_requests(runtime: ToolRuntime, status: str | None = None) -> str:
    """查询设备申请：员工只能看到**本人**的申请，HR 可以看到**全部**申请。

    可以按状态过滤（pending / approved / rejected）。
    """
    role = _role_of(runtime)
    if role == "hr":
        if _require(runtime, "read_all_device_requests"):
            return _err("permission_denied", "当前角色没有查看全部申请的权限")
    else:
        denied = _require(runtime, "read_own_device_requests")
        if denied:
            return denied

    wanted = (status or "").strip() or None
    if wanted is not None and wanted not in VALID_REQUEST_STATUSES:
        return _err(
            "invalid_argument",
            f"status 只能是 {list(VALID_REQUEST_STATUSES)} 之一",
        )

    users = _load_users()
    devices = _load_devices()
    records = _load_requests()

    if role != "hr":
        # B6：员工只按 applicant_user_id 过滤，范围来自 Context，不由调用方传入
        own_id = _user_id_of(runtime)
        records = [r for r in records if r.get("applicant_user_id") == own_id]

    if wanted is not None:
        records = [r for r in records if r.get("status") == wanted]

    views = [_request_view(record, users, devices) for record in records]
    return _ok(
        {
            "role": role,
            "scope": "all" if role == "hr" else "own",
            "status_filter": wanted,
            "count": len(views),
            "requests": views,
        }
    )


# --------------------------------------------------------------------------
# 写操作 Tool（B4：interrupt 之前算好编号；确认后才写；恢复后校验/幂等）
# --------------------------------------------------------------------------


def _build_create_candidate(
    context: Any,
    device: dict[str, Any],
    quantity: int,
    reason: str,
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """构造待确认的申请记录。

    **编号必须在这里（interrupt 之前）算好** —— 否则恢复时会算出不同的号，
    导致重复创建两条申请（课件 D5§5.2 明确要求避免）。
    """
    return {
        "request_id": _next_request_id(requests),
        "applicant_user_id": _field(context, "user_id"),
        "applicant_name": _field(context, "display_name"),
        "device_id": device.get("device_id"),
        "device_name": device.get("name"),
        "quantity": quantity,
        "reason": reason,
    }


@tool
def create_device_request(
    device_id: str, quantity: int, reason: str, runtime: ToolRuntime
) -> str:
    """为**当前登录人**提交一条设备申请（需要人工确认后才会写入）。"""
    context = _context_of(runtime)
    denied = _require(runtime, "create_device_request")
    if denied:
        return denied

    device_id = (device_id or "").strip()
    reason = (reason or "").strip()
    if not device_id:
        return _err("invalid_argument", "device_id 不能为空")
    if not reason:
        return _err("invalid_argument", "reason 不能为空（申请必须填写真实工作理由）")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return _err("invalid_argument", "quantity 必须是整数")

    devices = _load_devices()
    device = _find_device(devices, device_id)
    if device is None:
        return _err("not_found", f"没有找到设备 {device_id}")

    role = _role_of(runtime)
    department_id = _field(context, "department_id")
    blocked = _device_is_requestable(device, role, department_id)
    if blocked:
        return _err("invalid_argument", blocked)

    limit = int(device.get("max_quantity_per_request") or 0)
    if quantity < 1 or quantity > limit:
        return _err(
            "invalid_argument",
            f"quantity 必须在 1 到 {limit} 之间（该设备单次上限 {limit}）",
        )

    requests = _load_requests()
    candidate = _build_create_candidate(context, device, quantity, reason, requests)

    decision = interrupt({"action": "create_device_request", "candidate": candidate})
    if not isinstance(decision, dict) or not decision.get("approved"):
        # 拒绝分支必须先于任何写盘操作返回 —— 用户拒绝时文件字节数不变
        return _err("user_rejected", "用户取消，未创建申请")

    # 幂等：恢复后先查该编号是否已存在，避免重复创建
    requests = _load_requests()
    existing = next(
        (r for r in requests if r.get("request_id") == candidate["request_id"]), None
    )
    if existing is not None:
        return _ok(
            {
                "created": False,
                "reason": "该申请编号已存在，未重复创建",
                "request": _request_view(existing, _load_users(), devices),
            }
        )

    record = {
        "request_id": candidate["request_id"],
        "applicant_user_id": candidate["applicant_user_id"],
        "device_id": candidate["device_id"],
        "quantity": candidate["quantity"],
        "reason": candidate["reason"],
        "status": "pending",
        "requested_at": _now_iso(),
        "reviewer_user_id": None,
        "reviewed_at": None,
        "review_comment": None,
    }
    requests.append(record)
    _save_requests(requests)

    return _ok(
        {
            "created": True,
            "request": _request_view(record, _load_users(), devices),
        }
    )


@tool
def approve_device_request(
    request_id: str, decision: str, runtime: ToolRuntime, comment: str = ""
) -> str:
    """批准或拒绝一条**待审批**的设备申请（仅 HR；需要人工确认后才会写入）。"""
    context = _context_of(runtime)
    denied = _require(runtime, "review_device_requests")
    if denied:
        return denied

    request_id = (request_id or "").strip()
    decision = (decision or "").strip()
    comment = (comment or "").strip()
    if decision not in VALID_REVIEW_DECISIONS:
        return _err(
            "invalid_argument",
            f"decision 只能是 {list(VALID_REVIEW_DECISIONS)} 之一",
        )
    if not request_id:
        return _err("invalid_argument", "request_id 不能为空")

    requests = _load_requests()
    target = next((r for r in requests if r.get("request_id") == request_id), None)
    if target is None:
        return _err("not_found", f"没有找到申请 {request_id}")
    if target.get("status") != "pending":
        # 已批准或已拒绝的记录不能再次审批
        return _err(
            "conflict",
            f"申请 {request_id} 当前状态为 {target.get('status')}，不能再次审批",
        )

    payload = {
        "action": "approve_device_request",
        "request_id": request_id,
        "decision": decision,
        "comment": comment,
        "applicant_user_id": target.get("applicant_user_id"),
        "device_id": target.get("device_id"),
        "quantity": target.get("quantity"),
    }
    answer = interrupt(payload)
    if not isinstance(answer, dict) or not answer.get("approved"):
        return _err("user_rejected", "用户取消，未修改申请状态")

    # 恢复后**重新校验四件事**（课件 D5§5.4）：角色仍为 HR、申请仍存在、
    # 状态仍为 pending、本次决定合法。任一不满足返回 conflict。
    if _require(runtime, "review_device_requests"):
        return _err("conflict", "恢复后权限已变化，拒绝写入")
    if decision not in VALID_REVIEW_DECISIONS:
        return _err("conflict", "恢复后决定不再合法，拒绝写入")

    requests = _load_requests()
    current = next((r for r in requests if r.get("request_id") == request_id), None)
    if current is None:
        return _err("conflict", f"申请 {request_id} 已不存在，拒绝写入")
    if current.get("status") != "pending":
        return _err(
            "conflict",
            f"申请 {request_id} 的状态已被改为 {current.get('status')}，拒绝重复审批",
        )

    current["status"] = decision
    current["reviewer_user_id"] = _user_id_of(runtime)
    current["reviewed_at"] = _now_iso()
    current["review_comment"] = comment or None
    _save_requests(requests)

    return _ok(
        {
            "updated": True,
            "request": _request_view(current, _load_users(), _load_devices()),
        }
    )
