import { useNavigate } from 'react-router-dom'
import { useWorkspaceSlug, workspaceRoute } from '../../utils/workspace'

export default function StageBreadcrumb({ currentLabel = '当前进度', className = '-mt-2 -ml-6' }) {
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()

  return (
    <div className={`flex items-center gap-3 text-[14px] ${className}`.trim()}>
      <button
        type="button"
        onClick={() => navigate(workspaceSlug ? workspaceRoute(workspaceSlug, '/projects') : '/projects')}
        className="stage-breadcrumb-link"
      >
        ← 项目总览
      </button>
      <span className="text-[#9baab9]">|</span>
      <span className="text-[#2f4a62] font-medium">{currentLabel}</span>
    </div>
  )
}
