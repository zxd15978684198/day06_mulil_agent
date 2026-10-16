/**
 * 登录态持久化（localStorage）。
 *
 * 只存三样：`token`、服务端认定的身份、当前 `threadId`。
 *
 * **为什么不再存 `pending` 和 `traceCursor`**（旧契约里它们都在这里）：
 *
 *  - `pending` 现在由服务端说了算 —— `GET /api/threads/{id}/messages` 会带回
 *    `needs_confirmation` + `confirmation`。本地再存一份迟早和服务端打架，
 *    典型症状是"本地有卡片、服务端说没有"：点一下必然 409 `no_pending`，
 *    而用户看到的按钮明明存在；
 *  - `traceCursor` 改成**按 thread 存**（见 `lib/history.ts`）。多了会话列表之后，
 *    单个游标会在切换会话时把上一个会话的轨迹长度带过来，右栏就会少渲染一段。
 *
 * Token 放 localStorage 是教学项目的取舍（刷新不掉线最简单）；
 * 它等价于明文口令的短时凭证，真要上线应换成 HttpOnly Cookie + CSRF 防护。
 */

import type { Identity, Role } from './api'

const STORAGE_KEY = 'day06.employee-assistant.v1'

export interface StoredSession {
  token: string
  /** 由 `GET /api/auth/me` 返回；展示名与角色一律用它，不用登录响应里的 */
  user: Identity
  /** 当前会话；还没建或刚退出时为 null */
  threadId: string | null
}

function coerceRole(value: unknown): Role {
  return value === 'hr' ? 'hr' : 'employee'
}

function coerceIdentity(value: unknown): Identity | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Partial<Identity>
  if (typeof record.user_id !== 'string' || record.user_id === '') return null
  return {
    user_id: record.user_id,
    username: typeof record.username === 'string' ? record.username : '',
    display_name: typeof record.display_name === 'string' ? record.display_name : '',
    role: coerceRole(record.role),
    department_id: typeof record.department_id === 'string' ? record.department_id : '',
  }
}

/**
 * 读取持久化的登录态。
 *
 * **任何异常都返回 null** —— 存坏的 localStorage 绝不允许把页面炸掉，
 * 最坏情况就是让用户重新登录一次。
 *
 * 注意这里**不校验 token 是否过期**：过期由服务端用 401 告诉我们，
 * 前端自己解 JWT 只会引入时钟不同步这一类新 bug。
 */
export function loadSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null

    const parsed = JSON.parse(raw) as Partial<StoredSession> | null
    if (!parsed || typeof parsed.token !== 'string' || parsed.token === '') return null

    const user = coerceIdentity(parsed.user)
    if (user === null) return null

    return {
      token: parsed.token,
      user,
      threadId: typeof parsed.threadId === 'string' && parsed.threadId !== '' ? parsed.threadId : null,
    }
  } catch {
    return null
  }
}

/** 写入登录态；隐私模式/配额满时静默失败，不影响本次会话继续用。 */
export function saveSession(session: StoredSession): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    /* 忽略：存不下也要能继续聊 */
  }
}

/** 清空登录态。401 的出口：收到它就调它，然后回登录页。 */
export function clearSession(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 忽略 */
  }
}
