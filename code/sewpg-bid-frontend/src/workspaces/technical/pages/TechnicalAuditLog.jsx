import { useCallback, useEffect, useMemo, useState } from 'react'
import { auditAPI } from '../../../api'
import AuditDetailModal from '../../../components/modals/AuditDetailModal'
import { PageEmpty, PageError, PageLoading } from '../components/TechnicalPageState'
import { bidTypeFromWorkspace, useWorkspaceSlug } from '../../../utils/workspace'

const defaultFilters = {
  user: '',
  module: '',
  action: '',
  status: '',
  startDate: '',
  endDate: '',
  keyword: '',
}

const actionColors = {
  generate: 'bg-primary-fixed text-primary',
  update: 'bg-secondary-container text-on-secondary-container',
  delete: 'bg-error-container text-on-error-container',
  auth: 'bg-surface-container-high text-on-surface-variant',
  config: 'bg-tertiary-fixed text-on-tertiary-fixed',
  import: 'bg-primary/10 text-primary',
}

const filterLabelClass = 'mb-1.5 block text-xs font-semibold text-outline'
const filterControlClass = 'h-9 w-full rounded-md border border-transparent bg-surface-container-low px-3 text-sm text-on-surface transition-colors focus:border-primary/30 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary/10'

const csvEscape = (value) => {
  const text = String(value ?? '')
  if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

const toCsv = (items = []) => {
  const headers = ['ID', '时间', '用户', '动作', '模块', '目标', '状态']
  const rows = items.map((item) => [
    item.id,
    item.time,
    item.user,
    item.action,
    item.moduleLabel,
    item.target,
    item.status,
  ])
  return [headers, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n')
}

const downloadCsv = (csv, fileName) => {
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

export default function AuditLog({ showToast = () => {} }) {
  const workspaceSlug = useWorkspaceSlug()
  const lockedBidType = bidTypeFromWorkspace(workspaceSlug)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const [queryFilters, setQueryFilters] = useState(defaultFilters)
  const [draftFilters, setDraftFilters] = useState(defaultFilters)
  const [detailAuditId, setDetailAuditId] = useState('')
  const [exporting, setExporting] = useState(false)

  const loadData = useCallback(async (filters, options = {}) => {
    if (options.silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError('')
    try {
      const response = await auditAPI.list({
        ...filters,
        bidType: lockedBidType,
      })
      setData(response)
    } catch (e) {
      console.error(e)
      const message = safeMessage(e, '日志加载失败，请稍后重试。')
      setError(message)
      if (options.silent) showToast(message, 'error')
    } finally {
      if (options.silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [lockedBidType, showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData(queryFilters)
    }, 0)
    return () => clearTimeout(timer)
  }, [queryFilters, loadData])

  const items = data?.items || []
  const filterOptions = data?.filterOptions || { users: [], modules: [], actions: [], statuses: [] }

  const hasActiveFilters = useMemo(
    () => Object.values(queryFilters).some((value) => String(value || '').trim()),
    [queryFilters],
  )

  const handleApplyFilters = () => {
    setQueryFilters({ ...draftFilters })
    showToast('筛选条件已应用')
  }

  const handleResetFilters = () => {
    setDraftFilters(defaultFilters)
    setQueryFilters(defaultFilters)
    showToast('筛选已重置')
  }

  const handleExportCsv = async () => {
    setExporting(true)
    try {
      const payload = await auditAPI.exportCsv({
        ...queryFilters,
        bidType: lockedBidType,
      })
      const exportItems = payload?.items || []
      if (!exportItems.length) {
        showToast('当前筛选条件下无可导出记录', 'error')
        return
      }
      const csv = toCsv(exportItems)
      const fileName = payload?.fileName || `audit_${Date.now()}.csv`
      downloadCsv(csv, fileName)
      showToast(`CSV 导出成功（${exportItems.length} 条）`)
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '导出 CSV 失败，请稍后重试。'), 'error')
    } finally {
      setExporting(false)
    }
  }

  if (loading && !data) {
    return <PageLoading title="正在加载日志..." description="正在同步最新操作记录。" />
  }

  if (error && !data) {
    return (
      <PageError
        title="日志加载失败"
        description={error}
        onRetry={() => loadData(queryFilters)}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3 animate-fade-in">
      <div className="overflow-hidden rounded-xl border border-outline-variant/55 bg-white shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="h-5 w-1 rounded-full bg-primary" />
              <h1 className="text-xl font-headline font-bold text-ink-strong">{lockedBidType ? `${lockedBidType}日志` : '日志'}</h1>
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                {data?.total || items.length} 条
              </span>
            </div>
            <p className="mt-1 text-sm text-on-surface-variant">支持筛选、diff 查看与 CSV 导出，满足联调追踪需求。</p>
            {(refreshing || error) && (
              <p className={`mt-1 text-xs ${error ? 'text-error' : 'text-outline'}`}>
                {error || '正在刷新数据...'}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={handleExportCsv}
            disabled={exporting}
            className="command-button command-button-primary h-9 min-h-9 whitespace-nowrap px-4 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[17px]">download</span>
            {exporting ? '导出中...' : '导出 CSV'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-outline-variant/50 bg-white p-4 shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(16rem,1.4fr)_repeat(4,minmax(8rem,1fr))]">
          <div>
          <label className={filterLabelClass}>关键字</label>
          <input
            value={draftFilters.keyword}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, keyword: event.target.value }))}
            placeholder="搜索用户、动作、目标"
            className={filterControlClass}
          />
        </div>

          <div>
          <label className={filterLabelClass}>用户</label>
          <select
            value={draftFilters.user}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, user: event.target.value }))}
            className={`${filterControlClass} cursor-pointer`}
          >
            <option value="">所有用户</option>
            {filterOptions.users.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </div>

          <div>
          <label className={filterLabelClass}>项目/模块</label>
          <select
            value={draftFilters.module}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, module: event.target.value }))}
            className={`${filterControlClass} cursor-pointer`}
          >
            <option value="">所有模块</option>
            {filterOptions.modules.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

          <div>
          <label className={filterLabelClass}>动作类型</label>
          <select
            value={draftFilters.action}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, action: event.target.value }))}
            className={`${filterControlClass} cursor-pointer`}
          >
            <option value="">所有动作</option>
            {filterOptions.actions.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

          <div>
          <label className={filterLabelClass}>状态</label>
          <select
            value={draftFilters.status}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, status: event.target.value }))}
            className={`${filterControlClass} cursor-pointer`}
          >
            <option value="">全部状态</option>
            {filterOptions.statuses.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(20rem,1fr)_auto] lg:items-end">
          <div>
            <label className={filterLabelClass}>时间范围</label>
            <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
            <input
              type="date"
              value={draftFilters.startDate}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, startDate: event.target.value }))}
                className={filterControlClass}
            />
            <span className="text-outline">-</span>
            <input
              type="date"
              value={draftFilters.endDate}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, endDate: event.target.value }))}
                className={filterControlClass}
            />
            </div>
          </div>

          <div className="flex justify-end gap-2">
          <button
              type="button"
            onClick={handleResetFilters}
              className="command-button command-button-secondary h-9 min-h-9 px-4 text-sm"
          >
            重置
          </button>
          <button
              type="button"
            onClick={handleApplyFilters}
              className="command-button command-button-primary h-9 min-h-9 px-4 text-sm"
          >
              <span className="material-symbols-outlined text-[17px]">tune</span>
            应用筛选
          </button>
          </div>
        </div>
      </div>

      {!items.length ? (
        <PageEmpty
          title={hasActiveFilters ? '筛选后暂无日志' : '暂无日志'}
          description={hasActiveFilters ? '请调整筛选条件后重试。' : '当前暂无可展示的日志记录。'}
          actionText={hasActiveFilters ? '清空筛选' : undefined}
          onAction={hasActiveFilters ? handleResetFilters : undefined}
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-outline-variant/50 bg-white shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
          <div className="max-h-[calc(100vh-22rem)] min-h-[420px] overflow-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead className="sticky top-0 z-[1]">
                <tr className="border-b border-surface-container-high bg-surface-container-lowest/95 backdrop-blur">
                  {['时间戳', '用户', '动作', '目标/模块', '状态', '操作'].map((header) => (
                    <th key={header} className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((log) => (
                  <tr key={log.id} className="border-b border-surface-container-high/60 transition-colors hover:bg-surface-container-lowest">
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-on-surface-variant">{log.time || '-'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-container text-xs font-bold text-on-primary">{log.userAvatar || '人'}</div>
                        <span className="text-on-surface font-medium">{log.user || '-'}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${actionColors[log.actionType] || 'bg-surface-container-high text-on-surface-variant'}`}>
                        {log.action || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <p className="max-w-[32rem] truncate text-on-surface">{log.target || '-'}</p>
                      <p className="mt-1 text-xs text-outline">{log.moduleLabel || '-'}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium ${log.status === '成功' ? 'text-secondary' : 'text-error'}`}>
                        <span className="material-symbols-outlined text-[16px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                          {log.status === '成功' ? 'check_circle' : 'error'}
                        </span>
                        {log.status || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => setDetailAuditId(log.id)}
                        className="inline-flex h-7 items-center rounded-md px-2 text-xs font-semibold text-primary hover:bg-primary/10"
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-surface-container-high bg-surface-container-lowest px-4 py-3 text-sm text-outline">
            <span>显示 {items.length} 条，共 {data?.total || items.length} 条记录</span>
            <button
              type="button"
              onClick={() => loadData(queryFilters, { silent: true })}
              className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-primary hover:bg-primary/10"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              刷新
            </button>
          </div>
        </div>
      )}

      {detailAuditId && (
        <AuditDetailModal
          auditId={detailAuditId}
          onClose={() => setDetailAuditId('')}
        />
      )}
    </div>
  )
}
