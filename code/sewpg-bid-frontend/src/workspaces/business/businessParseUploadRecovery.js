const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const completedStatuses = new Set(['completed'])
const failedStatuses = new Set(['failed', 'error'])

const normalizeStatus = (progress) => String(progress?.status || '').toLowerCase()

export const isUploadAndRunTimeout = (error) => error?.code === 'TIMEOUT'

export const isParseProgressCompleted = (progress) =>
  completedStatuses.has(normalizeStatus(progress)) || Number(progress?.percentage || 0) >= 100

export const isParseProgressFailed = (progress) => failedStatuses.has(normalizeStatus(progress))

export const shouldPollParseProgress = ({ uploading = false, progress = null } = {}) => {
  if (uploading) return true
  const status = normalizeStatus(progress)
  return status === 'running' || status === 'processing' || status === 'queued'
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
  let lastError = null
  let firstPoll = true

  while (firstPoll || Date.now() - startedAt < maxPollMs) {
    firstPoll = false
    try {
      lastProgress = await parseClient.progress(projectId)
      onProgress?.(lastProgress)
    } catch (error) {
      lastError = error
    }

    if (isParseProgressCompleted(lastProgress)) {
      const result = parseClient.results ? await parseClient.results(projectId) : null
      return { completed: true, failed: false, progress: lastProgress, result }
    }

    if (isParseProgressFailed(lastProgress)) {
      return { completed: false, failed: true, progress: lastProgress }
    }

    const elapsedMs = Date.now() - startedAt
    if (elapsedMs >= maxPollMs) break
    await sleep(Math.min(Math.max(1, pollIntervalMs), maxPollMs - elapsedMs))
  }

  return { completed: false, failed: false, progress: lastProgress, error: lastError }
}
