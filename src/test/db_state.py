"""持久化升级后的测试侧取数工具：JSON 时代 ``bt._load_*`` / ``bt.login_as`` 的对应物。

为什么单独一个模块：本次升级把 Tool 层的数据源从 ``src/data/*.json`` 换成了
``agent_service`` 库（见 ``docs/状态持久化升级计划.md`` §8），测试里原本
"读文件 → 比字节数与 sha256" 的断言必须换成"读库 → 比有序行摘要"。取数与摘要
集中在这里，三个测试文件共用同一口径，避免各写一套而互相漂移。

硬约束（课件 Day05 §6.2）：**在 Session 关闭之前**把 ORM 对象转成 dict ——
出了 ``with`` 块再摸属性会 DetachedInstanceError。本模块每个函数都在 with 内完成
转换，因此调用方拿到的是纯 dict，不受会话生命周期影响。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from personal_assistant.business_tools import get_login_user
from personal_assistant.database import SessionLocal
from personal_assistant.models import (
    Department,
    Device,
    DeviceRequest,
    User,
)


def _moment(value: datetime | None) -> str | None:
    """库里是 naive UTC，对外统一补 `Z`（与出参口径一致，见 business_tools._iso）。"""

    return None if value is None else value.isoformat(timespec="seconds") + "Z"


def users_rows() -> list[dict[str, Any]]:
    """全部用户（对应旧 ``bt._load_users()``）。"""

    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.user_id)).all()
        return [
            {
                "user_id": u.user_id,
                "username": u.username,
                "display_name": u.display_name,
                "role": u.role,
                "account_status": u.account_status,
                "department_id": u.department_id,
                "expertise": list(u.expertise or []),
                "office_contact": u.office_contact,
                "is_public": u.is_public,
                "login_enabled": u.login_enabled,
            }
            for u in users
        ]


def departments_rows() -> list[dict[str, Any]]:
    """全部部门（对应旧 ``bt._load_departments()``）。"""

    with SessionLocal() as db:
        rows = db.scalars(select(Department).order_by(Department.department_id)).all()
        return [
            {
                "department_id": d.department_id,
                "name": d.name,
                "responsibilities": list(d.responsibilities or []),
            }
            for d in rows
        ]


def devices_rows() -> list[dict[str, Any]]:
    """全部设备（对应旧 ``bt._load_devices()``）。"""

    with SessionLocal() as db:
        rows = db.scalars(select(Device).order_by(Device.device_id)).all()
        return [
            {
                "device_id": d.device_id,
                "name": d.name,
                "category": d.category,
                "description": d.description,
                "eligible_roles": list(d.eligible_roles or []),
                "eligible_department_ids": list(d.eligible_department_ids or []),
                "max_quantity_per_request": d.max_quantity_per_request,
                "request_requirements": d.request_requirements,
                "is_requestable": d.is_requestable,
            }
            for d in rows
        ]


def requests_rows() -> list[dict[str, Any]]:
    """全部申请（对应旧 ``json.loads(REQUESTS.read_text())["requests"]``）。

    多一个 ``device_name``（联表取），旧 JSON 里没有；其余键与旧记录逐键同名，
    测试里已有断言不用改。
    """

    with SessionLocal() as db:
        pairs = db.execute(
            select(DeviceRequest, Device.name)
            .join(Device, DeviceRequest.device_id == Device.device_id)
            .order_by(DeviceRequest.request_id)
        ).all()
        return [
            {
                "request_id": r.request_id,
                "applicant_user_id": r.applicant_user_id,
                "device_id": r.device_id,
                "device_name": device_name,
                "quantity": r.quantity,
                "reason": r.reason,
                "status": r.status,
                "requested_at": _moment(r.requested_at),
                "reviewer_user_id": r.reviewer_user_id,
                "reviewed_at": _moment(r.reviewed_at),
                "review_comment": r.review_comment,
            }
            for r, device_name in pairs
        ]


def login_user(username: str) -> dict[str, Any]:
    """按用户名查可登录账号（对应旧 ``bt.login_as(username)``）。

    与旧版一样抛 ``ValueError`` / ``PermissionError``；区别是它现在**直连数据库**，
    因此"JSON 里改一行就能登录"的时代结束了 —— 停用账号必须改库。
    """

    with SessionLocal() as db:
        user = get_login_user(db, username)
        return {
            "user_id": user.user_id,
            "username": str(user.username or ""),
            "display_name": user.display_name,
            "role": str(user.role or ""),
            "department_id": user.department_id,
        }


def requests_snapshot() -> tuple[int, str, int]:
    """申请表的 ``(内容长度, 摘要[:16], 行数)`` —— 旧 ``snapshot()`` 的库版。

    第 3 位（行数）沿用旧断言里的 ``before[2]``；整体相等即"这一轮没有改库"。
    """

    rows = requests_rows()
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return len(payload), digest, len(rows)


def table_counts() -> dict[str, int]:
    """五张表的行数（验收 `V3` 用）。"""

    with SessionLocal() as db:
        return {
            "departments": db.scalar(select(func.count()).select_from(Department)) or 0,
            "users": db.scalar(select(func.count()).select_from(User)) or 0,
            "devices": db.scalar(select(func.count()).select_from(Device)) or 0,
            "device_requests": db.scalar(select(func.count()).select_from(DeviceRequest)) or 0,
        }


def dump_requests_backup(path: Path) -> int:
    """把申请表导出成 JSON（验收跑完要还原，替代旧的"复制文件"）。"""

    rows = requests_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(rows)


def load_requests_backup(path: Path) -> int:
    """用备份 JSON 覆盖申请表（先清空再插回，主键与时间原样保留）。"""

    rows = json.loads(path.read_text(encoding="utf-8"))
    with SessionLocal.begin() as db:
        db.execute(delete(DeviceRequest))
        for row in rows:
            db.add(
                DeviceRequest(
                    request_id=row["request_id"],
                    applicant_user_id=row["applicant_user_id"],
                    device_id=row["device_id"],
                    quantity=row["quantity"],
                    reason=row["reason"],
                    status=row["status"],
                    requested_at=datetime.fromisoformat(str(row["requested_at"]).rstrip("Z")),
                    reviewer_user_id=row.get("reviewer_user_id"),
                    reviewed_at=(
                        datetime.fromisoformat(str(row["reviewed_at"]).rstrip("Z"))
                        if row.get("reviewed_at")
                        else None
                    ),
                    review_comment=row.get("review_comment"),
                )
            )
    return len(rows)
