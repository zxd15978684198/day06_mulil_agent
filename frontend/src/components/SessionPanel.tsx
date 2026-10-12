import type { StoredSession } from '../lib/session'
import { cn } from '../lib/utils'
import PanelSection from './PanelSection'

/**
 * 左栏：身份与能力。
 *
 * 这块不只是"填空" —— 它把**三道权限闸门**里最直观的那一道摆到台面上：
 * 同一个问题，换个身份能做的事不一样。演示时不用讲，看一眼侧栏就明白。
 *
 * 能力清单的事实来源：`CLAUDE.md` 的架构图（Supervisor 只挂 Agent Tools，
 * 专家各持自己的业务 Tool，`ask_hr_agent` 只对 HR 可见）。
 *
 * 视觉粒度见 `PanelSection` 的注释：**分组有边界，条目靠间距与字重**。
 */

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

const EXAMPLES: Record<string, readonly string[]> = {
  employee: [
    '公司的年假是怎么规定的？',
    '研发部找谁对接？',
    '我想申请一台 24 英寸显示器，用于双屏办公',
  ],
  hr: ['现在有哪些申请待审批？', '我想申请一台 24 英寸显示器，用于双屏办公'],
}

const ROLE_LABEL: Record<string, string> = { employee: '员工', hr: 'HR' }

interface SessionPanelProps {
  session: StoredSession
  /** 点示例问题 → 填进输入框（不直接发送，留给用户改） */
  onPickExample: (text: string) => void
}

export default function SessionPanel({ session, onPickExample }: SessionPanelProps) {
  const isHr = session.role === 'hr'
  const examples = EXAMPLES[session.role] ?? EXAMPLES.employee

  return (
    <div className="space-y-3 p-3">
      <PanelSection title="当前身份" hint={ROLE_LABEL[session.role] ?? session.role}>
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control border border-hairline bg-surface-3 text-sm font-semibold text-accent-text"
          >
            {session.displayName.slice(0, 1)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink-0">{session.displayName}</p>
            <p className="truncate font-mono text-[11.5px] text-ink-3">
              {session.sessionId.slice(0, 8)}
            </p>
          </div>
        </div>
        <p className="mt-2.5 text-[11.5px] leading-relaxed text-ink-3">
          身份由服务端按账号查表决定，聊天里说什么都改不了它。
        </p>
      </PanelSection>

      <PanelSection title="这个身份能做什么">
        <ul className="space-y-3.5">
          {CAPABILITIES.map((item) => {
            const locked = item.hrOnly === true && !isHr
            return (
              <li key={item.label}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className={cn('text-[13px]', locked ? 'text-ink-2' : 'text-ink-0')}>
                    {item.label}
                  </span>
                  {locked && (
                    <span className="shrink-0 rounded-full bg-surface-3 px-1.5 py-0.5 text-[10.5px] text-ink-3">
                      需 HR
                    </span>
                  )}
                </div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">{item.detail}</p>
              </li>
            )
          })}
        </ul>
      </PanelSection>

      <PanelSection title="试试这样问" hint="点一下填进输入框">
        <ul className="-mx-1.5 space-y-0.5">
          {examples.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => onPickExample(example)}
                className={cn(
                  'group flex w-full items-start gap-1.5 rounded-control px-1.5 py-2 text-left',
                  'text-[12.5px] leading-relaxed text-ink-1 transition-colors',
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
    </div>
  )
}
