const runningStatuses = new Set(['running', 'processing', 'queued'])
const failedStatuses = new Set(['failed', 'error'])
const internalDirectoryTextPattern = /futurecode|opencode|S2|Skill|session|流式片段|provider|model/i
const EXPECTED_DIRECTORY_DURATION_SECONDS = 15 * 60

const directorySteps = [
  { id: 'task-1', label: '准备生成资料' },
  { id: 'task-2', label: '智能生成目录' },
  { id: 'task-3', label: '保存目录结果' },
]

const normalizeStatus = (value) => String(value || '').toLowerCase()
const finiteNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}
const clampPercentage = (value) => Math.max(0, Math.min(100, finiteNumber(value)))

export const isDirectoryProgressRunning = (progress) => runningStatuses.has(normalizeStatus(progress?.status))
export const isDirectoryProgressFailed = (progress) => failedStatuses.has(normalizeStatus(progress?.status))

export const buildDirectoryRegenerationPrompt = ({ dirty = false, hasDownstreamResults = false } = {}) => {
  const warnings = ['重新生成将覆盖当前目录审核稿。']
  if (dirty) warnings.push('重新生成将丢弃未保存修改。')
  if (hasDownstreamResults) warnings.push('已有素材匹配和正文结果将失效，需重新确认目录并生成。')
  return `${warnings.join('\n')}\n确认继续吗？`
}

export const shouldShowTemplateDirectoryGenerationButton = (progress = {}) =>
  normalizeStatus(progress?.status) !== 'completed'

export const beginDirectoryProgressEpoch = ({ incoming = null } = {}) => incoming

export const loadConsistentOutlineReviewSnapshot = async ({
  loadDirectoryState,
  loadOutline,
  loadProject,
}) => {
  const generationPayload = await loadDirectoryState()
  let [outlinePayload, projectPayload] = await Promise.all([loadOutline(), loadProject()])
  const generationCompletedAt = String(generationPayload?.generatedAt || '').trim()
  const outlineGeneratedAt = String(outlinePayload?.generatedAt || '').trim()

  if (
    normalizeStatus(generationPayload?.status) === 'completed'
    && generationCompletedAt
    && generationCompletedAt !== outlineGeneratedAt
  ) {
    outlinePayload = await loadOutline()
  }

  return { outlinePayload, generationPayload, projectPayload }
}

export const directoryElapsedSeconds = (progress = {}, nowMs = Date.now()) => {
  const events = Array.isArray(progress?.events) ? progress.events : []
  const eventTimes = events
    .map((event) => Date.parse(String(event?.at || '')))
    .filter((value) => Number.isFinite(value))
  const startedAt = eventTimes.length ? Math.min(...eventTimes) : null
  const terminalEventTimes = events
    .filter((event) => {
      const step = normalizeStatus(event?.step)
      return step === 'failed' || step === 'error' || normalizeStatus(event?.level) === 'error'
    })
    .map((event) => Date.parse(String(event?.at || '')))
    .filter((value) => Number.isFinite(value))
  const failedAt = terminalEventTimes.length
    ? Math.max(...terminalEventTimes)
    : eventTimes.length
      ? Math.max(...eventTimes)
      : finiteNumber(nowMs)
  const effectiveNow = isDirectoryProgressFailed(progress) ? failedAt : finiteNumber(nowMs)
  const eventElapsed = startedAt === null ? 0 : Math.max(0, (effectiveNow - startedAt) / 1000)
  const output = progress?.opencodeOutput || {}
  const serverElapsed = Math.max(finiteNumber(output?.elapsedSeconds), finiteNumber(output?.idleSeconds))
  return Math.max(eventElapsed, serverElapsed)
}

export const estimateDirectoryDisplayPercentage = ({
  status = 'idle',
  elapsedSeconds = 0,
  fallbackPercentage = 0,
} = {}) => {
  const normalizedStatus = normalizeStatus(status)
  if (normalizedStatus === 'completed') return 100
  if (failedStatuses.has(normalizedStatus)) return clampPercentage(fallbackPercentage)
  if (!runningStatuses.has(normalizedStatus)) return clampPercentage(fallbackPercentage)

  const elapsed = Math.max(0, finiteNumber(elapsedSeconds))
  if (elapsed <= EXPECTED_DIRECTORY_DURATION_SECONDS) {
    return 5 + 90 * (elapsed / EXPECTED_DIRECTORY_DURATION_SECONDS)
  }

  const overtime = elapsed - EXPECTED_DIRECTORY_DURATION_SECONDS
  return 95 + 4 * (1 - Math.exp(-overtime / (10 * 60)))
}

