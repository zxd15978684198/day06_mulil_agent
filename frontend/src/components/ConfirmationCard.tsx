import { motion, useReducedMotion } from 'motion/react'
import { useMemo } from 'react'

import type { Confirmation } from '../lib/api'
import { cn } from '../lib/utils'

/**
 * 待确认操作的卡片。
 *
 * 三条硬约束（都来自 `frontend/CONTRACTS.md`）：
 *
 * 1. **模板分派的唯一依据是 `confirmation.action`**（`C2`）。不得根据字段形状猜类型 ——
 *    猜错会把"审批"渲染成"申请"，比不渲染更糟。
 * 2. **按钮语义必须是「是否执行 agent 已经决定好的动作」，不是「这条申请批不批」**（`C5`）。
 *    所以文案是「确认执行 / 取消本次操作」，并且卡片**先展示 agent 打算做什么**再给按钮。
 * 3. **未知 action 不许白屏**（`P-3`）：落到通用模板，把字段如实列出来。
 *
 * 布局是"结构化优先 + 通用兜底"两段式：模板命中的话，关键字段用表格醒目展示；
 * 无论是否命中，**完整原始字段**都收在下面的折叠区里 —— 这样即使模板过时了，
 * 用户依然能看清自己要批的是什么。
 */

interface ConfirmationCardProps {
  confirmation: Confirmation
  /** 请求在飞的时候为 true —— 两个按钮都必须禁用（防双击导致两次 resume） */
  busy: boolean
  onDecide: (approved: boolean) => void
}

type FieldRow = { label: string; value: string; emphasis?: boolean }

interface Template {
  title: string
  /** agent 打算做什么 —— 用一句人话写清楚，这是用户判断的依据 */
  intent: string
  rows: (payload: Record<string, unknown>) => FieldRow[]
}

const TEMPLATES: Record<string, Template> = {
  create_device_request: {
    title: '提交设备申请',
    intent: 'agent 打算**新建**一条设备申请记录并写入业务数据。',
    rows: (payload) => {
      const candidate = asRecord(payload.candidate)
      return [
        { label: '申请人', value: text(candidate.applicant_name ?? candidate.applicant_user_id), emphasis: true },
        { label: '设备', value: text(candidate.device_name ?? candidate.device_id), emphasis: true },
        { label: '数量', value: text(candidate.quantity) },
        { label: '申请理由', value: text(candidate.reason) },
        { label: '预分配编号', value: text(candidate.request_id) },
      ]
    },
  },
  approve_device_request: {
    title: '审批设备申请',
    intent: 'agent 打算把这条申请的**状态改成下面这个决定**并写入业务数据。',
    rows: (payload) => [
      { label: '申请单号', value: text(payload.request_id), emphasis: true },
      { label: '申请人', value: text(payload.applicant_name ?? payload.applicant_user_id), emphasis: true },
      { label: '设备', value: text(payload.device_name ?? payload.device_id) },
      { label: '数量', value: text(payload.quantity) },
      { label: 'agent 的决定', value: decisionLabel(payload.decision), emphasis: true },
      { label: '审批意见', value: text(payload.comment) },
    ],
  },
}

/** 未知 action 的兜底模板：不猜语义，只如实陈列。 */
const FALLBACK: Template = {
  title: '待确认的操作',
  intent: 'agent 请求执行一个操作。这是一类前端还不认识的操作类型，请按下面的原始字段自行判断。',
  rows: () => [],
}

