import { useNavigate, useParams } from 'react-router-dom'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'

export default function TechnicalStageGroupNav({
  items = [],
  current = '',
  variant = 'default',
  className = '',
}) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()

  const visibleItems = items.filter((item) => item?.path && item?.label)
  if (!visibleItems.length) return null

  const compact = variant === 'compact'
  const shellClass = compact
    ? 'inline-grid grid-flow-col auto-cols-[7.25rem] gap-1 rounded-md border border-surface-container-high bg-surface-container-lowest p-1'
    : 'flex flex-wrap items-center gap-2 border border-surface-container-high bg-surface-container-low px-3 py-2'
  const buttonClass = compact
    ? 'inline-flex h-8 w-full items-center justify-center gap-1.5 rounded px-2.5 text-xs font-semibold transition-colors'
    : 'inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-semibold transition-colors'

  return (
    <div className={`${shellClass} ${className}`.trim()}>
      {visibleItems.map((item) => {
        const active = item.key === current
        return (
          <button
            key={item.key || item.path}
            type="button"
            onClick={() => navigate(projectRoute(id, item.path, workspaceSlug))}
            className={`${buttonClass} ${
              active
                ? 'bg-primary text-on-primary'
                : 'bg-surface-container-lowest text-on-surface-variant hover:bg-surface-container-high'
            }`}
          >
            {item.icon ? <span className="material-symbols-outlined text-[16px] leading-none">{item.icon}</span> : null}
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
