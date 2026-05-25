import { projectRoute } from '../../utils/workspace'

const TECHNICAL_WORKSPACE = 'tech'

const TECHNICAL_STAGE_ROUTES = {
  1: '/template-directory',
  2: '/outline',
  3: '/gaps',
  4: '/gaps',
  5: '/editor',
  6: '/editor',
}

const TECHNICAL_COMPACT_STAGE_LABELS = {
  1: '目录生成',
  2: '目录确认',
  3: '素材匹配',
  4: '素材匹配',
  5: '编辑导出',
  6: '编辑导出',
}

const toStageId = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

export const getTechnicalCompactStageLabel = (stageId, fallback = '') => (
  TECHNICAL_COMPACT_STAGE_LABELS[toStageId(stageId)] || fallback
)

export const getTechnicalStageRoute = (projectId, stageId, workspaceSlug = TECHNICAL_WORKSPACE) => {
  const routePath = TECHNICAL_STAGE_ROUTES[toStageId(stageId)]
  return routePath && projectId ? projectRoute(projectId, routePath, workspaceSlug || TECHNICAL_WORKSPACE) : ''
}
