import { useState } from 'react'
import { authAPI } from '../api'
import enterpriseLogo from '../assets/logo-removebg.png'
import RoleChip from '../components/shared/RoleChip'

const QUICK_LOGIN = [
  {
    role: 'T',
    email: 'liminyuan@sewpg.com',
    name: '李明远',
    title: '风电技术高级工程师',
    department: '技术中心 / 风电技术部',
    employeeId: 'T-1024',
  },
  {
    role: 'B',
    email: 'wangzhiyuan@sewpg.com',
    name: '王致远',
    title: '商务标主管',
    department: '商务中心 / 投标商务部',
    employeeId: 'B-2308',
  },
  {
    role: 'TB',
    email: 'zhangxiaoyan@sewpg.com',
    name: '张晓岩',
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
    <div className="min-h-screen relative overflow-hidden bg-[#05202E]">
      <div className="absolute inset-0">
        <div className="absolute top-1/3 -left-40 h-[480px] w-[480px] rounded-full bg-[#0067B6] opacity-25 blur-3xl" />
        <div
          className="absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.5) 1px, transparent 1px)',
            backgroundSize: '48px 48px',
          }}
        />
      </div>

      <div className="relative min-h-screen grid lg:grid-cols-[5fr_4fr] xl:grid-cols-[7fr_5fr]">
        <div className="hidden lg:flex flex-col justify-between p-12 xl:p-16 text-white">
          <div className="flex items-center gap-3 animate-float-in">
            <img src={enterpriseLogo} alt="上海电气" className="h-9 w-auto object-contain" />
            <div className="leading-tight">
              <div className="text-[15px] font-headline font-semibold tracking-wide">投标智能体平台</div>
              <div className="text-[11px] text-white/55 mt-0.5">上海电气风电集团股份有限公司</div>
            </div>
          </div>

          <div
            className="space-y-8 animate-float-in"
            style={{ animationDelay: '0.08s' }}
          >
            <div>
              <div className="inline-block text-[11px] tracking-[0.18em] text-white/55 uppercase mb-3">
                Bid Intelligence Platform
              </div>
              <h1 className="text-[40px] xl:text-[48px] font-headline font-bold leading-[1.18] text-white">
                让标书工作
                <br />
                回归专业判断
              </h1>
              <p className="text-[14px] text-white/65 mt-5 max-w-md leading-[1.85]">
                以 AI 替代重复性事务，把投标团队的精力集中在评分点应答、技术方案与商务谈判上。统一管理素材库与
                Wiki，技术标与商务标双线协同，全过程审计可溯。
              </p>
            </div>

            <div className="flex flex-col gap-2.5 max-w-md">
              {CAPABILITIES.map((cap) => (
                <div key={cap.text} className="flex items-center gap-3 text-[13px] text-white/75">
                  <span
                    className="material-symbols-outlined text-[18px] text-[#69c0ff]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    {cap.icon}
                  </span>
                  {cap.text}
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between text-[11px] text-white/40">
            <span>© 上海电气风电集团股份有限公司</span>
            <span>v 1.0</span>
          </div>
        </div>

        <div className="flex items-center justify-center p-6 lg:p-12 xl:p-16 bg-white/[0.02]">
          <div
            className="w-full max-w-[420px] space-y-6 animate-float-in"
            style={{ animationDelay: '0.16s' }}
          >
            <div className="lg:hidden flex items-center gap-3 text-white">
              <img src={enterpriseLogo} alt="上海电气" className="h-9 w-auto object-contain" />
              <span className="text-[15px] font-headline font-semibold">投标智能体平台</span>
            </div>

            <div className="rounded-xl bg-white shadow-[0_24px_60px_-20px_rgba(0,0,0,0.5)] p-7 xl:p-8">
              <div className="mb-6">
                <h2 className="text-[20px] font-headline font-bold text-on-surface">账号登录</h2>
                <p className="text-[12px] text-on-surface-variant mt-1.5">请使用您的统一身份账号</p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-[12px] font-medium text-on-surface-variant mb-1.5">
                    邮箱
                  </label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline pointer-events-none">
                      mail
                    </span>
                    <input
                      type="email"
                      autoComplete="email"
                      className="w-full h-11 pl-10 pr-4 bg-surface-container-low border-none rounded-lg text-[14px] focus:ring-2 focus:ring-primary/30 transition-all"
                      placeholder="请输入邮箱"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-[12px] font-medium text-on-surface-variant mb-1.5">
                    密码
                  </label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline pointer-events-none">
                      lock
                    </span>
                    <input
                      type="password"
                      autoComplete="current-password"
                      className="w-full h-11 pl-10 pr-4 bg-surface-container-low border-none rounded-lg text-[14px] focus:ring-2 focus:ring-primary/30 transition-all"
                      placeholder="请输入密码"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </div>
                </div>
                {error && (
                  <div className="rounded-lg border border-error/30 bg-error-container/30 px-3 py-2 text-[12px] text-error animate-fade-in">
                    {error}
                  </div>
                )}
                <div className="flex items-center justify-between text-[12px] pt-1">
                  <label className="flex items-center gap-1.5 text-on-surface-variant cursor-pointer select-none">
                    <input type="checkbox" className="rounded border-outline" defaultChecked />
                    保持登录
                  </label>
                  <a className="text-primary font-medium hover:underline" href="#">忘记密码？</a>
                </div>
                <button
                  type="submit"
                  disabled={loading || !email}
                  className="w-full h-11 bg-gradient-to-r from-[#005995] to-[#0068b7] text-white font-semibold rounded-lg hover:shadow-[0_8px_24px_-8px_rgba(0,62,111,0.5)] transition-all active:scale-[0.99] disabled:opacity-50 disabled:hover:shadow-none"
                >
                  {loading ? '登录中…' : '登录'}
                </button>
              </form>

              <div className="flex items-center gap-3 my-5">
                <div className="flex-1 h-px bg-outline-variant/50" />
                <span className="text-[11px] text-outline tracking-wide">选择身份登录</span>
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
                      className={`group w-full flex items-center gap-3 rounded-lg border border-outline-variant/50 bg-white px-3 py-2.5 text-left transition-all hover:border-primary hover:bg-primary-fixed/40 disabled:opacity-50 ${isLoading ? 'animate-ring-glow' : ''}`}
                    >
                      <div className="shrink-0 h-10 w-10 rounded-md bg-[#0e3a5b] flex items-center justify-center text-white font-semibold text-[15px]">
                        {account.name[0]}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-[14px] font-semibold text-on-surface truncate">
                            {account.name}
                          </span>
                          <span className="text-[11px] text-outline font-mono">
                            {account.employeeId}
                          </span>
                          <RoleChip role={account.role} showLabel={false} className="ml-auto" />
                        </div>
                        <div className="text-[12px] text-on-surface-variant truncate mt-0.5">
                          {account.title} · {account.department}
                        </div>
                      </div>
                      <span
                        className={`material-symbols-outlined text-[18px] transition-all ${isLoading ? 'animate-spin-slow text-primary' : 'text-outline group-hover:text-primary group-hover:translate-x-0.5'}`}
                      >
                        {isLoading ? 'progress_activity' : 'chevron_right'}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            <p className="text-center text-[11px] text-white/40">
              安全声明 · 系统使用情况将留存审计日志
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
