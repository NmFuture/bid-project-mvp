import { useState } from 'react'
import { authAPI } from '../api'
import enterpriseLogo from '../assets/logo-removebg.png'
import RoleChip from '../components/shared/RoleChip'

const QUICK_LOGIN = [
  {
    role: 'T',
    email: 'anbo@nmscholar.fun',
    name: '安博',
    title: '风电技术高级工程师',
    department: '技术中心 / 风电技术部',
    employeeId: 'T-1024',
  },
  {
    role: 'B',
    email: 'mage@nmscholar.fun',
    name: '马哥',
    title: '商务标主管',
    department: '商务中心 / 投标商务部',
    employeeId: 'B-2308',
  },
  {
    role: 'TB',
    email: 'xiaoge@nmscholar.fun',
    name: '肖哥',
    title: '投标项目经理',
    department: '投标管理中心',
    employeeId: 'P-0517',
  },
]

const QUICK_LOGIN_PASSWORD = '123456'

const CAPABILITIES = [
  { icon: 'document_scanner', text: '招标文件结构化解析' },
  { icon: 'workspaces', text: '技术标 · 商务标双线协同' },
  { icon: 'fact_check', text: '评分点全量覆盖审计' },
  { icon: 'group', text: '在线共创与版本溯源' },
]

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingRole, setLoadingRole] = useState(null)
  const [error, setError] = useState('')

  const doLogin = async (mail, pwd) => {
    setError('')
    try {
      const payload = await authAPI.login({ email: mail.trim(), password: pwd })
      onLogin?.(payload)
    } catch (err) {
      setError(err?.message || '登录失败，请确认账号信息后重试。')
      throw err
    }
  }

  const handleQuickLogin = async (account) => {
    setLoadingRole(account.role)
    try {
      await doLogin(account.email, QUICK_LOGIN_PASSWORD)
    } catch {
      // 错误已通过 setError 显示
    } finally {
      setLoadingRole(null)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await doLogin(email, password)
    } catch {
      // 错误已通过 setError 显示
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-[100dvh] overflow-x-hidden bg-brand-deep">
      <div className="grid min-h-[100dvh] min-w-0 lg:grid-cols-[minmax(0,5fr)_minmax(24rem,4fr)] xl:grid-cols-[minmax(0,7fr)_minmax(26rem,5fr)]">
        <section className="hidden flex-col justify-between border-r border-white/10 p-12 text-white lg:flex xl:p-16" aria-label="平台介绍">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-10 items-center rounded-md bg-white px-3 py-1.5 shadow-sm">
              <img src={enterpriseLogo} alt="上海电气" width="112" height="28" className="h-7 w-auto object-contain" />
            </span>
            <div className="leading-tight">
              <div className="font-headline text-sm font-semibold">投标智能体平台</div>
              <div className="mt-0.5 text-xs text-white/55">上海电气风电集团股份有限公司</div>
            </div>
          </div>

          <div className="space-y-8">
            <div>
              <div className="mb-3 inline-block text-xs text-white/55 uppercase">
                Bid Intelligence Platform
              </div>
              <p className="font-headline text-[40px] font-bold leading-[1.18] text-white">
                让标书工作
                <br />
                回归专业判断
              </p>
              <p className="text-[14px] text-white/65 mt-5 max-w-md leading-[1.85]">
                以 AI 替代重复性事务，把投标团队的精力集中在评分点应答、技术方案与商务谈判上。统一管理素材库与
                Wiki，技术标与商务标双线协同，全过程审计可溯。
              </p>
            </div>

            <div className="flex flex-col gap-2.5 max-w-md">
              {CAPABILITIES.map((cap) => (
                <div key={cap.text} className="flex items-center gap-3 text-[13px] text-white/75">
                  <span
                    className="material-symbols-outlined text-[18px] text-primary-container"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                    aria-hidden="true"
                  >
                    {cap.icon}
                  </span>
                  {cap.text}
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-white/40">
            <span>© 上海电气风电集团股份有限公司</span>
            <span>v 1.0</span>
          </div>
        </section>

        <section className="flex min-w-0 items-center justify-center px-4 py-8 sm:px-6 lg:p-12 xl:p-16" aria-label="账号登录">
          <div className="min-w-0 w-full max-w-[420px] space-y-6">
            <div className="lg:hidden flex items-center gap-3 text-white">
              <span className="inline-flex h-10 items-center rounded-md bg-white px-3 py-1.5 shadow-sm">
                <img src={enterpriseLogo} alt="上海电气" width="112" height="28" className="h-7 w-auto object-contain" />
              </span>
              <span className="font-headline text-sm font-semibold">投标智能体平台</span>
            </div>

            <div className="rounded-lg border border-white/20 bg-white p-5 shadow-[0_12px_28px_rgba(13,33,55,0.14)] sm:p-7 xl:p-8">
              <div className="mb-6">
                <h1 className="font-headline text-2xl font-semibold text-on-surface">账号登录</h1>
                <p className="mt-1.5 text-xs text-on-surface-variant">请使用您的统一身份账号</p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="login-email" className="block text-sm font-medium text-on-surface-variant mb-1.5">
                    邮箱
                  </label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline pointer-events-none" aria-hidden="true">
                      mail
                    </span>
                    <input
                      type="email"
                      id="login-email"
                      name="email"
                      autoComplete="email"
                      spellCheck={false}
                      aria-invalid={Boolean(error)}
                      aria-describedby={error ? 'login-error' : undefined}
                      className="h-11 w-full rounded-md border border-outline-variant bg-surface-container-low pl-10 pr-4 text-base text-on-surface transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 lg:text-sm"
                      placeholder="请输入邮箱…"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                </div>
                <div>
                  <label htmlFor="login-password" className="block text-sm font-medium text-on-surface-variant mb-1.5">
                    密码
                  </label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline pointer-events-none" aria-hidden="true">
                      lock
                    </span>
                    <input
                      type="password"
                      id="login-password"
                      name="password"
                      autoComplete="current-password"
                      aria-invalid={Boolean(error)}
                      aria-describedby={error ? 'login-error' : undefined}
                      className="h-11 w-full rounded-md border border-outline-variant bg-surface-container-low pl-10 pr-4 text-base text-on-surface transition-colors focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 lg:text-sm"
                      placeholder="请输入密码…"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>
                </div>
                {error && (
                  <div id="login-error" role="alert" aria-live="assertive" className="rounded-md border border-error/30 bg-error-container/30 px-3 py-2 text-sm text-error">
                    {error}
                  </div>
                )}
                <div className="flex items-center justify-between pt-1 text-xs">
                  <label className="flex items-center gap-1.5 text-on-surface-variant cursor-pointer select-none">
                    <input type="checkbox" name="remember" className="h-4 w-4 rounded border-outline" defaultChecked />
                    保持登录
                  </label>
                  <a className="text-primary font-medium hover:underline" href="#">忘记密码？</a>
                </div>
                <button
                  type="submit"
                  disabled={loading || !email}
                  className="h-11 w-full rounded-md bg-primary text-sm font-semibold text-white transition-colors hover:bg-on-primary-fixed-variant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? '登录中…' : '登录'}
                </button>
              </form>

              <div className="flex items-center gap-3 my-5">
                <div className="flex-1 h-px bg-outline-variant/50" />
                <span className="text-xs text-outline">选择身份登录</span>
                <div className="flex-1 h-px bg-outline-variant/50" />
              </div>

              <div className="space-y-2">
                {QUICK_LOGIN.map((account) => {
                  const isLoading = loadingRole === account.role
                  return (
                    <button
                      key={account.role}
                      type="button"
                      onClick={() => handleQuickLogin(account)}
                      disabled={!!loadingRole || loading}
                      className="group flex min-h-12 min-w-0 w-full items-center gap-3 rounded-md border border-outline-variant bg-white px-3 py-2.5 text-left transition-colors hover:border-primary hover:bg-primary-fixed/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-brand-avatar text-sm font-semibold text-white">
                        {account.name[0]}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[14px] font-semibold text-on-surface truncate">
                            {account.name}
                          </span>
                          <span className="font-mono text-xs text-outline">
                            {account.employeeId}
                          </span>
                          <RoleChip role={account.role} showLabel={false} className="ml-auto" />
                        </div>
                        <div className="mt-0.5 truncate text-xs text-on-surface-variant">
                          {account.title} · {account.department}
                        </div>
                      </div>
                      <span
                        className={`material-symbols-outlined text-[18px] ${isLoading ? 'animate-spin-slow text-primary' : 'text-outline group-hover:text-primary'}`}
                        aria-hidden="true"
                      >
                        {isLoading ? 'progress_activity' : 'chevron_right'}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            <p className="text-center text-xs text-white/40">
              安全声明 · 系统使用情况将留存审计日志
            </p>
          </div>
        </section>
      </div>
    </main>
  )
}
