/**
 * 打字机：把"一批一批到达的文本"变成"一帧一帧长出来的文本"。
 *
 * **为什么需要它**：后端两条路径给文本的粒度不一样 ——
 *  - 逐 token 路径：`text_delta` 是**逐 token** 的（实测一次知识问答 40～85 条），
 *    直接渲染就已经有打字感；
 *  - 整段路径：模型只在节点结束时才给全文，后端把**整段回答**当成**一条** delta 发出来。
 *    这时直接渲染就是"啪"地出现一整段，完全没有打字过程。
 *
 * 所以这里不做"按时间假装打字"的表演，只做**平滑**：新到的文本进队列，每帧放出若干字。
 * 进料是**全文快照**而不是增量（见 `push`）—— SSE 的 delta 边界不可靠，
 * 按"快照比已收到的更长"来判断新增部分最稳，重复投喂同一个快照也不会重复出字。
 *
 * **`finish()` 为什么是异步的**（这里改过一次，值得记下来）：
 * 最初写成"流一结束就把队列一次放完"，理由是"流结束时队列本来就基本空了，看不出来"。
 * 真机实测推翻了它：设备申请这条路上整段回答就是**末尾一条 delta**，而它紧跟着
 * `done`，于是 `finish()` 把 **100% 的动画**都吞了 —— 界面上正文从 23 字符直接跳到
 * 234 字符，一个字都没"打"出来（浏览器逐 150ms 采样只有 2 个不同的长度值）。
 * 现在 `finish()` 让剩余文本继续按帧吐，吐完才 resolve；调用方 `await` 它之后再落
 * 正式消息，就不会出现"动画到一半被整段覆盖"。
 */
export interface Typewriter {
  /**
   * 推进到"到目前为止的全文"。
   *
   * 传**快照**而不是增量：调用方手里是累积文本（`acc += delta`），直接把累积值
   * 追加进队列会让队列按平方增长，把回答重复吐好几遍。快照不比已收到的长就忽略，
   * 所以重复投喂同一个快照是幂等的。
   */
  push: (snapshot: string) => void
  /**
   * 流结束：让队列里剩下的文本**继续按帧吐完**，吐完才 resolve。
   *
   * 调用方要 `await` 它之后再落正式消息 —— 否则一次性写入会把动画中的文本覆盖掉。
   * 队列已空时立刻 resolve。
   */
  finish: () => Promise<void>
  /** 放弃：停掉定时器、丢掉还没放出的字符（组件卸载时用），并兑现挂着的 `finish()` */
  dispose: () => void
  /** 当前已经放出的文本 */
  text: () => string
}

/** 无 DOM 环境（单测跑在 Node 里）也要能用，所以 rAF 与定时器二选一。 */
const hasRaf = typeof requestAnimationFrame === 'function'

function schedule(callback: () => void): number {
  if (hasRaf) return requestAnimationFrame(callback)
  return setTimeout(callback, 16) as unknown as number
}

function unschedule(handle: number): void {
  if (hasRaf) cancelAnimationFrame(handle)
  else clearTimeout(handle)
}

/**
 * @param onReveal 每次"放出"后回调当前**已放出的全文**（不是增量）—— 调用方整段替换即可
 * @param charsPerFrame 每帧放出的**基准**字数；默认 3（60fps 下约 180 字/秒）
 */
export function createTypewriter(
  onReveal: (text: string) => void,
  charsPerFrame = 3,
): Typewriter {
  let received = ''
  let shown = ''
  let queued = ''
  let handle: number | null = null
  /** `finish()` 的等待者；队列吐空时兑现 */
  let settle: (() => void) | null = null

  function stop(): void {
    if (handle !== null) {
      unschedule(handle)
      handle = null
    }
  }

  function resolveSettle(): void {
    if (settle !== null) {
      const done = settle
      settle = null
      done()
    }
  }

  /**
   * 积压越多放得越快。
   *
   * 恒定 3 字/帧意味着一条 1200 字的回答要打 6.7 秒 —— 短回答上很好看，
   * 长回答上就是"卡住了"。分档之后：少量积压保持一个字一个字，
   * 大量积压（模型一次给了整段）也只要一两秒。两者都是"看着在长出来"。
   */
  function step(): number {
    if (queued.length > 600) return 24
    if (queued.length > 240) return 12
    if (queued.length > 80) return 6
    return charsPerFrame
  }

  function tick(): void {
    handle = null
    if (queued === '') {
      resolveSettle()
      return
    }
    const take = Math.min(step(), queued.length)
    shown += queued.slice(0, take)
    queued = queued.slice(take)
    onReveal(shown)
    if (queued !== '') handle = schedule(tick)
    else resolveSettle()
  }

  return {
    push(snapshot) {
      // 只认"比已收到的更长"的那一截 —— 等长或更短都当重复投喂忽略
      if (snapshot.length <= received.length) return
      queued += snapshot.slice(received.length)
      received = snapshot
      if (handle === null) handle = schedule(tick)
    },
    finish() {
      if (queued === '') {
        stop()
        return Promise.resolve()
      }
      // 已经有一帧在排队就不要重复排，只挂上等待者
      if (handle === null) handle = schedule(tick)
      return new Promise<void>((resolve) => {
        settle = resolve
      })
    },
    dispose() {
      stop()
      queued = ''
      // 兑现等待者：组件卸载时若还挂着 `await finish()`，不能让那个 async 函数永远悬着
      resolveSettle()
    },
    text: () => shown,
  }
}
