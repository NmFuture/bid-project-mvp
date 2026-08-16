import {
  technicalDirectoryAPI,
  technicalGapsAPI,
  technicalGenerateAPI,
  technicalParseAPI,
  technicalScoreIndexAPI,
} from '../../api/index.js'
import { directoryDisplayPercentage } from './technicalDirectoryProgress.js'
import { bodyFillDisplayPercentage } from './technicalBodyFillProgress.js'
import { factCurateDisplayPercentage } from './technicalFactCurateProgress.js'
import { generationDisplayPercentage } from './technicalGenerationProgress.js'
import { parseDisplayPercentage } from './technicalParseUploadRecovery.js'
import { scoreIndexDisplayPercentage } from './technicalScoreIndexProgress.js'

const projectRoute = (projectId, page) => `/workspace/tech/projects/${encodeURIComponent(projectId)}/${page}`

// displayPercentage 必须与对应页面进度条同一算法，否则右下角卡片和页面会显示两个百分比
export const TECHNICAL_TASK_DEFINITIONS = {
  parse: {
    taskName: '技术标解析',
    status: (projectId) => technicalParseAPI.progress(projectId),
    displayPercentage: (progress) => parseDisplayPercentage(progress || {}),
    route: ({ projectId }) => `/parse/technical?projectId=${encodeURIComponent(projectId)}`,
  },
  'directory-generate': {
    taskName: '生成目录',
    status: (projectId) => technicalDirectoryAPI.status(projectId),
    displayPercentage: (progress) => directoryDisplayPercentage(progress || {}),
    route: ({ projectId }) => projectRoute(projectId, 'template-directory'),
  },
  'outline-regenerate': {
    taskName: '重新生成目录',
    status: (projectId) => technicalDirectoryAPI.status(projectId),
    displayPercentage: (progress) => directoryDisplayPercentage(progress || {}),
    route: ({ projectId }) => projectRoute(projectId, 'outline'),
  },
  'material-match': {
    taskName: '素材匹配',
    status: (projectId) => technicalGapsAPI.detectionStatus(projectId),
    route: ({ projectId }) => projectRoute(projectId, 'outline'),
  },
  // 首次生成正文和重新生成正文是后端同一个 fill-generation 任务，只登记一条，
  // 由发起页写入 taskName 和 page，恢复时不改写，避免同一个任务出现两张卡。
  'body-generate': {
    taskName: '生成正文',
    status: (projectId) => technicalGenerateAPI.status(projectId),
    displayPercentage: (progress) => generationDisplayPercentage(progress || {}),
    route: ({ projectId, page }) => projectRoute(projectId, page || 'gaps'),
  },
  'index-regenerate': {
    taskName: '重新生成索引',
    status: (projectId) => technicalScoreIndexAPI.status(projectId),
    displayPercentage: (progress) => scoreIndexDisplayPercentage(progress || {}),
    route: ({ projectId }) => projectRoute(projectId, 'editor'),
  },
  // 下面两个同样跑在 worker 队列里（fact_curate / technical_body_fill），关掉页面任务照跑，
  // 以前只能守在缺口页看进度，现在跟其他任务一样落到右下角卡片。
  // 两者的状态都包在一层 xxxState 里，与其他任务的扁平结构不同，取值时要多剥一层。
  'fact-curate': {
    taskName: '事实表 AI 填写',
    status: (projectId) => technicalGapsAPI.curateFactsStatus(projectId),
    displayPercentage: (progress) => factCurateDisplayPercentage(progress?.factCurateState || progress || {}),
    route: ({ projectId }) => projectRoute(projectId, 'gaps'),
  },
  'body-fill': {
    taskName: '一键填写',
    status: (projectId) => technicalGapsAPI.bodyFillStatus(projectId),
    displayPercentage: (progress) => bodyFillDisplayPercentage(progress?.bodyFillState || progress || {}),
    route: ({ projectId }) => projectRoute(projectId, 'gaps'),
  },
}

export function technicalTaskRoute(task) {
  const definition = TECHNICAL_TASK_DEFINITIONS[task?.taskType]
  const base = definition?.route?.(task) || '/workspace/tech/projects'
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}progressTask=${encodeURIComponent(task?.taskType || '')}`
}
