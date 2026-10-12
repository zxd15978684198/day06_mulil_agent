/**
 * 侧边栏的显示/隐藏偏好 —— **左、右两侧各自独立**。
 *
 * 三条设计约束：
 *  1. **两侧互不影响**：只看左栏时不该被迫连右栏一起收起；
 *  2. **持久化**：用户级偏好，刷新后要保持；
 *  3. **可动画**：所以不能用 `display: none`（没法过渡），要用宽度过渡 + 裁剪。
 *
 * 快捷键 `Ctrl/⌘ + B` 只切**左栏** —— 这是 VS Code 等编辑器的既定语义（那个键管的就是
 * 左侧文件树）。右栏不给快捷键，免得"按一下不知道该蹦出哪边"。
 */

import { useCallback, useEffect, useState } from 'react'

export type SidebarSide = 'left' | 'right'

const STORAGE_PREFIX = 'day06.employee-assistant.sidebar-'
const SHORTCUT_SIDE: SidebarSide = 'left'

/** 每侧一份订阅者，保证同屏多个消费者（顶栏按钮 / 栏内按钮）状态同步 */
const listeners: Record<SidebarSide, Set<(hidden: boolean) => void>> = {
  left: new Set(),
  right: new Set(),
}

function keyOf(side: SidebarSide): string {
  return `${STORAGE_PREFIX}${side}-hidden`
}

function readStored(side: SidebarSide): boolean {
  try {
    return localStorage.getItem(keyOf(side)) === '1'
  } catch {
    return false
  }
}

function writeStored(side: SidebarSide, hidden: boolean): void {
  try {
    localStorage.setItem(keyOf(side), hidden ? '1' : '0')
  } catch {
    /* 存不下也要能切 */
  }
}

function toggleSide(side: SidebarSide): void {
  const next = !readStored(side)
  writeStored(side, next)
  for (const listener of listeners[side]) listener(next)
}

/** 返回某一侧的 `[是否隐藏, 切换函数]`。 */
export function useSidebarHidden(side: SidebarSide): readonly [boolean, () => void] {
  const [hidden, setHidden] = useState<boolean>(() => readStored(side))

  useEffect(() => {
    const listener = (next: boolean) => setHidden(next)
    listeners[side].add(listener)
    // 订阅前可能已被别处改过（例如上一次挂载留下的值），对齐一次
    setHidden(readStored(side))
    return () => {
      listeners[side].delete(listener)
    }
  }, [side])

  const toggle = useCallback(() => toggleSide(side), [side])

  return [hidden, toggle] as const
}

/** `Ctrl/⌘ + B` 切换**左栏**。 */
export function useSidebarShortcut(): void {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        toggleSide(SHORTCUT_SIDE)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])
}

export const SIDEBAR_SHORTCUT_HINT = 'Ctrl / ⌘ + B'