export default function ConfirmationCard({
  confirmation,
  busy,
  onDecide,
}: ConfirmationCardProps) {
  const reduceMotion = useReducedMotion()
  const action = typeof confirmation.action === 'string' ? confirmation.action : ''
  const template = TEMPLATES[action]
  const active = template ?? FALLBACK

  const rows = useMemo(() => {
    const produced = active.rows(confirmation as Record<string, unknown>)
    // 模板字段若全是空值，就当作没命中，避免给出一张全是"—"的卡片
    const meaningful = produced.filter((row) => row.value !== '—' && row.value !== '')
    return meaningful.length > 0 ? meaningful : []
  }, [active, confirmation])

  const leftovers = useMemo(() => {
    const consumed = new Set(['action', 'candidate'])
    for (const key of Object.keys(confirmation)) {
      if (rows.some((row) => row.label.includes(key))) consumed.add(key)
    }
    return Object.entries(confirmation).filter(([key]) => !consumed.has(key))
  }, [confirmation, rows])

  const degraded = rows.length === 0

  return (
    <motion.section
      className="rounded-card border border-accent/40 bg-surface-1"
      aria-label="待确认的操作"
      {...enter(reduceMotion)}
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-hairline px-3.5 py-2.5">
        <h3 className="text-sm font-medium text-ink-0">{active.title}</h3>
        <code className="shrink-0 font-mono text-[11px] text-ink-3">{action || '（无 action）'}</code>
      </header>

      <div className="space-y-3 px-3.5 py-3">
        <p className="text-xs leading-relaxed text-ink-1">{renderEmphasis(active.intent)}</p>

        {degraded ? (
          <p className="rounded-control border border-warn/40 bg-warn-soft px-3 py-2 text-xs text-warn">
            这个操作没有可结构化的字段（可能不是设备类操作）。下面是后端原样返回的内容，
            请据此判断 —— 不认识这个操作类型时，<strong className="font-medium">建议点「取消本次操作」</strong>。
          </p>
        ) : (
          <dl className="overflow-hidden rounded-control border border-hairline">
            {rows.map((row) => (
              <div
                key={row.label}
                className="flex gap-3 border-b border-hairline px-3 py-1.5 last:border-b-0"
              >
                <dt className="w-24 shrink-0 text-[11px] leading-5 text-ink-3">{row.label}</dt>
                <dd
                  className={cn(
                    'min-w-0 flex-1 break-words text-[12.5px] leading-5',
                    row.emphasis ? 'font-medium text-ink-0' : 'text-ink-1',
                  )}
                >
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
        )}

        {leftovers.length > 0 && (
          <details className="rounded-control border border-hairline bg-surface-0">
            <summary className="cursor-pointer list-none px-3 py-1.5 text-[11px] text-ink-3 hover:text-ink-2">
              原始字段（{leftovers.length} 项，点击展开）
            </summary>
            <dl className="space-y-1 border-t border-hairline px-3 py-2">
              {leftovers.map(([key, value]) => (
                <div key={key} className="flex gap-3 text-[11px]">
                  <dt className="w-32 shrink-0 font-mono text-ink-3">{key}</dt>
                  <dd className="min-w-0 break-words font-mono text-ink-1">{preview(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        )}

        <p className="text-[11px] leading-relaxed text-ink-3">
          「确认执行」= 按上面的内容**真正写入**；「取消本次操作」= **一个字节都不改**。
          这里确认的是"要不要执行 agent 已经想好的这一步"，不是"这条申请批不批"。
        </p>
      </div>

      <footer className="flex gap-2 border-t border-hairline px-3.5 py-2.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecide(true)}
          className={cn(
            'rounded-control bg-accent px-3 py-1.5 text-xs font-medium text-on-accent',
            'transition-colors hover:bg-accent-hi disabled:cursor-not-allowed disabled:opacity-50',
          )}
        >
          {busy ? '处理中…' : '确认执行'}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecide(false)}
          className={cn(
            'rounded-control border border-hairline-strong bg-surface-2 px-3 py-1.5 text-xs text-ink-1',
            'transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50',
          )}
        >
          取消本次操作
        </button>
      </footer>
    </motion.section>
  )
}

/**
 * 入场动效：淡入 + 轻微上浮（比消息气泡稍慢一点，因为卡片是"要你注意"的元素）。
 * `prefers-reduced-motion` 打开时返回空对象 —— 完全不做动画。
 */
function enter(reduceMotion: boolean | null) {
  if (reduceMotion) return {}
  return {
    initial: { opacity: 0, y: 10 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.22, ease: 'easeOut' as const },
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function text(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value.trim() === '' ? '—' : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return preview(value)
}

function decisionLabel(value: unknown): string {
  if (value === 'approved') return '批准'
  if (value === 'rejected') return '驳回'
  return text(value)
}

function preview(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return '[无法展示]'
  }
}

/** 只支持 `**加粗**` 这一种标记 —— 足够表达重点，又不引第三方解析器。 */
function renderEmphasis(source: string) {
  const parts = source.split(/\*\*(.+?)\*\*/g)
  return parts.map((part, index) =>
    index % 2 === 1 ? (
      <strong key={index} className="font-medium text-ink-0">
        {part}
      </strong>
    ) : (
      <span key={index}>{part}</span>
    ),
  )
}
