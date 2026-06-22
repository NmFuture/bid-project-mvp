export const technicalProjectParseResultRoute = (projectId = '') =>
  projectId ? `/parse/technical?projectId=${encodeURIComponent(projectId)}` : '/parse/technical'

export const technicalProjectParseResultMenuRoute = (projectId = '', event = null) => {
  event?.stopPropagation?.()
  return technicalProjectParseResultRoute(projectId)
}

export const technicalProjectParseResultNavigation = (projectId = '') => ({
  to: technicalProjectParseResultRoute(projectId),
  options: { replace: true },
})

export const selectTechnicalParseProjectId = ({
  queryProjectId = '',
  currentProjectId = '',
  reviewItems = [],
} = {}) => {
  const queryId = String(queryProjectId || '').trim()
  if (queryId && reviewItems.some((item) => item?.id === queryId)) return queryId
  const currentId = String(currentProjectId || '').trim()
  if (queryId && currentId && reviewItems.some((item) => item?.id === currentId)) return currentId
  return ''
}

export const shouldSyncTechnicalProjectParseResultRoute = ({
  projectId = '',
  queryProjectId = '',
  parseCompleted = false,
} = {}) => Boolean(parseCompleted && projectId && projectId !== queryProjectId)
