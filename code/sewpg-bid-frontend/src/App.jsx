import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { useCallback, useEffect, useState } from 'react'
import AppShell from './components/layout/AppShell'
import ProjectList from './pages/ProjectList'
import ProjectEntryRedirect from './pages/ProjectEntryRedirect'
import ParseResult from './pages/ParseResult'
import OutlineReview from './pages/OutlineReview'
import GapRecognition from './pages/GapRecognition'
import GenerateProgress from './pages/GenerateProgress'
import CoverageHeatmap from './pages/CoverageHeatmap'
import CoCreationEditor from './pages/CoCreationEditor'
import FinalExport from './pages/FinalExport'
import MaterialDB from './pages/MaterialDB'
import MaterialWiki from './pages/MaterialWiki'
import AuditLog from './pages/AuditLog'
import TenderReview from './pages/TenderReview'
import Settings from './pages/Settings'
import Login from './pages/Login'
import Toast from './components/shared/Toast'
import { authAPI } from './api'
import { projectRoute, useWorkspaceSlug, workspaceFromSlug, workspaceRoute } from './utils/workspace'

const AUTH_STORAGE_KEY = 'sewpg.auth.session'

const readStoredSession = () => {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && parsed.token) return parsed
    return null
  } catch {
    return null
  }
}

const persistSession = (session) => {
  if (typeof window === 'undefined') return
  if (!session) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
    return
  }
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session))
}

function WorkspaceRedirect() {
  const { workspace } = useParams()
  const resolved = workspaceFromSlug(workspace)
  if (!resolved) return <Navigate to="/parse" replace />
  return <Navigate to={workspaceRoute(resolved.slug, '/projects')} replace />
}

function ProjectPathRedirect({ path }) {
  const { id } = useParams()
  const workspaceSlug = useWorkspaceSlug()
  return <Navigate to={projectRoute(id, path, workspaceSlug)} replace />
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
        const next = { token: payload?.token || stored.token, user: stored.user || payload?.user || null }
        setSession(next)
        persistSession(next)
      } catch {
        if (!mounted) return
        setSession(null)
        persistSession(null)
      } finally {
        if (mounted) setAuthLoading(false)
      }
    }
    syncSession()
    return () => {
      mounted = false
    }
  }, [])

  const handleLogin = useCallback((payload) => {
    const next = { token: payload?.token || '', user: payload?.user || null }
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
          <Route path="/" element={<Navigate to="/parse" replace />} />
          <Route path="/parse" element={<TenderReview showToast={showToast} />} />
          <Route path="/review" element={<TenderReview showToast={showToast} />} />
          <Route path="/workspace/:workspace" element={<WorkspaceRedirect />} />
          <Route path="/workspace/:workspace/projects" element={<ProjectList showToast={showToast} />} />
          <Route path="/workspace/:workspace/flow" element={<WorkspaceRedirect />} />
          <Route path="/workspace/:workspace/projects/:id" element={<ProjectEntryRedirect />} />
          <Route path="/workspace/:workspace/projects/:id/template-directory" element={<ParseResult showToast={showToast} />} />
          <Route path="/workspace/:workspace/projects/:id/parse" element={<ProjectPathRedirect path="/template-directory" />} />
          <Route path="/workspace/:workspace/projects/:id/directory" element={<ProjectPathRedirect path="/template-directory" />} />
          <Route path="/workspace/:workspace/projects/:id/outline" element={<OutlineReview showToast={showToast} />} />
          <Route path="/workspace/:workspace/projects/:id/gaps" element={<GapRecognition showToast={showToast} />} />
          <Route path="/workspace/:workspace/projects/:id/gaps-fill" element={<ProjectPathRedirect path="/gaps" />} />
          <Route path="/workspace/:workspace/projects/:id/gaps/review" element={<ProjectPathRedirect path="/gaps" />} />
          <Route path="/workspace/:workspace/projects/:id/generate" element={<GenerateProgress showToast={showToast} />} />
          <Route path="/workspace/:workspace/projects/:id/coverage" element={<CoverageHeatmap showToast={showToast} />} />
          <Route path="/workspace/:workspace/projects/:id/editor" element={<CoCreationEditor showToast={showToast} />} />
          <Route path="/workspace/:workspace/projects/:id/export" element={<FinalExport showToast={showToast} />} />
          <Route path="/workspace/:workspace/materials/structured" element={<MaterialDB showToast={showToast} />} />
          <Route path="/workspace/:workspace/materials/wiki" element={<MaterialWiki showToast={showToast} />} />
          <Route path="/workspace/:workspace/logs" element={<AuditLog showToast={showToast} />} />
          <Route path="/projects" element={<ProjectList showToast={showToast} />} />
          <Route path="/projects/:id" element={<ProjectEntryRedirect />} />
          <Route path="/projects/:id/template-directory" element={<ParseResult showToast={showToast} />} />
          <Route path="/projects/:id/parse" element={<ProjectPathRedirect path="/template-directory" />} />
          <Route path="/projects/:id/directory" element={<ProjectPathRedirect path="/template-directory" />} />
          <Route path="/projects/:id/outline" element={<OutlineReview showToast={showToast} />} />
          <Route path="/projects/:id/gaps" element={<GapRecognition showToast={showToast} />} />
          <Route path="/projects/:id/gaps-fill" element={<ProjectPathRedirect path="/gaps" />} />
          <Route path="/projects/:id/gaps/review" element={<ProjectPathRedirect path="/gaps" />} />
          <Route path="/projects/:id/generate" element={<GenerateProgress showToast={showToast} />} />
          <Route path="/projects/:id/coverage" element={<CoverageHeatmap showToast={showToast} />} />
          <Route path="/projects/:id/editor" element={<CoCreationEditor showToast={showToast} />} />
          <Route path="/projects/:id/export" element={<FinalExport showToast={showToast} />} />
          <Route path="/materials/structured" element={<MaterialDB showToast={showToast} />} />
          <Route path="/materials/wiki" element={<MaterialWiki showToast={showToast} />} />
          <Route path="/audit" element={<AuditLog showToast={showToast} />} />
          <Route path="/settings" element={<Settings showToast={showToast} />} />
        </Routes>
      </AppShell>
    </>
  )
}
