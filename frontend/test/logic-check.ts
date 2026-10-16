/**
 * P2/P3/P4 逻辑层校验（不是 TDD，是**用实测数据跑一遍**）。
 *
 * 数据来源：`.tmp/live_test.txt` 里同一 session 连发三轮的真实响应。
 * 跑法：`cd frontend && node tests/logic-check.ts`
 *   （Node 22.6+ 支持直接跑 .ts，做类型擦除）
 */

import { parseToolResult, sliceNewTrace, summarizeTrace } from '../src/lib/trace.ts'
import { clearSession, loadSession, saveSession } from '../src/lib/session.ts'
import {
  clearHistory,
  loadHistory,
  loadTraceCursor,
  saveHistory,
  saveTraceCursor,
} from '../src/lib/history.ts'
import { ApiError } from '../src/lib/api.ts'
import { formatAbsolute, formatRelative, parseServerTime } from '../src/lib/time.ts'

let pass = 0
let fail = 0

function check(name: string, ok: boolean, detail = ''): void {
  if (ok) {
    pass += 1
    console.log(`  PASS  ${name}`)
  } else {
    fail += 1
    console.log(`  FAIL  ${name}${detail ? `  ← ${detail}` : ''}`)
  }
}

// ---------------------------------------------------------------------------
// 真实数据（逐字取自 .tmp/live_test.txt）
// ---------------------------------------------------------------------------

const ROUND_A_TRACE: unknown[] = []

const ROUND_B_TRACE = [
  {
    type: 'agent_tool_calls',
    calls: [
      {
        name: 'ask_employee_service_agent',
        args: {
          task: '员工申请一台 24 英寸显示器，申请理由：原有显示器已损坏，需要更换使用。请协助提交该设备申请。',
        },
      },
    ],
  },
]

const RESULT_CONTENT = JSON.stringify({
  agent: 'employee_service_agent',
  answer: '申请已提交成功 ✅\n\n| 项目 | 内容 |\n|---|---|\n| 申请单号 | REQ-2026-0020 |',
  business_tools: ['list_requestable_devices', 'create_device_request'],
})

const ROUND_C_TRACE = [ROUND_B_TRACE[0], { type: 'agent_tool_result', name: 'ask_employee_service_agent', content: RESULT_CONTENT }]

console.log('\n[1] C1 游标切片：三轮连发不许出现重复条目')

let cursor = 0
const a = sliceNewTrace(ROUND_A_TRACE as never, cursor)
check('A 轮 fresh 为空（"你好"不触发 Agent 调用）', a.fresh.length === 0, `got ${a.fresh.length}`)
check('A 轮 nextCursor = 0', a.nextCursor === 0)
cursor = a.nextCursor

const b = sliceNewTrace(ROUND_B_TRACE as never, cursor)
check('B 轮 fresh = 1 条', b.fresh.length === 1, `got ${b.fresh.length}`)
check(
  'B 轮那条是 agent_tool_calls',
  b.fresh.length === 1 && (b.fresh[0] as { type: string }).type === 'agent_tool_calls',
)
check('B 轮 nextCursor = 1', b.nextCursor === 1)
cursor = b.nextCursor

const c = sliceNewTrace(ROUND_C_TRACE as never, cursor)
check('C 轮 fresh = 1 条（**不是 2 条**，这就是 K1 的防重复）', c.fresh.length === 1, `got ${c.fresh.length}`)
check(
  'C 轮新增的那条是 agent_tool_result',
  c.fresh.length === 1 && (c.fresh[0] as { type: string }).type === 'agent_tool_result',
)
check('C 轮 nextCursor = 2', c.nextCursor === 2)

console.log('\n[2] C1 反面对照：不用游标（直接 append）会怎样')
check(
  '三轮原始长度累计 0→1→2，恰好等于 naive append 的重复来源',
  ROUND_A_TRACE.length === 0 && ROUND_B_TRACE.length === 1 && ROUND_C_TRACE.length === 2,
)

console.log('\n[3] 游标越界（换会话/后端重启/被手改）')

const outOfRange = sliceNewTrace(ROUND_C_TRACE as never, 99)
check('越界时回退到 0，把整段当新增（宁可见不静默）', outOfRange.fresh.length === 2, `got ${outOfRange.fresh.length}`)
const negative = sliceNewTrace(ROUND_C_TRACE as never, -5)
check('负数游标同样回退到 0', negative.fresh.length === 2)
const exact = sliceNewTrace(ROUND_C_TRACE as never, 2)
check('游标恰好等于长度时 fresh 为空（正常的一轮）', exact.fresh.length === 0)

console.log('\n[4] agent_tool_result.content 是 JSON 字符串')

