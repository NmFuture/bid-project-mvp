import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { readRunningParses } from '../../shared/parseRunningMarker'
import {
  clearTechnicalTask,
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

const clampPercentage = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.round(number))) : 0
}

export default function TechnicalBackgroundTaskStack() {
  const navigate = useNavigate()
  const [tasks, setTasks] = useState(() => readTechnicalTasks())

  useEffect(() => {
    let disposed = false

    const load = () => {
      if (!disposed) setTasks(readTechnicalTasks())
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
        let progress = null
        try {
          progress = await definition.status(task.projectId)
        } catch (error) {
          // 后端查无此任务说明登记已经失效，直接清掉；其余失败只当网络波动，保留上一次进度等下一轮。
          if (error?.status === 404) clearTechnicalTask(task.taskType, task.projectId)
          return
        }
        const status = String(progress?.status || task.status || '').toLowerCase()
        updateTechnicalTask(task.taskType, task.projectId, {
          taskName: task.taskName || definition.taskName,
          status,
          percentage: status === 'completed' ? 100 : clampPercentage(progress?.percentage ?? task.percentage),
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

  // 终态只是通知：用户点开查看或主动关掉就该消失，不留在角落误导成「还在跑」。
  const consumeTerminalTask = (task) => {
    if (technicalTaskIsActive(task)) return
    clearTechnicalTask(task.taskType, task.projectId)
    setTasks(readTechnicalTasks())
  }

  const visibleTasks = tasks.slice(0, 3)
  const overflowCount = tasks.length - visibleTasks.length

  return (
    <div
      className="fixed bottom-20 right-4 z-40 flex w-[min(320px,calc(100vw-2rem))] flex-col gap-2 md:bottom-6 md:right-6"
      aria-label="技术标后台任务"
    >
      {visibleTasks.map((task) => {
        const active = technicalTaskIsActive(task)
        const failed = task.status === 'failed' || task.status === 'stale'
        const cancelled = task.status === 'cancelled'
        return (
          <div
            key={task.key}
            className="flex items-stretch rounded-md border border-outline-variant/70 bg-white shadow-[0_10px_24px_rgba(13,33,55,0.14)] transition-colors hover:border-primary/45"
          >
            <button
              type="button"
              onClick={() => {
                consumeTerminalTask(task)
                navigate(technicalTaskRoute(task))
              }}
              className="grid min-h-[76px] flex-1 grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-x-3 rounded-l-md px-3 py-2.5 text-left transition-colors hover:bg-primary/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span
                aria-hidden="true"
                className={`material-symbols-outlined row-span-3 text-[22px] ${failed ? 'text-error' : active ? 'animate-spin text-primary' : cancelled ? 'text-outline' : 'text-success'}`}
              >
                {failed ? 'error' : active ? 'progress_activity' : cancelled ? 'stop_circle' : 'check_circle'}
              </span>
              <span className="truncate text-sm font-semibold text-on-surface">{task.taskName}</span>
              <span className={`row-span-3 text-sm font-bold tabular-nums ${cancelled ? 'text-outline' : 'text-primary'}`}>{clampPercentage(task.percentage)}%</span>
              <span className="truncate text-xs text-on-surface-variant">{task.projectName}</span>
              <span className="truncate text-xs text-outline">{active ? '后台运行中' : failed ? '任务未完成' : cancelled ? '任务已停止' : '任务已完成'}</span>
            </button>
            {active ? null : (
              <button
                type="button"
                aria-label={`关闭${task.taskName}通知`}
                title="关闭通知"
                onClick={() => consumeTerminalTask(task)}
                className="flex w-9 shrink-0 items-center justify-center rounded-r-md text-outline transition-colors hover:bg-primary/[0.06] hover:text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">close</span>
              </button>
            )}
          </div>
        )
      })}
      {overflowCount > 0 ? (
        <p className="rounded-md border border-outline-variant/70 bg-white px-3 py-1.5 text-center text-xs text-on-surface-variant shadow-[0_10px_24px_rgba(13,33,55,0.14)]">
          另有 {overflowCount} 个任务
        </p>
      ) : null}
    </div>
  )
}
