import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import {
  ApiError,
  confirm,
  createThread,
  fetchMessages,
  listThreads,
  streamChat,
  type Confirmation,
  type HistoryReply,
  type ThreadInfo,
  type TraceEntry,
} from '../lib/api'
import {
  clearHistory,
  loadHistory,
  loadTraceCursor,
  newMessageId,
  saveHistory,
  saveTraceCursor,
  type ChatMessage,
} from '../lib/history'
import { SIDEBAR_SHORTCUT_HINT, useSidebarHidden, useSidebarShortcut } from '../lib/layout'
import type { StoredSession } from '../lib/session'
import { sliceNewTrace } from '../lib/trace'
import { createTypewriter, type Typewriter } from '../lib/typewriter'
import { cn } from '../lib/utils'
import ConfirmationCard from './ConfirmationCard'
import IdentityCard from './IdentityCard'
import LiveTraceRail, { type LiveStep } from './LiveTraceRail'
import MessageBubble from './MessageBubble'
import SessionPanel from './SessionPanel'
import ThemeSwitcher from './ThemeSwitcher'

interface ChatViewProps {
  session: StoredSession
  /** 当前 `threadId` 变了要写回上层（上层负责落盘） */
  onSessionChange: (next: StoredSession) => void
  onSignOut: () => void
  onSessionExpired: () => void
}

/**
 * 把回放接口的响应转成界面消息。
 * 它**不带轨迹**（trace 只活在检查点里），所以拿不到本地缓存时右栏就是空的。
 */
function mapServerMessages(reply: HistoryReply): ChatMessage[] {
  return reply.messages.map((message) => ({
    id: newMessageId(),
    role: message.role,
    text: message.content,
  }))
}

/**
 * 对话页布局 + 三个数据源的交汇点。
 *
 * ```
 * ┌──────────────────────────────────────────────┐
 * │ 顶栏：身份芯片（悬停→状态卡片） · 主题 · 退出    │
 * ├──────────┬────────────────────┬──────────────┤
 * │ 左：会话  │  消息流（768px）    │ 右：本轮轨迹  │  ← 三栏只占这一行
 * │ 列表卡片  │                    │              │
 * ├──────────┴────────────────────┴──────────────┤
 * │ 输入框（整宽底栏）                             │  ← 侧栏止于其上方
 * └──────────────────────────────────────────────┘
 * ```
 *
 * **三个事实来源，职责必须分清**（这是本次改造的核心）：
 *
 * | 数据 | 权威来源 | 本地缓存的作用 |
 * | --- | --- | --- |
 * | 消息正文、未决确认 | `GET /api/threads/{id}/messages` | 只在条数一致时顶替（它带轨迹） |
 * | 会话列表 | `GET /api/threads` | 无（一次性请求） |
 * | `trace` 轨迹 | **只有本地**（服务端不落库） | 唯一的来源 |
 *
 * 所以刷新后的正确行为是：正文和确认卡片来自服务端，右栏的轨迹来自本地。
 * 换了浏览器就只剩正文 —— 这是诚实的降级，而不是假装有轨迹。
 */
