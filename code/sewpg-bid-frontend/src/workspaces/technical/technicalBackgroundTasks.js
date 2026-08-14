export const TECHNICAL_TASK_STORAGE_KEY = 'sewpg.technical.backgroundTasks.v1'
export const TECHNICAL_TASKS_CHANGED_EVENT = 'sewpg:technical-background-tasks-changed'

const TASK_TTL_MS = 7 * 24 * 60 * 60 * 1000
const ACTIVE_STATUSES = new Set(['queued', 'running', 'processing', 'cancel_requested'])

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

export function sortTechnicalTasks(tasks) {
  return [...tasks].sort((left, right) => {
    const activeDelta = Number(ACTIVE_STATUSES.has(String(right.status || '').toLowerCase()))
      - Number(ACTIVE_STATUSES.has(String(left.status || '').toLowerCase()))
    if (activeDelta) return activeDelta
    return Date.parse(right.updatedAt || 0) - Date.parse(left.updatedAt || 0)
  })
}

export function readTechnicalTasks(storage = defaultStorage(), now = Date.now()) {
  const tasks = parseStoredTasks(storage)
  const fresh = tasks.filter((task) => {
    if (!task.key || !task.taskType || !task.projectId) return false
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

export function clearTechnicalTask(taskType, projectId, storage = defaultStorage()) {
  const key = technicalTaskKey(taskType, projectId)
  const tasks = parseStoredTasks(storage)
  const next = tasks.filter((task) => task.key !== key)
  if (next.length === tasks.length) return false
  writeTasks(storage, next)
  return true
}

export const technicalTaskIsActive = (task) => ACTIVE_STATUSES.has(String(task?.status || '').toLowerCase())
