import { useState, type FormEvent } from 'react'

import { ApiError, login } from '../lib/api'
import type { StoredSession } from '../lib/session'
import { cn } from '../lib/utils'
import ThemeSwitcher from './ThemeSwitcher'

/**
 * 演示账号（逐字取自 `src/data/day05_users.json`，共 10 个可登录账号，这里列前 5 个常用的）。
 * 登录页必须把账号写出来：后端**没有"列出用户"的接口**，不写出来演示时对方不知道该输什么。
 */
const DEMO_ACCOUNTS = [
  { username: 'zhang_wei', name: '张伟', role: 'employee' },
  { username: 'li_na', name: '李娜', role: 'employee' },
  { username: 'chen_hao', name: '陈浩', role: 'employee' },
  { username: 'wang_fang', name: '王芳', role: 'hr' },
  { username: 'zheng_kai', name: '郑凯', role: 'hr' },
] as const

const ROLE_LABEL: Record<string, string> = {
  employee: '员工',
  hr: 'HR',
}

interface LoginViewProps {
  onSignedIn: (session: StoredSession) => void
}

export default function LoginView({ onSignedIn }: LoginViewProps) {
  const [username, setUsername] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function signIn(candidate: string) {
    const name = candidate.trim()
    if (!name || busy) return

    setBusy(name)
    setError(null)
    try {
      const result = await login(name)
      onSignedIn({
        sessionId: result.session_id,
        displayName: result.display_name,
        role: result.role,
        traceCursor: 0,
        pending: null,
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    void signIn(username)
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center bg-surface-0 p-6">
      {/* 未登录也能换主题：演示时可以先选主题再登录 */}
      <ThemeSwitcher className="absolute top-4 right-4" />
      <div className="w-full max-w-sm">
        <header className="mb-6">
          <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-control border border-hairline bg-surface-2 text-sm font-semibold text-accent-text">
            星
          </div>
          <h1 className="text-lg font-semibold text-ink-0">企业员工服务助手</h1>
          <p className="mt-1 text-sm text-ink-2">
            多 Agent 协作 · 制度问答与员工服务申请
          </p>
        </header>

        <section className="rounded-card border border-hairline bg-surface-1 p-4">
          <h2 className="mb-3 text-xs font-medium tracking-wide text-ink-2">
            选择一个演示账号
          </h2>

          <ul className="space-y-1.5">
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.username}>
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void signIn(account.username)}
                  className={cn(
                    'flex w-full items-center justify-between gap-3 rounded-control border border-hairline',
                    'bg-surface-2 px-3 py-2 text-left transition-colors',
                    'hover:border-hairline-strong hover:bg-surface-3',
                    'disabled:cursor-not-allowed disabled:opacity-50',
                  )}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="text-sm text-ink-0">{account.name}</span>
                    <span className="font-mono text-xs text-ink-3">{account.username}</span>
                  </span>
                  <span
                    className={cn(
                      'shrink-0 rounded-full border px-2 py-0.5 text-[11px]',
                      account.role === 'hr'
                        ? 'border-accent/40 bg-accent-soft text-accent-text'
                        : 'border-hairline-strong text-ink-2',
                    )}
                  >
                    {ROLE_LABEL[account.role]}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <div className="my-4 flex items-center gap-3">
            <span className="h-px flex-1 bg-hairline" />
            <span className="text-[11px] text-ink-3">或输入账号</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>

          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="例如 zhang_wei"
              aria-label="登录账号"
              autoComplete="username"
              className={cn(
                'min-w-0 flex-1 rounded-control border border-hairline bg-surface-3 px-3 py-2',
                'font-mono text-sm text-ink-0 placeholder:text-ink-3',
                'focus:border-accent focus:outline-none',
              )}
            />
            <button
              type="submit"
              disabled={busy !== null || username.trim() === ''}
              className={cn(
                'shrink-0 rounded-control bg-accent px-3 py-2 text-sm font-medium text-on-accent',
                'transition-colors hover:bg-accent-hi',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
            >
              {busy !== null ? '登录中' : '登录'}
            </button>
          </form>

          <p
            role="alert"
            aria-live="polite"
            className={cn(
              'mt-3 rounded-control border px-3 py-2 text-xs',
              error
                ? 'border-danger/40 bg-danger-soft text-danger'
                : 'invisible border-transparent',
            )}
          >
            {error ?? '占位'}
          </p>
        </section>

        <p className="mt-4 text-center text-[11px] leading-relaxed text-ink-3">
          登录身份由服务端按账号查表决定，聊天内容无法改变它。
          <br />
          共 10 个可登录账号，均为教学数据。
        </p>
      </div>
    </main>
  )
}
