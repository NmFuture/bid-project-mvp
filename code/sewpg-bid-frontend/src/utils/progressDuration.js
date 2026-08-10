// 五处进度条共用的耗时文案：运行中显示「已运行 x」，终态显示「总耗时 x」。
export const formatProgressDuration = (value) => {
  const number = Number(value)
  const seconds = Math.max(0, Math.floor(Number.isFinite(number) ? number : 0))
  if (seconds <= 0) return ''
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes > 0) return `${minutes} 分 ${remainingSeconds} 秒`
  return `${seconds} 秒`
}

export const progressElapsedLine = (seconds, { finished = false } = {}) => {
  const text = formatProgressDuration(seconds)
  if (!text) return ''
  return `${finished ? '总耗时' : '已运行'} ${text}`
}
