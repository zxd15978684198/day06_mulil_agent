import { useState, type FormEvent } from 'react'

import { ApiError, fetchMe, login } from '../lib/api'
import type { StoredSession } from '../lib/session'
import { cn } from '../lib/utils'
import ThemeSwitcher from './ThemeSwitcher'

/**
 * 演示账号（取自教学数据的 10 个可登录账号，这里列 5 个常用的）。
 * 登录页必须把账号写出来：后端**没有"列出用户"的接口**，不写出来演示时对方不知道该输什么。
 *
 * **口令是统一的 `123456`**（`src/migrations/sql/V002__seed_login_password_hashes.sql`
 * 灌入的 Argon2id 摘要，10 个账号共用一个教学口令），所以输入框默认填好它。
 *
 * **点账号只"填入"，不提交**：唯一的提交入口是右侧「登录」按钮（表单内 Enter 等价）。
 * 两个动作分开，"选谁"与"是否登录"就不会被一次误点合并 ——
 * 手滑点到别的账号时，不会把身份直接换掉。
 */
const DEMO_ACCOUNTS = [
  { username: 'zhang_wei', name: '张伟', role: 'employee' },
  { username: 'li_na', name: '李娜', role: 'employee' },
  { username: 'chen_hao', name: '陈浩', role: 'employee' },
  { username: 'wang_fang', name: '王芳', role: 'hr' },
  { username: 'zheng_kai', name: '郑凯', role: 'hr' },
] as const

const DEMO_PASSWORD = '123456'

const ROLE_LABEL: Record<string, string> = {
  employee: '员工',
  hr: 'HR',
}

interface LoginViewProps {
  onSignedIn: (session: StoredSession) => void
}

export default function LoginView({ onSignedIn }: LoginViewProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState(DEMO_PASSWORD)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  /**
   * 登录是**两步**：
   *   1. `POST /api/sessions`（表单）换 Token —— 它**不创建会话**；
   *   2. `GET /api/auth/me` 换身份 —— 展示名与角色一律以它为准。
   * 第 2 步不是多余的：Token 里只有 `sub`（用户编号），
   * 若拿登录输入的用户名去显示，就等于让前端自己推断身份。
   *
   * `threadId` 留 null：会话由对话页按需创建（`POST /api/threads`），
   * 这样"只看一眼就退出"的登录不会在库里留下空会话。
   */
  async function signIn(candidate: string) {
    const name = candidate.trim()
    if (!name || busy) return

    setBusy(name)
    setError(null)
    try {
      const token = await login(name, password)
      const user = await fetchMe(token.access_token)
      onSignedIn({ token: token.access_token, user, threadId: null })
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
            {DEMO_ACCOUNTS.map((account) => {
              // 选中态**由输入框的值推导**，不另存一份 state：
              // 手动输入 zhang_wei 时这一行同样会亮，两个来源不会打架。
              const active = username.trim().toLowerCase() === account.username
              return (
                <li key={account.username}>
                  <button
                    type="button"
                    disabled={busy !== null}
                    aria-pressed={active}
                    onClick={() => {
                      setUsername(account.username)
                      setError(null)
                    }}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-control border px-3 py-2 text-left transition-colors',
                      active
                        ? 'border-accent bg-accent-soft'
                        : 'border-hairline bg-surface-2 hover:border-hairline-strong hover:bg-surface-3',
                      'disabled:cursor-not-allowed disabled:opacity-50',
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        'flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border',
                        active ? 'border-accent bg-accent text-on-accent' : 'border-hairline-strong',
                      )}
                    >
                      {active && (
                        <svg
                          viewBox="0 0 12 12"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={2}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="h-2.5 w-2.5"
                        >
                          <path d="M2.5 6.2 4.8 8.5 9.5 3.8" />
                        </svg>
                      )}
                    </span>
                    <span className="flex min-w-0 flex-1 items-baseline gap-2">
                      <span className="text-sm text-ink-0">{account.name}</span>
                      <span className="truncate font-mono text-xs text-ink-3">{account.username}</span>
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
              )
            })}
          </ul>

          <p className="mt-2 text-[11px] leading-relaxed text-ink-3">
            点一下只是把账号填进去，确认无误再按下面的「登录」。
          </p>

          <div className="my-4 flex items-center gap-3">
            <span className="h-px flex-1 bg-hairline" />
            <span className="text-[11px] text-ink-3">或手动输入</span>
            <span className="h-px flex-1 bg-hairline" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-2">
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="账号，例如 zhang_wei"
              aria-label="登录账号"
              autoComplete="username"
              className={cn(
                'w-full rounded-control border border-hairline bg-surface-3 px-3 py-2',
                'font-mono text-sm text-ink-0 placeholder:text-ink-3',
                'focus:border-accent focus:outline-none',
              )}
            />
            <div className="flex gap-2">
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                placeholder="口令"
                aria-label="登录口令"
                autoComplete="current-password"
                className={cn(
                  'min-w-0 flex-1 rounded-control border border-hairline bg-surface-3 px-3 py-2',
                  'font-mono text-sm text-ink-0 placeholder:text-ink-3',
                  'focus:border-accent focus:outline-none',
                )}
              />
              <button
                type="submit"
                disabled={busy !== null || username.trim() === '' || password === ''}
                className={cn(
                  'shrink-0 rounded-control bg-accent px-3 py-2 text-sm font-medium text-on-accent',
                  'transition-colors hover:bg-accent-hi',
                  'disabled:cursor-not-allowed disabled:opacity-50',
                )}
              >
                {busy !== null ? '登录中' : '登录'}
              </button>
            </div>
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
          共 10 个可登录账号，教学口令统一为 <span className="font-mono">{DEMO_PASSWORD}</span>。
        </p>
      </div>
    </main>
  )
}
