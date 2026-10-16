/**
 * 后端接口的类型化封装 + 错误分型。
 *
 * 契约（Bearer JWT + 资源化的 thread）：
 *
 * | 方法 | 路径 | 说明 |
 * | --- | --- | --- |
 * | POST | `/api/sessions` | **OAuth2 表单**（`username`/`password`）→ `{access_token,token_type}` |
 * | GET | `/api/auth/me` | 服务端认定的身份（前端不得自行推断角色） |
 * | GET | `/api/threads` | 当前用户的会话列表（**裸数组**，按创建时间倒序） |
 * | POST | `/api/threads` | 新建会话 → 201 `{thread_id,created_at}` |
 * | GET | `/api/threads/{id}/messages` | 历史回放 + 未决确认 |
 * | POST | `/api/threads/{id}/chat/stream` | SSE 流式对话 |
 * | POST | `/api/threads/{id}/confirmation` | 处理待确认 |
 *
 * **相对旧契约的三处结构性差异**（改造前这里打的是 `/api/chat/stream` + `session_id`）：
 *
 * 1. 登录只发 Token，**不创建会话** —— 会话改由 `POST /api/threads` 单独创建，
 *    所以"登录成功"和"有一个可聊的 thread"是两件独立的事，前端必须显式建；
 * 2. 除登录外**每个请求都带 `Authorization: Bearer <token>`**；
 *    这也是对话必须走 `fetch` + 手写 SSE 解析（`lib/sse.ts`）而不是 `EventSource`
 *    的原因：`EventSource` 不能自定义请求头，塞不进 Token；
 * 3. **409 有三种含义**，只能靠响应体的 `detail` 区分（服务端没有给错误码）：
 *    - `当前会话正在处理上一条消息` → 重试即可（前端应禁用发送按钮，等上一轮结束）
 *    - `请先处理当前待确认操作` → 要弹确认卡片（数据已经挂在检查点上）
 *    - `当前会话没有待确认的操作` → 卡片已过期（多半是另一个标签页处理过了）
 *    把三者混成一个"409 = 待确认"会让第三种情况永远无法自愈。
 *
 * 前端**只写相对路径** `/api/...`：
 *   - dev：Vite 代理转发到 127.0.0.1:8000（vite.config.ts 的 server.proxy）
 *   - build：同源，FastAPI 自己就是服务方
 * 所以任何地方都不需要硬编码主机，也不需要 CORS。
 */

import { readSSE } from './sse.ts'

/** 登录用户的角色。取值由服务端查表决定，前端不得自行推断。 */
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
 * 待确认载荷。**只有 `action` 是后端保证存在的字段**，
 * 其余字段随 action 变化，所以这里必须留成索引签名，不能写死形状。
 */
export interface Confirmation {
  action: string
  [key: string]: unknown
}

/** `POST /api/threads/{id}/confirmation` 的响应体。 */
export interface AgentReply {
  /** 中断那一轮是 null —— 此时**不应该**渲染助手气泡 */
  answer: string | null
  needs_confirmation: boolean
  /** 可能退化成 `{message: "..."}`，甚至不出现 */
  confirmation: Confirmation | null
  /** **线程累计**轨迹，不是本轮增量 —— 用 lib/trace.ts 切片后再渲染 */
  trace: TraceEntry[]
}

/** `GET /api/auth/me` 的响应体：身份的唯一来源。 */
export interface Identity {
  user_id: string
  username: string
  display_name: string
  role: Role
  department_id: string
}

/** 会话列表项。`created_at` 是 ISO 字符串（naive UTC，后端 `utc_now()`）。 */
export interface ThreadInfo {
  thread_id: string
  created_at: string
}

/** 服务端回放的一条消息。**只有正文，没有 trace** —— trace 不落库。 */
export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

