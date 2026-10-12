/**
 * 三个接口的类型化封装 + 错误四态映射。
 *
 * 契约依据：`frontend/CONTRACTS.md` 的 C1–C6 与 K1–K9。
 * 关键决定：前端**只写相对路径** `/api/...`。
 *   - dev：Vite 代理转发到 127.0.0.1:8000（vite.config.ts 的 server.proxy）
 *   - build：同源，FastAPI 自己就是服务方
 * 所以任何地方都不需要硬编码主机，也不需要 CORS。
 *
 * **对话走 `POST /api/chat/stream`（SSE），不走 `POST /api/chat`** —— 后者在
 * `agent_api.py` 里被整段注释掉了，打过去是 404。流式版同时给"逐字正文"和
 * "agent 级进度事件"，打字机效果就来自前者。
 */

import { readSSE } from './sse'

/** 登录用户的角色。取值由服务端查表决定，前端不得自行推断（契约 R4）。 */
export type Role = 'employee' | 'hr'

/** `trace` 里的一条轨迹。实测只会出现 `agent_tool_calls` 与 `agent_tool_result` 两种。 */
export interface TraceEntry {
  type: string
  name?: string
  calls?: { name: string; args?: unknown }[]
  /** `agent_tool_result` 专用：**一个 JSON 字符串**，不是对象（实测） */
  content?: string
}

/**
 * 待确认载荷。**只有 `action` 是后端保证存在的字段**（契约 C2），
 * 其余字段随 action 变化，所以这里必须留成索引签名，不能写死形状。
 */
export interface Confirmation {
  action: string
  [key: string]: unknown
}

/** `POST /api/chat` 与 `POST /api/confirmation` 的响应体。 */
export interface AgentReply {
  /** 中断那一轮是 null —— 此时**不应该**渲染助手气泡（K8） */
  answer: string | null
  needs_confirmation: boolean
  /** 可能退化成 `{message: "..."}`，甚至不出现（K7） */
  confirmation: Confirmation | null
  /** **线程累计**轨迹，不是本轮增量（C1）—— 用 lib/trace.ts 切片后再渲染 */
  trace: TraceEntry[]
}

export interface LoginResult {
  session_id: string
  display_name: string
  role: Role
}

/**
 * 错误四态 + 网络错误。
 * 映射依据：C3（409）、C4（404）、以及 `agent_api.py` 的 401/503。
 */
export type ApiErrorKind =
  | 'user_not_found' // 401
  | 'session_expired' // 404 —— 后端重启后旧 session_id 变死键（K4）
  | 'pending_confirmation' // 409 —— 必须先处理待确认（K6）
  | 'backend_down' // 503
  | 'network' // 请求根本没发出去 / 代理挂了
  | 'unknown'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number

  constructor(kind: ApiErrorKind, status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

/**
 * 面向用户的文案。
 *
 * 注意 401 的措辞：后端 `create_session` 目前把**一切**异常都映射成
 * `401 此用户不存在`（见 `agent_api.py:96-98`，已在 CONTRACTS.md 记为已知限制），
 * 所以网关故障时也会给 401。文案故意写成中性的，"不可登录"而不是"账号不存在"。
 */
const KIND_MESSAGE: Record<ApiErrorKind, string> = {
  user_not_found: '登录失败：账号不可用，或服务暂时异常',
  session_expired: '会话已失效，请重新登录',
  pending_confirmation: '当前会话还有一条待确认的操作，请先处理它',
  backend_down: '服务暂时不可用，请稍后重试',
  network: '连不上服务，请确认后端已经启动',
  unknown: '请求失败，请查看浏览器控制台',
}

function statusToKind(status: number): ApiErrorKind {
  if (status === 401) return 'user_not_found'
  if (status === 404) return 'session_expired'
  if (status === 409) return 'pending_confirmation'
  if (status === 503) return 'backend_down'
  return 'unknown'
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    // fetch 只在网络层失败时 reject（后端没起、代理挂了、DNS……）
    throw new ApiError('network', 0, KIND_MESSAGE.network)
  }

  if (!res.ok) {
    const kind = statusToKind(res.status)
    throw new ApiError(kind, res.status, KIND_MESSAGE[kind])
  }

  try {
    return (await res.json()) as T
  } catch {
    throw new ApiError('unknown', res.status, '服务返回了无法解析的内容')
  }
}

/** `POST /api/sessions` —— 用用户名换一个会话。 */
export function login(username: string): Promise<LoginResult> {
  return postJson<LoginResult>('/api/sessions', { username })
}

/** agent 级进度事件的载荷（`tool_start` / `tool_end`）。 */
export interface ToolEvent {
  /** 英文 Agent Tool 名，例如 `knowledge_agent` */
  name: string
  /** 中文展示名，例如「知识 Agent」。后端给什么就显示什么，前端不自己映射 */
  label: string
}

/** 流的正常收尾状态：`waiting_confirmation` 表示紧接着要弹确认卡片。 */
export type StreamStatus = 'completed' | 'waiting_confirmation'

/**
 * 流的最终结局。
 *
 * `error` 这一态是流式接口**独有**的：HTTP 状态码在响应头发出时就定死了，
 * 之后模型超时或报错只能靠流里的 `error` 事件表达（见 `agent_api.py` 的
 * `except TimeoutError` / `except Exception`）。
 */
