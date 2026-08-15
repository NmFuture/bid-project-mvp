// 技术标/商务标解析结果路由的同源实现：两侧仅 /parse/<workspace> 前缀不同，
// 由 createProjectParseResultRoutes 绑定前缀；select/shouldSync 与前缀无关，直接共享。

export const createProjectParseResultRoutes = (parseBasePath = '') => {
  const projectParseResultRoute = (projectId = '') =>
    projectId ? `${parseBasePath}?projectId=${encodeURIComponent(projectId)}` : parseBasePath

  const projectParseResultMenuRoute = (projectId = '', event = null) => {
    event?.stopPropagation?.()
    return projectParseResultRoute(projectId)
  }

  const projectParseResultNavigation = (projectId = '') => ({
    to: projectParseResultRoute(projectId),
    options: { replace: true },
  })

  return {
    projectParseResultRoute,
    projectParseResultMenuRoute,
    projectParseResultNavigation,
  }
}

export const selectParseProjectId = ({
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

export const shouldSyncProjectParseResultRoute = ({
  projectId = '',
  queryProjectId = '',
  parseCompleted = false,
} = {}) => Boolean(parseCompleted && projectId && projectId !== queryProjectId)
