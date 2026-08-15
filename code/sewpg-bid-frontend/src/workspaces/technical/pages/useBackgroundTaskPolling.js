import { useCallback, useEffect, useRef } from 'react'
import { runBackgroundTaskTick } from './technicalGapTaskPolling'

// 后台任务轮询 hook（从 TechnicalGapRecognition.jsx 的 factCurate/bodyFill 两个轮询 effect 抽出）。
// running 期间按固定间隔取状态：每拍回写 state；到终态时按 jobId+finishedAt 去重，
// 同一任务只触发一次 onTerminal。历史语义保留：
// - 轮询失败静默吞掉，下个周期继续取（任务在后台 worker，前端报错不影响执行）；
// - 去重 ref 在 onTerminal 之前置位，收尾异步失败也不会重复通知；
// - 重新提交任务时用 resetNotified() 清空去重标记（原 bodyFillNotifiedRef.current = ''）。
export const useBackgroundTaskPolling = ({
  running,
  fetchStatus,
  extractState,
  terminalStatuses,
  onState,
  onTerminal,
  pollIntervalMs = 2000,
}) => {
  const notifiedRef = useRef('')

  useEffect(() => {
    if (!running) return undefined
    const timer = window.setInterval(async () => {
      try {
        const { payload, state, notifyKey } = await runBackgroundTaskTick({
          fetchStatus,
          extractState,
          terminalStatuses,
          onState,
          lastNotifiedKey: notifiedRef.current,
        })
        if (!notifyKey) return
        notifiedRef.current = notifyKey
        await onTerminal(payload, state)
      } catch {
        // 轮询失败不打断任务，下个周期继续取
      }
    }, pollIntervalMs)
    return () => window.clearInterval(timer)
  }, [running, fetchStatus, extractState, terminalStatuses, onState, onTerminal, pollIntervalMs])

  const resetNotified = useCallback(() => {
    notifiedRef.current = ''
  }, [])

  return { resetNotified }
}
