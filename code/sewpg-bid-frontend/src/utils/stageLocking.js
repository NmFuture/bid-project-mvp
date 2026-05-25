const toStageId = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
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
  if (!resolvedTarget) return '阶段信息异常，请稍后重试。'

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
