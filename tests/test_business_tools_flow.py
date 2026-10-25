"""7 个业务 Tool 的成功/失败/权限分支（fake Session，不连 MySQL）。"""

from __future__ import annotations

import json
from dataclasses import MISSING, fields
from datetime import datetime
from types import SimpleNamespace

import pytest
from langchain.tools import ToolRuntime

from personal_assistant import business_tools as bt
from personal_assistant.business_tools import RunContext


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeDb:
    def __init__(
        self,
        *,
        scalars: list[list[object]] | None = None,
        execute: list[list[object]] | None = None,
        get: dict[object, object] | None = None,
        scalar: object | None = None,
    ) -> None:
        self._scalars = list(scalars or [])
        self._execute = list(execute or [])
        self._get = dict(get or {})
        self._scalar = scalar
        self.added: list[object] = []

    def __enter__(self) -> _FakeDb:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def scalars(self, _statement: object) -> _Rows:
        return _Rows(self._scalars.pop(0) if self._scalars else [])

    def execute(self, _statement: object) -> _Rows:
        return _Rows(self._execute.pop(0) if self._execute else [])

    def get(self, model: object, key: str) -> object | None:
        return self._get.get((model, key))

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def scalar(self, _statement: object) -> object | None:
        return self._scalar


class _Factory:
    def __init__(self, db: _FakeDb) -> None:
        self._db = db

    def __call__(self) -> _FakeDb:
        return self._db

    def begin(self) -> _FakeDb:
        return self._db


def _runtime(role: str = "employee", tool_call_id: str = "call-1") -> ToolRuntime:
    ctx = RunContext(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role=role,
        department_id="DEPT-001",
    )
    kwargs: dict[str, object] = {}
    for field_info in fields(ToolRuntime):
        if field_info.name == "context":
            kwargs["context"] = ctx
        elif field_info.name == "state":
            kwargs["state"] = {}
        elif field_info.name == "tools":
            kwargs["tools"] = []
        elif field_info.name == "tool_call_id":
            kwargs["tool_call_id"] = tool_call_id
        elif field_info.default is MISSING and field_info.default_factory is MISSING:
            kwargs[field_info.name] = None
    return ToolRuntime(**kwargs)


