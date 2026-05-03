import { projectRoute } from './workspace'

export const STAGE_ROUTE_BUILDERS = {
  1: (projectId, workspaceSlug = '') => projectRoute(projectId, '/template-directory', workspaceSlug),
  2: (projectId, workspaceSlug = '') => projectRoute(projectId, '/outline', workspaceSlug),
  3: (projectId, workspaceSlug = '') => projectRoute(projectId, '/gaps', workspaceSlug),
  4: (projectId, workspaceSlug = '') => projectRoute(projectId, '/generate', workspaceSlug),
  5: (projectId, workspaceSlug = '') => projectRoute(projectId, '/editor', workspaceSlug),
  6: (projectId, workspaceSlug = '') => projectRoute(projectId, '/export', workspaceSlug),
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

export const getStageNavigationRoute = (projectId, stage, workspaceSlug = '') => {
  const routeStageId = typeof stage === 'object' && stage !== null
    ? stage.routeStageId || stage.id
    : stage
  return getStageRoute(projectId, routeStageId, workspaceSlug)
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
  return Math.min(6, Math.max(1, highestCompleted + 1))
}

export const getStrictStageLockReason = (stages = [], targetStageId) => {
  const resolvedTarget = toStageId(targetStageId)
  if (!resolvedTarget) return '阶段信息异常，请刷新后重试。'

  const targetIndex = stages.findIndex((stage) => toStageId(stage?.id) === resolvedTarget)
  const activeIndex = stages.findIndex((stage) => stage?.status === 'active')

  if (targetIndex >= 0 && activeIndex >= 0 && targetIndex > activeIndex) {
    return `请先完成当前阶段：${stages[activeIndex]?.name || `S${stages[activeIndex]?.id}`}`
  }

  if (targetIndex < 0) {
    const activeStageId = getActiveStageId(stages)
    if (resolvedTarget > activeStageId) {
      return `请先完成当前阶段 S${activeStageId}`
    }
  }

  return ''
}
