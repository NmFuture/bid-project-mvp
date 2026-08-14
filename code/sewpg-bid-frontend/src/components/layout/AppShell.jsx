import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import enterpriseLogo from '../../assets/logo-removebg.png'
import {
  WORKSPACE_TYPES,
  workspaceFromPathname,
  workspaceSwitchRoute,
  workspaceRoute,
} from '../../utils/workspace'
import {
  availableWorkspacesFor,
  defaultWorkspaceFor,
  canViewBothWorkspaces,
} from '../../utils/permissions'
import RoleChip from '../shared/RoleChip'
import ParseRunningBanner from './ParseRunningBanner'

// 一级导航：7 项，对所有角色一致；2-5 项的链接随当前 workspace 变化。
const NAV_DEFINITIONS = [
  { key: 'dashboard', icon: 'dashboard', label: '工作台', match: /^\/dashboard/, path: () => '/dashboard' },
  {
    key: 'parse',
    icon: 'document_scanner',
    label: '解析',
    match: /^\/parse\/(business|technical)/,
    path: (slug) => (slug === 'business' ? '/parse/business' : '/parse/technical'),
  },
  {
    key: 'projects',
    icon: 'folder_open',
    label: '项目',
    match: /^\/workspace\/(business|tech)\/projects/,
    path: (slug) => workspaceRoute(slug, '/projects'),
  },
  {
    key: 'materials',
    icon: 'database',
    label: '素材库',
    match: /^\/workspace\/(business|tech|shared)\/materials/,
    path: (slug) => workspaceRoute(slug, '/materials/raw'),
  },
  {
    key: 'logs',
    icon: 'history',
    label: '日志',
    match: /^\/workspace\/(business|tech)\/logs/,
    path: (slug) => workspaceRoute(slug, '/logs'),
  },
  { key: 'monitoring', icon: 'monitoring', label: '耗时监控', match: /^\/monitoring/, path: () => '/monitoring' },
  { key: 'settings', icon: 'settings', label: '设置', match: /^\/settings/, path: () => '/settings' },
]

const WORKSPACE_STORAGE_KEY = 'sewpg.workspace'
const SHARED_WORKSPACE_META = {
  icon: 'database',
  label: '共用',
}

