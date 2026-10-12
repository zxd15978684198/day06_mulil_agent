import { useEffect, useRef, useState } from 'react'

import { THEMES, useTheme } from '../lib/theme'
import { cn } from '../lib/utils'

/**
 * 主题切换器。登录页与对话页顶栏各放一个（未登录时也该能换主题 —— 演示时先选主题再登录）。
 *
 * 刻意**不显示色块预览**：色值只存在于 CSS 的 `html[data-theme='...']` 里，
 * 想画预览就得在 TS 里再抄一份十六进制，那是第二处重复维护点。改用文字说明。
 */
export default function ThemeSwitcher({ className }: { className?: string }) {
  const [theme, setTheme] = useTheme()
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement | null>(null)

  const current = THEMES.find((item) => item.id === theme) ?? THEMES[0]

  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false)
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  return (
    <div ref={boxRef} className={cn('relative', className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`切换主题（当前：${current.label}）`}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          'flex items-center gap-1.5 rounded-control border border-hairline bg-surface-2 px-2.5 py-1.5',
          'text-xs text-ink-1 transition-colors hover:border-hairline-strong hover:bg-surface-3',
        )}
      >
        <span aria-hidden className="text-ink-2">
          ◐
        </span>
        <span>{current.label}</span>
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="选择主题"
          className={cn(
            'absolute right-0 z-30 mt-1.5 w-52 overflow-hidden rounded-card',
            'border border-hairline-strong bg-surface-1 py-1',
          )}
        >
          {THEMES.map((item) => {
            const selected = item.id === theme
            return (
              <li key={item.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => {
                    setTheme(item.id)
                    setOpen(false)
                  }}
                  className={cn(
                    'flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition-colors',
                    selected ? 'bg-accent-soft' : 'hover:bg-surface-2',
                  )}
                >
                  <span
                    className={cn(
                      'text-[12.5px]',
                      selected ? 'font-medium text-accent-text' : 'text-ink-0',
                    )}
                  >
                    {item.label}
                  </span>
                  <span className="text-[11px] text-ink-3">{item.hint}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
