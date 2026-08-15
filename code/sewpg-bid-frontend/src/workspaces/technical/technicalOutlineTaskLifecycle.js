export const scopeTechnicalTaskPayload = (projectId, payload) => ({
  ...payload,
  _projectId: String(projectId),
})

export const technicalTaskBelongsToProject = (payload, projectId) => (
  Boolean(payload)
  && String(payload._projectId) === String(projectId)
)

export const technicalTaskResponseMatchesProject = (capturedId, currentId) => (
  capturedId !== null
  && capturedId !== undefined
  && String(capturedId) !== ''
  && String(capturedId) === String(currentId)
)

export const canStartTechnicalTaskFinalize = ({
  payload,
  projectId,
  shouldFinalize,
  epoch,
  handledEpoch,
  finalizingEpoch,
}) => (
  technicalTaskBelongsToProject(payload, projectId)
  && Boolean(shouldFinalize)
  && Number(epoch) > 0
  && Number(handledEpoch) !== Number(epoch)
  && Number(finalizingEpoch) !== Number(epoch)
)

const RECOVERABLE_ACTIVE_STATUSES = new Set(['queued', 'running', 'processing', 'cancel_requested'])
const RECOVERABLE_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const TASK_STATE_TIMESTAMPS = ['startedAt', 'updatedAt', 'generatedAt', 'completedAt']

export const recoverableTechnicalTaskState = (payload, requestStartedAt) => {
  const status = String(payload?.status || '').toLowerCase()
  if (RECOVERABLE_ACTIVE_STATUSES.has(status)) return true
  if (!RECOVERABLE_TERMINAL_STATUSES.has(status)) return false

  const requestTime = typeof requestStartedAt === 'number'
    ? requestStartedAt
    : Date.parse(String(requestStartedAt || ''))
  if (!Number.isFinite(requestTime)) return false

  return TASK_STATE_TIMESTAMPS.some((field) => {
    const timestamp = Date.parse(String(payload?.[field] || ''))
    return Number.isFinite(timestamp) && timestamp >= requestTime
  })
}
