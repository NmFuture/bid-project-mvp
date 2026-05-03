import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import enterpriseLogo from '../../assets/logo-removebg.png'
import { WORKSPACE_TYPES, workspaceFromPathname, workspaceRoute } from '../../utils/workspace'

const NAV_ITEMS = [
  { path: '/parse', icon: 'document_scanner', label: '解析', match: '/parse' },
  { path: '/workspace/tech/projects', icon: 'engineering', label: '技术标', match: '/workspace/tech' },
  { path: '/workspace/business/projects', icon: 'request_quote', label: '商务标', match: '/workspace/business' },
  { path: '/audit', icon: 'history', label: '审计', match: '/audit' },
  { path: '/settings', icon: 'settings', label: '设置', match: '/settings' },
]

const WORKSPACE_NAV_ITEMS = [
  { key: 'projects', path: '/projects', icon: 'folder_open', label: '项目' },
  { key: 'materials', path: '/materials/structured', icon: 'database', label: '素材库' },
  { key: 'logs', path: '/logs', icon: 'history_edu', label: '日志' },
]

export default function AppShell({ children, currentUser = null, onLogout = () => {} }) {
  const location = useLocation()
  const [showUserMenu, setShowUserMenu] = useState(false)
  const userName = String(currentUser?.name || '当前用户')
  const userEmail = String(currentUser?.email || '')
  const userAvatar = String(currentUser?.avatar || userName[0] || '用')
  const workspaceSlug = workspaceFromPathname(location.pathname)
  const workspace = workspaceSlug ? WORKSPACE_TYPES[workspaceSlug] : null

  const isActive = (match) => location.pathname.startsWith(match) || (match === '/parse' && location.pathname.startsWith('/review'))
  const isWorkspaceNavActive = (item) => {
    const target = workspaceRoute(workspaceSlug, item.path)
    if (item.key === 'projects') {
      return location.pathname === target || /^\/workspace\/[^/]+\/projects(\/|$)/.test(location.pathname)
    }
    if (item.key === 'materials') {
      return /^\/workspace\/[^/]+\/materials(\/|$)/.test(location.pathname)
    }
    return location.pathname.startsWith(target)
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* ===== Header ===== */}
      <header className="fixed top-0 w-full z-50 h-12 bg-[#05202E] text-white border-b border-[#154e7a] flex items-center justify-between gap-2 px-3 md:px-5">
        <div className="flex items-center gap-3 min-w-0">
          <img
            src={enterpriseLogo}
            alt="上海电气"
            className="h-7 w-auto object-contain shrink-0"
          />
          <span className="text-[18px] font-semibold tracking-tight text-white font-headline leading-none truncate">
            投标智能体平台
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="hidden md:inline text-xs text-[#d6ebff]">欢迎您，{userName}</span>
          {/* User Avatar */}
          <div className="relative">
            <button
              className="w-8 h-8 rounded-full overflow-hidden border border-[#8fb8d8] cursor-pointer bg-[#20679f] flex items-center justify-center text-white font-semibold text-sm"
              onClick={() => setShowUserMenu(!showUserMenu)}
            >
              {userAvatar}
            </button>
            {showUserMenu && (
              <div className="absolute right-0 top-12 w-48 bg-white rounded-xl shadow-[0_8px_24px_-8px_rgba(0,0,0,0.15)] border border-surface-container-high py-2 animate-fade-in z-50">
                <div className="px-4 py-3 border-b border-surface-container-high">
                  <div className="text-sm font-semibold text-on-surface">{userName}</div>
                  <div className="text-xs text-outline">{userEmail || '未绑定邮箱'}</div>
                </div>
                <button
                  type="button"
                  className="w-full text-left flex items-center gap-3 px-4 py-2.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
                >
                  <span className="material-symbols-outlined text-lg">person</span>
                  个人信息
                </button>
                <button
                  type="button"
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

      {/* ===== Sidebar + Main ===== */}
      <div className="flex flex-1 pt-12 min-h-0">
        {/* Sidebar */}
        <aside className="hidden md:flex flex-col bg-[#0067B6] fixed left-0 top-12 h-[calc(100vh-4.75rem)] w-[74px] z-40 pt-0 pb-0 border-r border-[#0f77c4]">
          {/* Nav Items */}
          <nav className="flex-1 overflow-y-auto flex flex-col gap-0 px-0 font-headline text-xs">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={`w-full flex flex-col items-center justify-center gap-1 px-0 py-3 border-y border-transparent transition-colors ${
                  isActive(item.match)
                    ? 'bg-[#4C95CD] text-white border-[#62a2d4]'
                    : 'text-white/90 hover:text-white hover:bg-[#237ac0]'
                }`}
              >
                <span
                  className="material-symbols-outlined text-[19px]"
                  style={{ fontVariationSettings: isActive(item.match) ? "'FILL' 1" : "'FILL' 0" }}
                >
                  {item.icon}
                </span>
                <span className="tracking-wide leading-none font-semibold">{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 md:ml-[74px] overflow-y-auto px-7 py-4 md:px-10 md:py-5 lg:px-12 lg:py-6 xl:px-14 relative bg-white min-h-0">
          {workspace && (
            <div className="mb-4 flex flex-col gap-3 border-b border-[#d7e1ec] pb-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-2 text-sm font-semibold text-[#163b58]">
                <span className="material-symbols-outlined text-[18px] text-[#0067B6]">{workspace.icon}</span>
                <span>{workspace.label}工作区</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {WORKSPACE_NAV_ITEMS.map((item) => {
                  const selected = isWorkspaceNavActive(item)
                  return (
                    <NavLink
                      key={item.key}
                      to={workspaceRoute(workspaceSlug, item.path)}
                      className={`inline-flex h-8 items-center gap-1.5 border px-3 text-sm font-medium transition-colors ${
                        selected
                          ? 'border-[#0067B6] bg-[#0067B6] text-white'
                          : 'border-[#c7d4e0] bg-white text-[#36576f] hover:border-[#0067B6] hover:text-[#0067B6]'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[17px]">{item.icon}</span>
                      {item.label}
                    </NavLink>
                  )
                })}
              </div>
            </div>
          )}
          {children}
        </main>
      </div>

      <footer className="md:ml-[74px] h-7 border-t border-outline-variant/45 bg-surface text-outline text-xs flex items-center justify-center">
        © 上海电气风电集团股份有限公司版权所有
      </footer>

      {/* Click outside to close menus */}
      {showUserMenu && (
        <div
          className="fixed inset-0 z-30"
          onClick={() => { setShowUserMenu(false) }}
        />
      )}
    </div>
  )
}
