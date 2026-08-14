import {
  technicalDirectoryAPI,
  technicalGapsAPI,
  technicalGenerateAPI,
  technicalParseAPI,
  technicalScoreIndexAPI,
} from '../../api/index.js'

const projectRoute = (projectId, page) => `/workspace/tech/projects/${encodeURIComponent(projectId)}/${page}`

export const TECHNICAL_TASK_DEFINITIONS = {
  parse: {
    taskName: '技术标解析',
    status: (projectId) => technicalParseAPI.progress(projectId),
    route: ({ projectId }) => `/parse/technical?projectId=${encodeURIComponent(projectId)}`,
  },
  'directory-generate': {
    taskName: '生成目录',
    status: (projectId) => technicalDirectoryAPI.status(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'template-directory'),
  },
  'outline-regenerate': {
    taskName: '重新生成目录',
    status: (projectId) => technicalDirectoryAPI.status(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'outline'),
  },
  'material-match': {
    taskName: '素材匹配',
    status: (projectId) => technicalGapsAPI.detectionStatus(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'outline'),
  },
  'body-generate': {
    taskName: '生成正文',
    status: (projectId) => technicalGenerateAPI.status(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'gaps'),
  },
  'body-regenerate': {
    taskName: '重新生成正文',
    status: (projectId) => technicalGenerateAPI.status(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'editor'),
  },
  'index-regenerate': {
    taskName: '重新生成索引',
    status: (projectId) => technicalScoreIndexAPI.status(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'editor'),
  },
}

export function technicalTaskRoute(task) {
  const definition = TECHNICAL_TASK_DEFINITIONS[task?.taskType]
  const base = definition?.route?.(task) || '/workspace/tech/projects'
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}progressTask=${encodeURIComponent(task?.taskType || '')}`
}
