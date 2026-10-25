"""教学登录、可信运行上下文与七个业务 Tool。

本模块是项目的**业务权限闸门**：所有身份判断都在这里执行，且都在**执行端**
（不是靠 Prompt 提示）。

* ``RunContext`` 由应用构造并注入（身份只来自数据库里的教学账号）；
  Tool 签名里没有身份参数；
* ``ROLE_PERMISSIONS`` 是课件 Day05 §2.3 的角色权限矩阵，**保持不变**；
* 每个 Tool 第一句取 ``runtime.context``，再判权限，再校验参数与业务状态；
* 写操作（创建 / 审批）在写库前调用 ``interrupt()`` 等人工确认，且**不跨 ``interrupt()``
  持有 Session** —— 用户确认期间不占用数据库连接（课件 Day05 §6 的 Session 生命周期）。

设计依据（Day06 执行计划 v2 §4.2）：B1 统一信封、B2 身份只取 context、
B4 interrupt 与幂等、B6 查询范围、B7 字段白名单、B8 设备四项校验、B9 登录。

**B3 已按 Day05 升级改写**：原「每次重新读盘 + 原子替换写 JSON」改为
「短命 Session 读取 / ``SessionLocal.begin()`` 短事务写入」；唯一可写对象
由 ``data/day05_device_requests.json`` 变为 ``agent_service.device_requests`` 表。
权限层、返回信封、interrupt 载荷形状与对外字段**一律未动**。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_assistant.database import SessionLocal

# §4.2 硬约束：multi_agent.py 从本模块导入这些名字。检索 Tool 的实现与 Chroma
# 访问都在 knowledge_base，这里只做名字导出（工具名已由
# @tool("search_company_knowledge") 固定，函数名保持 knowledge_base.search_knowledge）。
from personal_assistant.knowledge_base import (
    search_knowledge as search_company_knowledge,
)
from personal_assistant.models import Department, Device, DeviceRequest, User, utc_now

VALID_REQUEST_STATUSES = ("pending", "approved", "rejected")
VALID_REVIEW_DECISIONS = ("approved", "rejected")
# `status` 参数同时接受 None / "" / "all" 表示不过滤：本项目原有约定是 None，
# 课件 §6.2 的约定是 "all"，两种都认，避免模型按任一份文档说话就被拒。
NO_STATUS_FILTER = (None, "", "all")

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
    "get_login_user",
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
    return json.dumps(
        {"ok": False, "error": code, "message": message}, ensure_ascii=False
    )


def _iso_z(moment: datetime | str | None) -> str | None:
    """把库里的 naive UTC `datetime` 输出成 `…Z` 字符串（None 原样返回）。

    升级前 JSON 里存的是带本地偏移的字符串（`…+08:00`），升级后库里统一存
    naive UTC（见 `models.utc_now()`），对外一律补 `Z`，让「同一列只有一种形态」。
    """
    if moment is None:
        return None
    if isinstance(moment, str):
        return moment
    return moment.isoformat(timespec="seconds") + "Z"


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


# --------------------------------------------------------------------------
# B9 教学登录（课件 Day05 §5.3：接收外部 Session、不再自带 Session 与兼容包装）
# --------------------------------------------------------------------------


def get_login_user(db: Session, username: str) -> User:
    """查询已登记且可用的教学账号。

    与课件的唯一差别：多校验 `role in {"employee", "hr"}` —— 数据里可能有
    `role` 为空或既非员工也非 HR 的记录，放进 RunContext 会让权限矩阵静默失效。
    """
    user = db.scalar(select(User).where(User.username == username.strip()))
    if user is None:
        raise ValueError("未找到可登录的教学账号")
    if (
        not user.login_enabled
        or user.account_status != "active"
        or user.role not in {"employee", "hr"}
    ):
        raise PermissionError("该教学账号当前不可登录")
    return user


# --------------------------------------------------------------------------
# ORM → 对外字段（在 Session 关闭前转成 dict：课件 §6.2 的硬要求）
# --------------------------------------------------------------------------


def _device_data(device: Device) -> dict[str, Any]:
    return {
        "device_id": device.device_id,
        "name": device.name,
        "category": device.category,
        "description": device.description,
        "eligible_roles": list(device.eligible_roles or []),
        "eligible_department_ids": list(device.eligible_department_ids or []),
        "max_quantity_per_request": device.max_quantity_per_request,
        "request_requirements": device.request_requirements,
        "is_requestable": device.is_requestable,
    }


def _request_data(
    record: DeviceRequest,
    device_name: str | None = None,
    applicant_name: str | None = None,
    reviewer_name: str | None = None,
) -> dict[str, Any]:
    """申请记录的对外字段。

    `applicant_name` / `reviewer_name` / `device_name` 不是表里的列，由调用方
    在查库时按稳定编号 join 出来（编号才是唯一 join key，不冗余存姓名）——
    升级前 JSON 版本也是这么做的，对外字段一个没少。
    """
    return {
        "request_id": record.request_id,
        "status": record.status,
        "applicant_user_id": record.applicant_user_id,
        "applicant_name": applicant_name,
        "device_id": record.device_id,
        "device_name": device_name,
        "quantity": record.quantity,
        "reason": record.reason,
        "requested_at": _iso_z(record.requested_at),
        "reviewer_user_id": record.reviewer_user_id,
        "reviewer_name": reviewer_name,
        "reviewed_at": _iso_z(record.reviewed_at),
        "review_comment": record.review_comment,
    }


# --------------------------------------------------------------------------
# 内部查找与校验
# --------------------------------------------------------------------------


def _display_name_map(
    db: Session, user_ids: Sequence[str | None]
) -> dict[str, str | None]:
    """一次查询把若干 user_id 映射成 display_name（避免逐行 N+1 查询）。"""
    wanted = {uid for uid in user_ids if uid}
    if not wanted:
        return {}
    rows = db.execute(
        select(User.user_id, User.display_name).where(User.user_id.in_(wanted))
    ).all()
    return {user_id: display_name for user_id, display_name in rows}


def _device_is_requestable(device: Device, role: str, department_id: str) -> str | None:
    """B8：四项**同时**校验。返回 None 表示可以申请，否则返回拒绝原因。"""
    if not device.is_requestable:
        return "该设备当前不开放申请"
    if int(device.max_quantity_per_request or 0) <= 0:
        return "该设备单次申请数量上限为 0，无法申请"
    eligible_roles = list(device.eligible_roles or [])
    if role not in eligible_roles:
        return f"当前角色 {role} 不在该设备的可申请角色内"
    eligible_departments = list(device.eligible_department_ids or [])
    # 空列表表示**无部门限制**，不是禁止申请（Day05 附录 A.3）
    if eligible_departments and department_id not in eligible_departments:
        return f"当前部门 {department_id} 不在该设备的可申请部门内"
    return None


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

    with SessionLocal() as db:
        rows = list(db.scalars(select(Department)).all())

    matched: list[dict[str, Any]] = []
    for department in rows:
        haystack = [
            str(department.name or ""),
            str(department.department_id or ""),
            *[str(item) for item in department.responsibilities or []],
        ]
        if any(keyword in field for field in haystack):
            matched.append(
                {
                    "department_id": department.department_id,
                    "name": department.name,
                    "responsibilities": list(department.responsibilities or []),
                    "office_location": department.office_location,
                    "public_contact": department.public_contact,
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

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.is_public.is_(True))).all())
        # 部门名称也参与匹配：调用方（模型）很可能传「信息技术部」而不是「DEPT-IT」，
        # 只匹配编号会让「软件账号开通找谁」这条链路断在第二步。
        department_names = {
            department_id: name
            for department_id, name in db.execute(
                select(Department.department_id, Department.name)
            ).all()
        }

    matched: list[dict[str, Any]] = []
    for user in users:
        haystack = [
            str(user.display_name or ""),
            str(user.job_title or ""),
            str(user.department_id or ""),
            department_names.get(user.department_id, ""),
            str(user.user_id or ""),
            *[str(item) for item in user.expertise or []],
        ]
        if any(keyword in field for field in haystack):
            matched.append(
                {field: getattr(user, field) for field in PUBLIC_EMPLOYEE_FIELDS}
            )

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

    with SessionLocal() as db:
        devices = list(db.scalars(select(Device)).all())

    available: list[dict[str, Any]] = []
    for device in devices:
        if _device_is_requestable(device, role, department_id) is not None:
            continue
        data = _device_data(device)
        available.append(
            {
                "device_id": data["device_id"],
                "name": data["name"],
                "category": data["category"],
                "description": data["description"],
                "max_quantity_per_request": data["max_quantity_per_request"],
                "request_requirements": data["request_requirements"],
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

    可以按状态过滤（pending / approved / rejected）；不传或传 all 表示不过滤。
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
    if wanted is not None and wanted != "all" and wanted not in VALID_REQUEST_STATUSES:
        return _err(
            "invalid_argument",
            f"status 只能是 {list(VALID_REQUEST_STATUSES)} 之一（或 all / 留空）",
        )

    statement = select(DeviceRequest, Device.name).join(
        Device, DeviceRequest.device_id == Device.device_id
    )
    if role != "hr":
        # B6：员工只按 applicant_user_id 过滤，范围来自 Context，不由调用方传入
        statement = statement.where(
            DeviceRequest.applicant_user_id == _user_id_of(runtime)
        )
    if wanted not in NO_STATUS_FILTER:
        statement = statement.where(DeviceRequest.status == wanted)

    with SessionLocal() as db:
        rows = db.execute(statement).all()
        names = _display_name_map(
            db,
            [record.applicant_user_id for record, _ in rows]
            + [record.reviewer_user_id for record, _ in rows],
        )
        # 出参必须在 Session 关闭之前就转成 dict（课件 §6.2）
        views = [
            _request_data(
                record,
                device_name=device_name,
                applicant_name=names.get(record.applicant_user_id or ""),
                reviewer_name=names.get(record.reviewer_user_id or ""),
            )
            for record, device_name in rows
        ]

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
# 写操作 Tool
#
# B4（业务规则）与课件 §6 的 Session 生命周期叠加成同一条流程：
#     短命 Session 校验 → interrupt() 等确认（不持 Session）→ 新事务写入
# 编号在 interrupt **之前**生成，且必须**跨 interrupt 稳定**：既保留本项目原有的幂等
# （恢复后按主键查重），又用 UUID 消灭课件指出的「最大编号 +1」并发撞主键问题。
#
# ⚠️ 为什么不能在这里直接 `uuid4()`（实测踩过，已修）：`interrupt()` 恢复时**整个函数
#    从头重跑**（LangGraph 从该节点入口重新执行），于是 `uuid4()` 会重新摇一次 ——
#    确认页上给用户看的编号与真正写进库的编号不是同一个，
#    而且"按编号查重"的幂等护栏
#    永远命中不了。现场证据：acceptance_day06 场景 7 打印
#    「真实申请编号: None（未预设 0019）/ 新记录: {}」，
#    而那一行其实已经写进库（19 -> 20）。
#    改法：编号由 `runtime.tool_call_id` 派生 —— 同一轮工具调用恢复后重跑得到同一个值。
# --------------------------------------------------------------------------


def _candidate_request_id(runtime: ToolRuntime) -> str:
    """申请编号：由**工具调用 id** 派生，跨 `interrupt()` 稳定。

    同一个工具调用在恢复后重跑时拿到同一个 `tool_call_id`，因此「确认页上显示的编号」
    ＝「真正写进库的编号」，按主键查重的幂等护栏也才真的有用。拿不到 `tool_call_id`
    时退回随机编号 —— 宁可丢掉幂等，也不能让所有申请撞同一个号。
    """

    seed = getattr(runtime, "tool_call_id", None)
    if not seed:
        return f"REQ-{uuid4().hex[:12].upper()}"
    return f"REQ-{hashlib.sha1(str(seed).encode('utf-8')).hexdigest()[:12].upper()}"


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

    # 第 1 段短命 Session：查设备 + 校验；出了 with 就归还连接，等待用户时不再占用
    with SessionLocal() as db:
        device = db.get(Device, device_id)
        if device is None:
            return _err("not_found", f"没有找到设备 {device_id}")
        role = _role_of(runtime)
        department_id = _field(context, "department_id")
        blocked = _device_is_requestable(device, role, department_id)
        if blocked:
            return _err("invalid_argument", blocked)
        limit = int(device.max_quantity_per_request or 0)
        device_name = device.name

    if quantity < 1 or quantity > limit:
        return _err(
            "invalid_argument",
            f"quantity 必须在 1 到 {limit} 之间（该设备单次上限 {limit}）",
        )

    candidate: dict[str, Any] = {
        "request_id": _candidate_request_id(runtime),
        "applicant_user_id": _field(context, "user_id"),
        "applicant_name": _field(context, "display_name"),
        "device_id": device_id,
        "device_name": device_name,
        "quantity": quantity,
        "reason": reason,
    }

    decision = interrupt({"action": "create_device_request", "candidate": candidate})
    if not isinstance(decision, dict) or not decision.get("approved"):
        # 拒绝分支必须先于任何写库操作返回 —— 用户拒绝时一行都不写
        return _err("user_rejected", "用户取消，未创建申请")

    # 第 2 段短事务：正常结束自动 commit，异常自动 rollback
    with SessionLocal.begin() as db:
        # 幂等：恢复后先查该编号是否已存在，避免重复创建
        existing = db.get(DeviceRequest, candidate["request_id"])
        if existing is not None:
            names = _display_name_map(
                db, [existing.applicant_user_id, existing.reviewer_user_id]
            )
            device = db.get(Device, existing.device_id)
            return _ok(
                {
                    "created": False,
                    "reason": "该申请编号已存在，未重复创建",
                    "request": _request_data(
                        existing,
                        device_name=device.name if device else None,
                        applicant_name=names.get(existing.applicant_user_id or ""),
                        reviewer_name=names.get(existing.reviewer_user_id or ""),
                    ),
                }
            )

        record = DeviceRequest(
            request_id=candidate["request_id"],
            applicant_user_id=candidate["applicant_user_id"],
            device_id=candidate["device_id"],
            quantity=quantity,
            reason=reason,
            status="pending",
            requested_at=utc_now(),
        )
        db.add(record)
        # flush 会执行 INSERT 与约束检查，但仍可回滚
        db.flush()
        data = _request_data(
            record,
            device_name=device_name,
            applicant_name=candidate["applicant_name"],
        )

    return _ok({"created": True, "request": data})


@tool
def approve_device_request(
    request_id: str, decision: str, runtime: ToolRuntime, comment: str = ""
) -> str:
    """批准或拒绝一条**待审批**的设备申请（仅 HR；需要人工确认后才会写入）。"""
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

    # 第 1 段短命 Session：暂停前先确认申请存在且仍待审批
    with SessionLocal() as db:
        target = db.get(DeviceRequest, request_id)
        if target is None:
            return _err("not_found", f"没有找到申请 {request_id}")
        if target.status != "pending":
            # 已批准或已拒绝的记录不能再次审批
            return _err(
                "conflict",
                f"申请 {request_id} 当前状态为 {target.status}，不能再次审批",
            )
        device = db.get(Device, target.device_id)
        names = _display_name_map(db, [target.applicant_user_id])
        payload = {
            "action": "approve_device_request",
            "request_id": request_id,
            "decision": decision,
            "comment": comment,
            "applicant_user_id": target.applicant_user_id,
            "applicant_name": names.get(target.applicant_user_id),
            "device_id": target.device_id,
            "device_name": device.name if device else None,
            "quantity": target.quantity,
        }

    answer = interrupt(payload)
    if not isinstance(answer, dict) or not answer.get("approved"):
        return _err("user_rejected", "用户取消，未修改申请状态")

    # 恢复后**重新校验**：角色仍为 HR、决定仍合法（课件 §6.3 只重新校验状态，
    # 这里保留本项目原有的两道校验，多一道不亏）。
    if _require(runtime, "review_device_requests"):
        return _err("conflict", "恢复后权限已变化，拒绝写入")
    if decision not in VALID_REVIEW_DECISIONS:
        return _err("conflict", "恢复后决定不再合法，拒绝写入")

    # 第 2 段短事务：SELECT … FOR UPDATE 锁定该行，防两个审批同时改同一行
    with SessionLocal.begin() as db:
        current = db.scalar(
            select(DeviceRequest)
            .where(DeviceRequest.request_id == request_id)
            .with_for_update()
        )
        if current is None:
            return _err("conflict", f"申请 {request_id} 已不存在，拒绝写入")
        # Interrupt 可能暂停很久，恢复后必须重新检查状态
        if current.status != "pending":
            return _err(
                "conflict",
                f"申请 {request_id} 的状态已被改为 {current.status}，拒绝重复审批",
            )

        current.status = decision
        current.reviewer_user_id = _user_id_of(runtime)
        current.reviewed_at = utc_now()
        current.review_comment = comment or None
        db.flush()
        device = db.get(Device, current.device_id)
        names = _display_name_map(
            db, [current.applicant_user_id, current.reviewer_user_id]
        )
        data = _request_data(
            current,
            device_name=device.name if device else None,
            applicant_name=names.get(current.applicant_user_id),
            reviewer_name=names.get(current.reviewer_user_id),
        )

    return _ok({"updated": True, "request": data})
