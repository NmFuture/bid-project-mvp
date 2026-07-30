const finiteNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

const validTimestamp = (value) => {
  const timestamp = String(value || '').trim()
  return Number.isFinite(Date.parse(timestamp)) ? timestamp : ''
}

export const resolveWikiJobElapsedTimestamp = (status = {}) => (
  validTimestamp(status?.startedAt) || validTimestamp(status?.createdAt)
)

export const calculateWikiJobElapsedSeconds = (timestamp, nowMs = Date.now()) => {
  const startedAt = Date.parse(String(timestamp || ''))
  const currentTime = Number(nowMs)
  if (!Number.isFinite(startedAt) || !Number.isFinite(currentTime)) return 0
  return Math.max(0, Math.floor((currentTime - startedAt) / 1000))
}

export const formatWikiJobElapsed = (seconds) => {
  const total = Math.max(0, Math.floor(finiteNumber(seconds)))
  const minutes = Math.floor(total / 60)
  const remaining = total % 60
  if (minutes > 0) return `${minutes} 分 ${remaining} 秒`
  return `${total} 秒`
}
