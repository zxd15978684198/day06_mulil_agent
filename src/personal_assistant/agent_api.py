import asyncio
import json
import os
from collections.abc import AsyncGenerator, AsyncIterable
from contextlib import asynccontextmanager
from typing import Any
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request, status, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from langchain_core.messages import AIMessage
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from personal_assistant.knowledge_base import (
    INDEX_MANIFEST_PATH,
    ensure_writable_tempdir,
)

from personal_assistant.multi_agent import (
    MultiAgentApplication,
    UserSession,
    message_text,
    outer_trace
)
from personal_assistant.paths import STATIC_DIR

from personal_assistant.schemas import (
    LoginResponse,
    LoginRequest,
    AgentReply,
    ChatRequest,
    ConfirmRequest
)

load_dotenv()
STREAM_TIMEOUT_SECONDS = int(os.getenv("STREAM_TIMEOUT_SECONDS", 90))


def get_session_or_404(request: Request,session_id) -> UserSession:
    session = request.app.state.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404,
                            detail="会话不存在请重新登录")
    return session

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 入口脚本统一把 %TEMP% 指向可写目录：chromadb 要在临时目录里开库，
    # 而库侧刻意不自己改进程全局状态（见 knowledge_base._require_usable_tempdir）。
    # main.py / build_index.py 都调了这一句，Web 入口同样需要。
    ensure_writable_tempdir()

    # 在接受前检查索引，今早暴露出"知识库未构建"的准备错误
    if not INDEX_MANIFEST_PATH.exists():
        raise RuntimeError('未构建向量库索引，请先运行:python build_index.py')

    # 整个应用只创建一套多agent，接口中通过此对象调用agent
    app.state.agent = MultiAgentApplication()

    # session保存当前登录用户，Key是session_id,value是UserSession
    app.state.sessions = {}

    # 保存等待用户确认的session_id
    app.state.pending_confirmations = set()

    # active_stream 保存正在运行 SSE 的session_id,防止同一会话并发执行
    app.state.active_streams = set()

    # yield 之前是启动阶段，执行到这里后，FastAPI才开始处理请求
    yield

    # yield之后是关闭阶段，清理当前进程中的临时状态
    app.state.sessions.clear()
    app.state.pending_confirmations.clear()
    app.state.active_streams.clear()

app = FastAPI(
    title="多Agent员工助手",
    description="使用普通http调用多agent助手",
    version="0.0.1",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:12367",
                   "http://localhost:12367"],
    # 不允许跨域请求携带Cookie等身份凭证
    allow_credentials=False,
    allow_methods=["GET","POST"],
    allow_headers=["Content-Type"],
)

app.mount("/static",
          StaticFiles(directory=STATIC_DIR),
          name="static")

