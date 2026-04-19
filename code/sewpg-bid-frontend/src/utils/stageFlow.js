export const STAGE_ROUTE_BUILDERS = {
  1: (projectId) => `/projects/${projectId}/parse`,
  2: (projectId) => `/projects/${projectId}/directory`,
  3: (projectId) => `/projects/${projectId}/outline`,
  4: (projectId) => `/projects/${projectId}/gaps`,
  5: (projectId) => `/projects/${projectId}/gaps-fill`,
  6: (projectId) => `/projects/${projectId}/gaps/review`,
  7: (projectId) => `/projects/${projectId}/generate`,
  8: (projectId) => `/projects/${projectId}/coverage`,
  9: (projectId) => `/projects/${projectId}/editor`,
  10: (projectId) => `/projects/${projectId}/export`,
}

const toStageId = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

export const getStageRoute = (projectId, stageId) => {
  const resolvedStageId = toStageId(stageId)
  const builder = STAGE_ROUTE_BUILDERS[resolvedStageId]
  if (!builder || !projectId) return ''
  return builder(projectId)
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
