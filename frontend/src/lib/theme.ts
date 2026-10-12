/**
 * 主题注册表与切换。
 *
 * 换肤本身**完全由 CSS 变量完成**（见 `src/index.css` 里的 `html[data-theme='...']`），
 * 这个模块只负责三件事：记住用户选的主题、把它写到 `<html data-theme>`、让界面跟着变。
 * 组件里**一个颜色都不用改** —— 因为所有颜色都走令牌，而令牌是 CSS 变量。
 */

import { useEffect, useState } from 'react'

export type ThemeId = 'indigo' | 'midnight' | 'graphite' | 'daylight'

export interface ThemeDef {
  id: ThemeId
  label: string
  /** 一句话说明这套主题长什么样（不写具体色值，避免和 CSS 里重复维护） */
  hint: string
  scheme: 'dark' | 'light'
}

export const THEMES: readonly ThemeDef[] = [
  { id: 'indigo', label: '靛蓝', hint: '深色 · 靛蓝强调色', scheme: 'dark' },
  { id: 'midnight', label: '午夜', hint: '纯黑 · 高对比', scheme: 'dark' },
  { id: 'graphite', label: '石墨', hint: '中性灰 · 青绿强调色', scheme: 'dark' },
  { id: 'daylight', label: '白昼', hint: '亮色 · 靛蓝强调色', scheme: 'light' },
] as const

export const DEFAULT_THEME: ThemeId = 'indigo'

/**
 * ⚠️ 这个键与候选列表在 `index.html` 的内联脚本里**各有一份拷贝**，必须同步修改。
 * 原因是防闪烁（FOUC）：主题必须在 React 挂载**之前**就写到 `<html>` 上，
 * 而那段脚本跑在打包产物之外，没法 import 这里的东西。这是唯一的重复，别再加第二处。
 */
const STORAGE_KEY = 'day06.employee-assistant.theme'

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && THEMES.some((theme) => theme.id === value)
}

export function loadTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isThemeId(stored)) return stored
  } catch {
    /* 隐私模式下读不到就走默认 */
  }
  return DEFAULT_THEME
}

function saveTheme(id: ThemeId): void {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* 存不下也要能切 */
  }
}

/** 把主题写到 `<html data-theme>`；CSS 里所有 `html[data-theme='...']` 规则由此生效。 */
export function applyTheme(id: ThemeId): void {
  document.documentElement.dataset.theme = id
}

/** 已挂载的切换器订阅者（同一时刻通常只有一个，但保持通用） */
const listeners = new Set<(id: ThemeId) => void>()

/** 切主题：写 DOM、写 localStorage、通知所有订阅者。 */
export function setTheme(id: ThemeId): void {
  applyTheme(id)
  saveTheme(id)
  for (const listener of listeners) listener(id)
}

/**
 * 读取当前主题并保持同步。
 * 初值取自 `loadTheme()`，但 `applyTheme` 可能已由 `index.html` 的内联脚本执行过，
 * 两者正常情况下一致。
 */
export function useTheme(): readonly [ThemeId, (id: ThemeId) => void] {
  const [theme, setLocal] = useState<ThemeId>(() => loadTheme())

  useEffect(() => {
    const listener = (id: ThemeId) => setLocal(id)
    listeners.add(listener)

    // 以防 React 挂载前内联脚本写的值与 localStorage 不一致（例如手动改过）
    const applied = document.documentElement.dataset.theme
    if (isThemeId(applied) && applied !== theme) setLocal(applied)

    return () => {
      listeners.delete(listener)
    }
  }, [theme])

  return [theme, setTheme] as const
}
