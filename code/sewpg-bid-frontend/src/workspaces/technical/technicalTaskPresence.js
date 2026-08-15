import { useEffect } from 'react'

// 本标签页里「哪个技术标任务正被页面自己跟踪、哪个正显示在用户眼前」。
// 只活在内存里：不跨标签页共享，页面卸载即释放，刷新后由页面重新登记。
//
// tracked（页面在跟踪）：该页正在轮询这个任务并把进度写进登记表，
//   右下角任务栈就不要再自己轮询同一个任务，否则两边算出来的百分比会互相打架。
// foreground（正显示在眼前）：页面内进度可见或进度弹窗开着，
//   右下角不重复显示同一个任务；关掉弹窗或离开页面后卡片才出现。
const trackedTasks = new Map()
const foregroundTasks = new Map()
const listeners = new Set()

export const technicalTaskPresenceKey = (taskType, projectId) => (
  `technical:${String(taskType || '')}:${String(projectId || '')}`
)

const notify = () => {
  listeners.forEach((listener) => {
    try {
      listener()
    } catch {
      // 单个订阅者出错不影响其它订阅者
    }
  })
}

const acquire = (registry, key) => {
  registry.set(key, (registry.get(key) || 0) + 1)
  notify()
  let released = false
  return () => {
    if (released) return
    released = true
    const next = (registry.get(key) || 0) - 1
    if (next > 0) registry.set(key, next)
    else registry.delete(key)
    notify()
  }
}

export const isTechnicalTaskTracked = (task) => (
  (trackedTasks.get(technicalTaskPresenceKey(task?.taskType, task?.projectId)) || 0) > 0
)

export const isTechnicalTaskForeground = (task) => (
  (foregroundTasks.get(technicalTaskPresenceKey(task?.taskType, task?.projectId)) || 0) > 0
)

// 每次调用返回新的集合：订阅者拿它当 state，身份变化即触发重算
export const technicalForegroundTaskKeys = () => new Set(foregroundTasks.keys())

export function subscribeTechnicalTaskPresence(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// 测试用：清空登记，避免用例之间互相污染
export function resetTechnicalTaskPresence() {
  trackedTasks.clear()
  foregroundTasks.clear()
  notify()
}

// 声明「本页正在跟踪这个任务」，返回释放函数。foreground 为 true 时同时声明它正显示在眼前。
export function acquireTechnicalTaskPresence(taskType, projectId, { foreground = false } = {}) {
  if (!taskType || !projectId) return () => {}
  const key = technicalTaskPresenceKey(taskType, projectId)
  const releases = [acquire(trackedTasks, key)]
  if (foreground) releases.push(acquire(foregroundTasks, key))
  return () => releases.forEach((release) => release())
}

// 页面在挂载期间声明自己在跟踪某个任务；foreground 为 true 时表示该任务此刻正显示在页面上。
export function useTechnicalTaskPresence(taskType, projectId, foreground = false) {
  useEffect(() => {
    if (!taskType || !projectId) return undefined
    return acquireTechnicalTaskPresence(taskType, projectId)
  }, [taskType, projectId])

  useEffect(() => {
    if (!taskType || !projectId || !foreground) return undefined
    return acquire(foregroundTasks, technicalTaskPresenceKey(taskType, projectId))
  }, [taskType, projectId, foreground])
}
