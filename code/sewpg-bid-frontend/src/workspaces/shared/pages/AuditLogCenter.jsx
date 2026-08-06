import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  businessAuditAPI,
  businessEventsAPI,
  technicalAuditAPI,
  technicalEventsAPI,
} from '../../../api'
import AuditDetailModal from '../../../components/modals/AuditDetailModal'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import { bidTypeFromWorkspace, useWorkspaceSlug } from '../../../utils/workspace'

const PAGE_SIZE = 20

const defaultAuditFilters = {
  user: '',
  module: '',
  action: '',
  status: '',
  startDate: '',
  endDate: '',
  keyword: '',
}

const defaultEventFilters = {
  eventType: '',
  user: '',
  sessionId: '',
  startDate: '',
  endDate: '',
  keyword: '',
}

const defaultSessionFilters = {
  user: '',
  startDate: '',
  endDate: '',
}

const actionColors = {
  generate: 'bg-primary-fixed text-primary',
  update: 'bg-secondary-container text-on-secondary-container',
  delete: 'bg-error-container text-on-error-container',
  auth: 'bg-surface-container-high text-on-surface-variant',
  config: 'bg-tertiary-fixed text-on-tertiary-fixed',
  import: 'bg-primary/10 text-primary',
}

// 事件类型徽章：错误红色、API 蓝色、点击灰色、导航紫色
const eventTypeMeta = {
  click: { label: '点击', className: 'bg-surface-container-high text-on-surface-variant' },
  route: { label: '导航', className: 'bg-tertiary-fixed text-on-tertiary-fixed' },
  api: { label: 'API', className: 'bg-primary/10 text-primary' },
  error: { label: '错误', className: 'bg-error-container text-on-error-container' },
}

const eventStatusMeta = {
  success: { label: '成功', className: 'bg-secondary-container text-on-secondary-container' },
  error: { label: '失败', className: 'bg-error-container text-on-error-container' },
  info: { label: '信息', className: 'bg-surface-container-high text-on-surface-variant' },
}

const filterLabelClass = 'mb-1.5 block text-xs font-semibold text-outline'
const filterControlClass =
  'h-9 w-full rounded-md border border-transparent bg-surface-container-low px-3 text-sm text-on-surface transition-colors focus:border-primary/30 focus:bg-white focus:outline-none focus:ring-2 focus:ring-primary/10'
const cardClass =
  'rounded-xl border border-outline-variant/50 bg-white shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]'

const safeMessage = (error, fallback) => error?.payload?.detail || error?.message || fallback

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

const pad = (value, length = 2) => String(value).padStart(length, '0')

const formatDateTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

const formatClock = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`
}

const truncateText = (value, max = 60) => {
  const text = String(value ?? '')
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function EventTypeBadge({ type }) {
  const meta = eventTypeMeta[type] || { label: type || '-', className: 'bg-surface-container-high text-on-surface-variant' }
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${meta.className}`}>
      {meta.label}
    </span>
  )
}

