import { useState } from 'react'
import { authAPI } from '../api'

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('admin@sewpg.com')
  const [password, setPassword] = useState('123456')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const payload = await authAPI.login({
        email: email.trim(),
        password,
      })
      onLogin?.(payload)
    } catch (err) {
      setError(err?.message || '登录失败，请检查账号密码后重试。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary via-primary-container to-primary flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-[0_24px_48px_-12px_rgba(0,62,111,0.3)] p-8 animate-fade-in">
        <div className="text-center mb-8">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center text-on-primary shadow-lg shadow-primary/30">
            <span className="material-symbols-outlined text-3xl">wind_power</span>
          </div>
          <h1 className="text-2xl font-headline font-extrabold text-primary">上海电气风电</h1>
          <p className="text-sm text-on-surface-variant mt-1">投标智能体管理系统</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <div>
            <label className="block text-sm font-medium text-on-surface mb-2">邮箱</label>
            <input
              type="email"
              className="w-full h-12 px-4 bg-surface-container-highest border-none rounded-lg text-sm focus:ring-2 focus:ring-primary/30 transition-all"
              placeholder="输入邮箱地址"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-on-surface mb-2">密码</label>
            <input
              type="password"
              className="w-full h-12 px-4 bg-surface-container-highest border-none rounded-lg text-sm focus:ring-2 focus:ring-primary/30 transition-all"
              placeholder="输入密码"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? (
            <div className="rounded-lg border border-error/30 bg-error-container/30 px-3 py-2 text-xs text-error">
              {error}
            </div>
          ) : null}
          <div className="flex items-center justify-between text-sm">
            <label className="flex items-center gap-2 text-on-surface-variant cursor-pointer">
              <input type="checkbox" className="rounded border-outline" defaultChecked />
              记住登录
            </label>
            <a href="#" className="text-primary font-medium hover:underline">忘记密码？</a>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full h-12 bg-gradient-to-r from-primary to-primary-container text-on-primary font-semibold rounded-lg hover:shadow-[0_8px_24px_-8px_rgba(0,62,111,0.5)] transition-all active:scale-[0.98] disabled:opacity-50"
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>

        <p className="text-center text-xs text-outline mt-6">© 2023 上海电气风电集团股份有限公司</p>
      </div>
    </div>
  )
}