/** `GET /api/threads/{id}/messages` 的响应体。 */
export interface HistoryReply {
  messages: HistoryMessage[]
  /**
   * 检查点上是否挂着一个未决确认。
   * **这是"该不该显示确认卡片"的唯一权威**，比本地存的 pending 可靠：
   * 换标签页、刷新、后端重启之后本地态可能已经骗人了。
   */
  needs_confirmation: boolean
  confirmation: Confirmation | null
}

/** `POST /api/sessions` 的响应体。 */
export interface LoginResult {
  access_token: string
  token_type: string
}

/**
 * 错误分型。
 *
 * 注意 `unauthorized`：后端**只有** token 验不过去才给 401（账号密码错也是 401），
 * 所以前端收到它就回登录页，不要试图猜原因。
 */
export type ApiErrorKind =
  | 'unauthorized' // 401 —— token 缺失/过期/伪造
  | 'thread_missing' // 404 —— 会话不存在或不属于当前用户
  | 'busy' // 409 —— 上一轮还在跑
  | 'pending_confirmation' // 409 —— 有待确认未处理
  | 'no_pending' // 409 —— 没有待确认可处理（卡片过期）
  | 'backend_down' // 503 —— agent 调用失败
  | 'network' // 请求根本没发出去 / 代理挂了
  | 'unknown'

/** 分型的兜底文案；服务端给了 `detail` 时一律以服务端为准。 */
const KIND_MESSAGE: Record<ApiErrorKind, string> = {
  unauthorized: '登录已失效，请重新登录',
  thread_missing: '这个会话不存在（可能已被删除，或不属于当前账号）',
  busy: '上一条还在处理，请稍候',
  pending_confirmation: '还有一条待确认的操作，请先处理它',
  no_pending: '当前没有待确认的操作（可能已在别处处理过）',
  backend_down: '服务暂时不可用，请稍后重试',
  network: '连不上服务，请确认后端已经启动',
  unknown: '请求失败，请查看浏览器控制台',
}

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

/** 409 的三种含义靠服务端文案区分（后端未提供机器可读的错误码）。 */
function classify(status: number, detail: string): ApiErrorKind {
  if (status === 401) return 'unauthorized'
  if (status === 404) return 'thread_missing'
  if (status === 503) return 'backend_down'
  if (status === 409) {
    if (detail.includes('正在处理')) return 'busy'
    if (detail.includes('没有待确认')) return 'no_pending'
    return 'pending_confirmation'
  }
  return 'unknown'
}

/** 尽力从错误响应里取出 `detail`；取不到就返回空串。 */
async function readDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json()
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail?: unknown }).detail
      if (typeof detail === 'string') return detail
    }
  } catch {
    /* 响应体不是 JSON（网关的 HTML 错误页等）—— 用兜底文案 */
  }
  return ''
}

/** 把非 2xx 的响应转成 `ApiError`（优先使用服务端 `detail`）。 */
async function toApiError(res: Response): Promise<ApiError> {
  const detail = await readDetail(res)
  const kind = classify(res.status, detail)
  return new ApiError(kind, res.status, detail !== '' ? detail : KIND_MESSAGE[kind])
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  token?: string
  /** JSON 请求体 */
  body?: unknown
  /** 表单请求体（登录用，OAuth2 要求 `application/x-www-form-urlencoded`） */
  form?: URLSearchParams
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (options.token !== undefined) headers.Authorization = `Bearer ${options.token}`

  let body: string | undefined
  if (options.form !== undefined) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    body = options.form.toString()
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  let res: Response
  try {
    res = await fetch(path, { method: options.method ?? 'GET', headers, body })
  } catch {
    // fetch 只在网络层失败时 reject（后端没起、代理挂了、DNS……）
    throw new ApiError('network', 0, KIND_MESSAGE.network)
  }

  if (!res.ok) throw await toApiError(res)

  try {
    return (await res.json()) as T
  } catch {
    throw new ApiError('unknown', res.status, '服务返回了无法解析的内容')
  }
}

