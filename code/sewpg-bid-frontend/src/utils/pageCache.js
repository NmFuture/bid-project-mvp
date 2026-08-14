import { useCallback, useEffect, useRef, useState } from 'react'

// 页面级会话缓存（stale-while-revalidate），沿用 ProjectStageProgress 的
// StageCache 模式：挂载时先用缓存渲染、后台静默刷新覆盖，避免每次路由切换
// 都经历「清空 → 转圈 → 整页替换」。
// 缓存只活在当前标签页内存里，刷新页面即失效；增删改后必须按前缀作废对应 key。
const store = new Map()

export const readPageCache = (key) => (key ? store.get(key) : undefined)

export const writePageCache = (key, data) => {
  if (key) store.set(key, data)
}

// prefix 为空时清空全部；否则作废所有以 prefix 开头的 key
// （例：invalidatePageCache('tech:projects') 覆盖该列表的全部筛选/分页组合）。
export const invalidatePageCache = (prefix = '') => {
  if (!prefix) {
    store.clear()
    return
  }
  for (const key of [...store.keys()]) {
    if (key.startsWith(prefix)) store.delete(key)
  }
}

// usePageData(key, fetcher)
// - key 命中缓存：立即返回缓存数据（loading=false），后台重新拉取并覆盖
// - key 未命中：loading=true，拉取成功后写入缓存
// key 需自包含全部查询参数（如 `tech:projects:${status}:${page}`），key 变化即重新评估。
// fetcher 用 ref 持有，可以内联书写 async () => ...，不会引发重复请求。
export function usePageData(key, fetcher) {
  const fetcherRef = useRef(fetcher)
  const mountedRef = useRef(true)

  useEffect(() => {
    fetcherRef.current = fetcher
  })

  const [data, setData] = useState(() => readPageCache(key) ?? null)
  const [loading, setLoading] = useState(() => readPageCache(key) === undefined)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    const hit = readPageCache(key)
    if (hit !== undefined) {
      setData(hit)
      setLoading(false)
    } else {
      setLoading(true)
    }
    setError('')
    try {
      const next = await fetcherRef.current()
      writePageCache(key, next)
      if (!mountedRef.current) return
      setData(next)
    } catch (e) {
      if (!mountedRef.current) return
      setError(e?.payload?.detail || e?.message || '加载失败')
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [key])

  useEffect(() => {
    mountedRef.current = true
    // 异步评估缓存与拉取，避免在 effect 体内同步 setState 造成级联渲染
    const timer = setTimeout(() => {
      const hit = readPageCache(key)
      setData(hit ?? null)
      setLoading(hit === undefined)
      setError('')
      void reload()
    }, 0)
    return () => {
      mountedRef.current = false
      clearTimeout(timer)
    }
  }, [key, reload])

  return { data, loading, error, reload }
}