export default function ChatView({
  session,
  onSessionChange,
  onSignOut,
  onSessionExpired,
}: ChatViewProps) {
  const { token, user, threadId } = session

  const [threads, setThreads] = useState<ThreadInfo[]>([])
  const [threadsLoading, setThreadsLoading] = useState(true)
  // 惰性初始化：先拿本地缓存垫一下，紧接着的回放请求会用服务端结果覆盖它
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    threadId === null ? [] : loadHistory(threadId),
  )
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** 正在被流式填充的那条助手消息 id；null = 当前没有流 */
  const [streamingId, setStreamingId] = useState<string | null>(null)
  /** 流式期间攒的 agent 级步骤（右栏中途唯一的信息源） */
  const [liveSteps, setLiveSteps] = useState<LiveStep[]>([])
  /**
   * 未决确认。**不再从 localStorage 恢复**，只由两处写入：
   *   - `GET /messages` 的 `needs_confirmation` + `confirmation`（权威）
   *   - 流里的 `confirmation` 事件（刚刚中断的这一轮）
   */
  const [pending, setPending] = useState<Confirmation | null>(null)

  const bottomRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  /** 该会话已经渲染过的累计轨迹条数；按 thread 持久化，切换会话不会串 */
  const cursorRef = useRef<number>(threadId === null ? 0 : loadTraceCursor(threadId))
  /**
   * 刚由前端创建的 thread：它的回放一定是空的，而且此时可能已经有流在跑，
   * 让那个 effect 去 `setMessages([])` 会把乐观插入的消息清掉。
   */
  const skipLoadRef = useRef<string | null>(null)
  /**
   * 打字机实例。放 ref 不放 state：它每帧都会回调一次，进 state 会让整棵树每帧重渲染。
   * 卸载时 dispose，免得 rAF 在组件没了之后还在跑。
   */
  const typewriterRef = useRef<Typewriter | null>(null)
  useEffect(() => () => typewriterRef.current?.dispose(), [])

  const locked = pending !== null

  // 左右两侧**各自独立**，各自持久化；Ctrl/⌘ + B 只切左栏（编辑器的既定语义）
  const [leftHidden, toggleLeft] = useSidebarHidden('left')
  const [rightHidden, toggleRight] = useSidebarHidden('right')
  useSidebarShortcut()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, pending])

  /** 右栏要的是"最新一条助手消息那一轮"的轨迹；它存的已经是本轮增量，不必再切片 */
  const lastAssistant = useMemo(
    () => [...messages].reverse().find((message) => message.role === 'assistant') ?? null,
    [messages],
  )
  const latestTrace = lastAssistant?.trace ?? []

  const persist = useCallback(
    (patch: Partial<StoredSession>) => {
      onSessionChange({ ...session, ...patch })
    },
    [onSessionChange, session],
  )

  /**
   * 所有接口错误的**唯一**出口。
   *
   * 401 直接回登录页（不静默重登：那会在用户不知情时换掉上下文）；
   * 404 说明当前 thread 没了（被删或换了账号看别人的），于是清掉当前会话、
   * 刷新列表 —— 而不是把用户踢回登录页，账号本身还是好的。
   *
   * 返回一句给用户看的话；已经接管处理的（401）返回空串。
   */
  const handleApiError = useCallback(
    (err: unknown): string => {
      if (err instanceof ApiError) {
        if (err.kind === 'unauthorized') {
          onSessionExpired()
          return ''
        }
        if (err.kind === 'thread_missing') {
          persist({ threadId: null })
          setPending(null)
          setMessages([])
          return `${err.message}，已回到"未选择会话"状态。`
        }
        return err.message
      }
      return '请求失败，请重试'
    },
    [onSessionExpired, persist],
  )

  /** 拉会话列表。返回列表，方便调用方接着挑一个（比如刚删掉一个 dead thread）。 */
  const refreshThreads = useCallback(async (): Promise<ThreadInfo[]> => {
    try {
      const list = await listThreads(token)
      setThreads(list)
      return list
    } catch (err) {
      const message = handleApiError(err)
      if (message !== '') setError(message)
      return []
    } finally {
      setThreadsLoading(false)
    }
  }, [handleApiError, token])

  useEffect(() => {
    void refreshThreads()
  }, [refreshThreads])

  /**
   * 切换会话时回放：**正文与未决确认以服务端为准**，轨迹只能来自本地缓存。
   *
   * 只有在"本地条数和服务端条数一致"时才用本地那份 —— 它带着轨迹。
   * 不一致说明本地缺消息（换了浏览器、清过缓存、或者另一处已经聊过），
   * 那就用服务端的正文，并把它写回本地，从这一轮起重新积累轨迹。
   */
  useEffect(() => {
    if (threadId === null) {
      setMessages([])
      setPending(null)
      return
    }
    if (skipLoadRef.current === threadId) {
      // 前端刚建的会话：回放必然为空，而流可能已经在跑，绝不能清空 UI
      skipLoadRef.current = null
      return
    }

    let cancelled = false
    const local = loadHistory(threadId)

    void (async () => {
      try {
        const reply = await fetchMessages(token, threadId)
        if (cancelled) return

        const fromServer = mapServerMessages(reply)
        if (local.length > 0 && local.length === fromServer.length) {
          setMessages(local)
        } else {
          setMessages(fromServer)
          saveHistory(threadId, fromServer)
        }

        setPending(reply.needs_confirmation ? reply.confirmation : null)
        cursorRef.current = loadTraceCursor(threadId)
        setError(null)
      } catch (err) {
        if (cancelled) return
        const message = handleApiError(err)
        if (message !== '') setError(message)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [handleApiError, threadId, token])

  const handlePickExample = useCallback((text: string) => {
    setDraft(text)
    setError(null)
    textareaRef.current?.focus()
  }, [])

  /** 显式新建会话：立刻落库并把界面切过去（空会话，没有历史要拉）。 */
  const handleCreateThread = useCallback(async () => {
    if (busy) return
    setError(null)
    try {
      const created = await createThread(token)
      skipLoadRef.current = created.thread_id
      setThreads((prev) => [created, ...prev])
      setMessages([])
      setPending(null)
      setLiveSteps([])
      cursorRef.current = 0
      saveTraceCursor(created.thread_id, 0)
      persist({ threadId: created.thread_id })
      textareaRef.current?.focus()
    } catch (err) {
      const message = handleApiError(err)
      if (message !== '') setError(message)
    }
  }, [busy, handleApiError, persist, token])

  const handleSelectThread = useCallback(
    (nextThreadId: string) => {
      if (nextThreadId === threadId) return
      setError(null)
      setLiveSteps([])
      setPending(null)
      cursorRef.current = loadTraceCursor(nextThreadId)
      persist({ threadId: nextThreadId })
    },
    [persist, threadId],
  )

  /** 首条消息时才建会话：避免"登录看一眼"就在库里留下空会话。 */
  const ensureThread = useCallback(async (): Promise<string | null> => {
    if (threadId !== null) return threadId
    try {
      const created = await createThread(token)
      skipLoadRef.current = created.thread_id
      setThreads((prev) => [created, ...prev])
      cursorRef.current = 0
      saveTraceCursor(created.thread_id, 0)
      persist({ threadId: created.thread_id })
      return created.thread_id
    } catch (err) {
      const message = handleApiError(err)
      if (message !== '') setError(message)
      return null
    }
  }, [handleApiError, persist, threadId, token])

  /** 统一提交一个后端响应：切片轨迹 → 落历史 → 更新游标与待确认。 */
  const commit = useCallback(
    (reply: Awaited<ReturnType<typeof confirm>>, base: ChatMessage[], activeThreadId: string) => {
      const { fresh, nextCursor } = sliceNewTrace(reply.trace, cursorRef.current)

      const nextMessages = [...base]
      // 中断轮 answer 是 null，但轨迹仍要展示 —— 它解释了卡片为什么出现。
      // 注意：中断轮也**必须推进游标**，否则下一轮会把这一轮的条目再渲染一遍。
      if (fresh.length > 0 || (reply.answer !== null && reply.answer !== '')) {
        nextMessages.push({
          id: newMessageId(),
          role: 'assistant',
          text: reply.answer ?? '',
          trace: fresh,
        })
      }

      cursorRef.current = nextCursor
      saveTraceCursor(activeThreadId, nextCursor)
      setMessages(nextMessages)
      saveHistory(activeThreadId, nextMessages)
      setPending(reply.needs_confirmation ? (reply.confirmation ?? null) : null)
    },
    [],
  )

  /**
   * 发一轮消息：**走 SSE 流，边收边渲染**。
   *
   * 与改造前的区别不只是"能不能打字"：
   *  - 抢在第一个 token 之前就把**助手气泡**插进去（正文为空 + 光标），
   *    否则"发出去了"到"第一个字出现"之间是一段什么都没有的静止期；
   *  - 正文由打字机按帧吐，模型来得多快都不会闪；
   *  - 轨迹分两路：流里的 `trace` 事件优先，没有就用 `liveSteps` 兜底，
   *    右栏至少能显示"派给了哪个专家"。
   *
   * **失败分两类，处理方式不同**：
   *  - 流都没建立起来（401/404/409/503/网络）→ `streamChat` 抛 `ApiError`。
   *    这时一个字都没收到，走"撤回乐观消息 + 把文字还给输入框"的老逻辑；
   *  - 流建好之后再断（超时、模型报错）→ 只能收到 `error` 事件。
   *    已经显示出来的部分回答**保留**，另挂一条错误提示。
   *
   * 流异常收尾后**额外做一次回放**：超时可能已经在检查点上留下了一个未决确认，
   * 而流自己不说这件事 —— 不同步的话用户会看到"发新消息被 409 拦住，却没有任何卡片"。
   */
  const send = useCallback(async () => {
    const text = draft.trim()
    if (text === '' || busy || locked) return

    setBusy(true)
    setError(null)
    setLiveSteps([])

    const base = messages
    const userId = newMessageId()
    const assistantId = newMessageId()
    setDraft('')

    const activeThreadId = await ensureThread()
    if (activeThreadId === null) {
      setBusy(false)
      return
    }

    setMessages([
      ...base,
      { id: userId, role: 'user', text },
      { id: assistantId, role: 'assistant', text: '' },
    ])
    setStreamingId(assistantId)

    // 打字机只认"到目前为止的全文"：它自己比对已吐出的长度，多出来的按帧放。
    // 这样不必去猜增量边界，文本重复到达也不会吐两遍。
    let acc = ''
    const typer = createTypewriter((revealed) => {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId ? { ...message, text: revealed } : message,
        ),
      )
    })
    typewriterRef.current = typer

    let confirmation: Confirmation | null = null
    let traceFromStream: TraceEntry[] | null = null
    let streamError: string | null = null

    try {
      const outcome = await streamChat(token, activeThreadId, text, {
        onDelta: (delta) => {
          acc += delta
          typer.push(acc)
        },
        onToolStart: (info) => setLiveSteps((prev) => [...prev, { kind: 'start', ...info }]),
        onToolEnd: (info) => setLiveSteps((prev) => [...prev, { kind: 'end', ...info }]),
        onToolError: (info) => setLiveSteps((prev) => [...prev, { kind: 'error', ...info }]),
        onConfirmation: (value) => {
          confirmation = value
        },
        onTrace: (trace) => {
          traceFromStream = trace
        },
        onStreamError: (message) => {
          streamError = message
        },
      })

      // 流结束了，但打字机可能还在吐收尾的那一段（实测设备申请这条路上整段回答
      // 就是末尾一条 delta）。必须等它吐完再落正式消息 —— 否则下一次 setMessages
      // 会把动画中的文本一次性覆盖掉，打字机就白做了。
      await typer.finish()

      const { fresh, nextCursor } =
        traceFromStream !== null
          ? sliceNewTrace(traceFromStream, cursorRef.current)
          : { fresh: [] as TraceEntry[], nextCursor: cursorRef.current }

      const finalMessages: ChatMessage[] = [...base, { id: userId, role: 'user', text }]
      // 中断那一轮 answer 是 null → 不插助手气泡；但轨迹有内容时仍要留下来
      if (acc !== '' || fresh.length > 0) {
        finalMessages.push({ id: assistantId, role: 'assistant', text: acc, trace: fresh })
      }

      cursorRef.current = nextCursor
      saveTraceCursor(activeThreadId, nextCursor)
      setMessages(finalMessages)
      saveHistory(activeThreadId, finalMessages)
      setPending(confirmation)

      if (outcome === 'error') {
        setError(streamError ?? '回答中断了，请重试')
        // 超时可能已经留下未决确认：问一次服务端，把卡片补出来
        try {
          const reply = await fetchMessages(token, activeThreadId)
          setPending(reply.needs_confirmation ? reply.confirmation : null)
        } catch {
          /* 同步失败不影响已经渲染的内容 */
        }
      }
    } catch (err) {
      // 流都没建立起来：撤回乐观插入的两条消息，并把文字还给输入框
      setMessages(base)
      saveHistory(activeThreadId, base)
      setDraft(text)
      const message = handleApiError(err)
      if (message !== '') {
        setError(message)
        // 409 带待确认语义时，卡片才是用户真正需要的那个东西
        if (err instanceof ApiError && err.kind === 'pending_confirmation') {
          try {
            const reply = await fetchMessages(token, activeThreadId)
            setPending(reply.needs_confirmation ? reply.confirmation : null)
          } catch {
            /* 忽略 */
          }
        }
      }
    } finally {
      typer.dispose()
      typewriterRef.current = null
      setStreamingId(null)
      setBusy(false)
    }
  }, [busy, draft, ensureThread, handleApiError, locked, messages, token])

  const decide = useCallback(
    async (approved: boolean) => {
      // 硬要求：in-flight 期间按钮必须禁用（ConfirmationCard 收 `busy` 后自己会 disable），
      // 否则双击会发出两次 resume —— 对一个会写盘的动作是真实的数据风险。
      if (busy || !locked || threadId === null) return

      setBusy(true)
      setError(null)
      try {
        commit(await confirm(token, threadId, approved), messages, threadId)
      } catch (err) {
        const message = handleApiError(err)
        if (message !== '') setError(message)
        // 卡片和服务端已经不一致（多半是别处处理过 / 上一条还在跑）：以服务端为准
        if (err instanceof ApiError && (err.kind === 'no_pending' || err.kind === 'busy')) {
          try {
            const reply = await fetchMessages(token, threadId)
            setPending(reply.needs_confirmation ? reply.confirmation : null)
          } catch {
            /* 忽略 */
          }
        }
      } finally {
        setBusy(false)
      }
    },
    [busy, commit, handleApiError, locked, messages, threadId, token],
  )

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void send()
  }

  function handleSignOut() {
    if (threadId !== null) clearHistory(threadId)
    onSignOut()
  }

  const canSend = !busy && !locked && draft.trim() !== ''

  return (
    <div className="flex h-screen flex-col bg-surface-0">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-hairline bg-surface-1 px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-3">
          {/* 身份信息收进悬停卡片：顶栏只留一个芯片，侧栏腾给会话 */}
          <IdentityCard session={session} threadCount={threads.length} />
          <span className="truncate font-mono text-[11px] text-ink-3">
            {threadId === null ? '未选择会话' : `会话 ${threadId.slice(0, 8)}`}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <ThemeSwitcher />
          <button
            type="button"
            onClick={handleSignOut}
            className={cn(
              'shrink-0 rounded-control border border-hairline bg-surface-2 px-3 py-1.5',
              'text-xs text-ink-1 transition-colors hover:border-hairline-strong hover:bg-surface-3',
            )}
          >
            退出登录
          </button>
        </div>
      </header>

      {/*
        三栏行：**只放消息区与两侧栏**。输入框不在这里 —— 见文件头注释。
        这一行同时是那两个箭头的**定位参照**：`top-1/2` 要相对"中间区域"居中，
        而不是相对整页（整页还含顶栏与底栏，中心会偏下 6px）。
        收起用**宽度过渡**而不是 `display: none`：后者没法过渡，会"啪"地消失。
        外层负责动画（宽度 + 裁剪），内层保持固定宽度，这样收起过程中内容不会被挤压变形。
        窄屏下两个状态都是 w-0（本来就该收起），所以不会有多余动画。
      */}
      <div className="relative flex min-h-0 flex-1">
        <aside
          aria-label="会话"
          inert={leftHidden}
          className={cn(
            'shrink-0 overflow-hidden transition-[width] duration-300 ease-out motion-reduce:transition-none',
            leftHidden ? 'w-0' : 'w-60',
          )}
        >
          <div
            className={cn(
              'relative h-full w-60 transition-opacity duration-200 motion-reduce:transition-none',
              leftHidden ? 'opacity-0' : 'opacity-100',
            )}
          >
            <div className="scroll-slim h-full w-60 overflow-y-auto border-r border-hairline bg-surface-1">
              <SessionPanel
                threads={threads}
                loading={threadsLoading}
                activeThreadId={threadId}
                role={user.role}
                onSelectThread={handleSelectThread}
                onCreateThread={() => void handleCreateThread()}
                onPickExample={handlePickExample}
              />
            </div>
          </div>
        </aside>

        <div className="scroll-slim min-w-0 flex-1 overflow-y-auto px-4 py-4">
          <div className="mx-auto flex max-w-3xl flex-col gap-3">
            {messages.length === 0 && (
              <div className="mt-12 text-center">
                <p className="text-sm text-ink-1">问点什么开始吧</p>
                <p className="mt-1.5 text-xs leading-relaxed text-ink-3">
                  左边的示例点一下就能填进输入框；
                  <br className="hidden sm:block" />
                  回答下方可以展开看 Supervisor 把任务派给了谁。
                  <br className="hidden sm:block" />
                  会话会存进数据库，刷新或换设备都能接着聊。
                </p>
              </div>
            )}

            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                streaming={message.id === streamingId}
              />
            ))}

            {pending !== null && (
              <ConfirmationCard confirmation={pending} busy={busy} onDecide={decide} />
            )}

            {/* 流已经在吐字时不再加这行：光标 + 右栏的实时步骤已经在表达"正在处理" */}
            {busy && streamingId === null && (
              <p className="text-xs text-ink-3" role="status">
                {locked ? '正在处理确认…' : 'agent 正在处理，通常需要十几秒…'}
              </p>
            )}

            {error !== null && (
              <p
                role="alert"
                className="rounded-control border border-danger/40 bg-danger-soft px-3 py-2 text-xs text-danger"
              >
                {error}
              </p>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        <aside
          aria-label="本轮轨迹"
          inert={rightHidden}
          className={cn(
            'shrink-0 overflow-hidden transition-[width] duration-300 ease-out motion-reduce:transition-none',
            rightHidden ? 'w-0' : 'w-80',
          )}
        >
          <div
            className={cn(
              'relative h-full w-80 transition-opacity duration-200 motion-reduce:transition-none',
              rightHidden ? 'opacity-0' : 'opacity-100',
            )}
          >
            <div className="scroll-slim h-full w-80 overflow-y-auto border-l border-hairline bg-surface-1">
              <LiveTraceRail
                entries={latestTrace}
                hasAssistantReply={lastAssistant !== null}
                steps={liveSteps}
              />
            </div>
          </div>
        </aside>

        {/* 四个箭头都挂在**中间区域**（这一行）上，所以它们的 `top-1/2`
            相对的是三栏行而不是整页 —— 整页还含顶栏 51px 与底栏 63px，中心会偏下 6px */}
        <DividerCollapseButton side="left" hidden={leftHidden} onToggle={toggleLeft} />
        <DividerCollapseButton side="right" hidden={rightHidden} onToggle={toggleRight} />
        <EdgeRestoreButton side="left" hidden={leftHidden} onToggle={toggleLeft} />
        <EdgeRestoreButton side="right" hidden={rightHidden} onToggle={toggleRight} />
      </div>

      {/* 整宽底栏：把两侧栏的宽度补成内边距，让输入框与消息列严格对齐（四种显隐组合都成立） */}
      <form
        onSubmit={handleSubmit}
        className={cn(
          'shrink-0 border-t border-hairline bg-surface-1 px-4 py-3',
          !leftHidden && 'pl-64',
          !rightHidden && 'pr-80',
        )}
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send()
              }
            }}
            rows={1}
            disabled={busy || locked}
            aria-label="输入消息"
            placeholder={
              locked ? '请先处理上面的待确认操作' : '说点什么…（Enter 发送，Shift+Enter 换行）'
            }
            className={cn(
              'scroll-slim max-h-40 min-h-[38px] min-w-0 flex-1 resize-y rounded-control border border-hairline',
              'bg-surface-3 px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3',
              'focus:border-accent focus:outline-none disabled:opacity-60',
            )}
          />
          <button
            type="submit"
            disabled={!canSend}
            className={cn(
              'shrink-0 rounded-control bg-accent px-4 py-2 text-sm font-medium text-on-accent',
              'transition-colors hover:bg-accent-hi disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {busy ? '处理中' : '发送'}
          </button>
        </div>
      </form>
    </div>
  )
}

