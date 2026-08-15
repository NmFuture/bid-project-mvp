const terminalStatuses = new Set(['completed', 'failed', 'error', 'cancelled'])

const isTerminalStatus = (payload) =>
  terminalStatuses.has(String(payload?.status || '').toLowerCase())

export const subscribeTechnicalGenerationStatus = ({
  fetchStatus,
  onStatus,
  onError,
  pollIntervalMs = 1200,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
}) => {
  let stopped = false
  let timer = null

  const stop = () => {
    stopped = true
    if (timer !== null) {
      clearTimer(timer)
      timer = null
    }
  }

  const poll = async () => {
    timer = null
    try {
      const payload = await fetchStatus()
      if (stopped) return
      onStatus(payload)
      if (isTerminalStatus(payload)) {
        stop()
        return
      }
    } catch (error) {
      if (stopped) return
      onError?.(error)
    }
    if (!stopped) timer = setTimer(poll, pollIntervalMs)
  }

  timer = setTimer(poll, pollIntervalMs)
  return stop
}
