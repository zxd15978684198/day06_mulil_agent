/**
 * 会话持久化（localStorage）。
 *
 * 为什么要持久化三样东西（而不是只存 session_id）：
 *  - `sessionId`：后端会话活在进程内存里（C4），刷新页面后只有靠它才能续上；
 *  - `traceCursor`：`trace` 是线程累计的（C1），不记住上一轮长度，刷新后要么重复渲染、
 *    要么整段丢失。这是 R1 方案明确接受的代价；
 *  - `pending`：未决确认没记住的话，刷新后用户会发现自己被 409 锁住却看不到那张卡片（K6）。
 */

import type { Confirmation, Role } from './api'

const STORAGE_KEY = 'day06.employee-assistant.v1'

export interface StoredSession {
  sessionId: string
  displayName: string
  role: Role
  /** 上一轮响应的 `trace.length` */
  traceCursor: number
  /** 尚未处理的确认；没有则为 null */
  pending: Confirmation | null
}

/**
 * 读取持久化的会话。
 *
 * **任何异常都返回 null** —— 存坏的 localStorage 绝不允许把页面炸掉，
 * 最坏情况就是让用户重新登录一次。
 */
export function loadSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null

    const parsed = JSON.parse(raw) as Partial<StoredSession> | null
    if (!parsed || typeof parsed.sessionId !== 'string' || parsed.sessionId === '') {
      return null
    }

    const cursor = Number(parsed.traceCursor)

    return {
      sessionId: parsed.sessionId,
      displayName: typeof parsed.displayName === 'string' ? parsed.displayName : '',
      role: parsed.role === 'hr' ? 'hr' : 'employee',
      traceCursor: Number.isFinite(cursor) && cursor >= 0 ? Math.floor(cursor) : 0,
      pending: coercePending(parsed.pending),
    }
  } catch {
    return null
  }
}

/**
 * 把 localStorage 里的 `pending` 收敛成合法的确认载荷，或 null。
 *
 * 不能用 `?? null` 糊过去：`'x' ?? null` 会原样返回 `'x'`。
 *
 * 判据是**要么有非空字符串 `action`**（契约 `C2`：`action` 是模板分派的唯一依据），
 * **要么有字符串 `message`**（契约 `K7`：后端对"不是字典的中断值"会退化成
 * `{"message": str(value)}`，这种载荷没有 `action` 但必须能恢复出来 ——
 * 否则刷新后卡片消失、而服务端仍挂着待确认，用户会被 409 锁住却看不到任何按钮）。
 */
function coercePending(value: unknown): Confirmation | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as { action?: unknown; message?: unknown }
  const hasAction = typeof record.action === 'string' && record.action !== ''
  const hasMessage = typeof record.message === 'string' && record.message !== ''
  if (!hasAction && !hasMessage) return null
  return value as Confirmation
}

/** 写入会话；隐私模式/配额满时静默失败，不影响本次会话继续用。 */
export function saveSession(session: StoredSession): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    /* 忽略：存不下也要能继续聊 */
  }
}

/** 清空会话。R3 的出口：拿到 404 就调它，然后回登录页。 */
export function clearSession(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 忽略 */
  }
}
