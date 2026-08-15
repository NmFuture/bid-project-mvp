import { formatProgressDuration } from '../../utils/progressDuration.js'

// 技术标正文生成（首次生成 / 重新生成）的进度展示逻辑。
// 与目录生成对齐：第一行是带量化计数的明细，第二行是耗时，进度条按「真实耗时占比」分配区间。
//
// 区间划分依据 PRJ-0004 实测（总 280 秒）：准备输入 64 秒、正文组装 168 秒、格式规范化 44 秒。
// 后端 percentage 的原始锚点（30 → 60 只花 1 秒，60 → 85 却要 168 秒）无法直接当进度用，
// 这里按阶段重新折算，并在阶段内按已用时间平滑爬升，保证「不会前 60% 一分钟、后 40% 好几分钟」。
const runningStatuses = new Set(['running', 'processing', 'queued', 'cancel_requested'])
const failedStatuses = new Set(['failed', 'error'])
const internalTextPattern = /futurecode|opencode|S2|S4|Skill|session|manifest|provider|model/i

const ASSEMBLY_STEPS = new Set(['assembly_waiting', 'assembler_session_ready', 'assembler_streaming'])

const STAGES = {
  bootstrap: { start: 3, end: 23, expectedSeconds: 65 },
  inputs_ready: { start: 23, end: 25, expectedSeconds: 3 },
  assembly_waiting: { start: 25, end: 82, expectedSeconds: 170 },
  assembler_session_ready: { start: 25, end: 82, expectedSeconds: 170 },
  assembler_streaming: { start: 25, end: 82, expectedSeconds: 170 },
  assembling: { start: 82, end: 85, expectedSeconds: 5 },
  format_cleaning: { start: 85, end: 97, expectedSeconds: 45 },
  format_session_ready: { start: 85, end: 97, expectedSeconds: 45 },
  format_streaming: { start: 85, end: 97, expectedSeconds: 45 },
  format_failed: { start: 88, end: 97, expectedSeconds: 30 },
  format_done: { start: 97, end: 100, expectedSeconds: 3 },
  done: { start: 100, end: 100, expectedSeconds: 1 },
}
const ASSEMBLY_STAGE = STAGES.assembly_waiting

// 没有事件流时（历史数据）按后端锚点折算，保持与阶段区间同一套刻度。
const PERCENTAGE_ANCHORS = [
  [0, 0], [5, 3], [30, 23], [60, 25], [62, 26], [70, 30],
  [85, 82], [90, 85], [91, 86], [93, 92], [94, 90], [96, 97], [100, 100],
]

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
const eventList = (state) => (Array.isArray(state?.events) ? state.events : []).filter((event) => event && typeof event === 'object')

export const isGenerationProgressRunning = (state) => runningStatuses.has(normalizeStatus(state?.status))
export const isGenerationProgressFailed = (state) => failedStatuses.has(normalizeStatus(state?.status))

export const normalizeAssemblyProgress = (state = {}) => {
  const raw = state?.assemblyProgress
  if (!raw || typeof raw !== 'object') return null
  const total = Math.max(0, Math.floor(finiteNumber(raw.total)))
  if (total <= 0) return null
  return {
    done: Math.max(0, Math.min(total, Math.floor(finiteNumber(raw.done)))),
    total,
    updatedAtMs: parseTime(raw.updatedAt),
  }
}

const generationStartMs = (state = {}) => {
  const startedAt = parseTime(state?.startedAt)
  if (startedAt !== null) return startedAt
  const times = eventList(state).map((event) => parseTime(event?.at)).filter((value) => value !== null)
  return times.length ? Math.min(...times) : null
}

const generationTerminalMs = (state = {}) => {
  const cancelledAt = parseTime(state?.cancelledAt)
  if (cancelledAt !== null) return cancelledAt
  const filledAt = parseTime(state?.filledAt)
  if (filledAt !== null) return filledAt
  const times = eventList(state).map((event) => parseTime(event?.at)).filter((value) => value !== null)
  return times.length ? Math.max(...times) : null
}

const isTerminal = (state) => {
  const status = normalizeStatus(state?.status)
  return status === 'completed' || status === 'cancelled' || failedStatuses.has(status)
}

// 总运行时长：起点是本次生成启动时间，终态冻结在完成/失败时刻。
export const generationElapsedSeconds = (state = {}, nowMs = Date.now()) => {
  const startMs = generationStartMs(state)
  if (startMs === null) return 0
  const endMs = isTerminal(state)
    ? (generationTerminalMs(state) ?? finiteNumber(nowMs))
    : finiteNumber(nowMs)
  return Math.max(0, (endMs - startMs) / 1000)
}

export const formatGenerationDuration = formatProgressDuration

const lastEvent = (state) => {
  const events = eventList(state)
  return events.length ? events[events.length - 1] : null
}

