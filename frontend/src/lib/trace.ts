/**
 * 轨迹的切片与规整。
 *
 * 这是全前端**最容易出错**的一个模块，因为后端的 `trace` 有三层反直觉：
 *  1. 它是**线程累计**的，不是本轮增量（C1）—— 直接 append 会让第 N 轮出现 N 份重复条目（K1）；
 *  2. `agent_tool_result.content` 是**一个 JSON 字符串**，内层业务 Tool 名藏在字符串里（实测）；
 *  3. 条目类型以后可能增加，所以渲染层必须对未知 `type` 兜底，不能白屏。
 */

import type { TraceEntry } from './api'

export interface SlicedTrace {
  /** 本轮新增的条目 */
  fresh: TraceEntry[]
  /** 下一轮该用的游标（= 后端这次给的全长） */
  nextCursor: number
}

/**
 * R1 的游标切片。
 *
 * 游标越界时（`cursor > trace.length`：换过会话、后端重启、手工改过 localStorage）
 * **故意回退到 0 而不是夹到 length**：夹到 length 会得到空数组，用户看到的是
 * "这一轮什么都没发生"这种安静的错误；回退到 0 最坏只是多显示几条历史，
 * 而"多显示"是可见的、可诊断的。宁可见、不静默。
 */
export function sliceNewTrace(
  trace: TraceEntry[] | undefined,
  cursor: number,
): SlicedTrace {
  const all = Array.isArray(trace) ? trace : []
  const safeCursor =
    Number.isFinite(cursor) && cursor >= 0 && cursor <= all.length ? Math.floor(cursor) : 0
  return { fresh: all.slice(safeCursor), nextCursor: all.length }
}

export interface ParsedToolResult {
  /** 内层专家的名字，例如 `employee_service_agent` */
  agent: string | null
  /** 内层专家的完整回答（可能是一大段 Markdown） */
  answer: string | null
  /** 内层真正调用的业务 Tool 名，例如 `["list_requestable_devices", "create_device_request"]` */
  businessTools: string[]
  /** 原始文本，解析失败时用来兜底展示 */
  raw: string
}

/**
 * 解析 `agent_tool_result.content`。
 *
 * **解析失败不抛异常、不白屏**：整段当纯文本返回（`raw`），由渲染层折叠展示。
 * 这条兜底是必须的 —— 内层回答是模型生成的 Markdown，不保证是合法 JSON，
 * 而且模型完全可能输出被截断的 JSON。
 */
export function parseToolResult(content: unknown): ParsedToolResult {
  const raw =
    typeof content === 'string'
      ? content
      : content == null
        ? ''
        : safeStringify(content)

  try {
    const obj = JSON.parse(raw) as Record<string, unknown> | null
    if (obj !== null && typeof obj === 'object' && !Array.isArray(obj)) {
      return {
        agent: typeof obj.agent === 'string' ? obj.agent : null,
        answer: typeof obj.answer === 'string' ? obj.answer : null,
        businessTools: Array.isArray(obj.business_tools)
          ? obj.business_tools.filter((x): x is string => typeof x === 'string')
          : [],
        raw,
      }
    }
  } catch {
    /* 落到下面的纯文本兜底 */
  }

  return { agent: null, answer: null, businessTools: [], raw }
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value) ?? String(value)
  } catch {
    return String(value)
  }
}

export interface TraceSummary {
  /** 本轮被调用的专家（Agent Tool 名） */
  agentTools: string[]
  /** 本轮内层真正执行的业务 Tool 名（去重保序） */
  businessTools: string[]
}

/** 折叠面板的摘要行用。**空轨迹返回两个空数组** —— 调用方据此决定不渲染面板。 */
export function summarizeTrace(entries: TraceEntry[]): TraceSummary {
  const agentTools: string[] = []
  const businessTools: string[] = []

  for (const entry of entries) {
    if (entry.type === 'agent_tool_calls') {
      for (const call of entry.calls ?? []) {
        if (typeof call?.name === 'string') agentTools.push(call.name)
      }
    } else if (entry.type === 'agent_tool_result') {
      if (typeof entry.name === 'string') agentTools.push(entry.name)
      for (const tool of parseToolResult(entry.content).businessTools) {
        if (!businessTools.includes(tool)) businessTools.push(tool)
      }
    }
  }

  return { agentTools: dedupe(agentTools), businessTools }
}

function dedupe(items: string[]): string[] {
  return items.filter((item, index) => items.indexOf(item) === index)
}

/** 一轮里是否发生过任何 Agent 调用 —— 为空时不渲染轨迹面板。 */
export function hasTraceContent(entries: TraceEntry[]): boolean {
  return entries.length > 0
}
