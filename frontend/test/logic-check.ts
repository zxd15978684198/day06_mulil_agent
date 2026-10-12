/**
 * P2/P3/P4 逻辑层校验（不是 TDD，是**用实测数据跑一遍**）。
 *
 * 数据来源：`.tmp/live_test.txt` 里同一 session 连发三轮的真实响应。
 * 跑法：`cd frontend && node test/logic-check.ts`
 *   （Node 22.6+ 支持直接跑 .ts，做类型擦除）
 */

import { parseToolResult, sliceNewTrace, summarizeTrace } from '../src/lib/trace.ts'
import { clearSession, loadSession, saveSession } from '../src/lib/session.ts'
import { ApiError } from '../src/lib/api.ts'

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

console.log('\n[7] localStorage 会话持久化的防御性')

const store = new Map<string, string>()
;(globalThis as unknown as { localStorage: Storage }).localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
  key: () => null,
  length: 0,
} as unknown as Storage

check('空存储 → null', loadSession() === null)

saveSession({
  sessionId: 'a57f6da7-8be4-45eb-95b8-5b3d23cda562',
  displayName: '张伟',
  role: 'employee',
  traceCursor: 2,
  pending: { action: 'create_device_request', candidate: { request_id: 'REQ-2026-0020' } },
})
const loaded = loadSession()
check('往返一致：sessionId', loaded?.sessionId === 'a57f6da7-8be4-45eb-95b8-5b3d23cda562')
check('往返一致：中文 displayName', loaded?.displayName === '张伟')
check('往返一致：traceCursor', loaded?.traceCursor === 2)
check('往返一致：pending 卡片的 action', loaded?.pending?.action === 'create_device_request')

store.set('day06.employee-assistant.v1', '{不是合法 JSON')
check('坏 JSON → null（不许炸页面）', loadSession() === null)

store.set('day06.employee-assistant.v1', JSON.stringify({ displayName: '没有 sessionId' }))
check('缺 sessionId → null', loadSession() === null)

store.set(
  'day06.employee-assistant.v1',
  JSON.stringify({ sessionId: 'x', role: '老板', traceCursor: -3, displayName: 42, pending: 'x' }),
)
const dirty = loadSession()
check('脏 role 收敛成 employee', dirty?.role === 'employee')
check('负 traceCursor 收敛成 0', dirty?.traceCursor === 0)
check('非字符串 displayName 收敛成空串', dirty?.displayName === '')
check('非对象 pending 收敛成 null', dirty?.pending === null)

clearSession()
check('clearSession 后为 null', loadSession() === null)

console.log('\n[8] 错误四态映射')

const e404 = new ApiError('session_expired', 404, 'x')
check('ApiError 带 kind/status', e404.kind === 'session_expired' && e404.status === 404 && e404 instanceof Error)

console.log(`\n===== 结果：${pass} passed, ${fail} failed =====`)
if (fail > 0) process.exit(1)
