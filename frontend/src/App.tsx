import { useCallback, useState } from 'react'

import ChatView from './components/ChatView'
import LoginView from './components/LoginView'
import { clearSession, loadSession, saveSession, type StoredSession } from './lib/session'

/**
 * 顶层状态机：没有登录态 → 登录页；有 → 对话页。
 *
 * 刻意不引入 react-router（只有两个视图，"是否已登录"本身就是全部路由状态；
 * 用路由库反而要额外处理"URL 说已登录但 localStorage 没有"这类不一致）。
 *
 * 初始值走 `loadSession()` 惰性初始化 —— 刷新页面时**不会闪一下登录页**。
 *
 * **这里不校验 token 是否还有效**：那需要一次网络往返，会让刷新时多一层中间态。
 * 校验交给第一个真正的接口调用 —— 它拿到 401 就回调 `onSessionExpired`，
 * 于是"过期"只有一条处理路径。
 */
export default function App() {
  const [session, setSession] = useState<StoredSession | null>(() => loadSession())
  const [notice, setNotice] = useState<string | null>(null)

  /** 登录成功：立刻落盘（刷新后免登录）。 */
  const handleSignedIn = useCallback((next: StoredSession) => {
    saveSession(next)
    setSession(next)
    setNotice(null)
  }, [])

  /** 对话页每轮会更新当前 `threadId`，这里负责落盘并保持内存态一致。 */
  const handleSessionChange = useCallback((next: StoredSession) => {
    saveSession(next)
    setSession(next)
  }, [])

  const handleSignOut = useCallback(() => {
    clearSession()
    setSession(null)
    setNotice(null)
  }, [])

  /**
   * token 失效的出口（401）：清 localStorage 回登录页。
   * **不做静默重登** —— 那会在用户不知情的情况下把对话上下文换掉。
   */
  const handleSessionExpired = useCallback(() => {
    clearSession()
    setSession(null)
    setNotice('登录已失效（Token 过期或后端已重启过密钥），请重新登录。')
  }, [])

  if (session === null) {
    return (
      <>
        {notice !== null && (
          <p
            role="status"
            className="border-b border-warn/40 bg-warn-soft px-4 py-2 text-center text-xs text-warn"
          >
            {notice}
          </p>
        )}
        <LoginView onSignedIn={handleSignedIn} />
      </>
    )
  }

  return (
    <ChatView
      session={session}
      onSessionChange={handleSessionChange}
      onSignOut={handleSignOut}
      onSessionExpired={handleSessionExpired}
    />
  )
}