/**
 * 展开态：收起箭头**骑在侧栏与消息区之间的分界线上、垂直居中**。
 *
 * 为什么骑在线上而不是长在面板里：面板内容区只有 256 / 320px 宽，
 * 任何常驻按钮都会吃掉正文宽度或压在文字上；骑在分界线上则两边都不占。
 * 对比度用 `text-ink-0` + `bg-surface-2` + `border-hairline-strong`
 * （先前用 `text-ink-3` 无底色，用户反馈"看不清楚"）。
 */
function DividerCollapseButton({
  side,
  hidden,
  onToggle,
}: {
  side: 'left' | 'right'
  hidden: boolean
  onToggle: () => void
}) {
  const isLeft = side === 'left'
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={isLeft ? '隐藏左栏' : '隐藏右栏'}
      title={isLeft ? `隐藏左栏（${SIDEBAR_SHORTCUT_HINT}）` : '隐藏右栏'}
      className={cn(
        'absolute top-1/2 z-30 flex h-7 w-7 -translate-y-1/2 items-center justify-center',
        'rounded-full border border-hairline-strong bg-surface-2 text-[14px] text-ink-0',
        'transition-opacity duration-200 motion-reduce:transition-none',
        'hover:bg-surface-3 hover:text-accent-text',
        isLeft ? 'left-64 -translate-x-1/2' : 'right-80 translate-x-1/2',
        hidden && 'pointer-events-none opacity-0',
      )}
    >
      <span aria-hidden>{isLeft ? '⟨' : '⟩'}</span>
    </button>
  )
}

