import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { businessParseAPI, technicalParseAPI } from '../../api'
import { clearParseRunning, readRunningParses } from '../../workspaces/shared/parseRunningMarker'

// 全局解析提示条：解析任务转入后台后，离开审核页也能看到进度；
// 任务结束时原地变成结果通知（完成/失败），用户点击跳回或手动关闭后才消失。
const BANNER_POLL_INTERVAL_MS = 5000
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'stale'])

const parseClientFor = (bidType) => (bidType === 'business' ? businessParseAPI : technicalParseAPI)
const parseRouteFor = (target) => (target.bidType === 'business'
  ? `/parse/business?projectId=${encodeURIComponent(target.projectId)}`
  : `/parse/technical?projectId=${encodeURIComponent(target.projectId)}`)
const bidTypeLabel = (bidType) => (bidType === 'business' ? '商务标' : '技术标')

export default function ParseRunningBanner() {
  const location = useLocation()
  const navigate = useNavigate()
  const [marker, setMarker] = useState(null)
  const [percentage, setPercentage] = useState(null)
  const [fileLabel, setFileLabel] = useState('')
  // result: { projectId, bidType, status: 'completed' | 'failed' | 'stale' }
  const [result, setResult] = useState(null)

  // 审核页自己有完整进度面板，/parse/ 路由下不重复提示
  const onParseRoute = location.pathname.startsWith('/parse/')

  useEffect(() => {
    if (onParseRoute) return undefined
    let stopped = false

    const refresh = async () => {
      const current = readRunningParses()[0] || null
      if (!current) {
        if (!stopped) {
          setMarker(null)
          setPercentage(null)
          setFileLabel('')
        }
        return
      }
      try {
        const progress = await parseClientFor(current.bidType).progress(current.projectId)
        const status = String(progress?.status || '').toLowerCase()
        if (TERMINAL_STATUSES.has(status)) {
          // 任务已结束：清除运行标记；取消视为用户主动操作，静默收起；
          // 完成/失败/中断保留结果通知，等用户点击查看或手动关闭。
          clearParseRunning(current.projectId, current.bidType)
          if (stopped) return
          setMarker(null)
          setPercentage(null)
          setFileLabel('')
          if (status !== 'cancelled') {
            setResult({ projectId: current.projectId, bidType: current.bidType, status })
          }
          return
        }
        if (stopped) return
        setResult(null)
        setMarker(current)
        const nextPercentage = Number(progress?.percentage)
        if (Number.isFinite(nextPercentage)) {
          setPercentage(Math.max(0, Math.min(100, Math.round(nextPercentage))))
        }
        // 目标文件名随进度下发，提醒用户当前在解析什么
        const names = Array.isArray(progress?.fileNames) ? progress.fileNames.filter(Boolean) : []
        setFileLabel(names.length ? (names.length > 1 ? `${names[0]} 等 ${names.length} 个` : names[0]) : '')
      } catch {
        // 进度查询失败时保持上次展示，静默等待下一轮
        if (!stopped) setMarker(current)
      }
    }

    refresh()
    const timer = setInterval(refresh, BANNER_POLL_INTERVAL_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [onParseRoute])

  if (onParseRoute) return null

  if (result) {
    const isSuccess = result.status === 'completed'
    const text = isSuccess
      ? `${bidTypeLabel(result.bidType)}解析完成 · 点击查看结果`
      : result.status === 'stale'
        ? `${bidTypeLabel(result.bidType)}解析可能中断 · 点击查看`
        : `${bidTypeLabel(result.bidType)}解析失败 · 点击查看`
    const dismiss = () => {
      setResult(null)
    }
    return (
      <div
        className={[
          'fixed bottom-20 right-4 z-40 inline-flex items-center gap-1 rounded-full border bg-white/95 py-1 pl-4 pr-1 text-xs font-semibold shadow-[0_8px_24px_-8px_rgba(13,33,55,0.35)] md:bottom-6 md:right-6',
          isSuccess ? 'border-primary/20 text-primary' : 'border-error/30 text-error',
        ].join(' ')}
      >
        <button
          type="button"
          onClick={() => {
            dismiss()
            navigate(parseRouteFor(result))
          }}
          className="inline-flex items-center gap-2 rounded-full py-1 transition-colors hover:opacity-80"
        >
          <span className="material-symbols-outlined text-[16px]">{isSuccess ? 'check_circle' : 'error'}</span>
          {text}
        </button>
        <button
          type="button"
          onClick={dismiss}
          aria-label="关闭通知"
          className="inline-flex h-6 w-6 items-center justify-center rounded-full text-outline transition-colors hover:bg-surface-container-high"
        >
          <span className="material-symbols-outlined text-[14px]">close</span>
        </button>
      </div>
    )
  }

  if (!marker) return null

  return (
    <button
      type="button"
      onClick={() => navigate(parseRouteFor(marker))}
      className="fixed bottom-20 right-4 z-40 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-white/95 px-4 py-2 text-xs font-semibold text-primary shadow-[0_8px_24px_-8px_rgba(13,33,55,0.35)] transition-colors hover:bg-primary/5 md:bottom-6 md:right-6"
    >
      <span className="material-symbols-outlined animate-spin text-[16px]">progress_activity</span>
      <span className="max-w-[220px] truncate">
        {`${bidTypeLabel(marker.bidType)}解析进行中${percentage == null ? '' : ` · ${percentage}%`}${fileLabel ? ` · ${fileLabel}` : ''}`}
      </span>
    </button>
  )
}
