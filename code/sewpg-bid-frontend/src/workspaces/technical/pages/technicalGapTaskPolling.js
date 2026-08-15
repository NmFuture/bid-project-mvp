// 后台任务轮询的纯逻辑（从 TechnicalGapRecognition.jsx 的 factCurate/bodyFill 轮询 effect 抽出），
// 不依赖 React，可用 node --test 直接验证。

// 终态通知 key：jobId + finishedAt 去重——同一任务的收尾那一拍只通知一次，
// 避免轮询在终态上多跑一拍时重复弹 toast（历史语义，勿改）。
export const backgroundTaskTerminalKey = (state, terminalStatuses) => {
  const status = String(state?.status || '')
  if (!terminalStatuses.includes(status)) return null
  return `${state?.jobId || ''}:${state?.finishedAt || ''}`
}

// 单拍轮询：取状态 → 每拍都回写 state → 终态且未通知过时返回 notifyKey（由调用方置位 ref 后再跑收尾）。
export const runBackgroundTaskTick = async ({
  fetchStatus,
  extractState,
  terminalStatuses,
  onState,
  lastNotifiedKey,
}) => {
  const payload = await fetchStatus()
  const state = extractState(payload)
  onState(state, payload)
  const notifyKey = backgroundTaskTerminalKey(state, terminalStatuses)
  if (!notifyKey || notifyKey === lastNotifiedKey) return { payload, state, notifyKey: null }
  return { payload, state, notifyKey }
}
