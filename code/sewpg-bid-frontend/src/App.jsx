import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { useCallback, useEffect, useState } from 'react'
import AppShell from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import Login from './pages/Login'
import Toast from './components/shared/Toast'
import { AUTH_EXPIRED_EVENT, AUTH_STORAGE_KEY, authAPI } from './api'
import { workspaceFromSlug, workspaceRoute } from './utils/workspace'
import { renderTechnicalRoutes } from './workspaces/technical/routes'
import { renderBusinessRoutes } from './workspaces/business/routes'

const readStoredSession = () => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || !parsed.token) return null
    if (Number.isFinite(parsed.expiresAt) && parsed.expiresAt <= Date.now()) {
      window.localStorage.removeItem(AUTH_STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
    return null
  }
}

const buildSession = (payload, fallback = {}) => {
  const token = payload?.token || fallback.token || ''
  const expiresIn = Number(payload?.expiresIn || fallback.expiresIn || 0)
  const fallbackExpiresAt = Number(fallback.expiresAt || 0)
  return {
    token,
    user: payload?.user || fallback.user || null,
    expiresIn: Number.isFinite(expiresIn) && expiresIn > 0 ? expiresIn : null,
    expiresAt:
      Number.isFinite(expiresIn) && expiresIn > 0
        ? Date.now() + expiresIn * 1000
        : Number.isFinite(fallbackExpiresAt) && fallbackExpiresAt > Date.now()
          ? fallbackExpiresAt
          : null,
  }
}

const persistSession = (session) => {
  if (typeof window === 'undefined') return
  if (!session?.token || !session?.user) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
    return
  }
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session))
}

function WorkspaceRedirect() {
  const { workspace } = useParams()
  const resolved = workspaceFromSlug(workspace)
  if (!resolved) return <Navigate to="/dashboard" replace />
  return <Navigate to={workspaceRoute(resolved.slug, '/projects')} replace />
}

export default function App() {
  const [authLoading, setAuthLoading] = useState(true)
  const [session, setSession] = useState(() => readStoredSession())
  const [toast, setToast] = useState(null)

  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }, [])

  useEffect(() => {
    let mounted = true
    const syncSession = async () => {
      const stored = readStoredSession()
      if (!stored?.token) {
        setSession(null)
        persistSession(null)
        setAuthLoading(false)
        return
      }
      setAuthLoading(true)
      try {
        const payload = await authAPI.me(stored.token)
        if (!mounted) return
        const next = buildSession(payload, stored)
        setSession(next)
        persistSession(next)
      } catch (error) {
        if (!mounted) return
        setSession(null)
        persistSession(null)
        if (error?.status === 401) {
          showToast('登录已过期，请重新登录。', 'error')
        }
      } finally {
        if (mounted) setAuthLoading(false)
      }
    }
    syncSession()
    return () => {
      mounted = false
    }
  }, [showToast])

  useEffect(() => {
    const handleAuthExpired = (event) => {
      setSession(null)
      persistSession(null)
      showToast(event?.detail?.message || '登录已过期，请重新登录。', 'error')
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
  }, [showToast])

  const handleLogin = useCallback((payload) => {
    const next = buildSession(payload)
    setSession(next)
    persistSession(next)
    showToast('登录成功')
  }, [showToast])

  const handleLogout = useCallback(async () => {
    try {
      await authAPI.logout()
    } catch {
      // 忽略退出异常，保证前端会话可被清理
    }
    setSession(null)
    persistSession(null)
    showToast('已退出登录')
  }, [showToast])

  if (authLoading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="text-sm text-on-surface-variant">正在校验登录状态...</div>
      </div>
    )
  }

  if (!session?.user) {
    return <Login onLogin={handleLogin} />
  }

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
      <AppShell currentUser={session?.user} onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard currentUser={session?.user} />} />
          {renderTechnicalRoutes({ user: session?.user, showToast })}
          {renderBusinessRoutes({ user: session?.user, showToast })}

          <Route path="/workspace/:workspace" element={<WorkspaceRedirect />} />
          <Route path="/settings" element={<Settings showToast={showToast} />} />
        </Routes>
      </AppShell>
    </>
  )
}
