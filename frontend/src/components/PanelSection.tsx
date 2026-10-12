import type { ReactNode } from 'react'

import { cn } from '../lib/utils'

/**
 * 侧栏里的一个**区块**。
 *
 * 为什么把边界放在"区块"这一级，而不是"条目"那一级：
 * 这个侧栏前后走了两个极端 ——
 *  ① 第一版给每条能力、每个示例都套 `border + bg + rounded`，六七个盒子叠起来是一堵"格子墙"；
 *  ② 第二版把框全去掉，结果内容糊成一片、分不出组（用户原话："多有内容都混到一块了"）。
 * 正确的粒度在中间：**分组有边界，条目靠间距与字重**。
 * 所以边框只画在区块上，区块内部一条线都不画。
 */
export default function PanelSection({
  title,
  hint,
  children,
  className,
}: {
  title: string
  /** 标题右侧的小字（计数、状态一类） */
  hint?: string
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={cn(
        'overflow-hidden rounded-card border border-hairline bg-surface-2',
        className,
      )}
    >
      <header className="flex items-baseline justify-between gap-2 border-b border-hairline bg-surface-1/40 px-3 py-2">
        <h2 className="text-[11.5px] font-medium tracking-wide text-ink-1">{title}</h2>
        {hint !== undefined && <span className="shrink-0 text-[11px] text-ink-3">{hint}</span>}
      </header>
      <div className="px-3 py-3">{children}</div>
    </section>
  )
}