const formatElapsedDuration = (value) => {
  const seconds = Math.max(0, Math.floor(finiteNumber(value)))
  if (seconds <= 0) return ''
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes > 0) return `${minutes} 分 ${remainingSeconds} 秒`
  return `${seconds} 秒`
}

const derivedStepStatuses = (status, percentage) => {
  if (status === 'completed') return ['done', 'done', 'done']
  if (failedStatuses.has(status)) {
    if (percentage < 30) return ['failed', 'pending', 'pending']
    if (percentage < 85) return ['done', 'failed', 'pending']
    return ['done', 'done', 'failed']
  }
  if (!runningStatuses.has(status)) return ['pending', 'pending', 'pending']
  if (percentage < 30) return ['running', 'pending', 'pending']
  if (percentage < 85) return ['done', 'running', 'pending']
  return ['done', 'done', 'running']
}

const normalizeTaskStatus = (value, fallback) => {
  const status = normalizeStatus(value)
  if (status === 'complete' || status === 'completed') return 'done'
  if (status === 'failed' || status === 'error') return 'failed'
  if (status === 'running' || status === 'processing') return 'running'
  if (status === 'done' || status === 'pending') return status
  return fallback
}

const buildSteps = (progress, status, percentage) => {
  const suppliedTasks = Array.isArray(progress?.tasks) ? progress.tasks : []
  const suppliedById = new Map(suppliedTasks.map((task) => [String(task?.id || ''), task]))
  const suppliedActiveIndex = directorySteps.findIndex((step) => {
    const suppliedStatus = normalizeStatus(suppliedById.get(step.id)?.status)
    return suppliedStatus === 'running' || suppliedStatus === 'processing' || suppliedStatus === 'failed' || suppliedStatus === 'error'
  })
  const fallbackStatuses = suppliedActiveIndex >= 0
    ? directorySteps.map((_, index) => index < suppliedActiveIndex ? 'done' : index === suppliedActiveIndex ? 'running' : 'pending')
    : derivedStepStatuses(status, percentage)
  return directorySteps.map((step, index) => ({
    ...step,
    status: normalizeTaskStatus(suppliedById.get(step.id)?.status, fallbackStatuses[index]),
  }))
}

const directoryStepRank = (progress) => {
  const status = normalizeStatus(progress?.status) || 'idle'
  const steps = buildSteps(progress, status, clampPercentage(progress?.percentage))
  const activeIndex = steps.findIndex((step) => step.status === 'running' || step.status === 'failed')
  if (activeIndex >= 0) return activeIndex
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (steps[index].status === 'done') return index
  }
  return 0
}

const activeStepId = (steps, percentage) => {
  const active = steps.find((step) => step.status === 'running' || step.status === 'failed')
  if (active) return active.id
  if (percentage < 30) return 'task-1'
  if (percentage < 85) return 'task-2'
  return 'task-3'
}

const visibleFailureSummary = (summary) => {
  const value = String(summary || '').trim()
  if (/模板|招标文件|投标文件|输入文件|文件不存在|未找到.*文件/i.test(value)) {
    return '未能读取招标文件或投标模板，请检查文件后重试。'
  }
  if (/超时|timeout|网络|连接|服务不可用|暂不可用|网关/i.test(value)) {
    return '目录生成服务暂时不可用，请稍后重试。'
  }
  if (/结果|格式|JSON|输出|解析响应/i.test(value)) {
    return '目录结果处理失败，请重新生成；如仍失败请联系管理员。'
  }
  if (value && !internalDirectoryTextPattern.test(value)) return value
  return '目录生成未完成，请稍后重试；如仍失败请联系管理员。'
}

const visibleCompletedSummary = (summary) => {
  const value = String(summary || '').trim()
  if (value && !internalDirectoryTextPattern.test(value)) return value
  return '目录生成完成，可进入目录确认。'
}