@app.get("/",include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

# 登录接口
@app.post("/api/sessions",response_model=LoginResponse,tags=["登录"])
def create_session(payload: LoginRequest,request: Request) -> LoginResponse:
    print("登录接口",payload.username)
    try:
        user = request.app.state.agent.start_session(payload.username)
        # 把用户保存到sessions里面，用来后续对话中查找
        request.app.state.sessions[user.thread_id] = user
        return LoginResponse(
            session_id=user.thread_id,
            display_name=user.context.display_name,
            role=user.context.role,
        )
    except Exception as e:
        raise HTTPException(status_code=401,
                            detail="此用户不存在")


def format_agent_result(
        request: Request,
        session_id: str,
        result: dict[str, Any],
) -> AgentReply:
    # 没有该键时使用空元组，表示本轮没有被interrupt暂停
    interrupts=result.get("__interrupt__",())
    if interrupts:
        request.app.state.pending_confirmations.add(session_id)
        value = interrupts[0].value
        # 多个中断返回字典value本身，单个中断包装成{"message":str(value)}
        confirmation = value if isinstance(value, dict) else {"message": str(value)}
        return AgentReply(
            answer=None,
            needs_confirmation=True,
            confirmation=confirmation,
            trace=outer_trace(result)
        )

    request.app.state.pending_confirmations.discard(session_id)

    # 只保留”不包含 Tool 调用“的AIMessage，它才是面向用户的回答
    answers = [message_text(message) for message in result.get("messages",[]) if isinstance(message, AIMessage) and not message.tool_calls]

    # 一轮运行可能产生多条AIMessage，最后一条才是最终回答
    answer = answers[-1] if answers else "agent 没有返回可展示的回答"

    return AgentReply(
        answer=answer,
        needs_confirmation=False,
        confirmation=None,
        trace=outer_trace(result)
    )

# 对话接口
# @app.post("/api/chat",response_model=AgentReply,tags=["对话"])
# def chat_agent(payload: ChatRequest,request: Request) -> AgentReply:
#     print(payload.session_id)
#     session = get_session_or_404(request,payload.session_id)
#
#     if payload.session_id in request.app.state.pending_confirmations:
#         raise HTTPException(status_code=409,detail="请先处理当前确认操作")
#
#     try:
#         result = request.app.state.agent.chat(
#             session,
#             payload.message,
#         )
#         return format_agent_result(request,payload.session_id,result)
#     except Exception as e:
#         raise HTTPException(
#             status_code=503,
#             detail="agent 调用失败，稍后尝试"
#         ) from e

def sse_event(
        event: str,
        data: dict,
        *,
        event_id: str | None = None,
        retry_ms: int | None = None,
) -> str:
    """把事件名称和字典转换成 SSE 文本块"""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id:{event_id}")

    lines.append(f"event:{event}")

    if retry_ms is not None:
        lines.append(f"retry:{retry_ms}")

    payload = json.dumps(data,ensure_ascii=False)
    lines.append(f"data:{payload}")
    return "\n".join(lines) + "\n\n"

# async def generate_report_events() -> AsyncGenerator[str]:
#     """依次生成报告处理过程中的三条SSE事件"""
#
#     yield sse_event(
#         "status",
#         {"message":"开始生成报告"},
#         event_id="1",
#         retry_ms=3000,
#     )
#
#     yield sse_event(
#             "progress",
#             {"percent":5,"message":"正在整理数据"},
#             event_id="2",
#             retry_ms=3000,
#         )
#
#     await asyncio.sleep(1)
#
#     yield sse_event(
#             "done",
#             {"status":"completed","message":"报告生成完毕"},
#             event_id="3",
#             retry_ms=3000,
#         )

async def stream_agent_events(
        request: Request,   # 可读取应用共享状态，也可以检查客户端是否已经断开
        session: UserSession,    # 保存当前登录用户的Context、thread_id和Spuervisor
        payload: ChatRequest    # payload 是FastApi已校验的请求体，包含session_id和message
) -> AsyncIterable[str]:
    """把agent内部事件转换成浏览器可以消化的SSE事件"""

    # 建立流后立即告诉页面，服务端已开始处理
    yield sse_event("status",{"message":"Agent 已经开始处理"})

    try:
        # timeout 限制整个agent流的最长运行时间，超时后进入 except TimeoutError
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            async for event in request.app.state.agent.stream_chat(
                session,
                payload.message
            ):
                if await request.is_disconnected():
                    return

                # 收到confirmation之后，把session_id加入待确认集合
                if event["event"] == "confirmation":
                    request.app.state.pending_confirmations.add(payload.session_id)

                yield sse_event(event["event"],event["data"],)
        # 根据session_id是否在确认集合当中，确认本轮结束状态
        status_value = (
            "waiting_confirmation"
            if payload.session_id in request.app.state.pending_confirmations
            else "completed"
        )

        yield sse_event("done",{"status":status_value})

    except TimeoutError:
        # 响应头已经发送，此时通过SSE error报告超时
        yield sse_event("error",
                        {"message":"agent 处理超时，请稍后重试"},
                        )
    except asyncio.CancelledError:
        # CancelledError 表示协程被取消；继续抛出，让ASGI SERVER完成清理
        raise
    except Exception as e:
        # 只返回可公开都错误，不暴露模型地址、密钥或堆栈
        yield sse_event("error",
                        {"message":"agent 调用失败，请稍后重试"})
        raise
    finally:
        # 每轮结束清空活跃集合当中的session_id,discard() 在元素不存在时也不会报错，适合在 finally 中安全清理。
        request.app.state.active_streams.discard(payload.session_id)


@app.post("/api/chat/stream")
async def stream_chat(
        payload: ChatRequest,
        request: Request,
) -> StreamingResponse:
    """校验请求后建立SSE响应，持续发送agent事件"""
    session = get_session_or_404(request,payload.session_id)

    # 同一会话等待确认时，不能继续提交新的聊天任务
    if payload.session_id in request.app.state.pending_confirmations:
        raise HTTPException(
            status_code=409,
            detail="请先处理当前待确认操作"
        )

    # active_streams中存在编号时，说明上一条SSE请求还在运行
    if payload.session_id in request.app.state.active_streams:
        raise HTTPException(
            status_code=409,
            detail="当前会话正在处理上一条消息"
        )

    # 在返回StreamingResponse前先占用运行标记，防止并发请求同时进入
    request.app.state.active_streams.add(payload.session_id)

    return StreamingResponse(
        stream_agent_events(request,session,payload),
        # 浏览器根据响应类别识别SSE事件流
        media_type="text/event-stream",
        # 要求客户端和中间缓存不要复用旧的事件流响应
        headers={"Cache-Control": "no-cache"},
    )

# 用户确认接口
@app.post("/api/confirmation",response_model=AgentReply,tags=["对话"])
async def confirmation_action(payload: ConfirmRequest,request: Request) -> AgentReply:
    session = get_session_or_404(request,payload.session_id)

    if payload.session_id not in request.app.state.pending_confirmations:
        raise HTTPException(status_code=409,detail="当前会话没有待确认的操作")

    try:
        result = request.app.state.agent.resume(
            session,
            approved = payload.approved,
        )
        return format_agent_result(request,payload.session_id,result)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail="agent 调用失败，请稍后重试"
        ) from e
