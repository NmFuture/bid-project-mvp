// 解析后台任务标记：上传解析提交为后台任务后写入 localStorage，
// 供全局提示条在离开审核页后仍能发现进行中的解析并引导跳回。
const PARSE_RUNNING_KEY_PREFIX = 'bid:parse-running:'
const PARSE_RUNNING_TTL_MS = 6 * 60 * 60 * 1000

const storageKeyFor = (projectId, bidType) => `${PARSE_RUNNING_KEY_PREFIX}${bidType}:${projectId}`

const resolveStorage = () => {
  try {
    if (typeof window !== 'undefined' && window.localStorage) return window.localStorage
  } catch {
    // 隐私模式等场景下 localStorage 可能不可用，视为无标记
  }
  return null
}

export const markParseRunning = (projectId, bidType) => {
  const storage = resolveStorage()
  const id = String(projectId || '').trim()
  const type = String(bidType || '').trim()
  if (!storage || !id || !type) return false
  try {
    storage.setItem(storageKeyFor(id, type), JSON.stringify({
      projectId: id,
      bidType: type,
      startedAt: Date.now(),
    }))
    return true
  } catch {
    return false
  }
}

export const clearParseRunning = (projectId, bidType) => {
  const storage = resolveStorage()
  const id = String(projectId || '').trim()
  const type = String(bidType || '').trim()
  if (!storage || !id || !type) return
  try {
    storage.removeItem(storageKeyFor(id, type))
  } catch {
    // 清除失败不影响主流程
  }
}

export const findRunningParseMarker = (bidType, now = Date.now()) => {
  const type = String(bidType || '').trim()
  if (!type) return null
  return readRunningParses(now).find((item) => item?.bidType === type) || null
}

export const readRunningParses = (now = Date.now()) => {
  const storage = resolveStorage()
  if (!storage) return []
  const running = []
  const staleKeys = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (!key || !key.startsWith(PARSE_RUNNING_KEY_PREFIX)) continue
    let parsed = null
    try {
      parsed = JSON.parse(storage.getItem(key) || '')
    } catch {
      parsed = null
    }
    const projectId = String(parsed?.projectId || '').trim()
    const bidType = String(parsed?.bidType || '').trim()
    const startedAt = Number(parsed?.startedAt || 0)
    // 坏数据或已过期的标记顺手清掉，避免长期残留
    if (!projectId || !bidType || !Number.isFinite(startedAt) || startedAt <= 0 || now - startedAt >= PARSE_RUNNING_TTL_MS) {
      staleKeys.push(key)
      continue
    }
    running.push({ projectId, bidType, startedAt })
  }
  staleKeys.forEach((key) => {
    try {
      storage.removeItem(key)
    } catch {
      // 清除失败不影响读取结果
    }
  })
  // 最早提交的排在最前，全局提示条逐个消化
  return running.sort((a, b) => a.startedAt - b.startedAt)
}