export const mergeMonotonicDirectoryProgress = (previous = null, incoming = null) => {
  if (!incoming) return incoming
  if (!previous) return incoming
  const previousStatus = normalizeStatus(previous?.status)
  const incomingStatus = normalizeStatus(incoming?.status)
  if (previousStatus === 'completed' && incomingStatus !== 'completed') return previous
  if (failedStatuses.has(previousStatus) && !failedStatuses.has(incomingStatus) && incomingStatus !== 'completed') {
    return previous
  }
  if (!runningStatuses.has(previousStatus) || !runningStatuses.has(incomingStatus)) return incoming

  const merged = { ...incoming }
  const previousPercentage = clampPercentage(previous?.percentage)
  const incomingPercentage = clampPercentage(incoming?.percentage)
  if (incomingPercentage < previousPercentage) merged.percentage = previousPercentage

  const phaseRegressed = directoryStepRank(incoming) < directoryStepRank(previous)
  if (phaseRegressed) merged.tasks = previous?.tasks

  const previousOutput = previous?.opencodeOutput || {}
  const incomingOutput = incoming?.opencodeOutput || {}
  const previousElapsed = Math.max(finiteNumber(previousOutput?.elapsedSeconds), finiteNumber(previousOutput?.idleSeconds))
  const incomingElapsed = Math.max(finiteNumber(incomingOutput?.elapsedSeconds), finiteNumber(incomingOutput?.idleSeconds))
  if (phaseRegressed || incomingElapsed < previousElapsed) {
    merged.opencodeOutput = previousOutput
  } else if (Object.keys(previousOutput).length || Object.keys(incomingOutput).length) {
    merged.opencodeOutput = {
      ...previousOutput,
      ...incomingOutput,
      elapsedSeconds: Math.max(finiteNumber(previousOutput?.elapsedSeconds), finiteNumber(incomingOutput?.elapsedSeconds)),
      idleSeconds: Math.max(finiteNumber(previousOutput?.idleSeconds), finiteNumber(incomingOutput?.idleSeconds)),
    }
  }
  return merged
}

export const summarizeDirectoryProgress = (progress = {}) => {
  const status = normalizeStatus(progress?.status) || 'idle'
  const percentage = clampPercentage(progress?.percentage)
  const steps = buildSteps(progress, status, percentage)

  if (status === 'completed') {
    return {
      status,
      statusText: '已完成',
      title: '目录生成完成',
      summary: visibleCompletedSummary(progress?.summary),
      percentage,
      tone: 'success',
      steps,
    }
  }

  if (failedStatuses.has(status)) {
    return {
      status,
      statusText: '生成失败',
      title: '目录生成失败',
      summary: visibleFailureSummary(progress?.summary),
      percentage,
      tone: 'danger',
      steps,
    }
  }

  if (runningStatuses.has(status)) {
    const stepId = activeStepId(steps, percentage)
    if (stepId === 'task-1') {
      return {
        status,
        statusText: status === 'queued' ? '等待生成' : '生成中',
        title: '准备生成资料',
        summary: '正在整理招标文件与投标模板，为目录生成做准备。',
        percentage,
        tone: 'running',
        steps,
      }
    }
    if (stepId === 'task-3') {
      return {
        status,
        statusText: '生成中',
        title: '保存目录结果',
        summary: '目录结构已经生成，正在整理并保存结果。',
        percentage,
        tone: 'running',
        steps,
      }
    }

    const output = progress?.opencodeOutput || {}
    const elapsedText = formatElapsedDuration(Math.max(
      finiteNumber(output?.elapsedSeconds),
      finiteNumber(output?.idleSeconds),
    ))
    return {
      status,
      statusText: '生成中',
      title: '智能生成目录',
      summary: elapsedText
        ? `正在分析招标要求并组织目录结构，已执行 ${elapsedText}。`
        : '正在分析招标要求并组织目录结构，请稍候。',
      percentage,
      tone: 'running',
      steps,
    }
  }

  return {
    status,
    statusText: '待生成',
    title: '等待生成目录',
    summary: '准备完成后可开始生成目录。',
    percentage,
    tone: 'neutral',
    steps,
  }
}
