"""业务 Tool 的纯函数/权限闸门测试（不连 MySQL）。"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from personal_assistant.business_tools import (
    RunContext,
    _candidate_request_id,
    _device_data,
    _device_is_requestable,
    _display_name_map,
    _err,
    _field,
    _iso_z,
    _ok,
    _request_data,
    _require,
    _require_identity,
    get_login_user,
)


def _runtime(role: str = "employee", user_id: str = "USR-001") -> object:
    return SimpleNamespace(
        context=RunContext(
            user_id=user_id,
            username="zhang_wei",
            display_name="张伟",
            role=role,
            department_id="DEPT-001",
        )
    )


def _device(**overrides: object) -> object:
    values = {
        "is_requestable": True,
        "max_quantity_per_request": 2,
        "eligible_roles": ["employee"],
        "eligible_department_ids": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_envelopes_and_iso_z() -> None:
    assert json.loads(_ok({"x": 1})) == {"ok": True, "data": {"x": 1}}
    assert json.loads(_err("bad", "原因")) == {
        "ok": False,
        "error": "bad",
        "message": "原因",
    }

    moment = datetime(2026, 1, 2, 3, 4, 5)
    assert _iso_z(None) is None
    assert _iso_z("already-Z") == "already-Z"
    assert _iso_z(moment) == "2026-01-02T03:04:05Z"


def test_field_supports_dataclass_and_mapping() -> None:
    assert _field({"role": " hr "}, "role") == "hr"
    assert _field(_runtime("employee").context, "role") == "employee"
    assert _field({}, "missing") == ""


def test_permission_gate() -> None:
    employee = _runtime("employee")
    hr = _runtime("hr")

    assert _require_identity(employee) is None
    assert _require_identity(SimpleNamespace(context=None)) is not None
    assert _require(employee, "create_device_request") is None
    assert json.loads(_require(employee, "review_device_requests"))["error"] == (
        "permission_denied"
    )
    assert _require(hr, "review_device_requests") is None
    assert json.loads(_require(SimpleNamespace(context=None), "x"))["error"] == (
        "permission_denied"
    )


def test_device_requestable_rules() -> None:
    assert _device_is_requestable(_device(), "employee", "DEPT-001") is None
    assert "不开放" in (
        _device_is_requestable(_device(is_requestable=False), "employee", "DEPT-001")
        or ""
    )
    assert "上限为 0" in (
        _device_is_requestable(
            _device(max_quantity_per_request=0), "employee", "DEPT-001"
        )
        or ""
    )
    assert "角色" in (
        _device_is_requestable(_device(eligible_roles=["hr"]), "employee", "DEPT-001")
        or ""
    )
    assert "部门" in (
        _device_is_requestable(
            _device(eligible_department_ids=["DEPT-002"]),
            "employee",
            "DEPT-001",
        )
        or ""
    )
    assert (
        _device_is_requestable(
            _device(eligible_department_ids=["DEPT-001"]),
            "employee",
            "DEPT-001",
        )
        is None
    )


def test_candidate_request_id_is_stable_per_tool_call() -> None:
    runtime = SimpleNamespace(tool_call_id="call-1")
    first = _candidate_request_id(runtime)
    second = _candidate_request_id(runtime)

    assert first == second
    assert first.startswith("REQ-")
    assert _candidate_request_id(SimpleNamespace()).startswith("REQ-")


def test_get_login_user_variants() -> None:
    ok_user = SimpleNamespace(
        user_id="USR-001",
        username="zhang_wei",
        display_name="张伟",
        role="employee",
        department_id="DEPT-001",
        login_enabled=True,
        account_status="active",
    )

    class _Db:
        def __init__(self, value: object | None) -> None:
            self.value = value

        def scalar(self, _statement: object) -> object | None:
            return self.value

    assert get_login_user(_Db(ok_user), " zhang_wei ") is ok_user
    with pytest.raises(ValueError):
        get_login_user(_Db(None), "missing")
    with pytest.raises(PermissionError):
        get_login_user(
            _Db(
                SimpleNamespace(
                    login_enabled=False,
                    account_status="active",
                    role="employee",
                )
            ),
            "zhang_wei",
        )
    with pytest.raises(PermissionError):
        get_login_user(
            _Db(
                SimpleNamespace(
                    login_enabled=True,
                    account_status="active",
                    role="guest",
                )
            ),
            "zhang_wei",
        )


def test_request_data_and_device_data() -> None:
    record = SimpleNamespace(
        request_id="REQ-1",
        status="pending",
        applicant_user_id="USR-001",
        device_id="DEV-1",
        quantity=1,
        reason="reason",
        requested_at=datetime(2026, 1, 1, 0, 0, 0),
        reviewer_user_id=None,
        reviewed_at=None,
        review_comment=None,
    )
    data = _request_data(record, device_name="显示器", applicant_name="张伟")
    assert data["requested_at"] == "2026-01-01T00:00:00Z"
    assert data["reviewed_at"] is None
    assert data["device_name"] == "显示器"

    device = SimpleNamespace(
        device_id="DEV-1",
        name="显示器",
        category="display",
        description="desc",
        eligible_roles=["employee"],
        eligible_department_ids=[],
        max_quantity_per_request=2,
        request_requirements="none",
        is_requestable=True,
    )
    assert _device_data(device)["device_id"] == "DEV-1"


def test_display_name_map_skips_empty_ids() -> None:
    class _Rows:
        def all(self) -> list[tuple[str, str]]:
            return [("USR-001", "张伟")]

    class _Db:
        def execute(self, _statement: object) -> _Rows:
            return _Rows()

    assert _display_name_map(_Db(), ["USR-001", None]) == {"USR-001": "张伟"}
    assert _display_name_map(_Db(), [None]) == {}
