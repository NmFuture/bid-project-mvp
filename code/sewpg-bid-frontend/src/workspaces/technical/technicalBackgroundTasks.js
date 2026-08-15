export const TECHNICAL_TASK_STORAGE_KEY = 'sewpg.technical.backgroundTasks.v1'
export const TECHNICAL_TASKS_CHANGED_EVENT = 'sewpg:technical-background-tasks-changed'

const TASK_TTL_MS = 7 * 24 * 60 * 60 * 1000
const ACTIVE_STATUSES = new Set(['queued', 'running', 'processing', 'cancel_requested'])
// 值得作为终态通知留在角落的状态。idle 或状态缺失都算「没有这个任务」：
// 留着会按「任务已完成」渲染，等于凭空多出一条从没发生过的通知。
export const TECHNICAL_TASK_NOTIFIABLE_STATUSES = new Set(['completed', 'failed', 'error', 'cancelled', 'stale'])

const taskStatusName = (task) => String(task?.status || '').toLowerCase()

export const technicalTaskIsTrackable = (task) => (
  ACTIVE_STATUSES.has(taskStatusName(task)) || TECHNICAL_TASK_NOTIFIABLE_STATUSES.has(taskStatusName(task))
)

const defaultStorage = () => (typeof window !== 'undefined' ? window.localStorage : null)

const emitChanged = () => {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(TECHNICAL_TASKS_CHANGED_EVENT))
}

export const technicalTaskKey = (taskType, projectId) => `technical:${taskType}:${projectId}`

const parseStoredTasks = (storage) => {
  if (!storage) return []
  try {
    const parsed = JSON.parse(storage.getItem(TECHNICAL_TASK_STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter((task) => task && typeof task === 'object') : []
  } catch {
    return []
  }
}

const writeTasks = (storage, tasks) => {
  if (!storage) return
  storage.setItem(TECHNICAL_TASK_STORAGE_KEY, JSON.stringify(tasks))
  emitChanged()
}

// 运行中的排在终态通知之前；同一组内按先来后到（开始时间升序）。
// 不能按最近更新时间排：每一拍轮询都会刷新 updatedAt，两条同时在跑的任务会一直互相换位。
export function sortTechnicalTasks(tasks) {
  const startedMs = (task) => {
    const parsed = Date.parse(task?.startedAt || task?.updatedAt || '')
    return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER
  }
  return [...tasks].sort((left, right) => {
    const activeDelta = Number(ACTIVE_STATUSES.has(taskStatusName(right)))
      - Number(ACTIVE_STATUSES.has(taskStatusName(left)))
    if (activeDelta) return activeDelta
    const startedDelta = startedMs(left) - startedMs(right)
    if (startedDelta) return startedDelta
    // 开始时间一样时用稳定键兜底，保证顺序不随刷新抖动
    return String(left?.key || '').localeCompare(String(right?.key || ''))
  })
}

export function readTechnicalTasks(storage = defaultStorage(), now = Date.now()) {
  const tasks = parseStoredTasks(storage)
  const fresh = tasks.filter((task) => {
    if (!task.key || !task.taskType || !task.projectId) return false
    if (!technicalTaskIsTrackable(task)) return false
    const updatedAt = Date.parse(task.updatedAt || task.startedAt || '')
    return Number.isFinite(updatedAt) && now - updatedAt <= TASK_TTL_MS
  })
  if (fresh.length !== tasks.length) writeTasks(storage, fresh)
  return sortTechnicalTasks(fresh)
}

export function markTechnicalTask(task, storage = defaultStorage()) {
  if (!task?.taskType || !task?.projectId) return null
  const key = technicalTaskKey(task.taskType, task.projectId)
  const tasks = parseStoredTasks(storage)
  const current = tasks.find((item) => item.key === key) || {}
  const now = new Date().toISOString()
  const next = {
    ...current,
    ...task,
    key,
    startedAt: task.startedAt || current.startedAt || now,
    updatedAt: task.updatedAt || now,
  }
  writeTasks(storage, [...tasks.filter((item) => item.key !== key), next])
  return next
}

export function updateTechnicalTask(taskType, projectId, patch, storage = defaultStorage()) {
  const key = technicalTaskKey(taskType, projectId)
  const current = parseStoredTasks(storage).find((task) => task.key === key)
  if (!current) return null
  return markTechnicalTask({
    ...current,
    ...patch,
    taskType,
    projectId,
    updatedAt: patch?.updatedAt || new Date().toISOString(),
  }, storage)
}

// 恢复场景专用：已有登记只打补丁，保留发起页写下的任务名和回跳页；查无登记才补建一条。
// 首次正文和重新生成正文共用一条登记，靠这个规则不被后进的页面改名。
export function restoreTechnicalTask(task, storage = defaultStorage()) {
  if (!task?.taskType || !task?.projectId) return null
  const { taskType, projectId, taskName, page, projectName, ...patch } = task
  const patched = updateTechnicalTask(taskType, projectId, patch, storage)
  if (patched) return patched
  return markTechnicalTask({ taskType, projectId, taskName, page, projectName, ...patch }, storage)
}

export function clearTechnicalTask(taskType, projectId, storage = defaultStorage()) {
  const key = technicalTaskKey(taskType, projectId)
  const tasks = parseStoredTasks(storage)
  const next = tasks.filter((task) => task.key !== key)
  if (next.length === tasks.length) return false
  writeTasks(storage, next)
  return true
}

export const technicalTaskIsActive = (task) => ACTIVE_STATUSES.has(taskStatusName(task))
