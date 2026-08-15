import { useEffect, useState } from 'react'
import BidProgressPanel from '../../../components/shared/BidProgressPanel'
import { progressElapsedLine } from '../../../utils/progressDuration'
import TechnicalTaskProgressDialog from './TechnicalTaskProgressDialog'

const EXPECTED_SECONDS = 60
const RUNNING_CAP = 92

const estimatePercentage = (elapsedSeconds) => (
  RUNNING_CAP * (1 - Math.exp(-Math.max(0, elapsedSeconds) / (EXPECTED_SECONDS / 2.5)))
)

export default function TechnicalMaterialMatchProgressModal({
  open,
  status = null,
  running: runningProp,
  error: errorProp,
  itemCount = 0,
  startedAtMs = 0,
  finishedAtMs = 0,
  onClose,
  onStop,
  stopping = false,
}) {
  const [nowMs, setNowMs] = useState(() => Date.now())
  const rawStatus = String(status?.status || '').toLowerCase()
  const running = runningProp ?? ['queued', 'running', 'processing', 'cancel_requested'].includes(rawStatus)
  const error = errorProp || status?.error || (rawStatus === 'failed' ? status?.message : '')

  useEffect(() => {
    if (!open || !running) return undefined
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [open, running])

  if (!open) return null

  const cancelled = rawStatus === 'cancelled'
  const failed = !cancelled && Boolean(error)
  const completed = rawStatus === 'completed'
  const title = running
    ? '正在进行素材匹配'
    : cancelled ? '素材匹配已停止' : failed ? '素材匹配失败' : '素材匹配完成'
  const resolvedStart = Date.parse(status?.startedAt || '') || startedAtMs
  const terminalAtMs = Date.parse(status?.completedAt || status?.cancelledAt || '')
  const endMs = terminalAtMs || (finishedAtMs > 0 ? finishedAtMs : nowMs)
  const elapsedSeconds = resolvedStart > 0 ? Math.max(0, (endMs - resolvedStart) / 1000) : 0
  const statusPercentage = Number(status?.percentage)
  const percentage = Number.isFinite(statusPercentage)
    ? statusPercentage
    : running ? estimatePercentage(elapsedSeconds) : 100
  const scopeText = itemCount > 0 ? `，共 ${itemCount} 个目录项` : ''
  const detail = status?.message || (cancelled
    ? '素材匹配已停止，目录确认结果已保留。'
    : failed
    ? '素材匹配未完成，目录确认结果已保留。'
    : running ? `正在按已确认目录匹配素材${scopeText}` : `素材匹配已完成${scopeText}`)

  return (
    <TechnicalTaskProgressDialog
      open={open}
      title={title}
      active={running}
      stopping={stopping}
      onClose={onClose}
      onStop={onStop}
    >
      <BidProgressPanel
        tone={cancelled ? 'neutral' : failed ? 'danger' : running ? 'running' : 'success'}
        detail={detail}
        elapsedText={progressElapsedLine(elapsedSeconds, { finished: completed || failed || cancelled })}
        percentage={percentage}
        running={running}
        icon={cancelled ? 'stop_circle' : ''}
      />
      {running ? <p className="text-xs text-outline">任务在后台运行，可以关闭弹窗或离开页面。</p> : null}
      {failed ? <div className="border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">{error}</div> : null}
      {cancelled ? (
        <div className="border border-outline-variant bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">
          素材匹配已停止，目录确认结果已保留。
        </div>
      ) : null}
    </TechnicalTaskProgressDialog>
  )
}
