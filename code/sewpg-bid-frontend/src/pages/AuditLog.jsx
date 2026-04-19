import { useCallback, useEffect, useMemo, useState } from 'react'
import { auditAPI } from '../api'
import AuditDetailModal from '../components/modals/AuditDetailModal'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'

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
      const response = await auditAPI.list(filters)
      setData(response)
    } catch (e) {
      console.error(e)
      const message = safeMessage(e, '审计日志加载失败，请稍后重试。')
      setError(message)
      if (options.silent) showToast(message, 'error')
    } finally {
      if (options.silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [showToast])

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
      const payload = await auditAPI.exportCsv(queryFilters)
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
    return <PageLoading title="正在加载审计日志..." description="正在同步最新操作记录。" />
  }

  if (error && !data) {
    return (
      <PageError
        title="审计日志加载失败"
        description={error}
        onRetry={() => loadData(queryFilters)}
      />
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">审计日志</h1>
          <p className="text-sm text-on-surface-variant mt-1">支持筛选、diff 查看与 CSV 导出，满足联调与合规追踪需求。</p>
          {(refreshing || error) && (
            <p className={`text-xs mt-1 ${error ? 'text-error' : 'text-outline'}`}>
              {error || '正在刷新数据...'}
            </p>
          )}
        </div>
        <button
          onClick={handleExportCsv}
          disabled={exporting}
          className="px-4 py-2 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span className="material-symbols-outlined text-sm">download</span>
          {exporting ? '导出中...' : '导出 CSV'}
        </button>
      </div>

      <div className="bg-surface-container-low rounded-xl p-5 flex flex-wrap gap-4 items-end">
        <div className="flex-1 min-w-[220px]">
          <label className="block text-xs font-medium text-outline mb-1.5">关键字</label>
          <input
            value={draftFilters.keyword}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, keyword: event.target.value }))}
            placeholder="搜索用户、动作、目标"
            className="w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
          />
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="block text-xs font-medium text-outline mb-1.5">用户</label>
          <select
            value={draftFilters.user}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, user: event.target.value }))}
            className="w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 cursor-pointer"
          >
            <option value="">所有用户</option>
            {filterOptions.users.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="block text-xs font-medium text-outline mb-1.5">项目/模块</label>
          <select
            value={draftFilters.module}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, module: event.target.value }))}
            className="w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 cursor-pointer"
          >
            <option value="">所有模块</option>
            {filterOptions.modules.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[160px]">
          <label className="block text-xs font-medium text-outline mb-1.5">动作类型</label>
          <select
            value={draftFilters.action}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, action: event.target.value }))}
            className="w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 cursor-pointer"
          >
            <option value="">所有动作</option>
            {filterOptions.actions.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[140px]">
          <label className="block text-xs font-medium text-outline mb-1.5">状态</label>
          <select
            value={draftFilters.status}
            onChange={(event) => setDraftFilters((prev) => ({ ...prev, status: event.target.value }))}
            className="w-full h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0 cursor-pointer"
          >
            <option value="">全部状态</option>
            {filterOptions.statuses.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 min-w-[220px]">
          <label className="block text-xs font-medium text-outline mb-1.5">时间范围</label>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={draftFilters.startDate}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, startDate: event.target.value }))}
              className="flex-1 h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
            />
            <span className="text-outline">-</span>
            <input
              type="date"
              value={draftFilters.endDate}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, endDate: event.target.value }))}
              className="flex-1 h-10 px-3 bg-surface-container-highest border-none rounded-md text-sm focus:ring-0"
            />
          </div>
        </div>

        <div className="flex gap-2 ml-auto">
          <button
            onClick={handleResetFilters}
            className="h-10 px-4 bg-surface-container-highest text-on-surface text-sm rounded-md hover:bg-surface-dim transition-colors"
          >
            重置
          </button>
          <button
            onClick={handleApplyFilters}
            className="h-10 px-4 bg-primary text-on-primary text-sm rounded-md hover:bg-primary-container transition-colors flex items-center gap-1"
          >
            <span className="material-symbols-outlined text-sm">tune</span>
            应用筛选
          </button>
        </div>
      </div>

      {!items.length ? (
        <PageEmpty
          title={hasActiveFilters ? '筛选后暂无日志' : '暂无审计日志'}
          description={hasActiveFilters ? '请调整筛选条件后重试。' : '当前暂无可展示的审计记录。'}
          actionText={hasActiveFilters ? '清空筛选' : undefined}
          onAction={hasActiveFilters ? handleResetFilters : undefined}
        />
      ) : (
        <div className="bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-container-high bg-surface-container-low">
                  {['时间戳', '用户', '动作', '目标/模块', '状态', '操作'].map((header) => (
                    <th key={header} className="px-5 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((log) => (
                  <tr key={log.id} className="border-b border-surface-container-high/50 hover:bg-surface-container-low transition-colors">
                    <td className="px-5 py-4 text-on-surface-variant font-mono text-xs">{log.time || '-'}</td>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-primary-container text-on-primary flex items-center justify-center text-xs font-bold">{log.userAvatar || '人'}</div>
                        <span className="text-on-surface font-medium">{log.user || '-'}</span>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${actionColors[log.actionType] || 'bg-surface-container-high text-on-surface-variant'}`}>
                        {log.action || '-'}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <p className="text-on-surface">{log.target || '-'}</p>
                      <p className="text-xs text-outline mt-1">{log.moduleLabel || '-'}</p>
                    </td>
                    <td className="px-5 py-4">
                      <span className={`flex items-center gap-1 text-xs font-medium ${log.status === '成功' ? 'text-secondary' : 'text-error'}`}>
                        <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>
                          {log.status === '成功' ? 'check_circle' : 'error'}
                        </span>
                        {log.status || '-'}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <button
                        onClick={() => setDetailAuditId(log.id)}
                        className="text-primary text-xs hover:underline"
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-6 py-4 border-t border-surface-container-high flex items-center justify-between text-sm text-outline">
            <span>显示 {items.length} 条，共 {data?.total || items.length} 条记录</span>
            <button
              onClick={() => loadData(queryFilters, { silent: true })}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <span className="material-symbols-outlined text-sm">refresh</span>
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
