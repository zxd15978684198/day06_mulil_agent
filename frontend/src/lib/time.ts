/**
 * 会话时间的显示。
 *
 * 后端 `utc_now()` 给的是 **naive UTC** 的 ISO 串（没有时区后缀）。
 * 直接 `new Date(...)` 会被浏览器当成本地时间，于是"8 小时前建的会话"
 * 看起来发生在未来 —— 所以先补一个 `Z` 再解析。
 *
 * 列表里用相对时间（"刚刚"/"12 分钟前"/"昨天 16:39"）：同一屏里几十条
 * 会话都顶着 `10-16 16:39` 这种戳，横向扫起来反而看不出新旧。
 */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** 解析服务端时间戳；解析不了返回 null（调用方决定降级文案）。 */
export function parseServerTime(raw: string): Date | null {
  if (typeof raw !== 'string' || raw === '') return null
  const parsed = new Date(/[Zz]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 当天的 0 点（本地时区）—— 用来判断"是不是同一天"，不能用 diff/86400000 硬除。 */
function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** 完整时间，`title` 悬浮提示用：`2026-10-16 16:39`。 */
export function formatAbsolute(date: Date): string {
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

function clockOf(date: Date): string {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * 相对时间。`now` 可注入，方便测试与"同一屏内时间基准一致"。
 *
 * 降级顺序：解析失败 → 空串（宁可不显示，也不显示错的时间）。
 */
export function formatRelative(raw: string, now: Date = new Date()): string {
  const date = parseServerTime(raw)
  if (date === null) return ''

  const diff = now.getTime() - date.getTime()
  // 未来时间说明客户端时钟慢或服务端时钟快 —— 直接给绝对时间，不猜
  if (diff < 0) return formatAbsolute(date)

  if (diff < MINUTE) return '刚刚'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} 分钟前`

  const dayGap = Math.round((startOfDay(now) - startOfDay(date)) / DAY)
  if (dayGap === 0) return `今天 ${clockOf(date)}`
  if (dayGap === 1) return `昨天 ${clockOf(date)}`
  if (dayGap < 7) return `${dayGap} 天前`
  if (date.getFullYear() === now.getFullYear()) {
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${clockOf(date)}`
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