def _department(**overrides: object) -> object:
    values = {
        "department_id": "DEPT-IT",
        "name": "信息技术部",
        "responsibilities": ["软件账号", "网络"],
        "office_location": "3F",
        "public_contact": "it@example.com",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _employee(**overrides: object) -> object:
    values = {
        "user_id": "USR-002",
        "display_name": "李娜",
        "department_id": "DEPT-IT",
        "job_title": "IT 支持",
        "expertise": ["账号开通"],
        "office_location": "3F",
        "office_contact": "li@example.com",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _device(**overrides: object) -> object:
    values = {
        "device_id": "DEV-1",
        "name": "显示器",
        "category": "display",
        "description": "24 英寸",
        "eligible_roles": ["employee"],
        "eligible_department_ids": [],
        "max_quantity_per_request": 2,
        "request_requirements": "无需额外审批",
        "is_requestable": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _request(**overrides: object) -> object:
    values = {
        "request_id": "REQ-1",
        "status": "pending",
        "applicant_user_id": "USR-001",
        "device_id": "DEV-1",
        "quantity": 1,
        "reason": "双屏",
        "requested_at": datetime(2026, 1, 1),
        "reviewer_user_id": None,
        "reviewed_at": None,
        "review_comment": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _install_db(monkeypatch: pytest.MonkeyPatch, db: _FakeDb) -> None:
    monkeypatch.setattr(bt, "SessionLocal", _Factory(db))


def test_find_department_success_empty_and_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb(scalars=[[_department()]])
    _install_db(monkeypatch, db)

    payload = json.loads(
        bt.find_department.invoke({"query": "软件", "runtime": _runtime()})
    )
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1

    empty = json.loads(bt.find_department.invoke({"query": "", "runtime": _runtime()}))
    assert empty["error"] == "invalid_argument"

    denied = json.loads(
        bt.find_department.invoke({"query": "软件", "runtime": _runtime(role="guest")})
    )
    assert denied["error"] == "permission_denied"

    db = _FakeDb(scalars=[[]])
    _install_db(monkeypatch, db)
    missing = json.loads(
        bt.find_department.invoke({"query": "不存在", "runtime": _runtime()})
    )
    assert missing["error"] == "not_found"


def test_find_public_employee_success_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb(
        scalars=[[_employee()]],
        execute=[[("DEPT-IT", "信息技术部")]],
    )
    _install_db(monkeypatch, db)

    payload = json.loads(
        bt.find_public_employee.invoke({"query": "李娜", "runtime": _runtime()})
    )
    assert payload["ok"] is True
    assert payload["data"]["employees"][0]["user_id"] == "USR-002"

    missing = json.loads(
        bt.find_public_employee.invoke({"query": "不存在", "runtime": _runtime()})
    )
    assert missing["error"] == "not_found"


def test_list_requestable_devices_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb(
        scalars=[
            [
                _device(),
                _device(device_id="DEV-2", is_requestable=False),
                _device(device_id="DEV-3", eligible_roles=["hr"]),
            ]
        ]
    )
    _install_db(monkeypatch, db)

    payload = json.loads(bt.list_requestable_devices.invoke({"runtime": _runtime()}))
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["devices"][0]["device_id"] == "DEV-1"


def test_query_device_requests_employee_and_hr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _request()
    db = _FakeDb(
        execute=[
            [(record, "显示器")],
            [("USR-001", "张伟")],
        ]
    )
    _install_db(monkeypatch, db)

    payload = json.loads(
        bt.query_device_requests.invoke({"status": "pending", "runtime": _runtime()})
    )
    assert payload["data"]["scope"] == "own"
    assert payload["data"]["count"] == 1

    db = _FakeDb(
        execute=[
            [(record, "显示器")],
            [("USR-001", "张伟")],
        ]
    )
    _install_db(monkeypatch, db)
    hr_payload = json.loads(
        bt.query_device_requests.invoke(
            {"status": "all", "runtime": _runtime(role="hr")}
        )
    )
    assert hr_payload["data"]["scope"] == "all"

    invalid = json.loads(
        bt.query_device_requests.invoke({"status": "unknown", "runtime": _runtime()})
    )
    assert invalid["error"] == "invalid_argument"


def test_create_device_request_success_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bt, "interrupt", lambda payload: {"approved": True})
    db = _FakeDb(get={(bt.Device, "DEV-1"): _device()})
    _install_db(monkeypatch, db)
    runtime = _runtime()

    payload = json.loads(
        bt.create_device_request.invoke(
            {
                "device_id": "DEV-1",
                "quantity": 1,
                "reason": "双屏",
                "runtime": runtime,
            }
        )
    )
    assert payload["ok"] is True
    assert payload["data"]["created"] is True
    assert db.added

    monkeypatch.setattr(bt, "interrupt", lambda payload: {"approved": False})
    rejected = json.loads(
        bt.create_device_request.invoke(
            {
                "device_id": "DEV-1",
                "quantity": 1,
                "reason": "双屏",
                "runtime": runtime,
            }
        )
    )
    assert rejected["error"] == "user_rejected"


def test_create_device_request_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb(get={(bt.Device, "DEV-1"): _device()})
    _install_db(monkeypatch, db)

    for args in (
        {"device_id": "", "quantity": 1, "reason": "x"},
        {"device_id": "DEV-1", "quantity": 1, "reason": ""},
    ):
        payload = json.loads(
            bt.create_device_request.invoke({**args, "runtime": _runtime()})
        )
        assert payload["error"] == "invalid_argument"

    # quantity 的 schema 是 int，非整数在 Tool 入参校验阶段就会被拦下；
    # 直接调用原函数才能覆盖内部的 int(quantity) 失败分支。
    payload = json.loads(
        bt.create_device_request.func(  # type: ignore[attr-defined]
            device_id="DEV-1",
            quantity="x",  # type: ignore[arg-type]
            reason="x",
            runtime=_runtime(),
        )
    )
    assert payload["error"] == "invalid_argument"

    not_found = json.loads(
        bt.create_device_request.invoke(
            {
                "device_id": "DEV-404",
                "quantity": 1,
                "reason": "x",
                "runtime": _runtime(),
            }
        )
    )
    assert not_found["error"] == "not_found"


def test_approve_device_request_success_reject_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _request()
    device = _device()
    db = _FakeDb(
        get={(bt.DeviceRequest, "REQ-1"): target, (bt.Device, "DEV-1"): device},
        execute=[[("USR-001", "张伟")], [("USR-001", "张伟")]],
        scalar=target,
    )
    _install_db(monkeypatch, db)
    monkeypatch.setattr(bt, "interrupt", lambda payload: {"approved": True})

    payload = json.loads(
        bt.approve_device_request.invoke(
            {
                "request_id": "REQ-1",
                "decision": "approved",
                "comment": "同意",
                "runtime": _runtime(role="hr"),
            }
        )
    )
    assert payload["ok"] is True
    assert target.status == "approved"

    denied = json.loads(
        bt.approve_device_request.invoke(
            {
                "request_id": "REQ-1",
                "decision": "approved",
                "runtime": _runtime(role="employee"),
            }
        )
    )
    assert denied["error"] == "permission_denied"

    target.status = "pending"
    db._execute = [[("USR-001", "张伟")], [("USR-001", "张伟")]]
    monkeypatch.setattr(bt, "interrupt", lambda payload: {"approved": False})
    rejected = json.loads(
        bt.approve_device_request.invoke(
            {
                "request_id": "REQ-1",
                "decision": "rejected",
                "runtime": _runtime(role="hr"),
            }
        )
    )
    assert rejected["error"] == "user_rejected"
