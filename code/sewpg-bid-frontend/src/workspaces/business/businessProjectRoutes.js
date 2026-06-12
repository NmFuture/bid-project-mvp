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
