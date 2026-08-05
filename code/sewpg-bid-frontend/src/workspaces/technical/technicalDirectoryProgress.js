const runningStatuses = new Set(['running', 'processing', 'queued'])
const failedStatuses = new Set(['failed', 'error'])
const internalDirectoryTextPattern = /futurecode|opencode|S2|Skill|session|流式片段|provider|model/i

// 批次间平滑：真实锚点之间按时间缓慢爬升，等待下一次真实计数
const CREEP_PERCENT_PER_SECOND = 0.05
const CREEP_MAX_PERCENT = 6
const RUNNING_DISPLAY_CAP = 96

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
const parseTime = (value) => {
  const parsed = Date.parse(String(value || ''))
  return Number.isFinite(parsed) ? parsed : null
}

export const isDirectoryProgressRunning = (progress) => runningStatuses.has(normalizeStatus(progress?.status))
export const isDirectoryProgressFailed = (progress) => failedStatuses.has(normalizeStatus(progress?.status))

const directoryStartMs = (progress = {}) => {
  const startedAt = parseTime(progress?.startedAt)
  if (startedAt !== null) return startedAt
  const eventTimes = (Array.isArray(progress?.events) ? progress.events : [])
    .map((event) => parseTime(event?.at))
    .filter((value) => value !== null)
  return eventTimes.length ? Math.min(...eventTimes) : null
}

const directoryTerminalMs = (progress = {}) => {
  const events = Array.isArray(progress?.events) ? progress.events : []
  if (isDirectoryProgressFailed(progress)) {
    const errorTimes = events
      .filter((event) => {
        const step = normalizeStatus(event?.step)
        return step === 'failed' || step === 'error' || normalizeStatus(event?.level) === 'error'
      })
      .map((event) => parseTime(event?.at))
      .filter((value) => value !== null)
    if (errorTimes.length) return Math.max(...errorTimes)
  }
  const generatedAt = parseTime(progress?.generatedAt)
  if (generatedAt !== null) return generatedAt
  const eventTimes = events.map((event) => parseTime(event?.at)).filter((value) => value !== null)
  return eventTimes.length ? Math.max(...eventTimes) : null
}

// 总运行时长：起点是本次生成启动时间，终态冻结在完成/失败时刻，不区分阶段
export const directoryElapsedSeconds = (progress = {}, nowMs = Date.now()) => {
  const startMs = directoryStartMs(progress)
  if (startMs === null) return 0
  const status = normalizeStatus(progress?.status)
  const endMs = status === 'completed' || failedStatuses.has(status)
    ? (directoryTerminalMs(progress) ?? finiteNumber(nowMs))
    : finiteNumber(nowMs)
  return Math.max(0, (endMs - startMs) / 1000)
}

export const formatDirectoryDuration = (value) => {
  const seconds = Math.max(0, Math.floor(finiteNumber(value)))
  if (seconds <= 0) return ''
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes > 0) return `${minutes} 分 ${remainingSeconds} 秒`
  return `${seconds} 秒`
}

export const normalizeDecisionProgress = (progress = {}) => {
  const raw = progress?.decisionProgress
  if (!raw || typeof raw !== 'object') return null
  const total = Math.max(0, Math.floor(finiteNumber(raw.total)))
  if (total <= 0) return null
  return {
    phase: String(raw.phase || 'chapters'),
    decided: Math.max(0, Math.min(total, Math.floor(finiteNumber(raw.decided)))),
    total,
  }
}

// 展示百分比：后端真实百分比为锚点，锚点之间按时间小步爬升且封顶,永不超过运行上限
export const directoryDisplayPercentage = (progress = {}, nowMs = Date.now()) => {
  const status = normalizeStatus(progress?.status)
  const base = clampPercentage(progress?.percentage)
  if (status === 'completed') return 100
  if (!runningStatuses.has(status)) return base
  const anchorMs = Number.isFinite(Number(progress?.percentageUpdatedAt))
    ? Number(progress.percentageUpdatedAt)
    : directoryStartMs(progress)
  const creepSeconds = anchorMs === null ? 0 : Math.max(0, (finiteNumber(nowMs) - anchorMs) / 1000)
  const creep = Math.min(CREEP_MAX_PERCENT, creepSeconds * CREEP_PERCENT_PER_SECOND)
  return Math.min(base + creep, Math.max(base, RUNNING_DISPLAY_CAP))
}

