import { useCallback, useEffect, useRef, useState } from 'react'
import { monitoringAPI } from '../api'
import StatusBadge from '../components/shared/StatusBadge'
import EmptyState from '../components/shared/EmptyState'
import Skeleton from '../components/shared/Skeleton'

const POLL_INTERVAL_MS = 15_000
const LIST_LIMIT = 50
const SUMMARY_DAYS = 7

const JOB_TYPE_LABELS = {
  s1_parse: '招标文件解析',
  s1_parse_continue: '解析续跑',
  docling_batch: 'PDF 预处理',
  directory_generation: '目录生成',
}

const STATUS_META = {
  succeeded: { variant: 'done', label: '成功' },
  failed: { variant: 'error', label: '失败' },
  cancelled: { variant: 'pending', label: '已取消' },
  running: { variant: 'running', label: '运行中' },
}

const METRIC_TONE = {
  primary: 'from-primary-fixed to-primary-fixed-dim text-on-primary-fixed-variant',
  success: 'from-secondary-fixed to-secondary-fixed-dim text-on-secondary-fixed-variant',
  warn: 'from-tertiary-fixed to-tertiary-fixed-dim text-on-tertiary-fixed-variant',
  info: 'from-ai-accent-light to-tertiary-fixed text-on-tertiary-container',
}

const jobTypeLabel = (jobType) => JOB_TYPE_LABELS[jobType] || jobType || '未知类型'

