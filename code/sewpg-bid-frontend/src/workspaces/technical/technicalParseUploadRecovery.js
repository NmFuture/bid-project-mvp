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
const internalAiParseTextPattern = /opencode|S1|Skill|manifest|输出片段|AI/i

const finiteNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

const parseTime = (value) => {
  const parsed = Date.parse(String(value || ''))
  return Number.isFinite(parsed) ? parsed : null
}

export const formatParseDuration = (value) => {
  const seconds = Math.max(0, Math.floor(Number(value || 0)))
  if (seconds <= 0) return ''
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes > 0) return `${minutes} 分 ${remainingSeconds} 秒`
  return `${seconds} 秒`
}

const parseStartMs = (progress = {}) => {
  const startedAt = parseTime(progress?.startedAt)
  if (startedAt !== null) return startedAt
  const eventTimes = (Array.isArray(progress?.events) ? progress.events : [])
    .map((event) => parseTime(event?.at))
    .filter((value) => value !== null)
  return eventTimes.length ? Math.min(...eventTimes) : null
}

const parseTerminalMs = (progress = {}) => {
  const completedAt = parseTime(progress?.completedAt || progress?.cancelledAt)
  if (completedAt !== null) return completedAt
  const eventTimes = (Array.isArray(progress?.events) ? progress.events : [])
    .map((event) => parseTime(event?.at))
    .filter((value) => value !== null)
  return eventTimes.length ? Math.max(...eventTimes) : null
}

export const parseElapsedSeconds = (progress = {}, nowMs = Date.now()) => {
  const startMs = parseStartMs(progress)
  if (startMs === null) return 0
  const status = normalizeStatus(progress)
  const endMs = status === 'completed' || failedStatuses.has(status)
    ? (parseTerminalMs(progress) ?? finiteNumber(nowMs))
    : finiteNumber(nowMs)
  return Math.max(0, (endMs - startMs) / 1000)
}

const isAiParsePhase = (progress = {}) => {
  const phaseKey = String(progress?.phaseKey || '').toLowerCase()
  const phaseLabel = String(progress?.phaseLabel || '')
  return phaseKey === 'opencode' || internalAiParseTextPattern.test(phaseLabel)
}

// 已解析条款数由后端按提交文件真实统计（清单行 + 项目基础信息字段），
// 没拿到计数时宁可回退成非量化文案，也不用会话数或百分比反推。
const buildAiParseSummary = (progress = {}, summary = '') => {
  const output = progress?.opencodeOutput || {}
  const total = Math.max(0, Math.floor(finiteNumber(output?.totalItems)))
  if (total > 0) {
    const completed = Math.max(0, Math.min(total, Math.floor(finiteNumber(output?.completedItems))))
    return `已解析条款 ${completed}/${total} 项`
  }
  if (summary && !internalAiParseTextPattern.test(summary)) return summary
  return '正在识别招标文件中的技术要求和原文依据，请稍候。'
}

const isAppendixPhase = (progress = {}) => String(progress?.phaseKey || '').toLowerCase() === 'appendix'

const buildAppendixSummary = (progress = {}, summary = '') => {
  const total = Math.max(0, Math.floor(finiteNumber(progress?.total)))
  if (total > 0) {
    const current = Math.max(0, Math.min(total, Math.floor(finiteNumber(progress?.current))))
    return `已提取附表 ${current}/${total} 项`
  }
  return summary
}

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
  // 并发轮询响应可能乱序返回，量化计数一旦倒退（27/64 掉回 15/64）用户会以为解析出错。
  if (samePhase) {
    const previousOutput = previous?.opencodeOutput || {}
    const incomingOutput = incoming?.opencodeOutput || {}
    const previousTotal = Math.max(0, Math.floor(finiteNumber(previousOutput?.totalItems)))
    const incomingTotal = Math.max(0, Math.floor(finiteNumber(incomingOutput?.totalItems)))
    if (previousTotal > 0 && (incomingTotal === 0 || incomingTotal === previousTotal)) {
      merged.opencodeOutput = {
        ...incomingOutput,
        completedItems: Math.max(
          Math.floor(finiteNumber(previousOutput?.completedItems)),
          Math.floor(finiteNumber(incomingOutput?.completedItems)),
        ),
        totalItems: previousTotal,
      }
    }
  }
  if (samePhase) {
    const previousTotal = Math.max(0, Math.floor(finiteNumber(previous?.total)))
    const incomingTotal = Math.max(0, Math.floor(finiteNumber(incoming?.total)))
    if (previousTotal > 0 && incomingTotal === previousTotal) {
      merged.current = Math.max(
        Math.floor(finiteNumber(previous?.current)),
        Math.floor(finiteNumber(incoming?.current)),
      )
    }
  }
  return merged
}

const statusTextByStatus = {
  completed: '解析完成',
  failed: '解析失败',
  error: '解析失败',
  stale: '可能中断',
  cancelled: '已停止',
  running: '解析中',
  processing: '解析中',
  queued: '等待解析',
  idle: '等待上传',
}

export const summarizeParseProgress = (progress = {}) => {
  const status = normalizeStatus(progress) || 'idle'
  const percentage = clampPercentage(progress?.percentage)
  const phaseLabel = String(progress?.phaseLabel || '').trim()
  const summary = String(progress?.summary || '').trim()
  const aiParsePhase = status !== 'completed' && isAiParsePhase(progress)
  const tone = status === 'stale' ? 'warning' : failedStatuses.has(status) ? 'danger' : status === 'completed' ? 'success' : 'running'

  if (aiParsePhase) {
    return {
      status,
      statusText: statusTextByStatus[status] || '解析中',
      title: '结构化解析中',
      detail: '',
      summary: buildAiParseSummary(progress, summary),
      percentage,
      tone,
    }
  }

  return {
    status,
    statusText: statusTextByStatus[status] || '解析中',
    title: phaseLabel || summary || '解析进度',
    detail: '',
    summary: status !== 'completed' && isAppendixPhase(progress)
      ? buildAppendixSummary(progress, summary)
      : summary,
    percentage,
    tone,
  }
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
