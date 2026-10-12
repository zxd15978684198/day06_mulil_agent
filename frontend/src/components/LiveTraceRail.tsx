import type { TraceEntry } from '../lib/api'
import { summarizeTrace } from '../lib/trace'
import { cn } from '../lib/utils'
import PanelSection from './PanelSection'
import TracePanel from './TracePanel'

/**
 * 右栏：本轮轨迹（常驻）。
 *
 * 与气泡下方的折叠面板**分工不同**：
 *  - 这里看**最新一轮**，默认展开，不需要点 —— 演示时"点一下才看得见"是最大的摩擦；
 *  - 气泡下方那份是**每轮各一份**，用来回翻历史。
 * 两者都保留是刻意的：一个管"实时可见"，一个管"可追溯"。
 *
 * 分块粒度与左栏一致（见 `PanelSection` 注释）：**分组有边界，条目靠间距与字重**。
 *
 * 数据有**两种来源**，优先级从高到低：
 *  1. `entries` —— 已落库的轨迹（来自 `/api/confirmation` 的 `AgentReply.trace` 或
 *     流里的 `trace` 事件）。信息最全，能展开看每个 Tool 的原始载荷。
 *  2. `steps` —— 流式期间攒的 **agent 级**步骤。信息粗（只有"调了哪个专家"），
 *     但胜在**轮次中途就有**：`/api/chat/stream` 不发累计轨迹，只有这些事件。
 * 两者都不在时给一句解释，而不是空白 —— 空白会让人以为坏了。
 */

/** 流式期间攒下来的一步：agent 级的开始 / 结束 / 失败。 */
export interface LiveStep {
  kind: 'start' | 'end' | 'error'
  /** 英文 Agent Tool 名，只用来做 key */
  name: string
  /** 中文展示名（后端给什么显示什么） */
  label: string
  /** 仅 `kind === 'error'` 时后端会给一句可公布的原因 */
  message?: string
}

export default function LiveTraceRail({
  entries,
  hasAssistantReply,
  steps = [],
}: {
  /** 最新一条助手消息自带的轨迹（已经是**本轮增量**，不需要再切片） */
  entries: TraceEntry[]
  /** 是否已经有过助手回复 —— 用来区分"还没聊"和"聊了但本轮没路由" */
  hasAssistantReply: boolean
  /** 流式期间的实时步骤；有正式轨迹时会被忽略 */
  steps?: LiveStep[]
}) {
  const summary = summarizeTrace(entries)
  const hasTrace = entries.length > 0
  const showSteps = !hasTrace && steps.length > 0

  // 只显示"结束"态的步数会把进行中的一步漏掉，所以直接数条数
  const hint = hasTrace
    ? `${summary.agentTools.length} 专家 · ${summary.businessTools.length} 工具`
    : showSteps
      ? `${steps.length} 步`
      : undefined

  return (
    <div className="space-y-3 p-3">
      <PanelSection title="本轮轨迹" hint={hint}>
        {hasTrace ? (
          <div className="space-y-3">
            <dl className="space-y-2">
              <SummaryRow label="专家" values={summary.agentTools} />
              <SummaryRow label="业务 Tool" values={summary.businessTools} />
            </dl>
            <div className="border-t border-hairline pt-3">
              <TracePanel entries={entries} bare />
            </div>
          </div>
        ) : showSteps ? (
          <StepList steps={steps} />
        ) : (
          <p className="text-[12.5px] leading-relaxed text-ink-2">
            {hasAssistantReply
              ? '这一轮没有轨迹可展示：要么 Supervisor 直接回答了、没转给专家，要么这条消息是接口补发 trace 事件之前存下的。'
              : '发一条消息，这里会实时显示 Supervisor 把任务派给了谁、专家又调了哪些业务 Tool。'}
          </p>
        )}
      </PanelSection>

      <p className="px-1 text-[11.5px] leading-relaxed text-ink-3">
        这里只看最新一轮；历史每一轮各自的轨迹，收在上方对应回答的下方。
      </p>
    </div>
  )
}

/** 流式步骤列表。刻意只画点与一行字 —— 中途还不知道专家用了哪些业务 Tool。 */
function StepList({ steps }: { steps: LiveStep[] }) {
  return (
    <ol className="space-y-2">
      {steps.map((step, index) => (
        <li key={`${step.name}-${index}`} className="flex items-start gap-2">
          <StepDot kind={step.kind} />
          <span className="min-w-0 flex-1 text-[12.5px] leading-relaxed text-ink-1">
            {stepText(step)}
            {/* 失败时把后端那句可公布的原因也带上，否则前端只能干说"失败了" */}
            {step.kind === 'error' && step.message ? (
              <span className="text-ink-3">（{step.message}）</span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  )
}

function stepText(step: LiveStep): string {
  if (step.kind === 'end') return `${step.label} 已返回`
  if (step.kind === 'error') return `${step.label} 调用失败`
  return `调用 ${step.label}`
}

function StepDot({ kind }: { kind: LiveStep['kind'] }) {
  const tone =
    kind === 'end' ? 'bg-ok' : kind === 'error' ? 'bg-danger' : 'animate-pulse bg-accent'
  return <span className={cn('mt-1.5 size-1.5 shrink-0 rounded-full', tone)} aria-hidden />
}

function SummaryRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="w-16 shrink-0 text-[12px] text-ink-3">{label}</dt>
      <dd className="flex min-w-0 flex-wrap gap-1">
        {values.length > 0 ? (
          values.map((value) => (
            <code
              key={value}
              className={cn(
                'rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11.5px] text-ink-1',
              )}
            >
              {value}
            </code>
          ))
        ) : (
          <span className="text-[12px] text-ink-3">—</span>
        )}
      </dd>
    </div>
  )
}
