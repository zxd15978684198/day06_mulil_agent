import type { ThreadInfo } from '../lib/api'
import { SIDEBAR_SHORTCUT_HINT } from '../lib/layout'
import { formatAbsolute, formatRelative, parseServerTime } from '../lib/time'
import { cn } from '../lib/utils'
import PanelSection from './PanelSection'

/**
 * 左栏：**只放会话**。
 *
 * 身份与"能做什么"搬去了顶栏的悬停卡片（见 `IdentityCard.tsx`），
 * 这里因此只剩下一件事：在会话之间切换。
 *
 * **为什么给列表加高度上限**：后端这台教学库里单个账号已经攒了几十条会话，
 * 列表若跟着容器长到满屏，左栏就变成"会话记录墙"——用户的原话是
 * "会话记录不要占据整个左侧边栏"。所以列表自己滚动（`LIST_MAX_HEIGHT`），
 * 卡片高度跟着条数走，少的时候就是一两个条目的高度。
 *
 * 只列最近 `MAX_VISIBLE` 条：接口还没有分页，全渲染没有意义；
 * 总数放在标题里，让人知道"还有更多"。
 */

const EXAMPLES: Record<string, readonly string[]> = {
  employee: [
    '公司的年假是怎么规定的？',
    '研发部找谁对接？',
    '我想申请一台 24 英寸显示器，用于双屏办公',
  ],
  hr: ['现在有哪些申请待审批？', '我想申请一台 24 英寸显示器，用于双屏办公'],
}

const MAX_VISIBLE = 12

/** 列表的高度上限：超过就在卡片内部滚动，不再往侧栏里长。 */
const LIST_MAX_HEIGHT = 'max-h-[min(46vh,20rem)]'

interface SessionPanelProps {
  threads: ThreadInfo[]
  /** 列表还在请求中（首屏） */
  loading: boolean
  /** 当前选中的会话；还没建会话时为 null */
  activeThreadId: string | null
  /** 决定示例问题用哪一套 */
  role: string
  onSelectThread: (threadId: string) => void
  onCreateThread: () => void
  /** 点示例问题 → 填进输入框（不直接发送，留给用户改） */
  onPickExample: (text: string) => void
}

export default function SessionPanel({
  threads,
  loading,
  activeThreadId,
  role,
  onSelectThread,
  onCreateThread,
  onPickExample,
}: SessionPanelProps) {
  const examples = EXAMPLES[role] ?? EXAMPLES.employee
  const visible = threads.slice(0, MAX_VISIBLE)
  const overflow = threads.length > MAX_VISIBLE

  return (
    <div className="flex h-full w-full flex-col gap-2.5 p-3">
      <PanelSection
        title="会话"
        hint={loading ? '加载中' : `${threads.length} 个`}
        action={
          <button
            type="button"
            onClick={onCreateThread}
            title={`新建会话（${SIDEBAR_SHORTCUT_HINT} 收起左栏）`}
            className={cn(
              'flex shrink-0 items-center gap-1 rounded-[6px] border border-hairline-strong px-1.5 py-0.5',
              'text-[11px] text-ink-1 transition-colors',
              'hover:border-accent hover:bg-accent-soft hover:text-accent-text',
              'active:translate-y-px motion-reduce:active:translate-y-0',
            )}
          >
            <span aria-hidden className="text-[11px] leading-none">
              ＋
            </span>
            新建
          </button>
        }
        bodyClassName={cn('p-1.5', !loading && visible.length > 0 && LIST_MAX_HEIGHT, 'overflow-y-auto scroll-slim')}
      >
        {loading ? (
          <>
            <ul className="space-y-1.5" aria-hidden>
              {[0, 1, 2].map((row) => (
                <li key={row} className="h-10 animate-pulse rounded-control bg-surface-3" />
              ))}
            </ul>
            <span role="status" className="sr-only">
              正在加载会话列表
            </span>
          </>
        ) : visible.length === 0 ? (
          <p className="px-1.5 py-3 text-[11.5px] leading-relaxed text-ink-3">
            还没有会话。
            <br />
            发第一条消息时会自动建一个。
          </p>
        ) : (
          <ul className="space-y-0.5">
            {visible.map((thread) => {
              const active = thread.thread_id === activeThreadId
              const parsed = parseServerTime(thread.created_at)
              return (
                <li key={thread.thread_id}>
                  <button
                    type="button"
                    onClick={() => onSelectThread(thread.thread_id)}
                    aria-current={active ? 'true' : undefined}
                    title={`${thread.thread_id}${parsed === null ? '' : ` · ${formatAbsolute(parsed)}`}`}
                    className={cn(
                      'relative flex w-full flex-col gap-0.5 rounded-control py-1.5 pl-2.5 pr-2 text-left',
                      'transition-colors active:translate-y-px motion-reduce:active:translate-y-0',
                      active
                        ? 'bg-accent-soft text-accent-text'
                        : 'text-ink-1 hover:bg-surface-3 hover:text-ink-0',
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'absolute inset-y-1.5 left-0 w-[2px] rounded-full transition-colors',
                        active ? 'bg-accent' : 'bg-transparent',
                      )}
                    />
                    <span className="truncate text-[12.5px] font-medium">
                      会话 {thread.thread_id.slice(0, 8)}
                    </span>
                    <span className="truncate font-mono text-[10.5px] tabular-nums text-ink-3">
                      {formatRelative(thread.created_at)}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {!loading && overflow && (
          <p className="px-1.5 pb-0.5 pt-1.5 text-[10.5px] text-ink-3">
            只显示最近 {MAX_VISIBLE} 个（共 {threads.length} 个）
          </p>
        )}
      </PanelSection>

      <PanelSection title="试试这样问" hint="点一下填进输入框" className="shrink-0">
        <ul className="-mx-1.5 space-y-0.5">
          {examples.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => onPickExample(example)}
                className={cn(
                  'group flex w-full items-start gap-1.5 rounded-control px-1.5 py-1.5 text-left',
                  'text-[12px] leading-relaxed text-ink-1 transition-colors',
                  'hover:bg-surface-3 hover:text-ink-0',
                )}
              >
                <span
                  aria-hidden
                  className="mt-px shrink-0 text-ink-3 transition-colors group-hover:text-accent-text"
                >
                  ›
                </span>
                <span>{example}</span>
              </button>
            </li>
          ))}
        </ul>
      </PanelSection>

      {/* 底部提示：撑到底部，也让"会话卡片"和侧栏底部之间留出呼吸空间 */}
      <p className="mt-auto px-1 text-[10.5px] leading-relaxed text-ink-3">
        {SIDEBAR_SHORTCUT_HINT} 收起这一栏
      </p>
    </div>
  )
}
