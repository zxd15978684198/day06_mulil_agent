"""JWT 与密码校验的单元测试（不连数据库）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest

from personal_assistant import auth


def _user(*, password: str = "correct-password", **overrides: object) -> object:
    data = {
        "user_id": "USR-001",
        "username": "zhang_wei",
        "display_name": "张伟",
        "role": "employee",
        "department_id": "DEPT-001",
        "password_hash": auth.password_hash.hash(password),
        "login_enabled": True,
        "account_status": "active",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class _FakeDb:
    def __init__(self, user: object | None) -> None:
        self._user = user

    def scalar(self, _statement: object) -> object | None:
        return self._user


def test_verify_password_accepts_correct_and_rejects_wrong() -> None:
    hashed = auth.password_hash.hash("secret")

    assert auth.verify_password("secret", hashed) is True
    assert auth.verify_password("wrong", hashed) is False


def test_authenticate_user_success() -> None:
    user = _user()
    assert (
        auth.authenticate_user(_FakeDb(user), " zhang_wei ", "correct-password") is user
    )


def test_authenticate_user_rejects_wrong_password_and_inactive_account() -> None:
    assert (
        auth.authenticate_user(_FakeDb(_user()), "zhang_wei", "correct-password")
        is not None
    )
    assert (
        auth.authenticate_user(
            _FakeDb(_user(password="other")), "zhang_wei", "correct-password"
        )
        is None
    )
    assert (
        auth.authenticate_user(
            _FakeDb(_user(login_enabled=False)),
            "zhang_wei",
            "correct-password",
        )
        is None
    )
    assert (
        auth.authenticate_user(
            _FakeDb(_user(account_status="disabled")),
            "zhang_wei",
            "correct-password",
        )
        is None
    )
    assert auth.authenticate_user(_FakeDb(None), "missing", "whatever") is None


def test_jwt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRATION", "30")

    token = auth.create_access_token("USR-001")

    assert auth.decode_access_token(token) == "USR-001"


def test_jwt_rejects_tampered_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    token = auth.create_access_token("USR-001")

    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_access_token(token + "tampered")


def test_jwt_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    now = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": "USR-001", "iat": now, "exp": now},
        "x" * 40,
        algorithm="HS256",
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        auth.decode_access_token(token)


def test_jwt_settings_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth._jwt_settings()

    monkeypatch.setenv("JWT_SECRET", "short")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth._jwt_settings()

    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    with pytest.raises(ValueError, match="HS256"):
        auth._jwt_settings()

    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("JWT_EXPIRATION", "0")
    with pytest.raises(ValueError, match="JWT_EXPIRATION"):
        auth._jwt_settings()