const derivedStepStatuses = (status, percentage) => {
  if (status === 'completed') return ['done', 'done', 'done']
  if (failedStatuses.has(status)) {
    if (percentage < 5) return ['failed', 'pending', 'pending']
    if (percentage < 88) return ['done', 'failed', 'pending']
    return ['done', 'done', 'failed']
  }
  if (!runningStatuses.has(status)) return ['pending', 'pending', 'pending']
  if (percentage < 5) return ['running', 'pending', 'pending']
  if (percentage < 88) return ['done', 'running', 'pending']
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

const activeStepIndex = (steps) => {
  const active = steps.findIndex((step) => step.status === 'running' || step.status === 'failed')
  if (active >= 0) return active
  const lastDone = steps.reduce((acc, step, index) => (step.status === 'done' ? index : acc), -1)
  return lastDone >= 0 ? Math.min(lastDone + 1, steps.length - 1) : 0
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

const decisionDetailText = (decisionProgress) => {
  if (!decisionProgress) return ''
  const label = decisionProgress.phase === 'appendix' ? '技术附表' : '目录条款'
  return `已判定${label} ${decisionProgress.decided}/${decisionProgress.total} 项`
}

export const mergeMonotonicDirectoryProgress = (previous = null, incoming = null, nowMs = Date.now()) => {
  if (!incoming) return incoming
  if (!previous) return { ...incoming, percentageUpdatedAt: finiteNumber(nowMs) }
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
  merged.percentageUpdatedAt = incomingPercentage > previousPercentage
    ? finiteNumber(nowMs)
    : finiteNumber(previous?.percentageUpdatedAt) || finiteNumber(nowMs)

  const phaseRegressed = directoryStepRank(incoming) < directoryStepRank(previous)
  if (phaseRegressed) merged.tasks = previous?.tasks

  const previousDecision = normalizeDecisionProgress(previous)
  const incomingDecision = normalizeDecisionProgress(incoming)
  if (previousDecision && (!incomingDecision || (
    incomingDecision.phase === previousDecision.phase && incomingDecision.decided < previousDecision.decided
  ))) {
    merged.decisionProgress = previous.decisionProgress
  }

  const previousStartedAt = String(previous?.startedAt || '')
  if (previousStartedAt && !String(incoming?.startedAt || '')) merged.startedAt = previousStartedAt
  return merged
}

// 卡片只展示两行：summary 是主行（运行中即真实判定计数），耗时由页面拼在次行。
// 阶段序号与阶段名不再对外展示——状态徽标已给出状态与百分比，重复标题只占位置。
export const summarizeDirectoryProgress = (progress = {}) => {
  const status = normalizeStatus(progress?.status) || 'idle'
  const percentage = clampPercentage(progress?.percentage)
  const steps = buildSteps(progress, status, percentage)
  const stepIndex = activeStepIndex(steps)

  if (status === 'completed') {
    return {
      status,
      statusText: '已完成',
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
      summary: visibleFailureSummary(progress?.summary),
      percentage,
      tone: 'danger',
      steps,
    }
  }

  if (runningStatuses.has(status)) {
    const decisionProgress = normalizeDecisionProgress(progress)
    const fallbackDetail = stepIndex === 0
      ? '正在整理招标文件与投标模板，为目录生成做准备。'
      : stepIndex === 2
        ? '目录结构已经生成，正在整理并保存结果。'
        : '正在分析招标要求并组织目录结构，请稍候。'
    return {
      status,
      statusText: status === 'queued' ? '等待生成' : '生成中',
      summary: decisionDetailText(decisionProgress) || fallbackDetail,
      percentage,
      tone: 'running',
      steps,
    }
  }

  return {
    status,
    statusText: '待生成',
    summary: '准备完成后可开始生成目录。',
    percentage,
    tone: 'neutral',
    steps,
  }
}