function EventStatusBadge({ status }) {
  const meta = eventStatusMeta[status] || { label: status || '-', className: 'bg-surface-container-high text-on-surface-variant' }
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${meta.className}`}>
      {meta.label}
    </span>
  )
}

function Pagination({ page, total, onChange }) {
  const totalPages = Math.max(1, Math.ceil((total || 0) / PAGE_SIZE))
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-outline">
        第 {page} / {totalPages} 页 · 共 {total || 0} 条
      </span>
      <button
        type="button"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        className="inline-flex h-8 items-center rounded-md px-2 text-xs font-semibold text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-40"
      >
        上一页
      </button>
      <button
        type="button"
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages}
        className="inline-flex h-8 items-center rounded-md px-2 text-xs font-semibold text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-40"
      >
        下一页
      </button>
    </div>
  )
}

function ModeTab({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`h-8 rounded-md px-3 text-sm font-medium transition-colors ${
        active ? 'bg-white text-primary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'
      }`}
    >
      {children}
    </button>
  )
}

// ===== 审计概览：平移原技术标审计日志页功能，并补充分页 =====
// 注：审计 list 接口一次性返回筛选后的全部 items（total 为筛选后总数），分页在前端切片完成
function AuditOverview({ auditAPI, lockedBidType, showToast }) {
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const [queryFilters, setQueryFilters] = useState(defaultAuditFilters)
  const [draftFilters, setDraftFilters] = useState(defaultAuditFilters)
  const [detailAuditId, setDetailAuditId] = useState('')
  const [exporting, setExporting] = useState(false)
  const [page, setPage] = useState(1)

  const loadData = useCallback(
    async (filters, options = {}) => {
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
    },
    [auditAPI, lockedBidType, showToast],
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData(queryFilters)
    }, 0)
    return () => clearTimeout(timer)
  }, [queryFilters, loadData])

  const items = data?.items || []
  const total = data?.total ?? items.length
  const pagedItems = useMemo(
    () => (data?.items || []).slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [data, page],
  )
  const filterOptions = data?.filterOptions || { users: [], modules: [], actions: [], statuses: [] }

  const hasActiveFilters = useMemo(
    () => Object.values(queryFilters).some((value) => String(value || '').trim()),
    [queryFilters],
  )

  const handleApplyFilters = () => {
    setPage(1)
    setQueryFilters({ ...draftFilters })
    showToast('筛选条件已应用')
  }

  const handleResetFilters = () => {
    setPage(1)
    setDraftFilters(defaultAuditFilters)
    setQueryFilters(defaultAuditFilters)
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
    return <PageError title="日志加载失败" description={error} onRetry={() => loadData(queryFilters)} />
  }

  return (
    <>
      <div className={`${cardClass} p-4`}>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-on-surface-variant">
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
              {total} 条
            </span>
            {(refreshing || error) && (
              <span className={`text-xs ${error ? 'text-error' : 'text-outline'}`}>
                {error || '正在刷新数据...'}
              </span>
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
        <div className={`${cardClass} overflow-hidden`}>
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
                {pagedItems.map((log) => (
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
            <Pagination page={page} total={total} onChange={setPage} />
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
          loadDetail={auditAPI.detail}
          onClose={() => setDetailAuditId('')}
        />
      )}
    </>
  )
}

// ===== 行为流 - 事件列表 =====
function EventList({ eventsAPI, showToast }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const [queryFilters, setQueryFilters] = useState(defaultEventFilters)
  const [draftFilters, setDraftFilters] = useState(defaultEventFilters)
  const [page, setPage] = useState(1)
  const [metaEvent, setMetaEvent] = useState(null)

  const loadData = useCallback(
    async (filters, nextPage) => {
      setLoading(true)
      setError('')
      try {
        const response = await eventsAPI.list({ ...filters, page: nextPage, pageSize: PAGE_SIZE })
        setData(response)
      } catch (e) {
        console.error(e)
        setError(safeMessage(e, '事件加载失败，请稍后重试。'))
      } finally {
        setLoading(false)
      }
    },
    [eventsAPI],
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData(queryFilters, page)
    }, 0)
    return () => clearTimeout(timer)
  }, [queryFilters, page, loadData])

  const items = data?.items || []
  const total = data?.total ?? items.length

  const handleApplyFilters = () => {
    setPage(1)
    setQueryFilters({ ...draftFilters })
    showToast('筛选条件已应用')
  }

  const handleResetFilters = () => {
    setPage(1)
    setDraftFilters(defaultEventFilters)
    setQueryFilters(defaultEventFilters)
    showToast('筛选已重置')
  }

  const renderResult = (event) => {
    if (event.eventType === 'api') {
      const httpStatus = event.meta?.httpStatus
      return (
        <div className="text-xs">
          <p className="font-mono text-on-surface">{truncateText(event.target, 48)}</p>
          <p className={`mt-1 ${event.status === 'error' ? 'text-error' : 'text-outline'}`}>
            {httpStatus ? `HTTP ${httpStatus}` : '网络错误'}
            {Number.isFinite(event.durationMs) ? ` · ${event.durationMs}ms` : ''}
          </p>
        </div>
      )
    }
    if (event.eventType === 'error') {
      return <span className="text-xs text-error">{truncateText(event.target, 48)}</span>
    }
    return <EventStatusBadge status={event.status} />
  }

  return (
    <>
      <div className={`${cardClass} p-4`}>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[repeat(3,minmax(8rem,1fr))_minmax(16rem,1.4fr)]">
          <div>
            <label className={filterLabelClass}>事件类型</label>
            <select
              value={draftFilters.eventType}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, eventType: event.target.value }))}
              className={`${filterControlClass} cursor-pointer`}
            >
              <option value="">全部类型</option>
              {Object.entries(eventTypeMeta).map(([value, meta]) => (
                <option key={value} value={value}>{meta.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className={filterLabelClass}>用户</label>
            <input
              value={draftFilters.user}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, user: event.target.value }))}
              placeholder="用户名"
              className={filterControlClass}
            />
          </div>

          <div>
            <label className={filterLabelClass}>会话 ID</label>
            <input
              value={draftFilters.sessionId}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, sessionId: event.target.value }))}
              placeholder="sessionId"
              className={filterControlClass}
            />
          </div>

          <div>
            <label className={filterLabelClass}>关键字</label>
            <input
              value={draftFilters.keyword}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, keyword: event.target.value }))}
              placeholder="搜索路由、目标"
              className={filterControlClass}
            />
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

      {loading && !data ? (
        <PageLoading title="正在加载事件..." description="正在同步用户行为事件。" />
      ) : error && !data ? (
        <PageError title="事件加载失败" description={error} onRetry={() => loadData(queryFilters, page)} />
      ) : !items.length ? (
        <PageEmpty title="暂无事件" description="当前筛选条件下暂无可展示的行为事件。" />
      ) : (
        <div className={`${cardClass} overflow-hidden`}>
          <div className="max-h-[calc(100vh-22rem)] min-h-[420px] overflow-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="sticky top-0 z-[1]">
                <tr className="border-b border-surface-container-high bg-surface-container-lowest/95 backdrop-blur">
                  {['时间', '用户', '类型', '页面路由', '动作目标', '结果', '操作'].map((header) => (
                    <th key={header} className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((event) => (
                  <tr
                    key={event.id}
                    className={`border-b border-surface-container-high/60 transition-colors hover:bg-surface-container-lowest ${
                      event.status === 'error' || event.eventType === 'error' ? 'bg-error-container/10' : ''
                    }`}
                  >
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-on-surface-variant">
                      {formatDateTime(event.clientTs)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-on-surface font-medium">
                      {event.userName || event.userId || '-'}
                    </td>
                    <td className="px-4 py-3">
                      <EventTypeBadge type={event.eventType} />
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-on-surface-variant" title={event.route}>
                        {truncateText(event.route, 32) || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="block max-w-[20rem] truncate text-on-surface" title={event.target}>
                        {event.target || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">{renderResult(event)}</td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => setMetaEvent(event)}
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
            <Pagination page={page} total={total} onChange={setPage} />
            <button
              type="button"
              onClick={() => loadData(queryFilters, page)}
              className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-primary hover:bg-primary/10"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              刷新
            </button>
          </div>
        </div>
      )}

      {metaEvent && (
        <AuditDetailModal
          auditId={metaEvent.id || '事件'}
          loadDetail={() =>
            Promise.resolve({
              time: formatDateTime(metaEvent.clientTs),
              user: metaEvent.userName || metaEvent.userId || '-',
              action: eventTypeMeta[metaEvent.eventType]?.label || metaEvent.eventType,
              target: metaEvent.target || metaEvent.route || '-',
              meta: metaEvent.meta || {},
            })
          }
          onClose={() => setMetaEvent(null)}
        />
      )}
    </>
  )
}

// ===== 行为流 - 会话列表 =====
function SessionList({ eventsAPI, showToast, onReplay }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const [queryFilters, setQueryFilters] = useState(defaultSessionFilters)
  const [draftFilters, setDraftFilters] = useState(defaultSessionFilters)
  const [page, setPage] = useState(1)

  const loadData = useCallback(
    async (filters, nextPage) => {
      setLoading(true)
      setError('')
      try {
        const response = await eventsAPI.sessions({ ...filters, page: nextPage, pageSize: PAGE_SIZE })
        setData(response)
      } catch (e) {
        console.error(e)
        setError(safeMessage(e, '会话加载失败，请稍后重试。'))
      } finally {
        setLoading(false)
      }
    },
    [eventsAPI],
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData(queryFilters, page)
    }, 0)
    return () => clearTimeout(timer)
  }, [queryFilters, page, loadData])

  const items = data?.items || []
  const total = data?.total ?? items.length

  const handleApplyFilters = () => {
    setPage(1)
    setQueryFilters({ ...draftFilters })
    showToast('筛选条件已应用')
  }

  const handleResetFilters = () => {
    setPage(1)
    setDraftFilters(defaultSessionFilters)
    setQueryFilters(defaultSessionFilters)
    showToast('筛选已重置')
  }

  return (
    <>
      <div className={`${cardClass} p-4`}>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(20rem,1.4fr)_auto] lg:items-end">
          <div>
            <label className={filterLabelClass}>用户</label>
            <input
              value={draftFilters.user}
              onChange={(event) => setDraftFilters((prev) => ({ ...prev, user: event.target.value }))}
              placeholder="用户名"
              className={filterControlClass}
            />
          </div>

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

      {loading && !data ? (
        <PageLoading title="正在加载会话..." description="正在汇总用户行为会话。" />
      ) : error && !data ? (
        <PageError title="会话加载失败" description={error} onRetry={() => loadData(queryFilters, page)} />
      ) : !items.length ? (
        <PageEmpty title="暂无会话" description="当前筛选条件下暂无可回放的行为会话。" />
      ) : (
        <div className={`${cardClass} overflow-hidden`}>
          <div className="max-h-[calc(100vh-22rem)] min-h-[420px] overflow-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead className="sticky top-0 z-[1]">
                <tr className="border-b border-surface-container-high bg-surface-container-lowest/95 backdrop-blur">
                  {['会话 ID', '用户', '开始时间', '结束时间', '事件数', '错误数', '操作'].map((header) => (
                    <th key={header} className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((session) => (
                  <tr key={session.sessionId} className="border-b border-surface-container-high/60 transition-colors hover:bg-surface-container-lowest">
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-on-surface" title={session.sessionId}>
                        {truncateText(session.sessionId, 20)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-on-surface font-medium">
                      {session.userName || session.userId || '-'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-on-surface-variant">
                      {formatDateTime(session.startTs)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-on-surface-variant">
                      {formatDateTime(session.endTs)}
                    </td>
                    <td className="px-4 py-3 text-on-surface">{session.eventCount ?? 0}</td>
                    <td className="px-4 py-3">
                      <span className={session.errorCount ? 'font-semibold text-error' : 'text-on-surface-variant'}>
                        {session.errorCount ?? 0}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => onReplay(session.sessionId)}
                        className="inline-flex h-7 items-center rounded-md px-2 text-xs font-semibold text-primary hover:bg-primary/10"
                      >
                        回放
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-surface-container-high bg-surface-container-lowest px-4 py-3 text-sm text-outline">
            <Pagination page={page} total={total} onChange={setPage} />
            <button
              type="button"
              onClick={() => loadData(queryFilters, page)}
              className="inline-flex h-8 items-center gap-1 rounded-md px-2 text-primary hover:bg-primary/10"
            >
              <span className="material-symbols-outlined text-[16px]">refresh</span>
              刷新
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ===== 行为流 - 会话回放时间线 =====
const describeEvent = (event) => {
  if (event.eventType === 'click') return `点击了「${event.target || event.element || '-'}」`
  if (event.eventType === 'route') return `跳转 ${event.target || event.route || '-'}`
  if (event.eventType === 'api') {
    const httpStatus = event.meta?.httpStatus
    const statusText = httpStatus ? `HTTP ${httpStatus}` : '网络错误'
    const duration = Number.isFinite(event.durationMs) ? ` · ${event.durationMs}ms` : ''
    return `${event.target || ''} ${statusText}${duration}`
  }
  if (event.eventType === 'error') return `错误: ${event.target || '-'}`
  return event.target || '-'
}

function SessionTimeline({ eventsAPI, sessionId, onBack }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [items, setItems] = useState([])

  useEffect(() => {
    let mounted = true
    const timer = setTimeout(() => {
      setLoading(true)
      setError('')
      eventsAPI
        .sessionTimeline(sessionId)
        .then((response) => {
          if (mounted) setItems(response?.items || [])
        })
        .catch((e) => {
          console.error(e)
          if (mounted) setError(safeMessage(e, '会话时间线加载失败，请稍后重试。'))
        })
        .finally(() => {
          if (mounted) setLoading(false)
        })
    }, 0)
    return () => {
      mounted = false
      clearTimeout(timer)
    }
  }, [eventsAPI, sessionId])

  const userName = items[0]?.userName || items[0]?.userId || '-'
  const errorCount = items.filter((item) => item.status === 'error' || item.eventType === 'error').length

  if (loading) {
    return <PageLoading title="正在加载会话回放..." description="正在还原该会话的操作时间线。" />
  }

  if (error) {
    return <PageError title="会话回放加载失败" description={error} onRetry={onBack} />
  }

  return (
    <div className={`${cardClass} overflow-hidden`}>
      <div className="flex flex-col gap-2 border-b border-surface-container-high px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span aria-hidden="true" className="h-5 w-1 rounded-full bg-primary" />
            <h2 className="text-base font-headline font-bold text-on-surface">会话回放</h2>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
              {items.length} 个事件
            </span>
            {errorCount > 0 && (
              <span className="rounded-full bg-error-container px-2 py-0.5 text-xs font-semibold text-on-error-container">
                {errorCount} 个错误
              </span>
            )}
          </div>
          <p className="mt-1 truncate font-mono text-xs text-outline" title={sessionId}>
            {sessionId} · {userName}
          </p>
        </div>
        <button
          type="button"
          onClick={onBack}
          className="command-button command-button-secondary h-9 min-h-9 whitespace-nowrap px-4 text-sm"
        >
          <span className="material-symbols-outlined text-[17px]">arrow_back</span>
          返回会话列表
        </button>
      </div>

      <div className="max-h-[calc(100vh-20rem)] min-h-[420px] overflow-auto px-5 py-4">
        {!items.length ? (
          <p className="py-8 text-center text-sm text-outline">该会话暂无事件记录。</p>
        ) : (
          <ol className="relative ml-3 border-l-2 border-surface-container-high">
            {items.map((event, index) => {
              const isError = event.status === 'error' || event.eventType === 'error'
              return (
                <li key={event.id || index} className="relative pb-5 pl-6 last:pb-1">
                  <span
                    className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full border-2 border-white ${
                      isError ? 'bg-error' : 'bg-primary'
                    }`}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-on-surface-variant">
                      {formatClock(event.clientTs)}
                    </span>
                    <EventTypeBadge type={event.eventType} />
                    <span className="font-mono text-xs text-outline" title={event.route}>
                      {truncateText(event.route, 40)}
                    </span>
                  </div>
                  <p className={`mt-1 text-sm ${isError ? 'font-medium text-error' : 'text-on-surface'}`}>
                    {describeEvent(event)}
                  </p>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </div>
  )
}

