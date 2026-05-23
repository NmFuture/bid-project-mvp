import { useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import enterpriseLogo from '../../assets/logo-removebg.png'
import {
  WORKSPACE_TYPES,
  workspaceFromPathname,
  workspaceRoute,
} from '../../utils/workspace'
import {
  availableWorkspacesFor,
  defaultWorkspaceFor,
  canViewBothWorkspaces,
} from '../../utils/permissions'
import RoleChip from '../shared/RoleChip'

// 一级导航：6 项，对所有角色一致；2-5 项的链接随当前 workspace 变化。
const NAV_DEFINITIONS = [
  { key: 'dashboard', icon: 'dashboard', label: '工作台', match: /^\/dashboard/, path: () => '/dashboard' },
  {
    key: 'parse',
    icon: 'document_scanner',
    label: '解析',
    match: /^\/(parse|review)/,
    path: (slug) => (slug === 'business' ? '/parse/business' : '/parse/technical'),
  },
  {
    key: 'projects',
    icon: 'folder_open',
    label: '项目',
    match: /^(\/workspace\/[^/]+)?\/projects/,
    path: (slug) => workspaceRoute(slug, '/projects'),
  },
  {
    key: 'materials',
    icon: 'database',
    label: '素材库',
    match: /^(\/workspace\/[^/]+)?\/materials/,
    path: (slug) => workspaceRoute(slug, '/materials/structured'),
  },
  {
    key: 'logs',
    icon: 'history',
    label: '日志',
    match: /^(\/workspace\/[^/]+)?\/(audit|logs)/,
    path: (slug) => workspaceRoute(slug, '/logs'),
  },
  { key: 'settings', icon: 'settings', label: '设置', match: /^\/settings/, path: () => '/settings' },
]

const WORKSPACE_STORAGE_KEY = 'sewpg.workspace'

export default function AppShell({ children, currentUser = null, onLogout = () => {} }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [showUserMenu, setShowUserMenu] = useState(false)

  const userName = String(currentUser?.name || '当前用户')
  const userEmail = String(currentUser?.email || '')
  const userDept = String(currentUser?.dept || '')
  const userRole = currentUser?.role || null
  const userInitial = userName[0] || '用'

  const allowedWorkspaces = useMemo(() => availableWorkspacesFor(currentUser), [currentUser])

  const urlWorkspace = workspaceFromPathname(location.pathname)
  const [manualWorkspace, setManualWorkspace] = useState(null)

  const activeWorkspace = useMemo(() => {
    if (urlWorkspace && allowedWorkspaces.includes(urlWorkspace)) return urlWorkspace
    if (manualWorkspace && allowedWorkspaces.includes(manualWorkspace)) return manualWorkspace
    if (typeof window !== 'undefined') {
      const stored = window.sessionStorage.getItem(WORKSPACE_STORAGE_KEY)
      if (stored && allowedWorkspaces.includes(stored)) return stored
    }
    return defaultWorkspaceFor(currentUser)
  }, [urlWorkspace, manualWorkspace, allowedWorkspaces, currentUser])

  useEffect(() => {
    if (typeof window === 'undefined' || !activeWorkspace) return
    window.sessionStorage.setItem(WORKSPACE_STORAGE_KEY, activeWorkspace)
  }, [activeWorkspace])

  useEffect(() => {
    if (!showUserMenu) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setShowUserMenu(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showUserMenu])

  const showSwitcher = canViewBothWorkspaces(currentUser)
  const workspaceForLinks = activeWorkspace
  const isWorkspaceExperience = location.pathname.startsWith('/workspace/tech')
    || location.pathname.startsWith('/parse/technical')
    || location.pathname.startsWith('/workspace/business')
    || location.pathname.startsWith('/parse/business')

  const handleSwitchWorkspace = (slug) => {
    if (slug === activeWorkspace) return
    setManualWorkspace(slug)
    if (urlWorkspace) {
      const tail = location.pathname.replace(/^\/workspace\/[^/]+/, '')
      navigate(`/workspace/${slug}${tail}`)
    }
  }

  const navItems = NAV_DEFINITIONS.map((it) => ({
    ...it,
    to: it.path(workspaceForLinks),
  }))

  const isActive = (def) => def.match.test(location.pathname)

  return (
    <div className={isWorkspaceExperience ? 'flex min-h-[100dvh] flex-col overflow-hidden bg-[#f6f8fb]' : 'h-screen flex flex-col overflow-hidden bg-surface'}>
      <header className={`fixed top-0 w-full z-50 h-12 bg-[#05202E] text-white border-b border-[#154e7a] flex items-center justify-between gap-2 px-3 md:px-5 ${isWorkspaceExperience ? 'shadow-[0_8px_30px_-22px_rgba(0,0,0,0.6)]' : ''}`}>
        <div className="flex items-center gap-3 min-w-0">
          <span className="inline-flex h-8 shrink-0 items-center rounded-sm bg-white px-2 py-1 shadow-sm">
            <img src={enterpriseLogo} alt="上海电气" className="h-6 w-auto object-contain" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-white font-headline leading-none truncate">
            投标智能体平台
          </span>
        </div>

        {showSwitcher && (
          <div className={`hidden md:flex items-center gap-1 rounded-full bg-white/10 p-0.5 ${isWorkspaceExperience ? 'border border-white/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]' : 'backdrop-blur'}`}>
            {allowedWorkspaces.map((slug) => {
              const ws = WORKSPACE_TYPES[slug]
              if (!ws) return null
              const active = activeWorkspace === slug
              return (
                <button
                  key={slug}
                  type="button"
                  onClick={() => handleSwitchWorkspace(slug)}
                  className={`inline-flex items-center gap-1.5 px-3 h-7 rounded-full text-xs font-medium transition-all ${isWorkspaceExperience ? 'duration-200' : ''} ${active ? 'bg-white text-[#05202E] shadow-sm' : isWorkspaceExperience ? 'text-white/80 hover:bg-white/10 hover:text-white' : 'text-white/80 hover:text-white'}`}
                >
                  <span
                    className="material-symbols-outlined text-[15px]"
                    style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                  >
                    {ws.icon}
                  </span>
                  {ws.label}
                </button>
              )
            })}
          </div>
        )}

        <div className="flex items-center gap-2">
          {userRole && (
            <span className="hidden md:inline-flex">
              <RoleChip role={userRole} />
            </span>
          )}
          <span className="hidden lg:inline text-xs text-[#d6ebff]">{userName}</span>
          <div className="relative">
            <button
              className="w-8 h-8 rounded-full overflow-hidden border border-[#8fb8d8] bg-[#20679f] flex items-center justify-center text-white font-semibold text-sm"
              onClick={() => setShowUserMenu((v) => !v)}
              aria-label="用户菜单"
              aria-haspopup="menu"
              aria-expanded={showUserMenu}
            >
              {userInitial}
            </button>
            {showUserMenu && (
              <div className="absolute right-0 top-12 w-56 bg-white rounded-xl shadow-[0_8px_24px_-8px_rgba(0,0,0,0.15)] border border-surface-container-high py-2 animate-fade-in z-50" role="menu">
                <div className="px-4 py-3 border-b border-surface-container-high">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-on-surface truncate">{userName}</div>
                    {userRole && <RoleChip role={userRole} showLabel={false} />}
                  </div>
                  {userDept && <div className="text-xs text-on-surface-variant mt-1 truncate">{userDept}</div>}
                  {userEmail && <div className="text-[11px] text-outline mt-1 truncate font-mono">{userEmail}</div>}
                </div>
                <button
                  type="button"
                  role="menuitem"
                  className="w-full text-left flex items-center gap-3 px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                  onClick={() => {
                    setShowUserMenu(false)
                    navigate('/settings')
                  }}
                >
                  <span className="material-symbols-outlined text-lg">settings</span>
                  设置
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowUserMenu(false)
                    onLogout?.()
                  }}
                  className="w-full text-left flex items-center gap-3 px-4 py-2.5 text-sm text-error hover:bg-error-container/30 transition-colors"
                >
                  <span className="material-symbols-outlined text-lg">logout</span>
                  退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex flex-1 pt-12 min-h-0">
        <aside className={`hidden md:flex flex-col bg-[#0067B6] fixed left-0 top-12 ${isWorkspaceExperience ? 'h-[calc(100dvh-3rem)] shadow-[10px_0_28px_-24px_rgba(0,64,114,0.8)]' : 'h-[calc(100vh-3rem)]'} w-[78px] z-40 border-r border-[#0f77c4]`}>
          <nav className="flex-1 overflow-y-auto flex flex-col gap-0 px-0 font-headline text-xs">
            {navItems.map((item) => {
              const active = isActive(item)
              return (
                <NavLink
                  key={item.key}
                  to={item.to}
                  className={`${isWorkspaceExperience ? 'group relative' : ''} w-full flex flex-col items-center justify-center gap-1 px-1 py-3 border-y border-transparent transition-all ${isWorkspaceExperience ? 'duration-200' : ''} ${active ? 'bg-[#4C95CD] text-white border-[#62a2d4]' : 'text-white/85 hover:text-white hover:bg-[#237ac0]'}`}
                >
                  {isWorkspaceExperience && active ? <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-white" /> : null}
                  <span
                    className={`material-symbols-outlined text-[20px] ${isWorkspaceExperience ? `transition-transform duration-200 ${active ? 'scale-105' : 'group-hover:scale-105'}` : ''}`}
                    style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                  >
                    {item.icon}
                  </span>
                  <span className="tracking-wide leading-none font-semibold text-[11px]">{item.label}</span>
                </NavLink>
              )
            })}
          </nav>

          {workspaceForLinks && WORKSPACE_TYPES[workspaceForLinks] && (
            <div className="px-2 pb-2 pt-1 border-t border-white/15">
              <div className="rounded-md bg-white/10 px-2 py-1.5 text-[10px] text-white/85 leading-tight text-center">
                <span
                  className="material-symbols-outlined text-[14px] block"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  {WORKSPACE_TYPES[workspaceForLinks].icon}
                </span>
                <span className="block mt-0.5 font-semibold">
                  {WORKSPACE_TYPES[workspaceForLinks].label}
                </span>
              </div>
            </div>
          )}
        </aside>

        <main className={isWorkspaceExperience ? 'workspace-shell-main flex-1 md:ml-[78px] overflow-y-auto min-h-0 px-4 pt-4 pb-24 md:px-6 md:py-5 lg:px-8 lg:py-6 xl:px-10' : 'flex-1 md:ml-[78px] overflow-y-auto bg-white min-h-0 px-7 py-4 md:px-10 md:py-5 lg:px-12 lg:py-6 xl:px-14'}>
          {isWorkspaceExperience ? (
            <div className="workspace-shell-frame">
              {children}
            </div>
          ) : children}
        </main>
      </div>

      <footer className={`${isWorkspaceExperience ? 'hidden md:flex bg-white/85' : 'flex bg-surface'} md:ml-[78px] h-7 border-t border-outline-variant/45 text-outline text-xs items-center justify-center`}>
        © 上海电气风电集团股份有限公司版权所有
      </footer>

      {isWorkspaceExperience ? (
        <nav className="fixed inset-x-0 bottom-0 z-50 grid grid-cols-6 border-t border-outline-variant/60 bg-white/95 px-1 pt-1 pb-[calc(env(safe-area-inset-bottom)+0.35rem)] shadow-[0_-12px_28px_-24px_rgba(13,33,55,0.35)] md:hidden">
          {navItems.map((item) => {
            const active = isActive(item)
            return (
              <NavLink
                key={item.key}
                to={item.to}
                className={`relative flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-md px-1 text-[10px] font-semibold transition-colors ${active ? 'bg-primary-fixed text-primary' : 'text-on-surface-variant hover:bg-surface-container-low hover:text-primary'}`}
              >
                {active ? <span className="absolute top-0 h-0.5 w-6 rounded-full bg-primary" /> : null}
                <span
                  className="material-symbols-outlined text-[20px]"
                  style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                >
                  {item.icon}
                </span>
                <span className="leading-none">{item.label}</span>
              </NavLink>
            )
          })}
        </nav>
      ) : null}

      {showUserMenu && (
        <div className="fixed inset-0 z-30" onClick={() => setShowUserMenu(false)} />
      )}
    </div>
  )
}
