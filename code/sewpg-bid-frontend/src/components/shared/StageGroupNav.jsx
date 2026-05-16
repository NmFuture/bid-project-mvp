import { useNavigate, useParams } from 'react-router-dom'
import { projectRoute, useWorkspaceSlug } from '../../utils/workspace'

export default function StageGroupNav({ items = [], current = '' }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()

  const visibleItems = items.filter((item) => item?.path && item?.label)
  if (!visibleItems.length) return null

  return (
    <div className="flex flex-wrap items-center gap-2 border border-surface-container-high bg-surface-container-low px-3 py-2">
      {visibleItems.map((item) => {
        const active = item.key === current
        return (
          <button
            key={item.key || item.path}
            type="button"
            onClick={() => navigate(projectRoute(id, item.path, workspaceSlug))}
            className={`inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-semibold transition-colors ${
              active
                ? 'bg-primary text-on-primary'
                : 'bg-surface-container-lowest text-on-surface-variant hover:bg-surface-container-high'
            }`}
          >
            {item.icon ? <span className="material-symbols-outlined text-[17px]">{item.icon}</span> : null}
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
