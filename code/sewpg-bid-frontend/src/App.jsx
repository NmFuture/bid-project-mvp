import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { useCallback, useEffect, useState } from 'react'
import AppShell from './components/layout/AppShell'
import Dashboard from './pages/Dashboard'
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
import BusinessTenderReview from './pages/BusinessTenderReview'
import Settings from './pages/Settings'
import Login from './pages/Login'
import Toast from './components/shared/Toast'
import { authAPI } from './api'
import { parseRouteFromBidType, projectRoute, useWorkspaceSlug, workspaceFromSlug, workspaceRoute } from './utils/workspace'
import { canAccessWorkspace, defaultWorkspaceFor } from './utils/permissions'

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
  if (!resolved) return <Navigate to="/dashboard" replace />
  return <Navigate to={workspaceRoute(resolved.slug, '/projects')} replace />
}

function ProjectPathRedirect({ path }) {
  const { id } = useParams()
  const workspaceSlug = useWorkspaceSlug()
  return <Navigate to={projectRoute(id, path, workspaceSlug)} replace />
}

// 角色级 workspace 守卫：T 用户进 /workspace/business/* 强制回到自己的 workspace，反之亦然。
function WorkspaceGuard({ user, children }) {
  const { workspace } = useParams()
  if (!workspace) return children
  if (canAccessWorkspace(user, workspace)) return children
  const fallback = defaultWorkspaceFor(user)
  return <Navigate to={`/workspace/${fallback}/projects`} replace />
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
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard currentUser={session?.user} />} />
          <Route path="/parse" element={<Navigate to="/parse/technical" replace />} />
          <Route path="/parse/technical" element={<TenderReview showToast={showToast} />} />
          <Route path="/parse/business" element={<BusinessTenderReview showToast={showToast} />} />
          <Route path="/review" element={<Navigate to={parseRouteFromBidType('技术标')} replace />} />
          <Route path="/workspace/:workspace" element={<WorkspaceGuard user={session?.user}><WorkspaceRedirect /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects" element={<WorkspaceGuard user={session?.user}><ProjectList showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/flow" element={<WorkspaceGuard user={session?.user}><WorkspaceRedirect /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id" element={<WorkspaceGuard user={session?.user}><ProjectEntryRedirect /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/template-directory" element={<WorkspaceGuard user={session?.user}><ParseResult showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/parse" element={<WorkspaceGuard user={session?.user}><ProjectPathRedirect path="/template-directory" /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/directory" element={<WorkspaceGuard user={session?.user}><ProjectPathRedirect path="/template-directory" /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/outline" element={<WorkspaceGuard user={session?.user}><OutlineReview showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/gaps" element={<WorkspaceGuard user={session?.user}><GapRecognition showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/gaps-fill" element={<WorkspaceGuard user={session?.user}><ProjectPathRedirect path="/gaps" /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/gaps/review" element={<WorkspaceGuard user={session?.user}><ProjectPathRedirect path="/gaps" /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/generate" element={<WorkspaceGuard user={session?.user}><GenerateProgress showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/coverage" element={<WorkspaceGuard user={session?.user}><CoverageHeatmap showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/editor" element={<WorkspaceGuard user={session?.user}><CoCreationEditor showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/projects/:id/export" element={<WorkspaceGuard user={session?.user}><FinalExport showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/materials/structured" element={<WorkspaceGuard user={session?.user}><MaterialDB showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/materials/wiki" element={<WorkspaceGuard user={session?.user}><MaterialWiki showToast={showToast} /></WorkspaceGuard>} />
          <Route path="/workspace/:workspace/logs" element={<WorkspaceGuard user={session?.user}><AuditLog showToast={showToast} /></WorkspaceGuard>} />
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
