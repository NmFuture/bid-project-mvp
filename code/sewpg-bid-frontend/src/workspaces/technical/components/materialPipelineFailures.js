// 素材流水线失败横幅的数据推导（R10-B07-05）：从进度快照里收集各阶段最近一次
// 终态中的失败/取消。清洗/深度解析来自后端按类型记忆的 lastTerminal，Wiki 来自
// 最近任务指针；都不依赖本次会话是否轮询到过 running。
// 抽成纯函数模块是为了可用 node:test 直接覆盖（组件本体是 JSX，且带轮询副作用）。
const TECHNICAL_BID_TYPE = '技术标'
const BUSINESS_BID_TYPE = '商务标'
export const DISMISSED_KEYS_LIMIT = 100
const DISMISSED_KEY_MAX_LENGTH = 300

const normalizeBidType = (value) => {
  const text = typeof value === 'string' ? value.trim() : ''
  return [TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE].includes(text) ? text : ''
}

const terminalBidType = (terminal) => (
  terminal && Object.prototype.hasOwnProperty.call(terminal, 'bidType')
    ? normalizeBidType(terminal.bidType)
    : TECHNICAL_BID_TYPE
)

const normalizeDismissedKeys = (values) => {
  if (!Array.isArray(values)) return []
  const seen = new Set()
  const newestFirst = []
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index]
    if (typeof value !== 'string') continue
    const key = value.trim()
    if (!key || key.length > DISMISSED_KEY_MAX_LENGTH || seen.has(key)) continue
    seen.add(key)
    newestFirst.push(key)
    if (newestFirst.length >= DISMISSED_KEYS_LIMIT) break
  }
  return newestFirst.reverse()
}

export const loadDismissedKeys = (serialized) => {
  if (typeof serialized !== 'string' || !serialized) return []
  try {
    return normalizeDismissedKeys(JSON.parse(serialized))
  } catch {
    return []
  }
}

export const appendDismissedKey = (keys, key) => normalizeDismissedKeys([
  ...(Array.isArray(keys) ? keys : []),
  key,
])

export const collectStageFailures = (payload, bidType = TECHNICAL_BID_TYPE) => {
  const failures = []
  const pushTerminal = (stageKey, stageLabel, terminal, retryable) => {
    const status = String(terminal?.status || '')
    if (!['failed', 'cancelled'].includes(status)) return
    const resolvedTerminalBidType = terminalBidType(terminal)
    if (!resolvedTerminalBidType || resolvedTerminalBidType !== normalizeBidType(bidType)) return
    failures.push({
      dismissKey: `${resolvedTerminalBidType}:${stageKey}:${String(terminal.jobId || status)}`,
      stageLabel,
      status,
      jobId: String(terminal.jobId || ''),
      message: String(terminal.message || ''),
      retryable,
    })
  }
  // 清洗失败没有自动重试入口（清洗只在上传时入队），横幅指引重新上传；
  // 深度解析/Wiki 失败可由 Wiki refresh 重试（refresh 会补排失败或未运行的深度解析）。
  pushTerminal('cleaning', '素材清洗', payload?.cleaning?.lastTerminal, false)
  pushTerminal('deepParse', '深度解析', payload?.deepParse?.lastTerminal, true)
  const wiki = payload?.wiki || {}
  pushTerminal('wiki', 'Wiki 增量构建', {
    jobId: wiki.jobId,
    ...(Object.prototype.hasOwnProperty.call(wiki, 'bidType') ? { bidType: wiki.bidType } : {}),
    status: wiki.status,
    message: wiki.error || wiki.message,
  }, true)
  return failures
}

export const firstUndismissedStageFailure = (
  payload,
  dismissedKeys = [],
  bidType = TECHNICAL_BID_TYPE,
) => {
  const dismissed = new Set(dismissedKeys)
  return collectStageFailures(payload, bidType).find((item) => !dismissed.has(item.dismissKey)) || null
}