/**
 * `POST /api/sessions` —— 用账号密码换一个 Token。
 *
 * **它不创建会话**：调用方拿到 token 后还要 `fetchMe()` 拿身份、`createThread()` 建会话。
 */
export function login(username: string, password: string): Promise<LoginResult> {
  return request<LoginResult>('/api/sessions', {
    method: 'POST',
    form: new URLSearchParams({ username, password }),
  })
}

/** `GET /api/auth/me` —— token 换身份（刷新页面后恢复登录态靠它）。 */
export function fetchMe(token: string): Promise<Identity> {
  return request<Identity>('/api/auth/me', { token })
}

/** `GET /api/threads` —— 当前用户的会话列表（裸数组，倒序）。 */
export function listThreads(token: string): Promise<ThreadInfo[]> {
  return request<ThreadInfo[]>('/api/threads', { token })
}

/** `POST /api/threads` —— 新建会话。 */
export function createThread(token: string): Promise<ThreadInfo> {
  return request<ThreadInfo>('/api/threads', { method: 'POST', token })
}

/**
 * `GET /api/threads/{id}/messages` —— 回放历史 + 取回未决确认。
 *
 * 有了它，前端**不再需要用 localStorage 假装历史**：服务端存的就是全部事实。
 * 换设备、清缓存、后端重启都不影响。
 */
export function fetchMessages(token: string, threadId: string): Promise<HistoryReply> {
  return request<HistoryReply>(`/api/threads/${encodeURIComponent(threadId)}/messages`, { token })
}

/** agent 级进度事件的载荷（`tool_start` / `tool_end` / `tool_error`）。 */
export interface ToolEvent {
  /** 英文 Agent Tool 名，例如 `ask_knowledge_agent` */
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
 * 之后模型超时或报错只能靠流里的 `error` 事件表达。
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
  /** 需要人工确认。载荷形状由服务端的 `interrupt()` 决定，`action` 一定存在 */
  onConfirmation?: (confirmation: Confirmation) => void
  /**
   * 流末尾的**线程累计**轨迹（后端会发）。
   * 收到就用 `lib/trace.ts` 的游标切片；收不到时调用方要自己兜底
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
 * `POST /api/threads/{id}/chat/stream` —— 发一轮消息并**边收边渲染**。
 *
 * HTTP 层的失败（401/404/409/503/网络）抛 `ApiError`；流建立**之后**的失败只能靠
 * `onStreamError` + 返回 `'error'` 表达 —— 那时响应头已经发出去了，状态码改不了。
 * 调用方两处都要接。
 */
export async function streamChat(
  token: string,
  threadId: string,
  message: string,
  handlers: StreamHandlers,
): Promise<StreamOutcome> {
  let res: Response
  try {
    res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message }),
    })
  } catch {
    throw new ApiError('network', 0, KIND_MESSAGE.network)
  }

  if (!res.ok) throw await toApiError(res)

  if (!res.body) throw new ApiError('unknown', res.status, '服务没有返回事件流')

  // 默认悲观：没等到 `done` 就算失败。服务端在 `error` 之后会关流，
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
        // 载荷就是 `interrupt()` 交出来的业务数据；`action` 是后端保证存在的字段
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
 * `POST /api/threads/{id}/confirmation` —— 处理待确认。
 *
 * `approved` 的语义是「**是否执行 agent 已经决定好的动作**」，**不是**「这条申请批不批」。
 * 所以调用方在 UI 上必须写「确认执行 / 取消本次操作」，
 * 绝不能写成「批准 / 驳回」—— 那会把后端语义讲成谎话。
 */
export function confirm(token: string, threadId: string, approved: boolean): Promise<AgentReply> {
  return request<AgentReply>(`/api/threads/${encodeURIComponent(threadId)}/confirmation`, {
    method: 'POST',
    token,
    body: { approved },
  })
}
