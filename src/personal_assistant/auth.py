import os
from datetime import timedelta, datetime, UTC

from dotenv import load_dotenv

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_assistant.models import User
from personal_assistant.paths import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env", override=False)

password_hash = PasswordHash.recommended()
# 用户名不存在时仍执行一次摘要验证，降低账号枚举的时间差异。
DUMMY_HASH = password_hash.hash("day06-dummy-password")

def verify_password(plain_password: str, stored_hash: str) -> bool:
    """验证明文密码是否符合数据库摘要"""
    return password_hash.verify(plain_password, stored_hash)

def authenticate_user(
    db: Session,
    username: str,
    password: str
) -> User | None:
    """验证账号状态和密码，失败时统一返回None"""

    # 先按照用户名查找账号，再统一判断密码、状态和角色是否登录
    user = db.scalar(
        select(User)
        .where(User.username == username.strip())
    )
    if user is None or user.password_hash is None:
        verify_password(password, DUMMY_HASH)
        return None

    password_verified = verify_password(password, user.password_hash)
    if (
        not password_verified or
        not user.login_enabled or
        user.account_status != "active"
        or user.role not in {"employee","hr"}
    ):
        return None
    return user

def _jwt_settings() -> tuple[str, str, int]:
    """读取并检查jwt配置"""
    jwt_secret = os.getenv("JWT_SECRET")
    if not jwt_secret or jwt_secret.startswith("<") or len(jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET 必须设置为至少32字节的随机值")

    jwt_algorithm = (os.getenv("JWT_ALGORITHM") or "HS256").strip()
    if jwt_algorithm != "HS256":
        raise ValueError("JWT_ALGORITHM 必须设置为 HS256")

    jwt_expiration_minutes = int(os.getenv("JWT_EXPIRATION", 30))
    if jwt_expiration_minutes < 1:
        raise ValueError("JWT_EXPIRATION 必须设置为至少1秒")

    return jwt_secret, jwt_algorithm, jwt_expiration_minutes


def create_access_token(
    user_id: str
) -> str:
    """把稳定用户编号写入sub，并签发短期Assessor令牌"""
    secret, algorithm, expiration_minutes = _jwt_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=expiration_minutes) # 30秒
    }
    return jwt.encode(payload, secret, algorithm=algorithm)

def decode_access_token(token: str) -> str:
    """解码Assessor令牌"""
    secret, algorithm, expiration_minutes = _jwt_settings()
    payload = jwt.decode(token,
                         secret,
                         algorithms=[algorithm],
                         options={"require": ["sub", "exp"]}
                         )
    user_id = payload["sub"]
    if not isinstance(user_id, str) or not user_id:
        raise jwt.InvalidTokenError("Invalid token")
    return user_id