const parsed = parseToolResult(RESULT_CONTENT)
check('解析出 agent 名', parsed.agent === 'employee_service_agent', String(parsed.agent))
check(
  '解析出内层业务 Tool 名',
  parsed.businessTools.join(',') === 'list_requestable_devices,create_device_request',
  parsed.businessTools.join(','),
)
check('解析出内层回答', typeof parsed.answer === 'string' && parsed.answer.includes('REQ-2026-0020'))

console.log('\n[5] 解析失败的兜底（不许白屏）')
const broken = parseToolResult('{"agent": "x", "answer": "截断了的')
check('坏 JSON 不抛异常', true)
check('坏 JSON 仍原样保留 raw 文本', broken.raw.includes('截断了的'))
check('坏 JSON 的 businessTools 退化为空数组', broken.businessTools.length === 0)
check('undefined 安全', parseToolResult(undefined).raw === '')

console.log('\n[6] 摘要：空轨迹必须能被识别为"不该渲染面板"')
check('空轨迹摘要全空', summarizeTrace([]).agentTools.length === 0 && summarizeTrace([]).businessTools.length === 0)
const sumB = summarizeTrace(ROUND_B_TRACE as never)
check('B 轮摘要：1 个专家、0 个业务 Tool', sumB.agentTools.join(',') === 'ask_employee_service_agent' && sumB.businessTools.length === 0)
const sumC = summarizeTrace(ROUND_C_TRACE as never)
check('C 轮摘要：业务 Tool 已从内层字符串里提取出来', sumC.businessTools.length === 2, sumC.businessTools.join(','))
check('专家名去重（B 与 C 都提到同一个专家，摘要里只出现一次）', sumC.agentTools.length === 1, sumC.agentTools.join(','))

console.log('\n[7] localStorage 登录态的防御性（新契约：token + user + threadId）')

const store = new Map<string, string>()
;(globalThis as unknown as { localStorage: Storage }).localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
  key: () => null,
  length: 0,
} as unknown as Storage

const IDENTITY = {
  user_id: 'USR-001',
  username: 'zhang_wei',
  display_name: '张伟',
  role: 'employee' as const,
  department_id: 'DEPT-PRODUCT',
}
const THREAD = 'a57f6da7-8be4-45eb-95b8-5b3d23cda562'

check('空存储 → null', loadSession() === null)

saveSession({ token: 'eyJhbGciOi.tests.token', user: IDENTITY, threadId: THREAD })
const loaded = loadSession()
check('往返一致：token', loaded?.token === 'eyJhbGciOi.tests.token')
check('往返一致：中文 display_name', loaded?.user.display_name === '张伟')
check('往返一致：user_id', loaded?.user.user_id === 'USR-001')
check('往返一致：threadId', loaded?.threadId === THREAD)

saveSession({ token: 't', user: IDENTITY, threadId: null })
check('threadId 为 null 时往返仍是 null（刚登录还没建会话）', loadSession()?.threadId === null)

store.set('day06.employee-assistant.v1', '{不是合法 JSON')
check('坏 JSON → null（不许炸页面）', loadSession() === null)

store.set('day06.employee-assistant.v1', JSON.stringify({ user: IDENTITY }))
check('缺 token → null', loadSession() === null)

store.set('day06.employee-assistant.v1', JSON.stringify({ token: 't' }))
check('缺 user → null（身份只认 GET /api/auth/me 给的）', loadSession() === null)

store.set('day06.employee-assistant.v1', JSON.stringify({ token: 't', user: { user_id: '' } }))
check('user_id 为空串 → null', loadSession() === null)

store.set(
  'day06.employee-assistant.v1',
  JSON.stringify({ token: 't', user: { user_id: 'USR-0x', role: '老板', display_name: 42 }, threadId: 7 }),
)
const dirty = loadSession()
check('脏 role 收敛成 employee', dirty?.user.role === 'employee')
check('非字符串 display_name 收敛成空串', dirty?.user.display_name === '')
check('非字符串 threadId 收敛成 null', dirty?.threadId === null)

store.set('day06.employee-assistant.v1', JSON.stringify({ token: 't', user: { user_id: 'USR-003', role: 'hr' } }))
check('role 为 hr 时保留 hr（不能把 HR 降成员工）', loadSession()?.user.role === 'hr')

clearSession()
check('clearSession 后为 null', loadSession() === null)

console.log('\n[8] 轨迹游标按 thread 隔离（加了会话列表之后必须如此）')

const T1 = 'thread-1'
const T2 = 'thread-2'
const cursorKey = (id: string) => `day06.employee-assistant.cursor.${id}`
const historyKey = (id: string) => `day06.employee-assistant.history.${id}`

check('没存过的会话 → 0', loadTraceCursor(T1) === 0)

saveTraceCursor(T1, 3)
check('读出写入的值', loadTraceCursor(T1) === 3)
check('另一个会话不受影响（这就是按 thread 存的意义）', loadTraceCursor(T2) === 0)

