// 「重新生成索引」的进度展示逻辑，与重新生成目录同一套刻度：
// 第一行是带量化计数的明细，第二行是耗时，百分比在后端锚点之间按时间小步爬升。
//
// 量化计数取自后端 indexProgress：total 是评分索引表的评审因素行数，
// done 是已经写进章节索引列的行数。章节判断那一步是一次整体调用、拿不到逐行回执，
// 所以计数会停在体检值直到判断结果落盘——宁可停住也不编造中间数。
const runningStatuses = new Set(['running', 'processing', 'queued', 'cancel_requested'])
const failedStatuses = new Set(['failed', 'error'])
const internalTextPattern = /opencode|manifest|skill|session|provider|model|xref/i

const CREEP_PERCENT_PER_SECOND = 0.05
const CREEP_MAX_PERCENT = 6
const RUNNING_DISPLAY_CAP = 96

const finiteNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}
const clampPercentage = (value) => Math.max(0, Math.min(100, finiteNumber(value)))
const normalizeStatus = (value) => String(value || '').toLowerCase()
const parseTime = (value) => {
  const parsed = Date.parse(String(value || ''))
  return Number.isFinite(parsed) ? parsed : null
}
const eventList = (state) =>
  (Array.isArray(state?.events) ? state.events : []).filter((event) => event && typeof event === 'object')

export const isScoreIndexProgressRunning = (state) => runningStatuses.has(normalizeStatus(state?.status))
export const isScoreIndexProgressFailed = (state) => failedStatuses.has(normalizeStatus(state?.status))

export const normalizeIndexProgress = (state = {}) => {
  const raw = state?.indexProgress
  if (!raw || typeof raw !== 'object') return null
  const total = Math.max(0, Math.floor(finiteNumber(raw.total)))
  if (total <= 0) return null
  return {
    done: Math.max(0, Math.min(total, Math.floor(finiteNumber(raw.done)))),
    total,
    phase: String(raw.phase || ''),
    updatedAtMs: parseTime(raw.updatedAt),
  }
}

const startMs = (state = {}) => {
  const startedAt = parseTime(state?.startedAt)
  if (startedAt !== null) return startedAt
  const times = eventList(state).map((event) => parseTime(event?.at)).filter((value) => value !== null)
  return times.length ? Math.min(...times) : null
}

const terminalMs = (state = {}) => {
  const cancelledAt = parseTime(state?.cancelledAt)
  if (cancelledAt !== null) return cancelledAt
  const finishedAt = parseTime(state?.finishedAt)
  if (finishedAt !== null) return finishedAt
  const times = eventList(state).map((event) => parseTime(event?.at)).filter((value) => value !== null)
  return times.length ? Math.max(...times) : null
}

const isTerminal = (state) => {
  const status = normalizeStatus(state?.status)
  return status === 'completed' || status === 'cancelled' || failedStatuses.has(status)
}

export const scoreIndexElapsedSeconds = (state = {}, nowMs = Date.now()) => {
  const start = startMs(state)
  if (start === null) return 0
  const end = isTerminal(state) ? (terminalMs(state) ?? finiteNumber(nowMs)) : finiteNumber(nowMs)
  return Math.max(0, (end - start) / 1000)
}

// 后端百分比只当锚点：章节判断那一步可能几十秒没有新事件，靠时间爬升让进度条不僵死，
// 但封顶 96%，不允许在任务真正完成前显示成已完成。
export const scoreIndexDisplayPercentage = (state = {}, nowMs = Date.now()) => {
  const status = normalizeStatus(state?.status)
  const base = clampPercentage(state?.percentage)
  if (status === 'completed') return 100
  if (!runningStatuses.has(status)) return base

  const progress = normalizeIndexProgress(state)
  const anchorMs = progress?.updatedAtMs
    ?? (eventList(state).length ? parseTime(eventList(state)[eventList(state).length - 1]?.at) : null)
    ?? startMs(state)
  const creepSeconds = anchorMs === null ? 0 : Math.max(0, (finiteNumber(nowMs) - anchorMs) / 1000)
  const creep = Math.min(CREEP_MAX_PERCENT, creepSeconds * CREEP_PERCENT_PER_SECOND)
  return Math.min(base + creep, Math.max(base, RUNNING_DISPLAY_CAP))
}

const visibleText = (value) => {
  const text = String(value || '').trim()
  return text && !internalTextPattern.test(text) ? text : ''
}

const visibleFailureSummary = (summary) => {
  const value = String(summary || '').trim()
  if (/请先生成正文|未找到|正文正在/.test(value) && !internalTextPattern.test(value)) return value
  if (/超时|timeout|网络|连接|服务不可用|暂不可用|网关/i.test(value)) {
    return '章节索引服务暂时不可用，成稿未被改动，请稍后重试。'
  }
  return visibleText(value) || '章节索引生成未完成，成稿未被改动，请稍后重试。'
}

export const scoreIndexDetailText = (progress) => {
  if (!progress) return ''
  return `已建立章节索引 ${progress.done}/${progress.total} 项`
}

// 只产出展示字段：tone 决定配色，detail 是卡片第一行。
export const summarizeScoreIndexProgress = (state = {}) => {
  const status = normalizeStatus(state?.status) || 'idle'

  if (status === 'completed') {
    return { status, tone: 'success', detail: visibleText(state?.summary) || '章节索引已重新生成。' }
  }

  if (failedStatuses.has(status)) {
    return { status, tone: 'danger', detail: visibleFailureSummary(state?.summary) }
  }

  if (status === 'cancelled') {
    return { status, tone: 'neutral', detail: '章节索引重新生成已停止。' }
  }

  if (runningStatuses.has(status)) {
    const progress = normalizeIndexProgress(state)
    // 章节判断是一次整体调用，期间计数只会停在 0：那一段用后端那句带数量的说明更有信息量，
    // 真正开始逐行建引用（done 已经动了或已进入 built 阶段）后再切回 X/Y 计数。
    const counterReady = Boolean(progress) && (progress.done > 0 || progress.phase === 'built')
    const detail = counterReady
      ? scoreIndexDetailText(progress)
      : visibleText(state?.summary) || scoreIndexDetailText(progress)
    return {
      status,
      tone: 'running',
      detail: detail || '正在定位评分索引表，请稍候。',
    }
  }

  return { status, tone: 'neutral', detail: '可在成稿生成后重新生成章节索引。' }
}
