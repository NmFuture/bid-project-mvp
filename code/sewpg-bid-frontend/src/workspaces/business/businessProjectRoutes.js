export const businessProjectParseResultRoute = (projectId = '') =>
  projectId ? `/parse/business?projectId=${encodeURIComponent(projectId)}` : '/parse/business'

export const businessProjectParseResultMenuRoute = (projectId = '', event = null) => {
  event?.stopPropagation?.()
  return businessProjectParseResultRoute(projectId)
}

export const businessProjectParseResultNavigation = (projectId = '') => ({
  to: businessProjectParseResultRoute(projectId),
  options: { replace: true },
})

export const selectBusinessParseProjectId = ({
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

export const shouldSyncBusinessProjectParseResultRoute = ({
  projectId = '',
  queryProjectId = '',
  parseCompleted = false,
} = {}) => Boolean(parseCompleted && projectId && projectId !== queryProjectId)