/**
 * 收起态：一条**贴着屏幕边缘**的窄箭头。左右各自贴自己那一边，
 * 半圆角朝内（`border-l-0` / `border-r-0`），看起来像从边上"探出来"的一小片。
 *
 * 常驻挂载、只切换透明度：这样它出现时能和面板滑出**同步淡入**，
 * 而不是"啪"地冒出来（挂载/卸载没法做 CSS 过渡）。
 * 不可见时用 `pointer-events-none` + `tabIndex=-1`，避免"看不见却点得到"。
 */
function EdgeRestoreButton({
  side,
  hidden,
  onToggle,
}: {
  side: 'left' | 'right'
  hidden: boolean
  onToggle: () => void
}) {
  const isLeft = side === 'left'
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-hidden={!hidden}
      tabIndex={hidden ? 0 : -1}
      aria-label={isLeft ? '显示左栏' : '显示右栏'}
      title={isLeft ? `显示左栏（${SIDEBAR_SHORTCUT_HINT}）` : '显示右栏'}
      className={cn(
        'absolute top-1/2 z-30 flex h-10 w-[20px] -translate-y-1/2 items-center justify-center',
        'border border-hairline-strong bg-surface-2 text-[14px] text-ink-0',
        'transition-opacity duration-200 motion-reduce:transition-none',
        'hover:bg-surface-3 hover:text-accent-text',
        isLeft ? 'left-0 rounded-r-control border-l-0' : 'right-0 rounded-l-control border-r-0',
        hidden ? 'opacity-100' : 'pointer-events-none opacity-0',
      )}
    >
      <span aria-hidden>{isLeft ? '⟩' : '⟨'}</span>
    </button>
  )
}
