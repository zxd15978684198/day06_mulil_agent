import { useState } from 'react'

import type { TraceEntry } from '../lib/api'
import { parseToolResult, summarizeTrace } from '../lib/trace'
import { cn } from '../lib/utils'

/**
 * 本轮轨迹面板。
 *
 * **空轨迹直接不渲染**（返回 null）—— 像"你好"这种不触发 Agent 调用的轮次，
 * 渲染一个"调用了 0 个 Agent Tool"的空盒子只会违背"平时安静"的目标。
 */
export default function TracePanel({
  entries,
  defaultOpen = false,
  bare = false,
}: {
  entries: TraceEntry[]
  /** 侧栏里常驻显示时希望默认展开；气泡下方保持默认折叠 */
  defaultOpen?: boolean
  /**
   * 只渲染条目本身，不要外层 `<details>` 与摘要行。
   * 给右侧常驻轨迹栏用 —— 那一栏本身就是容器、也已经显示了专家与业务 Tool 的摘要，
   * 再套一层边框和"调用了 N 个…"就是同一句话说两遍。
   */
  bare?: boolean
}) {
  // 用受控的 open + onToggle 跟踪状态：这样 `defaultOpen` 只决定初值，
  // 用户仍然能自由折叠（若直接把 `open` 写死成常量，React 会在每次重渲染时把它掰回去）
  const [open, setOpen] = useState(defaultOpen)

  if (entries.length === 0) return null

  const rows = entries.map((entry, index) => (
    <TraceRow key={`${entry.type}-${index}`} entry={entry} />
  ))

  if (bare) return <div className="space-y-2.5">{rows}</div>

  const summary = summarizeTrace(entries)

  return (
    <details
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
      className="group mt-2 rounded-control border border-hairline bg-surface-1"
    >
      <summary
        className={cn(
          'flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 text-[11px] text-ink-2',
          'hover:text-ink-1',
        )}
      >
        <span className="text-ink-3 transition-transform group-open:rotate-90">▸</span>
        <span>
          调用了 {summary.agentTools.length} 个 Agent Tool
          {summary.businessTools.length > 0 && ` · ${summary.businessTools.length} 个业务 Tool`}
        </span>
        <span className="ml-auto flex flex-wrap justify-end gap-1">
          {summary.businessTools.map((tool) => (
            <code
              key={tool}
              className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-1"
            >
              {tool}
            </code>
          ))}
        </span>
      </summary>

      <div className="space-y-2 border-t border-hairline px-3 py-2">{rows}</div>
    </details>
  )
}

function TraceRow({ entry }: { entry: TraceEntry }) {
  if (entry.type === 'agent_tool_calls') {
    return (
      <div className="space-y-1">
        {(entry.calls ?? []).map((call, index) => (
          <div key={`${call.name}-${index}`}>
            <div className="flex items-baseline gap-2">
              <span className="text-[11.5px] text-ink-3">路由 →</span>
              <code className="font-mono text-[12px] text-accent-text">{call.name}</code>
            </div>
            <Foldable label="task" text={safeJson(call.args)} mono />
          </div>
        ))}
      </div>
    )
  }

  if (entry.type === 'agent_tool_result') {
    const parsed = parseToolResult(entry.content)
    // 必须去重：业务 Tool 会被同一个专家调用多次（实测 `search_company_knowledge` 出现过 5 次），
    // 直接 map 出 5 个同名 chip 会撞 React 的 key，控制台报 duplicate key 并可能丢节点。
    const tools = dedupe(parsed.businessTools)
    return (
      <div className="space-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-[11.5px] text-ink-3">返回 ←</span>
          <code className="font-mono text-[12px] text-ink-1">
            {parsed.agent ?? entry.name ?? '未知专家'}
          </code>
          {tools.map((tool) => (
            <code
              key={tool}
              className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-ink-2"
            >
              {tool}
            </code>
          ))}
        </div>
        {/* 解析失败时 parsed.raw 就是原始文本，照样折叠展示，不白屏 */}
        <Foldable label="内层回答" text={parsed.answer ?? parsed.raw} />
        <Foldable label="原始载荷" text={parsed.raw} mono />
      </div>
    )
  }

  // 未知类型：兜底展示，绝不因为后端新增了条目类型而白屏
  return <Foldable label={entry.type} text={safeJson(entry)} mono />
}

function safeJson(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

/** 去重保序（用于渲染 key 与计数）。 */
function dedupe(items: string[]): string[] {
  return items.filter((item, index) => items.indexOf(item) === index)
}

interface FoldableProps {
  label: string
  text: string
  mono?: boolean
}

/**
 * 「内层回答」「原始载荷」「task」统一是一个**可折叠的框**。
 *
 * 早先按体积决定"直接铺开还是折起来"（超过阈值才渲染 `<details>`），结果是同一块 UI
 * 时而可点、时而只是一段普通文字 —— 短内容根本没有折叠入口，看起来像功能消失了。
 * 现在一律渲染 `<details>`、一律默认收起，只有内容为空时才不渲染；折叠行为与长短无关。
 */
function Foldable({ label, text, mono = false }: FoldableProps) {
  if (text === '') return null

  const lineCount = text.split('\n').length

  return (
    <details className="group/fold">
      <summary
        className={cn(
          'flex cursor-pointer list-none items-center gap-1.5 text-[11px] text-ink-3',
          'hover:text-ink-2',
        )}
      >
        <span className="transition-transform group-open/fold:rotate-90">▸</span>
        <span>{label}</span>
        <span>
          （共 {text.length} 字符 / {lineCount} 行）
        </span>
      </summary>
      <pre
        className={cn(
          'scroll-slim mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-control bg-surface-0 px-2.5 py-2 text-[11.5px] leading-relaxed text-ink-1',
          mono && 'font-mono',
        )}
      >
        {text}
      </pre>
    </details>
  )
}
