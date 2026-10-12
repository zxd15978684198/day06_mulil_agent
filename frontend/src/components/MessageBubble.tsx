import { motion, useReducedMotion } from 'motion/react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { ChatMessage } from '../lib/history'
import { cn } from '../lib/utils'
import TracePanel from './TracePanel'

/**
 * 一条消息。
 *
 * 两种形态差别很大：
 *  - 用户消息：右对齐气泡（`surface-2`），纯文本，不解析 Markdown；
 *  - 助手消息：整宽排版，**走 Markdown（含 GFM 表格）** —— 后端的回答大量使用
 *    表格与列表（实测审批回复就是一张 6 行表），按纯文本渲染会很难看。
 *    计划 `L0-S2` 把"markdown 富渲染"留在范围内，富媒体（图片/附件）才在范围外。
 *
 * 动效刻意**极轻**（淡入 + 6px 上浮，180ms）：这套界面的视觉规则是"靠 surface 阶梯
 * 和发丝边框分层"，动效只需要让新内容"出现得顺"，不该抢注意力。
 * `prefers-reduced-motion` 打开时**完全不做动画**。
 *
 * `streaming` 为真时表示这条正文正在被流式填充：末尾跟一个 `▍` 光标。
 * 光标是**拼进 Markdown 源码**的，不是独立的 DOM 节点 —— 这样它永远紧跟着最后
 * 一个字符（而不是掉到段落下面）。代价是它不能自己做闪烁动画。
 */
export default function MessageBubble({
  message,
  streaming = false,
}: {
  message: ChatMessage
  /** 正在流式接收：正文末尾跟一个光标，流结束（或中断）后撤掉 */
  streaming?: boolean
}) {
  const reduceMotion = useReducedMotion()

  if (message.role === 'user') {
    return (
      <motion.div className="flex justify-end" {...enter(reduceMotion)}>
        <div className="max-w-[80%] whitespace-pre-wrap rounded-card border border-hairline bg-surface-2 px-3.5 py-2.5 text-sm leading-relaxed text-ink-0">
          {message.text}
        </div>
      </motion.div>
    )
  }

  const hasText = message.text.trim() !== ''

  return (
    <motion.div className="flex justify-start" {...enter(reduceMotion)}>
      <div className="w-full max-w-[92%]">
        {/* 中断那一轮 answer 是 null（K8）：**没有助手气泡**，但轨迹仍然值得看
            —— 它解释了"为什么会弹出确认卡片"。所以这里只跳过气泡，不跳过面板。
            流式期间即使一个字都还没吐出来也要出气泡：光标得有个落脚处。 */}
        {(hasText || streaming) && (
          <div
            className={cn(
              'rounded-card border border-hairline bg-surface-1 px-3.5 py-2.5 text-sm text-ink-0',
            )}
          >
            <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
              {streaming ? `${message.text}▍` : message.text}
            </Markdown>
          </div>
        )}

        {/* 空轨迹时 TracePanel 自己返回 null，这里不用判断 */}
        <TracePanel entries={message.trace ?? []} />
      </div>
    </motion.div>
  )
}

/** 统一的入场参数；`prefers-reduced-motion` 时返回空对象（= 不介入）。 */
function enter(reduceMotion: boolean | null) {
  if (reduceMotion) return {}
  return {
    initial: { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.18, ease: 'easeOut' as const },
  }
}

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mt-3 mb-1.5 text-sm font-semibold text-ink-0">{children}</h3>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mt-3 mb-1.5 text-sm font-semibold text-ink-0">{children}</h3>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h4 className="mt-3 mb-1.5 text-[13px] font-semibold text-ink-0">{children}</h4>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-ink-0">{children}</strong>
  ),
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-accent-text underline underline-offset-2"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-hairline-strong pl-3 text-ink-1">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-hairline" />,
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="scroll-slim my-2 overflow-x-auto">
      <table className="w-full border-collapse text-[12.5px]">{children}</table>
    </div>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="border border-hairline bg-surface-2 px-2 py-1 text-left font-medium text-ink-1">
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="border border-hairline px-2 py-1 align-top text-ink-0">{children}</td>
  ),
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="scroll-slim my-2 overflow-x-auto rounded-control border border-hairline bg-surface-0 px-3 py-2 font-mono text-[12px] leading-relaxed text-ink-1">
      {children}
    </pre>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[12px] text-ink-1">
      {children}
    </code>
  ),
}
