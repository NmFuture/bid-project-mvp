import { projectRoute } from '../../utils/workspace'

const BUSINESS_WORKSPACE = 'business'

const BUSINESS_STAGE_ROUTES = {
  1: '/template-directory',
  2: '/outline',
  3: '/gaps',
  4: '/gaps',
  5: '/editor',
  6: '/editor',
}

const BUSINESS_COMPACT_STAGE_LABELS = {
  1: '目录生成',
  2: '审核目录',
  3: '素材匹配',
  4: '素材匹配',
  5: '共创导出',
  6: '共创导出',
}

const toStageId = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

export const getBusinessCompactStageLabel = (stageId, fallback = '') => (
  BUSINESS_COMPACT_STAGE_LABELS[toStageId(stageId)] || fallback
)

export const getBusinessStageRoute = (projectId, stageId) => {
  const routePath = BUSINESS_STAGE_ROUTES[toStageId(stageId)]
  return routePath && projectId ? projectRoute(projectId, routePath, BUSINESS_WORKSPACE) : ''
}