// ===== 行为流：事件列表 / 会话回放 =====
function BehaviorFlow({ eventsAPI, showToast }) {
  const [view, setView] = useState('events')
  const [replaySessionId, setReplaySessionId] = useState('')

  if (replaySessionId) {
    return (
      <SessionTimeline
        eventsAPI={eventsAPI}
        sessionId={replaySessionId}
        onBack={() => setReplaySessionId('')}
      />
    )
  }

  return (
    <>
      <div className="flex items-center gap-2">
        <div className="inline-flex rounded-lg bg-surface-container-low p-1">
          <ModeTab active={view === 'events'} onClick={() => setView('events')}>
            事件列表
          </ModeTab>
          <ModeTab active={view === 'sessions'} onClick={() => setView('sessions')}>
            会话回放
          </ModeTab>
        </div>
      </div>
      {view === 'events' ? (
        <EventList eventsAPI={eventsAPI} showToast={showToast} />
      ) : (
        <SessionList eventsAPI={eventsAPI} showToast={showToast} onReplay={setReplaySessionId} />
      )}
    </>
  )
}

export default function AuditLogCenter({ showToast = () => {} }) {
  const workspaceSlug = useWorkspaceSlug()
  const lockedBidType = bidTypeFromWorkspace(workspaceSlug)
  const isBusiness = workspaceSlug === 'business'
  const auditAPI = isBusiness ? businessAuditAPI : technicalAuditAPI
  const eventsAPI = isBusiness ? businessEventsAPI : technicalEventsAPI
  const [mode, setMode] = useState('audit')

  return (
    <div className="flex flex-col gap-3 animate-fade-in">
      <div className="overflow-hidden rounded-xl border border-outline-variant/55 bg-white shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="h-5 w-1 rounded-full bg-primary" />
              <h1 className="text-xl font-headline font-bold text-on-surface">
                {lockedBidType ? `${lockedBidType}日志` : '日志'}
              </h1>
            </div>
            <p className="mt-1 text-sm text-on-surface-variant">
              {mode === 'audit'
                ? '支持筛选、diff 查看与 CSV 导出，满足联调追踪需求。'
                : '按事件与会话维度还原用户操作行为，辅助问题定位。'}
            </p>
          </div>
          <div className="inline-flex self-start rounded-lg bg-surface-container-low p-1 lg:self-auto">
            <ModeTab active={mode === 'audit'} onClick={() => setMode('audit')}>
              审计概览
            </ModeTab>
            <ModeTab active={mode === 'events'} onClick={() => setMode('events')}>
              行为流
            </ModeTab>
          </div>
        </div>
      </div>

      {mode === 'audit' ? (
        <AuditOverview auditAPI={auditAPI} lockedBidType={lockedBidType} showToast={showToast} />
      ) : (
        <BehaviorFlow eventsAPI={eventsAPI} showToast={showToast} />
      )}
    </div>
  )
}
