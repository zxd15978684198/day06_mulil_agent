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
 *
 * `action` 是标题栏右侧的操作位（例如"会话"区块里的新建按钮）——
 * 放在标题栏而不是内容区，是为了让操作永远浮在滚动区之外：
 * 列表滚到底时按钮不会跟着消失。
 */
export default function PanelSection({
  title,
  hint,
  action,
  children,
  className,
  bodyClassName,
}: {
  title: string
  /** 标题右侧的小字（计数、状态一类） */
  hint?: string
  /** 标题栏最右侧的操作位 */
  action?: ReactNode
  children: ReactNode
  /** 外层（区块）额外样式 —— 高度上限、伸缩行为都加在这里 */
  className?: string
  /** 内容区额外样式 —— 内边距、滚动容器加在这里 */
  bodyClassName?: string
}) {
  return (
    <section
      className={cn(
        'overflow-hidden rounded-card border border-hairline bg-surface-2',
        className,
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b border-hairline bg-surface-1/40 py-1.5 pl-3 pr-1.5">
        <h2 className="flex min-w-0 items-baseline gap-1.5">
          <span className="shrink-0 text-[11.5px] font-medium tracking-wide text-ink-1">{title}</span>
          {hint !== undefined && (
            <span className="truncate text-[11px] tabular-nums text-ink-3">{hint}</span>
          )}
        </h2>
        {action}
      </header>
      <div className={cn('px-3 py-3', bodyClassName)}>{children}</div>
    </section>
  )
}
