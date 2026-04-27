import { projectRoute } from './workspace'

export const STAGE_ROUTE_BUILDERS = {
  1: (projectId, workspaceSlug = '') => projectRoute(projectId, '/parse', workspaceSlug),
  2: (projectId, workspaceSlug = '') => projectRoute(projectId, '/directory', workspaceSlug),
  3: (projectId, workspaceSlug = '') => projectRoute(projectId, '/outline', workspaceSlug),
  4: (projectId, workspaceSlug = '') => projectRoute(projectId, '/gaps', workspaceSlug),
  5: (projectId, workspaceSlug = '') => projectRoute(projectId, '/gaps-fill', workspaceSlug),
  6: (projectId, workspaceSlug = '') => projectRoute(projectId, '/gaps/review', workspaceSlug),
  7: (projectId, workspaceSlug = '') => projectRoute(projectId, '/generate', workspaceSlug),
  8: (projectId, workspaceSlug = '') => projectRoute(projectId, '/coverage', workspaceSlug),
  9: (projectId, workspaceSlug = '') => projectRoute(projectId, '/editor', workspaceSlug),
  10: (projectId, workspaceSlug = '') => projectRoute(projectId, '/export', workspaceSlug),
}

const toStageId = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

export const getStageRoute = (projectId, stageId, workspaceSlug = '') => {
  const resolvedStageId = toStageId(stageId)
  const builder = STAGE_ROUTE_BUILDERS[resolvedStageId]
  if (!builder || !projectId) return ''
  return builder(projectId, workspaceSlug)
}

export const getActiveStageId = (stages = []) => {
  if (!Array.isArray(stages) || !stages.length) return 1

  const activeStage = stages.find((stage) => stage?.status === 'active')
  if (activeStage) return Math.max(1, toStageId(activeStage.id) || 1)

  const completedIds = stages
    .filter((stage) => stage?.status === 'completed')
    .map((stage) => toStageId(stage.id))
    .filter(Boolean)

  if (!completedIds.length) return 1

  const highestCompleted = Math.max(...completedIds)
  return Math.min(10, Math.max(1, highestCompleted + 1))
}

export const getStrictStageLockReason = (stages = [], targetStageId) => {
  const resolvedTarget = toStageId(targetStageId)
  if (!resolvedTarget) return '阶段信息异常，请刷新后重试。'

  const activeStageId = getActiveStageId(stages)
  if (resolvedTarget > activeStageId) {
    return `请先完成当前阶段 S${activeStageId}`
  }

  return ''
}
