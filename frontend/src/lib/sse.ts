/**
 * SSE 帧解析。
 *
 * 只做一件事：把 `fetch` 拿到的字节流切成 `{event, data}` 帧。刻意与 `api.ts` 分开，
 * 因为协议解析是最容易写错、也最值得单测的一块：
 *
 *  1. 一帧以**空行**结束，但网络分片既可能把一帧切成几段，也可能一次到达好几帧；
 *  2. `data:` 后面**规范上有一个空格**，而本项目后端（`agent_api.py` 的 `sse_event`）
 *     发的是 `data:{"text":"..."}` —— 没有空格。SSE 规范说"去掉一个前导空格"，
 *     所以必须**只去一个**：去零个则带冒号后紧跟的 `{` 前那个空格（如果有）会被当成数据，
 *     去多个则会把正文里的缩进吃掉；
 *  3. `event:` 缺省是 `message`；`id:` / `retry:` / 以 `:` 开头的注释行（心跳）都要忽略。
 */

export interface SSEMessage {
  event: string
  data: string
}

/**
 * 把一段可能不完整的缓冲切成完整帧。
 *
 * 返回 `rest` 是"还没收到空行、不能确定完整"的尾段，调用方必须留到下一块数据到达再拼。
 * **不能丢掉它** —— 丢一次就丢一个事件，而 SSE 的分片边界是按字节来的，任何位置都可能切。
 */
export function splitSSEBuffer(buffer: string): { frames: SSEMessage[]; rest: string } {
  // 兼容 \r\n\r\n：先归一成 \n，再按空行切
  const parts = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = parts.pop() ?? ''
  const frames: SSEMessage[] = []
  for (const part of parts) {
    const frame = parseSSEFrame(part)
    if (frame !== null) frames.push(frame)
  }
  return { frames, rest }
}

/** 解析单个帧文本；没有 `data:` 字段时返回 null（纯注释/心跳块）。 */
export function parseSSEFrame(raw: string): SSEMessage | null {
  const dataLines: string[] = []
  let event = 'message'

  for (const line of raw.split('\n')) {
    if (line === '' || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    if (colon === -1) continue
    const field = line.slice(0, colon)
    let value = line.slice(colon + 1)
    // 规范：冒号后若紧跟一个空格，去掉它（**只去一个**）
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
    // id / retry 前端暂时用不到，忽略
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

/**
 * 逐块读取响应体并按帧回调，返回时保证缓冲里最后那半帧也被处理。
 *
 * `getReader()` 拿到的是一把锁，所以必须 `releaseLock()` —— 否则同一个 Response
 * 之后再用会被拒。读取过程中抛错（网络断）时也会走 `finally` 释放。
 */
export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: SSEMessage) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const { frames, rest } = splitSSEBuffer(buffer)
      buffer = rest
      for (const frame of frames) onFrame(frame)
    }
    // 收尾：把解码器里残留的字节取出来，并给最后一帧补上空行让它被解析
    const { frames } = splitSSEBuffer(buffer + decoder.decode() + '\n\n')
    for (const frame of frames) onFrame(frame)
  } finally {
    reader.releaseLock()
  }
}
