from pydantic import BaseModel, ConfigDict, Field
from typing import Any

class RequestModel(BaseModel):
    """所有请求字符串都想去掉首尾空格"""
    model_config = ConfigDict(str_strip_whitespace=True)

class LoginRequest(RequestModel):
    # username对应week15准备好的教学账号，不是密码字段
    username: str = Field(min_length=1,max_length=50)

class ChatRequest(RequestModel):
    # 用session_id 找回服务端保存的UserSession
    session_id: str = Field(min_length=1)
    # 这里提交本轮消息，不需要重复提交全部历史对话
    message: str = Field(min_length=1,max_length=2000)

class ConfirmRequest(RequestModel):
    session_id: str = Field(min_length=1)
    approved: bool


class LoginResponse(BaseModel):
    session_id: str
    display_name: str
    role: str

class AgentReply(BaseModel):
    # 流程被暂停时没有最终回答，因此允许为None
    answer: str | None = None
    # 页面根据判断应该展示，还是展示确认按钮
    needs_confirmation: bool = False
    # 保存iterrupt的携带的操作名称，参数和提示信息
    confirmation: dict[str, Any] | None = None
    # 每个响应都应创建自己的空列表，避免共享对象
    trace: list[dict[str, Any]] = Field(default_factory=list)

