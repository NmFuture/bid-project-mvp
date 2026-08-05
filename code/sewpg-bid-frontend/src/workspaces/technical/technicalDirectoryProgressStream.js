const terminalStatuses = new Set(['completed', 'failed', 'error'])

// SSE 断开后等待浏览器自动重连的宽限期；超时仍未恢复才降级为轮询
const STREAM_RECOVERY_GRACE_MS = 5000
const FALLBACK_POLL_INTERVAL_MS = 1000
const EVENT_SOURCE_CLOSED = 2

export const isTerminalDirectoryStatus = (payload) =>
  terminalStatuses.has(String(payload?.status || '').toLowerCase())

/**
 * 订阅目录生成进度：优先用 SSE 推送，流不可用时降级为轮询。
 *
 * 终态必须由本函数主动关流——服务端发完 completed/failed 就结束响应，
 * 若不关闭 EventSource，浏览器会把正常结束当作断线并无限重连。
 *
 * 返回取消订阅函数，重复调用安全。
 */
export const subscribeDirectoryProgress = ({
  openStream,
  fetchStatus,
  onState,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  pollIntervalMs = FALLBACK_POLL_INTERVAL_MS,
  recoveryGraceMs = STREAM_RECOVERY_GRACE_MS,
}) => {
  let stopped = false
  let polling = false
  let source = null
  let pollTimer = null
  let recoveryTimer = null

  const clearRecoveryTimer = () => {
    if (recoveryTimer === null) return
    clearTimer(recoveryTimer)
    recoveryTimer = null
  }

  const closeStream = () => {
    if (!source) return
    try {
      source.close()
    } catch {
      // 关闭失败不影响后续降级或清理
    }
    source = null
  }

  const stop = () => {
    stopped = true
    clearRecoveryTimer()
    closeStream()
    if (pollTimer !== null) {
      clearTimer(pollTimer)
      pollTimer = null
    }
  }

  const deliver = (payload) => {
    if (stopped) return
    clearRecoveryTimer()
    onState(payload)
    if (isTerminalDirectoryStatus(payload)) stop()
  }

  const pollOnce = async () => {
    if (stopped) return
    try {
      deliver(await fetchStatus())
    } catch {
      // 保持页面可操作，下一轮继续尝试
    }
    if (!stopped) pollTimer = setTimer(pollOnce, pollIntervalMs)
  }

  const startPolling = () => {
    if (stopped || polling) return
    polling = true
    clearRecoveryTimer()
    closeStream()
    pollTimer = setTimer(pollOnce, pollIntervalMs)
  }

  const handleStreamError = () => {
    if (stopped || polling || recoveryTimer !== null) return
    if (source?.readyState === EVENT_SOURCE_CLOSED) {
      startPolling()
      return
    }
    recoveryTimer = setTimer(() => {
      recoveryTimer = null
      startPolling()
    }, recoveryGraceMs)
  }

  try {
    source = openStream({ onState: deliver, onError: handleStreamError })
  } catch {
    source = null
  }
  if (!source) startPolling()

  return stop
}
