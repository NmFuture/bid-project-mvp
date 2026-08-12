import { useEffect, useMemo, useState } from 'react'
import { Dialog, DialogBody, DialogFooter, DialogHeader } from '../ui/Dialog'

const flattenObject = (input, prefix = '', output = {}) => {
  if (input === null || input === undefined) {
    output[prefix || 'root'] = input
    return output
  }
  if (typeof input !== 'object' || Array.isArray(input)) {
    output[prefix || 'root'] = input
    return output
  }

  Object.entries(input).forEach(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      flattenObject(value, path, output)
      return
    }
    output[path] = value
  })
  return output
}

const toDisplay = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export default function AuditDetailModal({ auditId, onClose, loadDetail }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(true)
      setError('')
      if (typeof loadDetail !== 'function') {
        setError('日志详情接口未配置。')
        setLoading(false)
        return
      }
      loadDetail(auditId)
        .then((res) => {
          setDetail(res)
        })
        .catch((e) => {
          console.error(e)
          setError(e?.message || '日志详情加载失败')
        })
        .finally(() => {
          setLoading(false)
        })
    }, 0)

    return () => clearTimeout(timer)
  }, [auditId, loadDetail])

  const diffRows = useMemo(() => {
    if (!detail?.diff) return []
    const before = flattenObject(detail.diff.before || {})
    const after = flattenObject(detail.diff.after || {})
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort()
    return keys.map((key) => ({
      key,
      before: before[key],
      after: after[key],
      changed: JSON.stringify(before[key]) !== JSON.stringify(after[key]),
    }))
  }, [detail])

  // 行为事件等无 diff 的记录通过 meta 传递附加信息，扁平化后展示
  const metaRows = useMemo(() => {
    if (!detail?.meta || typeof detail.meta !== 'object' || Array.isArray(detail.meta)) return []
    return Object.entries(flattenObject(detail.meta))
  }, [detail])

  return (
    <Dialog open onClose={onClose} size="xl" className="max-w-5xl">
        <DialogHeader onClose={onClose}>
          <div>
            <h2 className="text-xl font-headline font-bold text-on-surface">日志详情</h2>
            <p className="text-xs text-outline mt-1">日志 ID：{auditId}</p>
          </div>
        </DialogHeader>

        <DialogBody className="p-4 sm:p-6">
          {loading && <div role="status" aria-label="正在加载日志详情" className="h-80 w-full animate-shimmer rounded-lg" />}
          {!loading && error && (
            <div role="alert" className="rounded-lg border border-error/20 bg-error-container/20 p-4 text-sm text-error">{error}</div>
          )}
          {!loading && !error && detail && (
            <div className="space-y-5">
              <div className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg bg-surface-container-low p-3">
                  <p className="text-outline">时间</p>
                  <p className="mt-1 text-on-surface">{detail.time || '-'}</p>
                </div>
                <div className="rounded-lg bg-surface-container-low p-3">
                  <p className="text-outline">用户</p>
                  <p className="mt-1 text-on-surface">{detail.user || '-'}</p>
                </div>
                <div className="rounded-lg bg-surface-container-low p-3">
                  <p className="text-outline">动作</p>
                  <p className="mt-1 text-on-surface">{detail.action || '-'}</p>
                </div>
                <div className="rounded-lg bg-surface-container-low p-3">
                  <p className="text-outline">目标</p>
                  <p className="mt-1 text-on-surface line-clamp-2">{detail.target || '-'}</p>
                </div>
              </div>

              {detail?.diff && (
              <div className="overflow-hidden rounded-lg border border-surface-container-high">
                <div className="grid min-w-[42rem] grid-cols-12 border-b border-surface-container-high bg-surface-container-low text-xs font-semibold text-on-surface-variant">
                  <div className="col-span-3 px-3 py-2">字段</div>
                  <div className="col-span-4 px-3 py-2">Before</div>
                  <div className="col-span-4 px-3 py-2">After</div>
                  <div className="col-span-1 px-3 py-2 text-center">变化</div>
                </div>
                <div className="max-h-[52dvh] overflow-auto">
                  {diffRows.map((row) => (
                    <div key={row.key} className="grid min-w-[42rem] grid-cols-12 border-b border-surface-container-high/60 text-xs">
                      <div className="col-span-3 px-3 py-2 font-mono text-on-surface break-all">{row.key}</div>
                      <div className={`col-span-4 px-3 py-2 whitespace-pre-wrap break-all ${row.changed ? 'bg-error-container/20 text-error' : 'text-on-surface-variant'}`}>
                        {toDisplay(row.before)}
                      </div>
                      <div className={`col-span-4 px-3 py-2 whitespace-pre-wrap break-all ${row.changed ? 'bg-secondary-container/30 text-secondary' : 'text-on-surface-variant'}`}>
                        {toDisplay(row.after)}
                      </div>
                      <div className="col-span-1 px-3 py-2 flex items-center justify-center">
                        <span aria-hidden="true" className={`material-symbols-outlined text-sm ${row.changed ? 'text-primary' : 'text-outline'}`}>
                          {row.changed ? 'change_circle' : 'remove'}
                        </span>
                      </div>
                    </div>
                  ))}
                  {!diffRows.length && (
                    <div className="p-4 text-sm text-outline">当前日志未返回可对比字段。</div>
                  )}
                </div>
              </div>
              )}

              {metaRows.length > 0 && (
                <div className="overflow-hidden rounded-lg border border-surface-container-high">
                  <div className="grid min-w-[36rem] grid-cols-12 border-b border-surface-container-high bg-surface-container-low text-xs font-semibold text-on-surface-variant">
                    <div className="col-span-3 px-3 py-2">附加信息（meta）</div>
                    <div className="col-span-9 px-3 py-2">值</div>
                  </div>
                  <div className="max-h-[52dvh] overflow-auto">
                    {metaRows.map(([key, value]) => (
                      <div key={key} className="grid min-w-[36rem] grid-cols-12 border-b border-surface-container-high/60 text-xs">
                        <div className="col-span-3 px-3 py-2 font-mono text-on-surface break-all">{key}</div>
                        <div className="col-span-9 px-3 py-2 whitespace-pre-wrap break-all text-on-surface-variant">
                          {toDisplay(value)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <button type="button" onClick={onClose} className="ui-control h-9 rounded-md px-5 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-container-high">
            关闭
          </button>
        </DialogFooter>
    </Dialog>
  )
}
