"""业务表与会话索引表的 ORM 契约。

**列的「真源」是本机 MySQL 的实际 DDL**（由 `scripts/day05_mysql_setup.sql` 建立，
行数与列已在升级计划 S0 逐列核对过）。本文件与 DDL 逐列对齐，可空性、CHECK 约束
一律以 DDL 为准。

旧版本有 6 处与 DDL 相反，本次按 DDL 修正：

| 位置 | 旧写法 | DDL 实际 |
| --- | --- | --- |
| `Department.name` | `Mapped[list[str]]` | `VARCHAR(100) NOT NULL UNIQUE` → `str` |
| `Department.responsibilities` | `Mapped[str]` | `JSON NOT NULL` → `list[str]` |
| `User.username` | 注解可空、却写 `nullable=False` | `VARCHAR(50) NULL` |
| `User.role` | `nullable=False` | `VARCHAR(30) NULL` |
| `User.account_status` | 注解可空、却写 `nullable=False` | `VARCHAR(30) NULL` |
| `User.department_id` | 可空 | `VARCHAR(30) NOT NULL` + FK |
| `ck_users_role` / `ck_users_status` | `role IN (…)` | `role IS NULL OR role IN (…)` |

（`Base` 由 `database.py` 提供，本模块导入 —— 不再各自定义一个。）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    """生成适合写入 MySQL `DATETIME` 的 **UTC 无时区**时间。

    对外输出时再补 `"Z"`（见 `business_tools._request_data`）：库里的 19 条申请
    与课件初始化 SQL 的 18 条都是这个口径（已用两组数据核对：
    本地 `2026-08-27T15:00:00+08:00` ↔ 库 `2026-08-27 07:00:00`）。
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Department(Base):
    __tablename__ = "departments"

    department_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    responsibilities: Mapped[list[str]] = mapped_column(JSON)
    office_location: Mapped[str] = mapped_column(String(200))
    public_contact: Mapped[str] = mapped_column(String(200))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IS NULL OR role IN ('employee', 'hr')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "account_status IS NULL OR account_status IN ('active', 'disabled')",
            name="ck_users_status",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    # 公开员工目录里的记录可能**不是登录账号**（27 人中只有 10 人可登录），
    # 所以 username / role / account_status 三个字段允许为空。
    username: Mapped[str | None] = mapped_column(
        String(50), unique=True, index=True, nullable=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    login_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    account_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.department_id"), nullable=False
    )
    job_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expertise: Mapped[list[str]] = mapped_column(JSON)
    office_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    office_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "max_quantity_per_request >= 0",
            name="ck_devices_max_quantity",
        ),
    )

    device_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    eligible_roles: Mapped[list[str]] = mapped_column(JSON)
    eligible_department_ids: Mapped[list[str]] = mapped_column(JSON)
    max_quantity_per_request: Mapped[int] = mapped_column(Integer)
    request_requirements: Mapped[str] = mapped_column(Text)
    is_requestable: Mapped[bool] = mapped_column(Boolean, default=True)


class DeviceRequest(Base):
    __tablename__ = "device_requests"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_device_requests_quantity"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_device_requests_status",
        ),
    )

    request_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    applicant_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id"))
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    reviewer_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentThread(Base):
    """`session_id` ↔ `user_id` 的索引表：让「登录后找回上次的会话」成为一次查询。

    - `thread_id` 是应用生成的 `uuid4().hex`，**长度 32**（远小于 DDL 的 VARCHAR(36)），
      与 LangGraph 检查点里的 `thread_id` 是同一个值；
    - 检查点在 SQLite 里，这张表只在 MySQL 里做**索引**，不存消息；
    - 挂掉/清空这张表不会丢对话内容（内容在检查点里），只是找不回 thread_id。
    """

    __tablename__ = "agent_threads"

    thread_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
