import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
  { path: '/projects', icon: 'folder_open', label: '项目', match: '/projects' },
  { path: '/materials/structured', icon: 'database', label: '素材库', match: '/materials' },
  { path: '/audit', icon: 'history_edu', label: '审计', match: '/audit' },
  { path: '/settings', icon: 'settings', label: '设置', match: '/settings' },
]

export default function AppShell({ children, currentUser = null, onLogout = () => {} }) {
  const location = useLocation()
  const [showUserMenu, setShowUserMenu] = useState(false)
  const userName = String(currentUser?.name || '当前用户')
  const userEmail = String(currentUser?.email || '')
  const userAvatar = String(currentUser?.avatar || userName[0] || '用')

  const isActive = (match) => location.pathname.startsWith(match)

  return (
    <div className="min-h-screen flex flex-col">
      {/* ===== Header ===== */}
      <header className="fixed top-0 w-full z-50 bg-[#f8f9ff]/80 backdrop-blur-xl shadow-[0_24px_48px_-12px_rgba(0,62,111,0.06)] flex justify-between items-center px-8 h-16">
        <div className="flex items-center">
          <div className="text-lg font-extrabold tracking-tight text-primary font-headline">
            上海电气风电投标智能体
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* User Avatar */}
          <div className="relative">
            <button
              className="w-10 h-10 rounded-full overflow-hidden border border-outline-variant/30 cursor-pointer bg-primary-container flex items-center justify-center text-on-primary font-bold text-sm"
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
      <div className="flex flex-1 pt-16">
        {/* Sidebar */}
        <aside className="hidden md:flex flex-col bg-surface-container-low fixed left-0 top-16 h-[calc(100vh-4rem)] w-64 z-40 pt-8 pb-8 transition-all">
          <div className="px-8 mb-8">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-primary-container flex items-center justify-center text-on-primary font-headline font-bold text-xl shadow-lg shadow-primary/20">
                <span className="material-symbols-outlined">wind_power</span>
              </div>
              <div className="flex flex-col">
                <span className="text-primary font-headline font-extrabold tracking-tight text-lg leading-tight">上海电气</span>
                <span className="text-on-surface-variant text-xs tracking-wider opacity-80">风电投标系统</span>
              </div>
            </div>
          </div>

          {/* Nav Items */}
          <nav className="flex-1 overflow-y-auto flex flex-col gap-2 font-headline font-medium text-sm">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={`flex items-center gap-4 px-8 py-4 transition-all duration-300 ease-out hover:translate-x-1 group ${
                  isActive(item.match)
                    ? 'bg-white text-primary rounded-l-full ml-4 shadow-sm border-r-4 border-secondary font-bold px-6'
                    : 'text-on-surface/70 hover:text-primary'
                }`}
              >
                <span
                  className={`material-symbols-outlined text-xl transition-transform group-hover:scale-110 ${
                    isActive(item.match) ? 'text-primary' : ''
                  }`}
                  style={{ fontVariationSettings: isActive(item.match) ? "'FILL' 1" : "'FILL' 0" }}
                >
                  {item.icon}
                </span>
                <span className="tracking-wide">{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 md:ml-64 overflow-y-auto p-6 md:p-8 lg:p-12 relative bg-surface min-h-[calc(100vh-4rem)]">
          {children}
        </main>
      </div>

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
