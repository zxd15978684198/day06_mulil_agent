import asyncio
import json
import os
import threading
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from opentelemetry import trace
from sqlalchemy import select

from personal_assistant.auth import authenticate_user, create_access_token
from personal_assistant.database import SessionLocal, engine
from personal_assistant.dependencies import (
    CurrentUser,
    get_current_user,
    get_owned_runtime_session,
)
from personal_assistant.knowledge_base import (
    INDEX_MANIFEST_PATH,
    ensure_writable_tempdir,
    warm_up_vector_store,
)
from personal_assistant.metrics import (
    dec_active_streams,
    inc_active_streams,
)
from personal_assistant.models import AgentThread
from personal_assistant.multi_agent import (
    MultiAgentApplication,
    UserSession,
    message_text,
    outer_trace,
)
from personal_assistant.paths import STATIC_DIR, checkpoint_path
from personal_assistant.request_context import hash_user_id
from personal_assistant.schemas import (
    AgentReply,
    ChatRequest,
    ConfirmRequest,
    CurrentUserResponse,
    HistoryMessage,
    ThreadHistoryResponse,
    ThreadResponse,
    TokenResponse,
)
from personal_assistant.structured_logging import (
    configure_logging,
    log_event,
    safe_error,
)
from personal_assistant.telemetry import (
    annotate_current_span,
    instrument_fastapi,
    setup_telemetry,
    shutdown_telemetry,
)

load_dotenv()
configure_logging()
STREAM_TIMEOUT_SECONDS = int(os.getenv("STREAM_TIMEOUT_SECONDS", 90))

# 默认 no-op：没有 OTLP 端点且没选 console 时，不创建 Provider、不启动后台线程。
# 必须在 MultiAgentApplication 创建之前初始化，HTTPX/LangChain 客户端才能被插桩。
TELEMETRY_ENABLED = setup_telemetry(engine=engine)

# 注意这里必须是赋值（`=`）而不是裸注解：`X: T` 只往 __annotations__ 里记一条，
# 不会绑定名字，运行时用它会 NameError。类型也不是 SQLAlchemy 的 Session ——
# get_owned_runtime_session 返回的是 multi_agent.UserSession。
RuntimeSessionDep = Annotated[UserSession, Depends(get_owned_runtime_session)]


def _warm_up_vector_store_in_background() -> None:
    """预热知识库索引并把结果打进启动日志。

    失败**不影响服务**：索引没建、临时目录不可写这类问题，真正的检索路径会照原样
    报出可操作的错误（`warm_up_vector_store()` 本身不抛异常）。
    """

    ok, detail = warm_up_vector_store()
    print(f"[预热] 知识库索引{'就绪' if ok else '未就绪'}：{detail}")


def get_session_or_404(request: Request, session_id: str) -> UserSession:
    """取会话；内存缓存里没有时，按 thread_id 从库里的线程索引重建。

    内存字典只是**缓存**：进程重启后它是空的，而 `agent_threads` 与检查点都还在。
    重建失败（没有这条线程登记、或账号已停用）才回 404，让前端重新登录。
    """
    session: UserSession | None = request.app.state.sessions.get(session_id)
    # if session:
    #     return session
    #
    # restored = request.app.state.agent.restore_session(session_id)
    # if restored is None:
    #     raise HTTPException(status_code=404,
    #                         detail="会话不存在请重新登录")
    # request.app.state.sessions[session_id] = restored
    # return restored
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在请重新登录")
    return session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 入口脚本统一把 %TEMP% 指向可写目录：chromadb 要在临时目录里开库，
    # 而库侧刻意不自己改进程全局状态（见 knowledge_base._require_usable_tempdir）。
    # main.py / build_index.py 都调了这一句，Web 入口同样需要。
    ensure_writable_tempdir()

    # 预热只读索引（本次性能优化，实测依据）：`_open_vector_store()` 冷启动 **22.97s**
    # （本地 embedding 权重加载 + Chroma 首次打开），热了之后一次检索只要 22–144ms。
    # 不预热就等于"服务重启后第一个知识问题多等 23 秒" —— 用户感知就是"忽快忽慢"。
    # 放**后台线程**而不是启动期：启动不该被拖慢 23 秒；预热与"用户登录、打字"重叠，
    # 谁先到谁加载，`_open_vector_store()` 里的锁保证只加载一次。
    threading.Thread(
        target=_warm_up_vector_store_in_background,
        name="warm-up-vector-store",
        daemon=True,
    ).start()

    # 在接受前检查索引，今早暴露出"知识库未构建"的准备错误
    if not INDEX_MANIFEST_PATH.exists():
        raise RuntimeError("未构建向量库索引，请先运行:python build_index.py")

    # 共享检查点：一条 SQLite 连接被所有会话共用（课件 §7.2），启动时打开、
    # 退出时由 AsyncExitStack 负责释放 —— 这就是「重启后还有历史」的总开关。
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(checkpoint_path()))
        )

        # 整个应用只创建一套多agent，接口中通过此对象调用agent
        app.state.agent = MultiAgentApplication(checkpointer=checkpointer)

        # session保存当前登录用户，Key是session_id,value是UserSession
        # 它只是缓存；真源是 agent_threads（线程索引）+ 检查点（消息与中断）
        app.state.sessions = {}

        # active_stream 保存正在运行 SSE 的session_id,防止同一会话并发执行
        app.state.active_streams = set()

        # 注：原先的 app.state.pending_confirmations 已删除（计划 §7 `R4`）——
        # 「待确认」只以检查点为准，进程内再存一份必然在重启后与检查点漂移。

        # yield 之前是启动阶段，执行到这里后，FastAPI才开始处理请求
        yield

        # yield之后是关闭阶段，清理当前进程中的临时状态并归还连接
        app.state.sessions.clear()
        app.state.active_streams.clear()
        # 归还 MySQL 连接池（课件 §7.6 的收尾动作）。
        # 注意：database.engine 是同步 create_engine，dispose() 返回 None，
        # 这里**不能** await；旧代码的 `await engine.dispose()` 会在退出时抛
        # TypeError，把后面的 telemetry flush 一起跳过。
        try:
            engine.dispose()
        finally:
            # BatchSpanProcessor / PeriodicExportingMetricReader 有缓冲，
            # 退出前必须 flush，否则最后一批数据丢失。
            shutdown_telemetry()