export type StreamOutcome = StreamStatus | 'error'

/** 流式回调。全部可选；不给就是不关心那个事件。 */
export interface StreamHandlers {
  /** 建立流后服务端立刻发的一条（目前内容固定是「Agent 已经开始处理」） */
  onStatus?: (message: string) => void
  /** 逐 token 的正文增量 —— 打字机的原料 */
  onDelta?: (text: string) => void
  onToolStart?: (info: ToolEvent) => void
  onToolEnd?: (info: ToolEvent) => void
  onToolError?: (info: ToolEvent & { message: string }) => void
  /** 需要人工确认。载荷形状与旧 `/api/chat` 的 `confirmation` 字段一致（契约 C2） */
  onConfirmation?: (confirmation: Confirmation) => void
  /**
   * 流末尾的**线程累计**轨迹。**可选** —— 取决于后端是否发 `trace` 事件。
   * 收到就按老规矩用 `lib/trace.ts` 的游标切片；收不到时调用方要自己兜底
   * （`ChatView` 用流里的 agent 级事件拼一个简版轨迹）。
   */
  onTrace?: (trace: TraceEntry[]) => void
  onDone?: (status: StreamStatus) => void
  /** 流中途服务端自报的错误。**HTTP 层错误不走这里**，那是 reject。 */
  onStreamError?: (message: string) => void
}

/** 从 `data:` 文本里取 JSON；解析失败返回空对象，**绝不因此白屏**。 */
function parseFrameData(raw: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(raw)
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>
    }
  } catch {
    /* 落到空对象 */
  }
  return {}
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/**
 * `POST /api/chat/stream` —— 发一轮消息并**边收边渲染**。
 *
 * HTTP 层的失败（401/404/409/503/网络）照旧抛 `ApiError`，四态语义与 `confirm()` 一致；
 * 流建立**之后**的失败只能靠 `onStreamError` + 返回 `'error'` 表达 —— 那时响应头
 * 已经发出去了，状态码改不了。调用方两处都要接。
 */
export async function streamChat(
  sessionId: string,
  message: string,
  handlers: StreamHandlers,
): Promise<StreamOutcome> {
  let res: Response
  try {
    res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ session_id: sessionId, message }),
    })
  } catch {
    throw new ApiError('network', 0, KIND_MESSAGE.network)
  }

  if (!res.ok) {
    const kind = statusToKind(res.status)
    // 后端 409/404/401/503 都带 `detail`，比前端写死的中文更准；解析不出来再用默认文案
    let detail = KIND_MESSAGE[kind]
    try {
      const body = (await res.json()) as { detail?: unknown }
      const fromServer = asString(body?.detail)
      if (fromServer !== '') detail = fromServer
    } catch {
      /* 保留默认文案 */
    }
    throw new ApiError(kind, res.status, detail)
  }

  if (!res.body) throw new ApiError('unknown', res.status, '服务没有返回事件流')

  // 默认悲观：没等到 `done` 就算失败。服务端在 `error` 之后会 `raise`，连接随即关闭，
  // 所以这个默认值正好盖住"流被异常掐断、连 error 事件都没发出来"的情况。
  let outcome: StreamOutcome = 'error'

  await readSSE(res.body, (frame) => {
    const data = parseFrameData(frame.data)

    switch (frame.event) {
      case 'status':
        handlers.onStatus?.(asString(data.message))
        break
      case 'text_delta':
        handlers.onDelta?.(asString(data.text))
        break
      case 'tool_start':
        handlers.onToolStart?.({ name: asString(data.name), label: asString(data.label) })
        break
      case 'tool_end':
        handlers.onToolEnd?.({ name: asString(data.name), label: asString(data.label) })
        break
      case 'tool_error':
        handlers.onToolError?.({
          name: asString(data.name),
          label: asString(data.label),
          message: asString(data.message),
        })
        break
      case 'confirmation':
        // 载荷就是 `interrupt()` 交出来的业务数据；`action` 是后端保证存在的字段（C2）
        handlers.onConfirmation?.({ ...data, action: asString(data.action) } as Confirmation)
        break
      case 'trace':
        if (Array.isArray(data.trace)) handlers.onTrace?.(data.trace as TraceEntry[])
        break
      case 'done': {
        const status: StreamStatus =
          data.status === 'waiting_confirmation' ? 'waiting_confirmation' : 'completed'
        outcome = status
        handlers.onDone?.(status)
        break
      }
      case 'error':
        outcome = 'error'
        handlers.onStreamError?.(asString(data.message))
        break
      default:
        // 未知事件忽略：后端以后新增事件不该让老前端白屏
        break
    }
  })

  return outcome
}

/**
 * `POST /api/confirmation` —— 处理待确认。
 *
 * `approved` 的语义是「**是否执行 agent 已经决定好的动作**」，**不是**「这条申请批不批」（C5）。
 * 所以这个函数的调用方在 UI 上必须写「确认执行 / 取消本次操作」，
 * 绝不能写成「批准 / 驳回」—— 那会把后端语义讲成谎话。
 */
export function confirm(sessionId: string, approved: boolean): Promise<AgentReply> {
  return postJson<AgentReply>('/api/confirmation', {
    session_id: sessionId,
    approved,
  })
}
