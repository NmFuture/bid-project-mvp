export const WIKI_JOB_POLL_INTERVAL_MS = 8000
export const WIKI_JOB_POLL_FAILURE_THRESHOLD = 3

// 串行轮询 Wiki job：上一请求完成后才安排下一次，避免慢请求重叠和乱序覆盖。
// 连续查询失败达到阈值时交还页面处理，让本地进行中状态可以显式退出。
export const startWikiJobStatusPolling = ({
  fetchStatus,
  onStatus,
  onNotFound = () => {},
  onUnavailable = () => {},
  intervalMs = WIKI_JOB_POLL_INTERVAL_MS,
  failureThreshold = WIKI_JOB_POLL_FAILURE_THRESHOLD,
  setTimer = (callback, delay) => window.setTimeout(callback, delay),
  clearTimer = (timerId) => window.clearTimeout(timerId),
}) => {
  let cancelled = false
  let timer = null
  let controller = null
  let consecutiveFailures = 0

  const scheduleNext = () => {
    if (!cancelled) timer = setTimer(poll, intervalMs)
  }

  const poll = async () => {
    if (cancelled) return
    const requestController = new AbortController()
    controller = requestController
    const context = {
      signal: requestController.signal,
      isCancelled: () => cancelled || requestController.signal.aborted,
    }
    let status
    try {
      status = await fetchStatus(requestController.signal)
    } catch (error) {
      if (cancelled) return
      if (error?.status === 404) {
        try {
          await onNotFound(error, context)
        } finally {
          if (controller === requestController) controller = null
        }
        return
      }
      consecutiveFailures += 1
      if (controller === requestController) controller = null
      if (consecutiveFailures >= Math.max(1, failureThreshold)) {
        onUnavailable(error)
        return
      }
      scheduleNext()
      return
    }

    if (cancelled) return
    consecutiveFailures = 0
    let shouldContinue
    try {
      shouldContinue = await onStatus(status, context)
    } finally {
      if (controller === requestController) controller = null
    }
    if (!cancelled && shouldContinue !== false) scheduleNext()
  }

  poll()
  return () => {
    cancelled = true
    controller?.abort()
    controller = null
    if (timer !== null) clearTimer(timer)
  }
}
