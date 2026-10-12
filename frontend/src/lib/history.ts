/**
 * 对话历史的本地持久化（P6 交付物）。
 *
 * 为什么不塞进 `lib/session.ts`：
 *  - `session.ts` 是 P3 的交付物，已被 `test/logic-check.ts` 用 36 条断言钉住；往里加字段会让那份证据失效；
 *  - 两者的键空间也不同：会话是"一个"，历史是"每个会话一份"。
 *
 * 为什么 R1 需要它：`trace` 是**线程累计**的（C1），前端靠 `traceCursor` 只渲染本轮新增。
 * 如果刷新后消息没了、游标还在，界面上就会出现"这一轮只有轨迹没有对话"的割裂。
 * 持久化消息让"游标 + 消息"始终成对恢复。
 *
 * 这是对计划 `L0-S2`「不做历史会话管理」的一处**刻意越界**：这里只恢复**当前会话**
 * 的消息，没有多会话列表、没有历史检索 —— 属于 `L0-S5`「刷新可续」的应有之义。
 */

import type { TraceEntry } from './api'

const KEY_PREFIX = 'day06.employee-assistant.history.'

/** 只保留最近这么多条，避免 localStorage 被长对话撑爆 */
const MAX_MESSAGES = 60

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  /** 该轮**新增**的轨迹条目（只有助手消息有） */
  trace?: TraceEntry[]
}

function keyOf(sessionId: string): string {
  return `${KEY_PREFIX}${sessionId}`
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
export function loadHistory(sessionId: string): ChatMessage[] {
  if (!sessionId) return []
  try {
    const raw = localStorage.getItem(keyOf(sessionId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isMessage).slice(-MAX_MESSAGES)
  } catch {
    return []
  }
}

export function saveHistory(sessionId: string, messages: ChatMessage[]): void {
  if (!sessionId) return
  try {
    localStorage.setItem(keyOf(sessionId), JSON.stringify(messages.slice(-MAX_MESSAGES)))
  } catch {
    /* 存不下也要能继续聊 */
  }
}

/** 退出登录时清掉本会话的历史。 */
export function clearHistory(sessionId: string): void {
  if (!sessionId) return
  try {
    localStorage.removeItem(keyOf(sessionId))
  } catch {
    /* 忽略 */
  }
}

/** 生成消息 id：只用时间戳 + 随机串，不引第三方 uuid。 */
export function newMessageId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}
