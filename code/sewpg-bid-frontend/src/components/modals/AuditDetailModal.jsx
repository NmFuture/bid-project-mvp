import { useEffect, useMemo, useState } from 'react'
import { auditAPI } from '../../api'

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

export default function AuditDetailModal({ auditId, onClose }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(true)
      setError('')
      auditAPI.detail(auditId)
        .then((res) => {
          setDetail(res)
        })
        .catch((e) => {
          console.error(e)
          setError(e?.message || '审计详情加载失败')
        })
        .finally(() => {
          setLoading(false)
        })
    }, 0)

    return () => clearTimeout(timer)
  }, [auditId])

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

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <div className="dialog-content w-full max-w-5xl animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-surface-container-high">
          <div>
            <h2 className="text-xl font-headline font-bold text-on-surface">审计详情</h2>
            <p className="text-xs text-outline mt-1">日志 ID：{auditId}</p>
          </div>
          <button onClick={onClose} className="close-plain text-on-surface-variant hover:text-primary transition-colors" aria-label="关闭">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="p-6">
          {loading && <div className="animate-shimmer w-full h-80 rounded-xl" />}
          {!loading && error && (
            <div className="bg-error-container/20 border border-error/20 rounded-lg p-4 text-sm text-error">{error}</div>
          )}
          {!loading && !error && detail && (
            <div className="space-y-5">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
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

              <div className="rounded-xl border border-surface-container-high overflow-hidden">
                <div className="grid grid-cols-12 bg-surface-container-low text-xs font-semibold text-on-surface-variant border-b border-surface-container-high">
                  <div className="col-span-3 px-3 py-2">字段</div>
                  <div className="col-span-4 px-3 py-2">Before</div>
                  <div className="col-span-4 px-3 py-2">After</div>
                  <div className="col-span-1 px-3 py-2 text-center">变化</div>
                </div>
                <div className="max-h-[52vh] overflow-auto">
                  {diffRows.map((row) => (
                    <div key={row.key} className="grid grid-cols-12 border-b border-surface-container-high/60 text-xs">
                      <div className="col-span-3 px-3 py-2 font-mono text-on-surface break-all">{row.key}</div>
                      <div className={`col-span-4 px-3 py-2 whitespace-pre-wrap break-all ${row.changed ? 'bg-error-container/20 text-error' : 'text-on-surface-variant'}`}>
                        {toDisplay(row.before)}
                      </div>
                      <div className={`col-span-4 px-3 py-2 whitespace-pre-wrap break-all ${row.changed ? 'bg-secondary-container/30 text-secondary' : 'text-on-surface-variant'}`}>
                        {toDisplay(row.after)}
                      </div>
                      <div className="col-span-1 px-3 py-2 flex items-center justify-center">
                        <span className={`material-symbols-outlined text-sm ${row.changed ? 'text-primary' : 'text-outline'}`}>
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
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-surface-container-high flex justify-end bg-surface-container-low rounded-b-xl">
          <button onClick={onClose} className="px-5 py-2 text-sm font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors">
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
