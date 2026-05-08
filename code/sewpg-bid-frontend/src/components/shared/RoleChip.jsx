import { ROLE_LABEL } from '../../utils/permissions'

const STYLE = {
  T: 'bg-primary-fixed text-on-primary-fixed-variant',
  B: 'bg-secondary-container text-on-secondary-container',
  TB: 'bg-tertiary-container text-on-tertiary-container',
}

const ICON = {
  T: 'engineering',
  B: 'request_quote',
  TB: 'workspaces',
}

// 角色徽章。在导航、用户菜单、工作台头部展示。
export default function RoleChip({ role, showLabel = true, className = '' }) {
  if (!role) return null
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${STYLE[role] || STYLE.T} ${className}`}
    >
      <span className="material-symbols-outlined text-[14px]" style={{ fontVariationSettings: "'FILL' 1" }}>
        {ICON[role] || 'person'}
      </span>
      {showLabel ? ROLE_LABEL[role] || role : role}
    </span>
  )
}