app = FastAPI(
    title="多Agent员工助手",
    description="使用普通http调用多agent助手",
    version="0.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:12367", "http://localhost:12367"],
    # 不允许跨域请求携带Cookie等身份凭证
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# 必须在 CORS 之后调用：Starlette 里最后 add 的 middleware 在最外层，
# 这样 OTel 才能覆盖被 CORS 拒绝/预检的请求；也不能放进 lifespan。
instrument_fastapi(app)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# 登录接口
# @app.post("/api/sessions",response_model=LoginResponse,tags=["登录"])
# def create_session(payload: LoginRequest,request: Request) -> LoginResponse:
#     print("登录接口",payload.username)
#     try:
#         # restore=True：同一账号重进时复用上次的 thread_id（课件 §8.2）
#         user = request.app.state.agent.start_session(payload.username, restore=True)
#         # 把用户保存到sessions里面，用来后续对话中查找
#         request.app.state.sessions[user.thread_id] = user
#         return LoginResponse(
#             session_id=user.thread_id,
#             display_name=user.context.display_name,
#             role=user.context.role,
#         )
#     except Exception as e:
#         raise HTTPException(status_code=401,
#                             detail="此用户不存在")


@app.post("/api/sessions", response_model=TokenResponse, tags=["Authentication"])
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """验证用户名和密码，只签发Token吗，不创建Thread"""

    with SessionLocal() as db:
        user = authenticate_user(db, form_data.username, form_data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # session关闭前取出主键，Token 只保存整个稳定的用户编号
        user_id = user.user_id
    return TokenResponse(access_token=create_access_token(user_id), token_type="bearer")


CurrentUserDep = Annotated[
    CurrentUser,
    Depends(get_current_user),
]


@app.get(
    "/api/auth/me",
    response_model=CurrentUserResponse,
    tags=["Authentication"],
)
def read_current_user(current_user: CurrentUserDep) -> CurrentUserResponse:
    """返回数据库最新且允许展示的用户信息"""
    return CurrentUserResponse(
        user_id=current_user.user_id,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        department_id=current_user.department_id,
    )


# 查询当前用户的会话列表
@app.get("/api/threads", response_model=list[ThreadResponse], tags=["Threads"])
def list_sessions(current_user: CurrentUserDep) -> list[ThreadResponse]:
    # user_id只能来自已经验证的 CurrentUser，不能由浏览器进行提交
    statement = (
        select(AgentThread)
        .where(AgentThread.user_id == current_user.user_id)
        .order_by(AgentThread.created_at.desc())
    )
    with SessionLocal() as db:
        threads = db.scalars(statement).all()
        return [
            ThreadResponse(thread_id=thread.thread_id, created_at=thread.created_at)
            for thread in threads
        ]


# 创建当前用户的新会话
@app.post(
    "/api/threads",
    response_model=ThreadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Threads"],
)
def create_thread(current_user: CurrentUserDep) -> ThreadResponse:
    # begin()正常结束时会自动提交，出现异常时自动回滚
    with SessionLocal.begin() as db:
        record = AgentThread(thread_id=str(uuid4()), user_id=current_user.user_id)
        db.add(record)
        db.flush()  # 执行INSERT ，但不会自动提交，需要手动调用commit()
        response = ThreadResponse(
            thread_id=record.thread_id, created_at=record.created_at
        )
    return response


"""
db.add(record)
    ↓ 放入待写入状态
db.flush()
    ↓ 执行 INSERT，事务尚未提交，可以读取 created_at
正常离开 SessionLocal.begin()
    ↓ 自动 commit
出现异常
    ↓ 自动 rollback
"""


@app.get(
    "/api/threads/{thread_id}/messages",
    response_model=ThreadHistoryResponse,
    tags=["Threads"],
)
async def list_thread_messages(
    request: Request,
    session: RuntimeSessionDep,
) -> ThreadHistoryResponse:
    """RuntimeSessionDep 已经完成 JWT 验证和 Thread 归属校验"""
    messages, confirmation = await request.app.state.agent.get_thread_history(session)
    return ThreadHistoryResponse(
        messages=[HistoryMessage(**message) for message in messages],
        needs_confirmation=confirmation is not None,
        confirmation=confirmation,
    )


def format_agent_result(
    request: Request,
    session_id: str,
    result: dict[str, Any],
) -> AgentReply:
    # 没有该键时使用空元组，表示本轮没有被interrupt暂停
    interrupts = result.get("__interrupt__", ())
    if interrupts:
        value = interrupts[0].value
        # 多个中断返回字典value本身，单个中断包装成{"message":str(value)}
        confirmation = value if isinstance(value, dict) else {"message": str(value)}
        return AgentReply(
            answer=None,
            needs_confirmation=True,
            confirmation=confirmation,
            trace=outer_trace(result),
        )

    # 只保留”不包含 Tool 调用“的AIMessage，它才是面向用户的回答
    answers = [
        message_text(message)
        for message in result.get("messages", [])
        if isinstance(message, AIMessage) and not message.tool_calls
    ]

    # 一轮运行可能产生多条AIMessage，最后一条才是最终回答
    answer = answers[-1] if answers else "agent 没有返回可展示的回答"

    return AgentReply(
        answer=answer,
        needs_confirmation=False,
        confirmation=None,
        trace=outer_trace(result),
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
    data: dict[str, Any],
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

    payload = json.dumps(data, ensure_ascii=False)
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


def _mark_http_outcome(outcome: str) -> None:
    """在 HTTP 根 Span 上标记本轮结果；agent.turn 可能因取消先记为 disconnected。"""

    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("agent.outcome", outcome)


async def stream_agent_events(
    request: Request,  # 可读取应用共享状态，也可以检查客户端是否已经断开
    session: UserSession,  # 保存当前登录用户的Context、thread_id和Spuervisor
    payload: ChatRequest,  # payload 是FastApi已校验的请求体，包含session_id和message
) -> AsyncIterable[str]:
    """把agent内部事件转换成浏览器可以消化的SSE事件"""

    request_id = request.headers.get("x-request-id") or ""

    # 建立流后立即告诉页面，服务端已开始处理
    yield sse_event("status", {"message": "Agent 已经开始处理"})

    try:
        # timeout 限制整个agent流的最长运行时间，超时后进入 except TimeoutError
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            async for event in request.app.state.agent.stream_chat(
                session,
                payload.message,
                request_id=request_id or None,
            ):
                if await request.is_disconnected():
                    _mark_http_outcome("disconnected")
                    log_event(
                        "stream.disconnected",
                        thread_id=session.thread_id,
                        request_id=request_id,
                        run_id="",
                    )
                    return

                yield sse_event(
                    event["event"],
                    event["data"],
                )
        # 本轮结束状态读**检查点**（计划 §7 `R4`）：进程重启后内存集合是空的，
        # 只有检查点知道这轮是不是停在人工确认上。
        status_value = (
            "waiting_confirmation"
            if await request.app.state.agent.has_pending_confirmation(session)
            else "completed"
        )

        yield sse_event("done", {"status": status_value})

    except TimeoutError:
        # 响应头已经发送，此时通过SSE error报告超时。
        # 超时是把这一轮的协程取消掉：检查点里可能留下 `next`（未执行完的节点），
        # 但**不会**留下 interrupt 记录 —— 于是 `pending_confirmation_of()` 判定
        # 「没有待确认」，`GET /messages` 与这里口径一致，客户端可以直接重试；
        # 重试会从检查点接着跑，需要人工确认时再正常抛出 confirmation 事件。
        _mark_http_outcome("timeout")
        log_event(
            "stream.timeout",
            thread_id=session.thread_id,
            request_id=request_id,
            run_id="",
            outcome="timeout",
            timeout_seconds=STREAM_TIMEOUT_SECONDS,
        )
        yield sse_event(
            "error",
            {"message": "本轮处理超时已被中断，会话状态已保留，请直接重试"},
        )
    except asyncio.CancelledError:
        # CancelledError 表示协程被取消；继续抛出，让ASGI SERVER完成清理
        raise
    except Exception as exc:
        # 只返回可公开都错误，不暴露模型地址、密钥或堆栈
        _mark_http_outcome("failed")
        log_event(
            "stream.failed",
            thread_id=session.thread_id,
            request_id=request_id,
            run_id="",
            outcome="failed",
            **safe_error(exc),
        )
        yield sse_event("error", {"message": "agent 调用失败，请稍后重试"})
        raise
    finally:
        # 每轮结束清空活跃集合当中的 session_id。
        # discard() 在元素不存在时也不会报错，适合在 finally 中安全清理。
        request.app.state.active_streams.discard(session.thread_id)
        dec_active_streams()


@app.post(
    "/api/threads/{thread_id}/chat/stream",
    response_class=StreamingResponse,
    tags=["对话"],
)
async def stream_chat(
    payload: ChatRequest,  # payload 是FastApi已校验的请求体，包含session_id和message
    request: Request,
    session: RuntimeSessionDep,
) -> StreamingResponse:
    """只在已认证用户拥有的Thread中云殉国Agent"""
    # HTTP 根 Span 在依赖注入前已创建；这里补 Langfuse 会话/用户属性。
    annotate_current_span(
        thread_id=session.thread_id,
        role=session.context.role,
        user_id_hash=hash_user_id(session.context.user_id),
    )

    active_streams: set[str] = request.app.state.active_streams

    # 进程中避免同一个Thread同时执行两次，造成状态写入竞争
    if session.thread_id in active_streams:
        raise HTTPException(status_code=409, detail="当前会话正在处理上一条消息")
    active_streams.add(session.thread_id)
    inc_active_streams()
    try:
        # 同一会话等待确认时，不能继续提交新的聊天任务（判断来自检查点，不是内存集合）
        if await request.app.state.agent.has_pending_confirmation(session):
            raise HTTPException(status_code=409, detail="请先处理当前待确认操作")
    except BaseException:
        # 必须捕获 BaseException：asyncio.CancelledError 继承它而非 Exception，
        # 客户端在 has_pending_confirmation 等待期间断开时也要归还名额，
        # 否则该 thread_id 会永久滞留在 active_streams，之后每次请求都被 409 挡掉。
        active_streams.discard(session.thread_id)
        dec_active_streams()
        raise

    return StreamingResponse(
        stream_agent_events(request, session, payload),
        # 浏览器根据响应类别识别SSE事件流
        media_type="text/event-stream",
        # 要求客户端和中间缓存不要复用旧的事件流响应
        headers={"Cache-Control": "no-cache"},
    )


# 用户确认接口
@app.post(
    "/api/threads/{thread_id}/confirmation", response_model=AgentReply, tags=["对话"]
)
async def confirmation_action(
    payload: ConfirmRequest, request: Request, session: RuntimeSessionDep
) -> AgentReply:
    # 检查会话是否在活跃集合中，防止同一Thread同时执行两次
    annotate_current_span(
        thread_id=session.thread_id,
        role=session.context.role,
        user_id_hash=hash_user_id(session.context.user_id),
    )

    active_streams: set[str] = request.app.state.active_streams

    if session.thread_id in active_streams:
        raise HTTPException(status_code=409, detail="当前会话正在处理上一条消息")

    active_streams.add(session.thread_id)
    inc_active_streams()
    try:
        if not await request.app.state.agent.has_pending_confirmation(session):
            raise HTTPException(status_code=409, detail="当前会话没有待确认的操作")
        result = await request.app.state.agent.resume(
            session,
            approved=payload.approved,
            request_id=request.headers.get("x-request-id"),
        )
        return format_agent_result(request, session.thread_id, result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail="agent 调用失败，请稍后重试") from e
    finally:
        active_streams.discard(session.thread_id)
        dec_active_streams()
