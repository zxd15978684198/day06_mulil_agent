import { useCallback, useEffect, useId, useRef, useState } from 'react'

import type { StoredSession } from '../lib/session'
import { cn } from '../lib/utils'

/**
 * 左上角的**员工状态卡片**（悬停展开、移出收起）。
 *
 * 为什么把它从侧栏里搬出来：侧栏原来的结构是"身份 + 会话 + 能力 + 示例"
 * 四段竖着叠，身份这种**低频查看、长期不变**的信息占着最贵的首屏位置，
 * 而会话列表这种高频操作反而被压在中间。用户原话："员工信息和会话记录混到一块了"。
 *
 * 所以职责重新切分：
 *  - 顶栏左上角只留一个**身份芯片**（头像 + 名字 + 角色），一眼能确认"我是谁"；
 *  - 完整状态（工号、部门、会话数、当前会话、能做什么）挂在悬停卡片里，按需展开；
 *  - 侧栏腾出来只放会话。
 *
 * 三个实现细节：
 *  1. **关闭有延迟**（`CLOSE_DELAY_MS`）：芯片和卡片之间隔着 8px，
 *     鼠标从芯片移到卡片上会瞬间穿过这段空隙，不延迟就会闪一下；
 *  2. **`focus` 也能展开**：悬停不是唯一的入口，键盘 Tab 过来同样看得见
 *     （纯 hover 的组件对键盘用户等于不存在）；
 *  3. **Escape 关闭**：展开态的浮层要让用户能撤出去。
 */

const ROLE_LABEL: Record<string, string> = { employee: '员工', hr: 'HR' }

interface Capability {
  label: string
  detail: string
  hrOnly?: boolean
}

const CAPABILITIES: readonly Capability[] = [
  { label: '制度问答', detail: '公司介绍、员工手册、各类规章制度与办公指引' },
  { label: '员工服务', detail: '查部门与公开联系人、查设备目录、提交设备申请、查自己的申请' },
  { label: 'HR 审批', detail: '审批待处理的设备申请', hrOnly: true },
] as const

/** 鼠标穿过芯片与卡片之间的空隙所需的时间，留足余量。 */
const CLOSE_DELAY_MS = 160

export default function IdentityCard({
  session,
  threadCount,
}: {
  session: StoredSession
  threadCount: number
}) {
  const { user, threadId } = session
  const [open, setOpen] = useState(false)
  const closeTimer = useRef<number | null>(null)
  const cardId = useId()
  const isHr = user.role === 'hr'
  const roleLabel = ROLE_LABEL[user.role] ?? user.role

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }, [])

  const openNow = useCallback(() => {
    cancelClose()
    setOpen(true)
  }, [cancelClose])

  const closeSoon = useCallback(() => {
    cancelClose()
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null
      setOpen(false)
    }, CLOSE_DELAY_MS)
  }, [cancelClose])

  // 组件卸载时别留下一个还在跑的定时器（它会 setState 到已卸载的组件上）
  useEffect(() => cancelClose, [cancelClose])

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        cancelClose()
        setOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, cancelClose])

  const fields: readonly { label: string; value: string; mono?: boolean }[] = [
    { label: '工号', value: user.user_id, mono: true },
    { label: '部门', value: user.department_id, mono: true },
    { label: '我的会话', value: `${threadCount} 个`, mono: true },
    {
      label: '当前会话',
      value: threadId === null ? '未选择' : threadId.slice(0, 8),
      mono: true,
    },
  ]

  return (
    <div
      className="relative"
      onMouseEnter={openNow}
      onMouseLeave={closeSoon}
      onFocus={openNow}
      onBlur={closeSoon}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-describedby={open ? cardId : undefined}
        className={cn(
          'flex items-center gap-2.5 rounded-control border py-1 pl-1 pr-2 text-left transition-colors',
          open
            ? 'border-hairline-strong bg-surface-2'
            : 'border-transparent hover:border-hairline hover:bg-surface-2',
        )}
      >
        <span
          aria-hidden
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] border text-[12.5px] font-semibold',
            isHr
              ? 'border-accent/40 bg-accent-soft text-accent-text'
              : 'border-hairline-strong bg-surface-3 text-ink-1',
          )}
        >
          {user.display_name.slice(0, 1)}
        </span>

        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="truncate text-[13.5px] font-medium text-ink-0">{user.display_name}</span>
          <span
            className={cn(
              'shrink-0 rounded-[5px] px-1 py-px text-[10px] tracking-wide',
              isHr ? 'bg-accent-soft text-accent-text' : 'bg-surface-3 text-ink-2',
            )}
          >
            {roleLabel}
          </span>
        </span>

        <span
          aria-hidden
          className={cn(
            'shrink-0 text-[9px] text-ink-3 transition-transform duration-200 motion-reduce:transition-none',
            open ? 'rotate-180' : 'rotate-0',
          )}
        >
          ▼
        </span>
      </button>

      <div
        id={cardId}
        role="dialog"
        aria-label="员工状态"
        className={cn(
          'absolute left-0 top-full z-50 mt-2 w-[19rem] origin-top-left rounded-card border border-hairline-strong bg-surface-2',
          'transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none',
          open
            ? 'visible translate-y-0 opacity-100'
            : 'invisible -translate-y-1 opacity-0',
        )}
      >
        <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
          <span
            aria-hidden
            className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-[9px] border text-[15px] font-semibold',
              isHr
                ? 'border-accent/40 bg-accent-soft text-accent-text'
                : 'border-hairline-strong bg-surface-3 text-ink-0',
            )}
          >
            {user.display_name.slice(0, 1)}
          </span>
          <div className="min-w-0">
            <p className="flex items-baseline gap-1.5">
              <span className="truncate text-sm font-semibold text-ink-0">{user.display_name}</span>
              <span className="shrink-0 text-[11px] text-ink-3">{roleLabel}</span>
            </p>
            <p className="truncate font-mono text-[11px] text-ink-3">{user.username}</p>
          </div>
          <span className="ml-auto flex shrink-0 items-center gap-1.5 text-[10.5px] text-ink-2">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-ok" />
            已登录
          </span>
        </div>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5 px-4 py-3">
          {fields.map((field) => (
            <div key={field.label} className="min-w-0">
              <dt className="text-[10.5px] text-ink-3">{field.label}</dt>
              <dd
                className={cn(
                  'truncate text-[12px] text-ink-0',
                  field.mono === true && 'font-mono tabular-nums',
                )}
                title={field.value}
              >
                {field.value}
              </dd>
            </div>
          ))}
        </dl>

        <div className="border-t border-hairline px-4 py-3">
          <p className="text-[10.5px] tracking-wide text-ink-3">这个身份能做什么</p>
          <ul className="mt-2 space-y-2">
            {CAPABILITIES.map((item) => {
              const locked = item.hrOnly === true && !isHr
              return (
                <li key={item.label}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={cn('text-[12.5px]', locked ? 'text-ink-3' : 'text-ink-0')}>
                      {item.label}
                    </span>
                    {locked && (
                      <span className="shrink-0 rounded-[5px] bg-surface-3 px-1 py-px text-[10px] text-ink-3">
                        需 HR
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink-2">{item.detail}</p>
                </li>
              )
            })}
          </ul>
        </div>

        <p className="border-t border-hairline px-4 py-2.5 text-[10.5px] leading-relaxed text-ink-3">
          身份由服务端按 Token 查表决定，聊天里说什么都改不了它。
        </p>
      </div>
    </div>
  )
}