saveTraceCursor(T1, -5)
check('负数收敛成 0', loadTraceCursor(T1) === 0)

store.set(cursorKey(T1), '不是数字')
check('脏数据 → 0（宁可多渲染一遍轨迹）', loadTraceCursor(T1) === 0)

store.set(cursorKey(T1), '2.7')
check('小数向下取整', loadTraceCursor(T1) === 2)

store.set(cursorKey(T1), '-1')
check('字符串负数 → 0', loadTraceCursor(T1) === 0)

console.log('\n[9] 每会话历史缓存的防御性')

saveHistory(T1, [
  { id: 'm1', role: 'user', text: '你好' },
  { id: 'm2', role: 'assistant', text: '有什么可以帮你' },
])
check('往返一致', loadHistory(T1).length === 2 && loadHistory(T1)[1].text === '有什么可以帮你')
check('另一个会话的历史为空', loadHistory(T2).length === 0)

store.set(historyKey(T1), JSON.stringify([{ id: 1 }, { id: 'ok', role: 'user', text: 'x' }]))
check('脏条目被过滤', loadHistory(T1).length === 1 && loadHistory(T1)[0].id === 'ok')

store.set(historyKey(T1), '不是数组')
check('非数组 → 空数组', loadHistory(T1).length === 0)

saveHistory(T1, [{ id: 'm1', role: 'user', text: '你好' }])
saveTraceCursor(T1, 5)
saveTraceCursor(T2, 9)
clearHistory(T1)
check('clearHistory 同时清掉历史与游标', loadHistory(T1).length === 0 && loadTraceCursor(T1) === 0)
check('clearHistory 只按传入的 threadId 清（T2 的游标仍在）', loadTraceCursor(T2) === 9)

console.log('\n[10] 错误分型')

const e404 = new ApiError('thread_missing', 404, 'x')
check(
  'ApiError 带 kind/status 且是 Error 实例',
  e404.kind === 'thread_missing' && e404.status === 404 && e404 instanceof Error,
)
check('message 被 Error 保留', new ApiError('busy', 409, '上一条还在处理').message === '上一条还在处理')

console.log('\n[11] 会话时间：naive UTC 解析 + 相对时间')

// 服务端时间戳是 naive UTC（没有时区后缀），必须补 Z 再解析，
// 否则"8 小时前建的会话"会被当成本地时间，显示成未来。
check(
  'naive UTC 串按 UTC 解析（补 Z）',
  parseServerTime('2026-10-16T08:39:00')?.getTime() === Date.UTC(2026, 9, 16, 8, 39, 0),
)
check(
  '带 Z 的串结果一致',
  parseServerTime('2026-10-16T08:39:00Z')?.getTime() === parseServerTime('2026-10-16T08:39:00')?.getTime(),
)
check('空串 → null', parseServerTime('') === null)
check('坏时间串 → null', parseServerTime('不是时间') === null)

// 相对时间的分支都用"本地日历"构造，避免测试机时区不同导致今天/昨天错位
const at = (y: number, m: number, d: number, h: number, mi = 0, s = 0) =>
  new Date(y, m - 1, d, h, mi, s)
/** 把某个本地时刻写成服务端那种 naive UTC 串（同一瞬间） */
const naiveOf = (date: Date) => date.toISOString().replace('Z', '')

const now = at(2026, 10, 16, 15, 0)
check('40 秒内 → 刚刚', formatRelative(naiveOf(at(2026, 10, 16, 14, 59, 20)), now) === '刚刚')
check('5 分钟前 → 5 分钟前', formatRelative(naiveOf(at(2026, 10, 16, 14, 55)), now) === '5 分钟前')
check('当天更早 → 今天 hh:mm', formatRelative(naiveOf(at(2026, 10, 16, 12, 0)), now) === '今天 12:00')
check('前一天 → 昨天 hh:mm', formatRelative(naiveOf(at(2026, 10, 15, 12, 0)), now) === '昨天 12:00')
check('4 天前 → 4 天前', formatRelative(naiveOf(at(2026, 10, 12, 12, 0)), now) === '4 天前')
check('8 天前 → 月-日 hh:mm', formatRelative(naiveOf(at(2026, 10, 8, 12, 0)), now) === '10-08 12:00')
check('跨年 → 完整日期', formatRelative(naiveOf(at(2025, 10, 8, 12, 0)), now) === '2025-10-08')
check('未来时间不猜，直接给绝对时间', formatRelative(naiveOf(at(2026, 10, 16, 16, 30)), now) === '2026-10-16 16:30')
check('解析失败 → 空串（宁可不显示）', formatRelative('不是时间', now) === '')
check('绝对时间格式', formatAbsolute(at(2026, 10, 16, 16, 39)) === '2026-10-16 16:39')

console.log(`\n===== 结果：${pass} passed, ${fail} failed =====`)
if (fail > 0) process.exit(1)
