const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const completedStatuses = new Set(['completed'])
const failedStatuses = new Set(['failed', 'error', 'stale', 'cancelled'])

const normalizeStatus = (progress) => String(progress?.status || '').toLowerCase()

export const isUploadAndRunTimeout = (error) => error?.code === 'TIMEOUT'

// 后端失败/停止时也会写 percentage=100，须先排除失败态再判断完成，
// 否则重解析失败会被误判为成功并展示旧的 parse_result。
export const isParseProgressCompleted = (progress) =>
  !failedStatuses.has(normalizeStatus(progress)) &&
  (completedStatuses.has(normalizeStatus(progress)) || Number(progress?.percentage || 0) >= 100)

export const isParseProgressFailed = (progress) => failedStatuses.has(normalizeStatus(progress))

export const isParseResultCompleted = (result) => completedStatuses.has(normalizeStatus(result))

const clampPercentage = (value) => Math.max(0, Math.min(100, Number(value || 0)))
const runningStatuses = new Set(['running', 'processing', 'queued'])

export const mergeMonotonicParseProgress = (previous = null, incoming = null) => {
  if (!incoming) return incoming
  if (!previous) return incoming
  const previousStatus = normalizeStatus(previous)
  const incomingStatus = normalizeStatus(incoming)
  if (!runningStatuses.has(previousStatus) || !runningStatuses.has(incomingStatus)) {
    return incoming
  }
  const previousPercentage = clampPercentage(previous?.percentage)
  const incomingPercentage = clampPercentage(incoming?.percentage)
  const merged = { ...incoming }
  if (incomingPercentage < previousPercentage) {
    merged.percentage = previousPercentage
  }

  const previousPhaseKey = String(previous?.phaseKey || '')
  const incomingPhaseKey = String(incoming?.phaseKey || '')
  const samePhase = previousPhaseKey && incomingPhaseKey
    ? previousPhaseKey === incomingPhaseKey
    : String(previous?.phaseLabel || '') === String(incoming?.phaseLabel || '')
  if (samePhase && previous?.phasePercent !== undefined && incoming?.phasePercent !== undefined) {
    const previousPhasePercent = clampPercentage(previous.phasePercent)
    const incomingPhasePercent = clampPercentage(incoming.phasePercent)
    if (incomingPhasePercent < previousPhasePercent) {
      merged.phasePercent = previousPhasePercent
    }
  }
  return merged
}

export const shouldPollParseProgress = ({ uploading = false, stopped = false, progress = null, result = null } = {}) => {
  if (stopped) return false
  if (uploading) return true
  if (isParseResultCompleted(result)) return false
  const status = normalizeStatus(progress)
  return status === 'running' || status === 'processing' || status === 'queued' || isParseProgressCompleted(progress)
}

export const pollParseProgressOnce = async ({
  projectId,
  parseClient,
  onProgress,
} = {}) => {
  if (!projectId || !parseClient?.progress) {
    return { completed: false, failed: false, progress: null, result: null }
  }

  const progress = await parseClient.progress(projectId)
  let result = null
  let error = null

  // 失败态不拉取结果：重解析失败时后端不清旧 parse_result，拉到的旧成功结果会被误判为成功。
  if (!isParseProgressFailed(progress) && isParseProgressCompleted(progress)) {
    try {
      result = parseClient.results ? await parseClient.results(projectId) : null
    } catch (caught) {
      error = caught
      result = null
    }
  }

  onProgress?.(progress)

  // 失败检查优先于完成检查，failed/error/stale/cancelled 直接按失败处理。
  if (isParseProgressFailed(progress)) {
    return { completed: false, failed: true, progress, result }
  }
  if (isParseResultCompleted(result)) {
    return { completed: true, failed: false, progress, result }
  }
  return { completed: false, failed: false, progress, result, error }
}

export const recoverUploadAndRunTimeout = async ({
  projectId,
  parseClient,
  pollIntervalMs = 1000,
  maxPollMs = 2 * 60 * 1000,
  onProgress,
  signal,
} = {}) => {
  if (!projectId || !parseClient?.progress) {
    return { completed: false, progress: null }
  }

  const startedAt = Date.now()
  let lastProgress = null
  let lastResult = null
  let lastError = null
  let firstPoll = true

  while (firstPoll || Date.now() - startedAt < maxPollMs) {
    if (signal?.aborted) {
      return { completed: false, failed: false, stopped: true, progress: lastProgress, result: lastResult, error: lastError }
    }
    firstPoll = false
    try {
      const snapshot = await pollParseProgressOnce({ projectId, parseClient, onProgress })
      lastProgress = snapshot.progress
      lastResult = snapshot.result
      lastError = snapshot.error || lastError
      if (signal?.aborted) {
        return { completed: false, failed: false, stopped: true, progress: lastProgress, result: lastResult, error: lastError }
      }
      if (snapshot.completed) return snapshot
      if (snapshot.failed) return snapshot
    } catch (error) {
      lastError = error
      if (signal?.aborted) {
        return { completed: false, failed: false, stopped: true, progress: lastProgress, result: lastResult, error: lastError }
      }
    }

    if (isParseProgressFailed(lastProgress)) {
      return { completed: false, failed: true, progress: lastProgress }
    }

    const elapsedMs = Date.now() - startedAt
    if (elapsedMs >= maxPollMs) break
    await sleep(Math.min(Math.max(1, pollIntervalMs), maxPollMs - elapsedMs))
  }

  return { completed: false, failed: false, progress: lastProgress, result: lastResult, error: lastError }
}
