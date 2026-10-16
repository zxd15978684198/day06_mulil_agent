/**
 * 对话历史的本地缓存 + 每会话的轨迹游标。
 *
 * **本地历史不再是唯一事实来源**：`GET /api/threads/{id}/messages` 才是。
 * 这里保留它，只为了两件服务端做不到的事：
 *
 *  1. **轨迹**：`trace` 只存在检查点里，不落 MySQL，回放接口不返回它。
 *     想刷新后右栏还有内容，就只能本地留一份；
 *  2. **乐观渲染**：用户消息发出去的瞬间就要出现在屏幕上，
 *     而服务端要等这一轮跑完才会在下次回放里给出它。
 *
 * `trace` 是**线程累计**的，前端靠游标只渲染本轮新增，所以游标必须**按 thread 存**：
 * 加了会话列表之后，共用单个游标会在切换会话时把上一个会话的长度带过来。
 *
 * 键空间（三个独立前缀，互不干扰）：
 *   - `day06.employee-assistant.history.<threadId>` → 消息数组
 *   - `day06.employee-assistant.cursor.<threadId>`  → 轨迹游标
 */

import type { TraceEntry } from './api'

const KEY_PREFIX = 'day06.employee-assistant.history.'
const CURSOR_PREFIX = 'day06.employee-assistant.cursor.'

/** 只保留最近这么多条，避免 localStorage 被长对话撑爆 */
const MAX_MESSAGES = 60

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  /** 该轮**新增**的轨迹条目（只有助手消息有） */
  trace?: TraceEntry[]
}

function keyOf(threadId: string): string {
  return `${KEY_PREFIX}${threadId}`
}

function cursorKeyOf(threadId: string): string {
  return `${CURSOR_PREFIX}${threadId}`
}

function isMessage(value: unknown): value is ChatMessage {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const candidate = value as Partial<ChatMessage>
  return (
    typeof candidate.id === 'string' &&
    (candidate.role === 'user' || candidate.role === 'assistant') &&
    typeof candidate.text === 'string'
  )
}

/** 读取某个会话的历史；任何异常都返回空数组（存坏的数据不许炸页面）。 */
export function loadHistory(threadId: string): ChatMessage[] {
  if (!threadId) return []
  try {
    const raw = localStorage.getItem(keyOf(threadId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isMessage).slice(-MAX_MESSAGES)
  } catch {
    return []
  }
}

export function saveHistory(threadId: string, messages: ChatMessage[]): void {
  if (!threadId) return
  try {
    localStorage.setItem(keyOf(threadId), JSON.stringify(messages.slice(-MAX_MESSAGES)))
  } catch {
    /* 存不下也要能继续聊 */
  }
}

/** 退出登录 / 删除会话时清掉该会话的缓存。 */
export function clearHistory(threadId: string): void {
  if (!threadId) return
  try {
    localStorage.removeItem(keyOf(threadId))
    localStorage.removeItem(cursorKeyOf(threadId))
  } catch {
    /* 忽略 */
  }
}

/**
 * 读取该会话的轨迹游标（已经渲染过的累计条目数）。
 *
 * 读不到就返回 0 —— 宁可多渲染一遍轨迹，也不能因为缓存坏了漏渲染。
 */
export function loadTraceCursor(threadId: string): number {
  if (!threadId) return 0
  try {
    const raw = localStorage.getItem(cursorKeyOf(threadId))
    const value = Number(raw)
    return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0
  } catch {
    return 0
  }
}

export function saveTraceCursor(threadId: string, cursor: number): void {
  if (!threadId) return
  try {
    localStorage.setItem(cursorKeyOf(threadId), String(Math.max(0, Math.floor(cursor))))
  } catch {
    /* 忽略 */
  }
}

/** 生成消息 id：只用时间戳 + 随机串，不引第三方 uuid。 */
export function newMessageId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}
