import { useCallback, useState } from 'react'

import ChatView from './components/ChatView'
import LoginView from './components/LoginView'
import { clearSession, loadSession, saveSession, type StoredSession } from './lib/session'

/**
 * 顶层状态机：没会话 → 登录页；有会话 → 对话页。
 *
 * 刻意不引入 react-router（决定 D2）：只有两个视图，而且"是否已登录"本身就是
 * 全部路由状态；用路由库反而要额外处理"URL 说已登录但 localStorage 没有"这类不一致。
 *
 * 初始值走 `loadSession()` 惰性初始化 —— 刷新页面时**不会闪一下登录页**。
 */
export default function App() {
  const [session, setSession] = useState<StoredSession | null>(() => loadSession())
  const [notice, setNotice] = useState<string | null>(null)

  const handleSignedIn = useCallback((next: StoredSession) => {
    saveSession(next)
    setSession(next)
    setNotice(null)
  }, [])

  /** 对话页每轮都会更新 `traceCursor` / `pending`，这里负责接收并保持内存态与 localStorage 一致。 */
  const handleSessionChange = useCallback((next: StoredSession) => {
    setSession(next)
  }, [])

  const handleSignOut = useCallback(() => {
    clearSession()
    setSession(null)
    setNotice(null)
  }, [])

  /**
   * R3 的出口：第一次拿到 404 就清 localStorage 回登录页。
   * 不做静默重登 —— 那会在用户不知情的情况下把对话上下文换掉。
   */
  const handleSessionExpired = useCallback(() => {
    clearSession()
    setSession(null)
    setNotice('会话已失效（通常是后端重启过），请重新登录。')
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
