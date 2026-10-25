# class RequestModel(BaseModel):
#     """所有请求字符串都想去掉首尾空格"""
#     model_config = ConfigDict(str_strip_whitespace=True)
#
# class LoginRequest(RequestModel):
#     # username对应week15准备好的教学账号，不是密码字段
#     username: str = Field(min_length=1,max_length=50)
#
# class ChatRequest(RequestModel):
#     # 用session_id 找回服务端保存的UserSession
#     session_id: str = Field(min_length=1)
#     # 这里提交本轮消息，不需要重复提交全部历史对话
#     message: str = Field(min_length=1,max_length=2000)
#
# class ConfirmRequest(RequestModel):
#     session_id: str = Field(min_length=1)
#     approved: bool
#
#
# class LoginResponse(BaseModel):
#     session_id: str
#     display_name: str
#     role: str
#
# class AgentReply(BaseModel):
#     # 流程被暂停时没有最终回答，因此允许为None
#     answer: str | None = None
#     # 页面根据判断应该展示，还是展示确认按钮
#     needs_confirmation: bool = False
#     # 保存iterrupt的携带的操作名称，参数和提示信息
#     confirmation: dict[str, Any] | None = None
#     # 每个响应都应创建自己的空列表，避免共享对象
#     trace: list[dict[str, Any]] = Field(default_factory=list)
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    """请求模型统一去掉字符串首尾空格。"""

    model_config = ConfigDict(str_strip_whitespace=True)


class TokenResponse(BaseModel):
    """密码验证成功后返回的 Bearer Token。"""

    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    """允许页面展示的当前用户信息。"""

    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


class ThreadResponse(BaseModel):
    """当前用户可以选择的对话 Thread。"""

    thread_id: str
    created_at: datetime


class HistoryMessage(BaseModel):
    """允许前端展示的一条历史消息。"""

    # 页面只展示用户输入和最终助手回复，不暴露 Tool 等内部消息。
    role: Literal["user", "assistant"]
    content: str


class ThreadHistoryResponse(BaseModel):
    """历史消息，以及可能尚未处理的人工确认。"""

    messages: list[HistoryMessage] = Field(default_factory=list)
    needs_confirmation: bool = False
    confirmation: dict[str, Any] | None = None


class ChatRequest(RequestModel):
    """向路径中的 Thread 发送一轮新消息。"""

    # thread_id 已放在 URL 路径中，请求体只接收本轮消息。
    message: str = Field(min_length=1, max_length=2000)


class ConfirmRequest(RequestModel):
    """恢复路径中 Thread 的人工确认。"""

    # 布尔值只表示本次人工确认结果，不携带用户或 Thread 身份。
    approved: bool


class AgentReply(BaseModel):
    """普通对话和确认接口共用的结构化响应。"""

    answer: str | None = None
    needs_confirmation: bool = False
    confirmation: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
