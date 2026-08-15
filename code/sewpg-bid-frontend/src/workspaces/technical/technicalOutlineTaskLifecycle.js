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