const formatDuration = (ms) => {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—'
  const totalSeconds = Math.round(ms / 1000)
  if (totalSeconds < 60) return `${totalSeconds} 秒`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes} 分 ${seconds} 秒`
}

const formatTime = (iso) => {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

// 把 byType 里匹配 predicate 的多行聚合成一组指标（按任务数加权）
const aggregateTypes = (rows, predicate) => {
  const matched = (rows || []).filter((row) => predicate(row.jobType))
  const count = matched.reduce((sum, row) => sum + (row.count || 0), 0)
  if (!count) return null
  const successCount = matched.reduce((sum, row) => sum + (row.successCount || 0), 0)
  const weightedAvg = (key) =>
    matched.reduce((sum, row) => sum + (row[key] || 0) * (row.count || 0), 0) / count
  return {
    count,
    successRate: successCount / count,
    avgDurationMs: weightedAvg('avgDurationMs'),
    p95DurationMs: Math.max(...matched.map((row) => row.p95DurationMs || 0)),
    avgQueueWaitMs: weightedAvg('avgQueueWaitMs'),
  }
}

const buildCards = (agg) => [
  { key: 'avg', label: '平均耗时', value: agg ? formatDuration(agg.avgDurationMs) : '—', icon: 'schedule', tone: 'primary' },
  { key: 'p95', label: 'P95 耗时', value: agg ? formatDuration(agg.p95DurationMs) : '—', icon: 'speed', tone: 'warn' },
  { key: 'rate', label: '成功率', value: agg ? `${(agg.successRate * 100).toFixed(1)}%` : '—', icon: 'task_alt', tone: 'success' },
  { key: 'queue', label: '平均排队', value: agg ? formatDuration(agg.avgQueueWaitMs) : '—', icon: 'hourglass_empty', tone: 'info' },
]

function MetricCard({ metric }) {
  const tone = METRIC_TONE[metric.tone] || METRIC_TONE.primary
  return (
    <div className={`relative overflow-hidden rounded-xl bg-gradient-to-br ${tone} p-4 animate-count-up`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="text-xs font-medium opacity-80">{metric.label}</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-headline font-bold tabular-nums">{metric.value}</span>
          </div>
        </div>
        <span
          className="material-symbols-outlined text-[26px] opacity-70"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {metric.icon}
        </span>
      </div>
    </div>
  )
}

function SectionHeader({ icon, title, hint }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <span
          className="material-symbols-outlined text-[20px] text-primary"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {icon}
        </span>
        <h2 className="text-base font-headline font-semibold text-on-surface">{title}</h2>
        {hint && <span className="text-xs text-outline">{hint}</span>}
      </div>
    </div>
  )
}

function PhaseRanking({ phases }) {
  const maxDuration = Math.max(...phases.map((p) => p.avgDurationMs || 0), 1)
  return (
    <div className="rounded-xl border border-outline-variant/40 bg-white p-4 space-y-2.5">
      {phases.map((phase, index) => {
        const widthPct = Math.max(((phase.avgDurationMs || 0) / maxDuration) * 100, 2)
        return (
          <div key={`${phase.jobType}-${phase.step}-${index}`} className="space-y-1">
            <div className="flex items-center justify-between text-xs gap-2">
              <span className="text-on-surface truncate">
                <span className="text-outline">{jobTypeLabel(phase.jobType)} · </span>
                {phase.label || phase.step}
              </span>
              <span className="shrink-0 font-mono text-on-surface-variant tabular-nums">
                平均 {formatDuration(phase.avgDurationMs)}
                <span className="text-outline"> / 最长 {formatDuration(phase.maxDurationMs)} / {phase.count || 0} 次</span>
              </span>
            </div>
            <div className="h-2 w-full bg-surface-container-high rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-primary to-primary-container transition-all duration-700"
                style={{ width: `${widthPct}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PhaseWaterfall({ phases }) {
  const sorted = [...phases].sort(
    (a, b) => new Date(a.startedAt || 0).getTime() - new Date(b.startedAt || 0).getTime(),
  )
  const starts = sorted.map((p) => new Date(p.startedAt || 0).getTime())
  const firstStart = Math.min(...starts)
  const lastEnd = Math.max(...sorted.map((p, i) => starts[i] + (p.durationMs || 0)))
  const span = Math.max(lastEnd - firstStart, 1)
  return (
    <div className="space-y-1.5">
      {sorted.map((phase, index) => {
        const offsetMs = new Date(phase.startedAt || 0).getTime() - firstStart
        const leftPct = Math.min((offsetMs / span) * 100, 99)
        const widthPct = Math.max(((phase.durationMs || 0) / span) * 100, 1.5)
        return (
          <div key={`${phase.step}-${index}`} className="flex items-center gap-2 text-xs">
            <span className="w-40 shrink-0 truncate text-on-surface">{phase.label || phase.step}</span>
            <div className="relative h-4 flex-1 bg-surface-container-high rounded-full overflow-hidden">
              <div
                className="absolute top-0 h-full bg-gradient-to-r from-primary to-primary-container rounded-full"
                style={{ left: `${leftPct}%`, width: `${Math.min(widthPct, 100 - leftPct)}%` }}
              />
            </div>
            <span className="w-20 shrink-0 text-right font-mono text-on-surface-variant tabular-nums">
              {formatDuration(phase.durationMs)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function JobRow({ item, expanded, detailState, onToggle }) {
  const status = STATUS_META[item.status] || { variant: 'pending', label: item.status || '未知' }
  const phases = (Array.isArray(item.phases) && item.phases.length > 0 && item.phases)
    || detailState?.data?.phases
    || []
  return (
    <div className="border-b border-surface-container-high last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        className="w-full grid grid-cols-[minmax(6rem,8rem)_1fr_minmax(4.5rem,6rem)_minmax(4.5rem,6rem)_minmax(4.5rem,6rem)_minmax(7rem,9rem)] items-center gap-2 px-4 py-2.5 text-left text-xs hover:bg-surface-container-low transition-colors"
      >
        <span className="text-on-surface">{jobTypeLabel(item.jobType)}</span>
        <span className="truncate text-on-surface">{item.projectName || item.projectId || '—'}</span>
        <span>
          <StatusBadge variant={status.variant} icon={null}>{status.label}</StatusBadge>
        </span>
        <span className="font-mono text-on-surface-variant tabular-nums">{formatDuration(item.queueWaitMs)}</span>
        <span className="font-mono text-on-surface-variant tabular-nums">{formatDuration(item.durationMs)}</span>
        <span className="font-mono text-outline tabular-nums">{formatTime(item.startedAt || item.queuedAt)}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-3 pt-1 bg-surface-container-low/50 space-y-2 animate-fade-in">
          {item.status === 'failed' && item.errorMessage && (
            <div className="rounded-lg bg-error-container/50 px-3 py-2 text-xs text-error break-all">
              {item.errorMessage}
            </div>
          )}
          {phases.length > 0 ? (
            <PhaseWaterfall phases={phases} />
          ) : detailState?.loading ? (
            <Skeleton className="h-12 w-full" />
          ) : detailState?.error ? (
            <div className="text-xs text-error">{detailState.error}</div>
          ) : (
            <div className="text-xs text-outline">暂无阶段耗时数据</div>
          )}
        </div>
      )}
    </div>
  )
}

export default function JobMonitor() {
  const [jobType, setJobType] = useState('')
  const [status, setStatus] = useState('')
  const [summary, setSummary] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedId, setExpandedId] = useState(null)
  const [details, setDetails] = useState({})
  const mountedRef = useRef(true)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [summaryPayload, listPayload] = await Promise.all([
        monitoringAPI.jobTimingSummary(SUMMARY_DAYS),
        monitoringAPI.listJobTimings({ jobType, status, days: SUMMARY_DAYS, limit: LIST_LIMIT }),
      ])
      if (!mountedRef.current) return
      setSummary(summaryPayload)
      setItems(listPayload?.items || [])
      setError(null)
    } catch (err) {
      if (!mountedRef.current) return
      setError(err?.message || '加载失败')
    } finally {
      if (mountedRef.current && !silent) setLoading(false)
    }
  }, [jobType, status])

  useEffect(() => {
    mountedRef.current = true
    load()
    const timer = window.setInterval(() => load(true), POLL_INTERVAL_MS)
    return () => {
      mountedRef.current = false
      window.clearInterval(timer)
    }
  }, [load])

  const toggleRow = (item) => {
    const id = item.id
    if (expandedId === id) {
      setExpandedId(null)
      return
    }
    setExpandedId(id)
    const hasPhases = Array.isArray(item.phases) && item.phases.length > 0
    if (hasPhases || details[id]?.loading || details[id]?.data) return
    setDetails((prev) => ({ ...prev, [id]: { loading: true } }))
    monitoringAPI
      .jobTimingDetail(id)
      .then((data) => {
        if (!mountedRef.current) return
        setDetails((prev) => ({ ...prev, [id]: { loading: false, data } }))
      })
      .catch((err) => {
        if (!mountedRef.current) return
        setDetails((prev) => ({ ...prev, [id]: { loading: false, error: err?.message || '阶段详情加载失败' } }))
      })
  }

  if (loading && !summary && items.length === 0) {
    return (
      <div className="px-7 md:px-10 lg:px-12 xl:px-14 py-6 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (error && !summary && items.length === 0) {
    return (
      <div className="px-7 md:px-10 lg:px-12 xl:px-14 py-6">
        <EmptyState
          icon="error"
          title="耗时监控加载失败"
          description={error}
          action={
            <button
              type="button"
              onClick={() => load()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-container hover:text-on-primary-container transition-colors"
            >
              重新加载
            </button>
          }
        />
      </div>
    )
  }

  const byType = summary?.byType || []
  const parseAgg = aggregateTypes(byType, (t) => t === 's1_parse' || t === 's1_parse_continue')
  const directoryAgg = aggregateTypes(byType, (t) => t === 'directory_generation')
  const phaseRanking = [...(summary?.byPhase || [])].sort(
    (a, b) => (b.avgDurationMs || 0) - (a.avgDurationMs || 0),
  )

  const metricGroups = [
    { key: 'parse', title: '招标文件解析', icon: 'document_scanner', agg: parseAgg },
    { key: 'directory', title: '目录生成', icon: 'account_tree', agg: directoryAgg },
  ]

  return (
    <div className="px-7 md:px-10 lg:px-12 xl:px-14 py-6 space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-[22px] font-headline font-bold text-on-surface tracking-tight">耗时监控</h1>
          <span className="text-xs text-outline">近 {summary?.days || SUMMARY_DAYS} 天</span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={jobType}
            onChange={(event) => setJobType(event.target.value)}
            className="rounded-lg border border-outline-variant/60 bg-white px-3 py-1.5 text-sm text-on-surface"
          >
            <option value="">全部类型</option>
            <option value="s1_parse">招标文件解析</option>
            <option value="directory_generation">目录生成</option>
          </select>
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="rounded-lg border border-outline-variant/60 bg-white px-3 py-1.5 text-sm text-on-surface"
          >
            <option value="">全部状态</option>
            <option value="succeeded">成功</option>
            <option value="failed">失败</option>
            <option value="cancelled">已取消</option>
            <option value="running">运行中</option>
          </select>
          <button
            type="button"
            onClick={() => load()}
            className="inline-flex items-center gap-1 rounded-lg border border-outline-variant/60 bg-white px-3 py-1.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">refresh</span>
            刷新
          </button>
        </div>
      </div>

      {metricGroups.map((group) => (
        <section key={group.key}>
          <SectionHeader
            icon={group.icon}
            title={group.title}
            hint={group.agg ? `${group.agg.count} 次任务` : '暂无数据'}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 stagger">
            {buildCards(group.agg).map((metric) => (
              <MetricCard key={metric.key} metric={metric} />
            ))}
          </div>
        </section>
      ))}

      <section>
        <SectionHeader icon="bar_chart" title="阶段耗时榜" hint="按平均耗时排序" />
        {phaseRanking.length === 0 ? (
          <EmptyState icon="bar_chart" title="暂无阶段耗时数据" className="rounded-xl border border-outline-variant/40 bg-white" />
        ) : (
          <PhaseRanking phases={phaseRanking} />
        )}
      </section>

      <section>
        <SectionHeader icon="list_alt" title="最近任务" hint={`最近 ${LIST_LIMIT} 条，点击行展开阶段瀑布`} />
        <div className="rounded-xl border border-outline-variant/40 bg-white overflow-hidden">
          <div className="grid grid-cols-[minmax(6rem,8rem)_1fr_minmax(4.5rem,6rem)_minmax(4.5rem,6rem)_minmax(4.5rem,6rem)_minmax(7rem,9rem)] gap-2 px-4 py-2 text-xs font-semibold text-on-surface-variant bg-surface-container-low border-b border-surface-container-high">
            <span>类型</span>
            <span>项目</span>
            <span>状态</span>
            <span>排队耗时</span>
            <span>总耗时</span>
            <span>开始时间</span>
          </div>
          {items.length === 0 ? (
            <EmptyState icon="inbox" title="暂无任务记录" className="py-8" />
          ) : (
            items.map((item) => (
              <JobRow
                key={item.id}
                item={item}
                expanded={expandedId === item.id}
                detailState={details[item.id]}
                onToggle={() => toggleRow(item)}
              />
            ))
          )}
        </div>
      </section>
    </div>
  )
}