const currentStageKey = (state) => {
  const step = String(lastEvent(state)?.step || '').trim()
  return step in STAGES ? step : ''
}

// 阶段内按已用时间渐进逼近区间末端：t = 预计耗时时约走完 92%，慢于预期也不会越界。
const easeWithinStage = (elapsedSeconds, expectedSeconds) => {
  const elapsed = Math.max(0, finiteNumber(elapsedSeconds))
  const tau = Math.max(1, finiteNumber(expectedSeconds)) / 2.5
  return 1 - Math.exp(-elapsed / tau)
}

const fallbackFromBackendPercentage = (percentage) => {
  const value = clampPercentage(percentage)
  let mapped = 0
  for (const [anchor, display] of PERCENTAGE_ANCHORS) {
    if (value >= anchor) mapped = display
  }
  return mapped
}

export const generationDisplayPercentage = (state = {}, nowMs = Date.now()) => {
  const status = normalizeStatus(state?.status)
  if (status === 'completed') return 100
  if (!runningStatuses.has(status)) return fallbackFromBackendPercentage(state?.percentage)

  const stageKey = currentStageKey(state)
  const stage = stageKey ? STAGES[stageKey] : null
  const assembly = normalizeAssemblyProgress(state)

  // 组装阶段有逐条真实计数时以计数为准，只在两次计数之间做小幅平滑。
  if (assembly && (!stageKey || ASSEMBLY_STEPS.has(stageKey))) {
    const span = ASSEMBLY_STAGE.end - ASSEMBLY_STAGE.start
    const base = ASSEMBLY_STAGE.start + (span * assembly.done) / assembly.total
    const next = ASSEMBLY_STAGE.start + (span * Math.min(assembly.done + 1, assembly.total)) / assembly.total
    const sinceUpdate = assembly.updatedAtMs === null
      ? 0
      : Math.max(0, (finiteNumber(nowMs) - assembly.updatedAtMs) / 1000)
    return Math.min(ASSEMBLY_STAGE.end, base + (next - base) * easeWithinStage(sinceUpdate, 8))
  }

  if (!stage) return fallbackFromBackendPercentage(state?.percentage)

  const stageStartMs = parseTime(lastEvent(state)?.at) ?? generationStartMs(state)
  const elapsedInStage = stageStartMs === null ? 0 : Math.max(0, (finiteNumber(nowMs) - stageStartMs) / 1000)
  return stage.start + (stage.end - stage.start) * easeWithinStage(elapsedInStage, stage.expectedSeconds)
}

const visibleText = (value) => {
  const text = String(value || '').trim()
  return text && !internalTextPattern.test(text) ? text : ''
}

const visibleFailureSummary = (summary) => {
  const value = String(summary || '').trim()
  if (/请先完成目录确认|请先完成素材匹配|素材|目录/.test(value) && !internalTextPattern.test(value)) return value
  if (/超时|timeout|网络|连接|服务不可用|暂不可用|网关/i.test(value)) {
    return '正文生成服务暂时不可用，请稍后重试。'
  }
  return visibleText(value) || '正文生成未完成，请稍后重试；如仍失败请联系管理员。'
}

const runningDetail = (state, stageKey) => {
  const assembly = normalizeAssemblyProgress(state)
  if (assembly && (!stageKey || ASSEMBLY_STEPS.has(stageKey))) {
    return `已组装目录项 ${assembly.done}/${assembly.total} 项`
  }
  const summary = visibleText(state?.summary)
  if (summary) return summary
  if (stageKey && stageKey.startsWith('format')) return '正在规范化 Word 格式，请稍候。'
  if (stageKey && ASSEMBLY_STEPS.has(stageKey)) return '正在按已确认目录和素材组装正文，请稍候。'
  return '正在准备目录与已选素材，请稍候。'
}

// 只产出展示字段：tone 决定配色，detail 是卡片第一行。状态词不再单独渲染——
// 图标与百分比已经表达状态，右侧再写一遍「生成中」是重复。
export const summarizeGenerationProgress = (state = {}) => {
  const status = normalizeStatus(state?.status) || 'idle'

  if (status === 'completed') {
    return {
      status,
      tone: 'success',
      detail: visibleText(state?.summary) || '正文生成完成。',
    }
  }

  if (failedStatuses.has(status)) {
    return {
      status,
      tone: 'danger',
      detail: visibleFailureSummary(state?.summary),
    }
  }

  if (status === 'cancelled') {
    return {
      status,
      tone: 'neutral',
      detail: '正文生成已停止。',
    }
  }

  if (runningStatuses.has(status)) {
    return {
      status,
      tone: 'running',
      detail: runningDetail(state, currentStageKey(state)),
    }
  }

  return {
    status,
    tone: 'neutral',
    detail: '准备完成后可开始生成正文。',
  }
}
