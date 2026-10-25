"""创建当前用户的依赖"""

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select

from personal_assistant.auth import decode_access_token
from personal_assistant.business_tools import RunContext
from personal_assistant.database import SessionLocal
from personal_assistant.models import AgentThread, User
from personal_assistant.multi_agent import UserSession

# 这里只负责Authentication从请求头获取Bearer token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/session")


@dataclass(frozen=True)
class CurrentUser:
    """从token和数据库中恢复出的请求级可信信息"""

    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


def _credentials_exception() -> HTTPException:
    """当token验证失败时抛出的异常"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证登录凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> CurrentUser:
    """验证JWT token并从数据库中恢复出当前用户信息"""

    # 第一步 验证请求头中的Token是否有效且未过期
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError as e:
        raise _credentials_exception() from e

    # 第二步 从数据库中获取用户信息
    # 这里假设我们有一个数据库连接池，可以使用SQLAlchemy等ORM框架
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.user_id == user_id))
        if (
            user is None
            or not user.login_enabled
            or user.account_status != "active"
            or user.username is None
            or user.role not in ["employee", "hr"]
        ):
            raise _credentials_exception()

        # 只有服务端验证之后的字段才能进入后续的 Agent 运行上下文
        return CurrentUser(
            user_id=user_id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            department_id=user.department_id,
        )


"""
身份恢复顺序是：
    ↓
读取 Authorization 请求头
    ↓
验证 JWT 签名与过期时间
    ↓
读取 sub 中的用户编号
    ↓
查询数据库最新账号状态
    ↓
构造 CurrentUser
"""


"""
身份恢复、资源归属和运行时会话构造串成一条嵌套依赖链

Authorization: Bearer <token>
        ↓
get_current_user()
        ↓ 得到可信 CurrentUser
路径中的 thread_id
        ↓
get_owned_runtime_session()
        ↓ 验证 thread_id + current_user.user_id
构造 RunContext 和 UserSession
        ↓
路由函数开始执行
"""

# CurrentUser保存本次请求已经验证的用户身份
# RunContext把可信用户属性传入Supervisor,Tool和Retriver
# UserSession组合RunContext和thread_id，和对应的supervisor


def get_owned_runtime_session(
    request: Request,
    thread_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> UserSession:
    """验证Thread归属、并构造请求时的运行会话"""

    # 同时匹配thread_id和当前用户的user_id，防止水平越权访问
    statement = select(AgentThread).where(
        AgentThread.thread_id == thread_id,
        AgentThread.user_id == current_user.user_id,
    )
    with SessionLocal() as db:
        agent_thread = db.scalar(statement)
        if agent_thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在"
            )
        restored_thread_id = agent_thread.thread_id

    # RunContext 把可信用户属性传入 Supervisor、Tool 和 Retriever；
    # 只使用服务端恢复的用户属性，不接受客户端自报的身份。
    context = RunContext(
        user_id=current_user.user_id,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        department_id=current_user.department_id,
    )
    # UserSession组合RunContext和thread_id，和对应的supervisor
    supervisor = request.app.state.agent.supervisors.get(current_user.role)
    return UserSession(
        context=context,
        thread_id=restored_thread_id,
        supervisor=supervisor,
    )
