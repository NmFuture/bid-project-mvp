const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const completedStatuses = new Set(['completed'])
const failedStatuses = new Set(['failed', 'error'])

const normalizeStatus = (progress) => String(progress?.status || '').toLowerCase()

export const isUploadAndRunTimeout = (error) => error?.code === 'TIMEOUT'

export const isParseProgressCompleted = (progress) =>
  completedStatuses.has(normalizeStatus(progress)) || Number(progress?.percentage || 0) >= 100

export const isParseProgressFailed = (progress) => failedStatuses.has(normalizeStatus(progress))

export const isParseResultCompleted = (result) => completedStatuses.has(normalizeStatus(result))

export const shouldPollParseProgress = ({ uploading = false, progress = null, result = null } = {}) => {
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

  if (isParseProgressCompleted(progress)) {
    try {
      result = parseClient.results ? await parseClient.results(projectId) : null
    } catch (caught) {
      error = caught
      result = null
    }
  }

  onProgress?.(progress)

  if (isParseResultCompleted(result)) {
    return { completed: true, failed: false, progress, result }
  }
  if (isParseProgressFailed(progress)) {
    return { completed: false, failed: true, progress, result }
  }
  return { completed: false, failed: false, progress, result, error }
}

export const recoverUploadAndRunTimeout = async ({
  projectId,
  parseClient,
  pollIntervalMs = 1000,
  maxPollMs = 2 * 60 * 1000,
  onProgress,
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
    firstPoll = false
    try {
      const snapshot = await pollParseProgressOnce({ projectId, parseClient, onProgress })
      lastProgress = snapshot.progress
      lastResult = snapshot.result
      lastError = snapshot.error || lastError
      if (snapshot.completed) return snapshot
      if (snapshot.failed) return snapshot
    } catch (error) {
      lastError = error
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
