import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { readRunningParses } from '../../shared/parseRunningMarker'
import {
  markTechnicalTask,
  readTechnicalTasks,
  TECHNICAL_TASKS_CHANGED_EVENT,
  technicalTaskIsActive,
  updateTechnicalTask,
} from '../technicalBackgroundTasks.js'
import {
  TECHNICAL_TASK_DEFINITIONS,
  technicalTaskRoute,
} from '../technicalBackgroundTaskDefinitions.js'

const POLL_INTERVAL_MS = 4000
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'stale'])

const clampPercentage = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : 0
}

export default function TechnicalBackgroundTaskStack() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState(() => readTechnicalTasks().slice(0, 3))

  useEffect(() => {
    let disposed = false

    const load = () => {
      if (!disposed) setTasks(readTechnicalTasks().slice(0, 3))
    }

    const refresh = async () => {
      const storedTasks = readTechnicalTasks()
      readRunningParses()
        .filter((marker) => marker.bidType !== 'business')
        .forEach((marker) => {
          const currentTask = storedTasks.find((task) => (
            task.taskType === 'parse' && task.projectId === marker.projectId
          ))
          markTechnicalTask({
            taskType: 'parse',
            projectId: marker.projectId,
            projectName: marker.projectName || currentTask?.projectName || marker.projectId,
            taskName: TECHNICAL_TASK_DEFINITIONS.parse.taskName,
            status: 'running',
            percentage: 0,
          })
        })

      const current = readTechnicalTasks()
      await Promise.allSettled(current.filter(technicalTaskIsActive).map(async (task) => {
        const definition = TECHNICAL_TASK_DEFINITIONS[task.taskType]
        if (!definition?.status) return
        const progress = await definition.status(task.projectId)
        const status = String(progress?.status || task.status || '').toLowerCase()
        updateTechnicalTask(task.taskType, task.projectId, {
          taskName: task.taskName || definition.taskName,
          status,
          percentage: TERMINAL_STATUSES.has(status) ? 100 : clampPercentage(progress?.percentage),
          summary: progress?.message || progress?.summary || '',
        })
      }))
      load()
    }

    load()
    refresh()
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS)
    window.addEventListener('storage', load)
    window.addEventListener(TECHNICAL_TASKS_CHANGED_EVENT, load)
    return () => {
      disposed = true
      window.clearInterval(timer)
      window.removeEventListener('storage', load)
      window.removeEventListener(TECHNICAL_TASKS_CHANGED_EVENT, load)
    }
  }, [])

  if (!tasks.length) return null

  return (
    <div
      className="fixed bottom-20 right-4 z-40 flex w-[min(320px,calc(100vw-2rem))] flex-col gap-2 md:bottom-6 md:right-6"
      aria-label="技术标后台任务"
    >
      {tasks.slice(0, 3).map((task) => {
        const active = technicalTaskIsActive(task)
        const failed = task.status === 'failed' || task.status === 'stale'
        return (
          <button
            key={task.key}
            type="button"
            onClick={() => navigate(technicalTaskRoute(task))}
            className="grid min-h-[76px] w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-x-3 rounded-md border border-outline-variant/70 bg-white px-3 py-2.5 text-left shadow-[0_10px_24px_rgba(13,33,55,0.14)] transition-colors hover:border-primary/45 hover:bg-primary/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span
              aria-hidden="true"
              className={`material-symbols-outlined row-span-3 text-[22px] ${failed ? 'text-error' : active ? 'animate-spin text-primary' : 'text-success'}`}
            >
              {failed ? 'error' : active ? 'progress_activity' : 'check_circle'}
            </span>
            <span className="truncate text-sm font-semibold text-on-surface">{task.taskName}</span>
            <span className="row-span-3 text-sm font-bold tabular-nums text-primary">{clampPercentage(task.percentage)}%</span>
            <span className="truncate text-xs text-on-surface-variant">{task.projectName}</span>
            <span className="truncate text-xs text-outline">{active ? '后台运行中' : failed ? '任务未完成' : '任务已完成'}</span>
          </button>
        )
      })}
    </div>
  )
}