export default function AppShell({ children, currentUser = null, onLogout = () => {} }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [showUserMenu, setShowUserMenu] = useState(false)
  const mainRef = useRef(null)

  // main 是独立滚动容器且跨路由常驻：路由切换时复位滚动位置，
  // 避免上一页的滚动残留/钳制导致新页面内容到达时二次跳变
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
  }, [location.pathname])

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
  const isSharedWorkspace = location.pathname.startsWith('/workspace/shared')
  const isWorkspaceExperience = location.pathname.startsWith('/workspace/tech')
    || location.pathname.startsWith('/parse/technical')
    || location.pathname.startsWith('/workspace/business')
    || isSharedWorkspace
    || location.pathname.startsWith('/parse/business')

  const handleSwitchWorkspace = (slug) => {
    if (slug === activeWorkspace) return
    setManualWorkspace(slug)
    const nextRoute = workspaceSwitchRoute(`${location.pathname}${location.search}${location.hash}`, slug)
    if (nextRoute) navigate(nextRoute)
  }

  const navItems = NAV_DEFINITIONS.map((it) => ({
    ...it,
    to: it.path(workspaceForLinks),
  }))

  const isActive = (def) => def.match.test(location.pathname)
  const primaryNavItems = navItems.slice(0, 4)
  const moreNavItems = navItems.slice(4)
  const moreNavActive = moreNavItems.some(isActive)
  const workspaceMeta = isSharedWorkspace
    ? SHARED_WORKSPACE_META
    : WORKSPACE_TYPES[workspaceForLinks]

  return (
    <div className={`flex h-[100dvh] flex-col overflow-hidden ${isWorkspaceExperience ? 'bg-workspace' : 'bg-surface'}`}>
      <a
        href="#main-content"
        className="skip-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        跳到主内容
      </a>
      <header className={`fixed top-0 w-full z-50 h-12 bg-brand-deep text-white border-b border-shell-header-border flex items-center justify-between gap-2 px-3 md:px-5 ${isWorkspaceExperience ? 'shadow-[0_8px_30px_-22px_rgba(0,0,0,0.6)]' : ''}`}>
        <div className="flex items-center gap-3 min-w-0">
          <span className="inline-flex h-8 shrink-0 items-center rounded-sm bg-white px-2 py-1 shadow-sm">
            <img src={enterpriseLogo} alt="上海电气" width="96" height="24" className="h-6 w-auto object-contain" />
          </span>
          <span className="truncate font-headline text-sm font-semibold leading-none text-white">
            投标智能体平台
          </span>
        </div>

        {showSwitcher && (
          <div
            className={`hidden md:flex items-center gap-1 rounded-full bg-white/10 p-0.5 ${isWorkspaceExperience ? 'border border-white/10 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]' : 'backdrop-blur'}`}
            role="group"
            aria-label="切换工作区"
          >
            {allowedWorkspaces.map((slug) => {
              const ws = WORKSPACE_TYPES[slug]
              if (!ws) return null
              const active = activeWorkspace === slug
              return (
                <button
                  key={slug}
                  type="button"
                  onClick={() => handleSwitchWorkspace(slug)}
                  aria-pressed={active}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/80 ${active ? 'bg-white text-brand-deep shadow-sm' : isWorkspaceExperience ? 'text-white/80 hover:bg-white/10 hover:text-white' : 'text-white/80 hover:text-white'}`}
                >
                  <span
                    className="material-symbols-outlined text-[15px]"
                    style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                    aria-hidden="true"
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
          <span className="hidden lg:inline text-xs text-brand-muted">{userName}</span>
          <div className="relative">
            <button
              type="button"
              className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-full border border-shell-avatar-border bg-shell-avatar text-sm font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/80 md:h-9 md:w-9"
              onClick={() => setShowUserMenu((v) => !v)}
              aria-label="用户菜单"
              aria-haspopup="menu"
              aria-expanded={showUserMenu}
            >
              {userInitial}
            </button>
            {showUserMenu && (
              <div className="absolute right-0 top-12 z-50 w-56 rounded-lg border border-surface-container-high bg-white py-2 shadow-[0_12px_28px_rgba(13,33,55,0.14)]" role="menu">
                <div className="px-4 py-3 border-b border-surface-container-high">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-on-surface truncate">{userName}</div>
                    {userRole && <RoleChip role={userRole} showLabel={false} />}
                  </div>
                  {userDept && <div className="text-xs text-on-surface-variant mt-1 truncate">{userDept}</div>}
                  {userEmail && <div className="mt-1 truncate font-mono text-xs text-outline">{userEmail}</div>}
                </div>
                <button
                  type="button"
                  role="menuitem"
                  className="w-full text-left flex items-center px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                  onClick={() => {
                    setShowUserMenu(false)
                    navigate('/settings')
                  }}
                >
                  设置
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowUserMenu(false)
                    onLogout?.()
                  }}
                  className="w-full text-left flex items-center px-4 py-2.5 text-sm text-error hover:bg-error-container/30 transition-colors"
                >
                  退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex flex-1 pt-12 min-h-0">
        <aside aria-label="主导航" className={`fixed left-0 top-12 z-40 hidden h-[calc(100dvh-3rem)] w-[78px] flex-col border-r border-shell-rail-border bg-shell-rail md:flex ${isWorkspaceExperience ? 'shadow-[10px_0_28px_-24px_rgba(0,64,114,0.8)]' : ''}`}>
          <nav aria-label="一级导航" className="flex flex-1 flex-col gap-0 overflow-y-auto px-0 font-headline text-xs">
            {navItems.map((item) => {
              const active = isActive(item)
              return (
                <NavLink
                  key={item.key}
                  to={item.to}
                  aria-current={active ? 'page' : undefined}
                  className={`${isWorkspaceExperience ? 'group relative' : ''} flex min-h-14 w-full flex-col items-center justify-center gap-1 border-y border-transparent px-1 py-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white ${active ? 'border-primary-fixed-dim bg-on-primary-fixed-variant text-white' : 'text-white/85 hover:bg-primary hover:text-white'}`}
                >
                  <span
                    className={`material-symbols-outlined text-[20px] ${isWorkspaceExperience ? `transition-transform duration-200 ${active ? 'scale-105' : 'group-hover:scale-105'}` : ''}`}
                    style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                    aria-hidden="true"
                  >
                    {item.icon}
                  </span>
                  <span className="text-xs font-semibold leading-none">{item.label}</span>
                </NavLink>
              )
            })}
          </nav>

          {workspaceMeta && (
            <div className="px-2 pb-2 pt-1 border-t border-white/15">
              <div className="rounded-md bg-white/10 px-2 py-1.5 text-center text-xs leading-tight text-white/85">
                <span
                  className="material-symbols-outlined text-[14px] block"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                  aria-hidden="true"
                >
                  {workspaceMeta.icon}
                </span>
                <span className="block mt-0.5 font-semibold">
                  {workspaceMeta.label}
                </span>
              </div>
            </div>
          )}
        </aside>

        <main
          id="main-content"
          ref={mainRef}
          tabIndex={-1}
          className={`${isWorkspaceExperience ? 'workspace-shell-main' : 'bg-surface-bright'} shell-scroll-area min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-4 pb-24 pt-4 focus:outline-none md:ml-[78px] md:px-6 md:py-5 lg:px-8 lg:py-6 xl:px-10`}
        >
          <div className="workspace-shell-frame">
            {children}
          </div>
        </main>
      </div>

      <footer className={`${isWorkspaceExperience ? 'bg-white/85' : 'bg-surface'} hidden h-7 items-center justify-center border-t border-outline-variant/45 text-xs text-outline md:ml-[78px] md:flex`}>
        © 上海电气风电集团股份有限公司版权所有
      </footer>

      <nav aria-label="移动端主导航" className="fixed inset-x-0 bottom-0 z-50 grid grid-cols-5 border-t border-outline-variant/60 bg-white px-1 pb-[calc(env(safe-area-inset-bottom)+0.35rem)] pt-1 shadow-[0_-12px_28px_-24px_rgba(13,33,55,0.35)] md:hidden">
          {primaryNavItems.map((item) => {
            const active = isActive(item)
            return (
              <NavLink
                key={item.key}
                to={item.to}
                aria-current={active ? 'page' : undefined}
                className={`relative flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-md px-1 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${active ? 'bg-primary-fixed text-primary' : 'text-on-surface-variant hover:bg-surface-container-low hover:text-primary'}`}
              >
                {active ? <span className="absolute top-0 h-0.5 w-6 rounded-full bg-primary" /> : null}
                <span
                  className="material-symbols-outlined text-[20px]"
                  style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                  aria-hidden="true"
                >
                  {item.icon}
                </span>
                <span className="leading-none">{item.label}</span>
              </NavLink>
            )
          })}
          <details
            className="group relative"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) {
                event.currentTarget.removeAttribute('open')
              }
            }}
            onKeyDown={(event) => {
              if (event.key !== 'Escape') return
              event.currentTarget.removeAttribute('open')
              event.currentTarget.querySelector('summary')?.focus()
            }}
          >
            <summary className={`relative flex min-h-12 cursor-pointer list-none flex-col items-center justify-center gap-0.5 rounded-md px-1 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [&::-webkit-details-marker]:hidden ${moreNavActive ? 'bg-primary-fixed text-primary' : 'text-on-surface-variant hover:bg-surface-container-low hover:text-primary'}`}>
              {moreNavActive ? <span className="absolute top-0 h-0.5 w-6 rounded-full bg-primary" /> : null}
              <span className="material-symbols-outlined text-[20px]" aria-hidden="true">more_horiz</span>
              <span className="leading-none">更多</span>
            </summary>
            <div className="absolute bottom-[calc(100%+0.5rem)] right-1 w-48 rounded-lg border border-outline-variant bg-white p-2 shadow-[0_12px_28px_rgba(13,33,55,0.14)]">
              <div className="px-2 pb-1 pt-0.5 text-xs font-semibold text-outline">更多功能</div>
              {moreNavItems.map((item) => {
                const active = isActive(item)
                return (
                  <NavLink
                    key={item.key}
                    to={item.to}
                    onClick={(event) => event.currentTarget.closest('details')?.removeAttribute('open')}
                    aria-current={active ? 'page' : undefined}
                    className={`flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${active ? 'bg-primary-fixed text-primary' : 'text-on-surface hover:bg-surface-container-low'}`}
                  >
                    <span
                      className="material-symbols-outlined text-[19px]"
                      style={{ fontVariationSettings: active ? "'FILL' 1" : "'FILL' 0" }}
                      aria-hidden="true"
                    >
                      {item.icon}
                    </span>
                    <span className="min-w-0 truncate">{item.label}</span>
                  </NavLink>
                )
              })}
            </div>
          </details>
        </nav>

      {showUserMenu && (
        <button
          type="button"
          aria-label="关闭用户菜单"
          tabIndex={-1}
          className="fixed inset-0 z-30 cursor-default"
          onClick={() => setShowUserMenu(false)}
        />
      )}

      <ParseRunningBanner />
    </div>
  )
}
