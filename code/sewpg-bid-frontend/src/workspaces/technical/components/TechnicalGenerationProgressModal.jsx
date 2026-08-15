import { useEffect, useState } from 'react'
import BidProgressPanel from '../../../components/shared/BidProgressPanel'
import TechnicalTaskProgressDialog from './TechnicalTaskProgressDialog'
import { progressElapsedLine } from '../../../utils/progressDuration'
import {
  generationDisplayPercentage,
  generationElapsedSeconds,
  isGenerationProgressFailed,
  isGenerationProgressRunning,
  summarizeGenerationProgress,
} from '../technicalGenerationProgress'
import { technicalGenerationPresentation } from '../pages/technicalGapRecognitionHelpers'

// 生成技术标正文 / 重新生成正文共用本弹窗，版式与目录生成一致：
// 卡片第一行是量化明细，第二行是耗时，右侧只留百分比。
export default function TechnicalGenerationProgressModal({
  open,
  status,
  onClose,
  onStop,
  stopping = false,
  taskTitle = '生成正文',
  completedMessage = '技术标正文已生成。可进入共创导出；后续如需重新生成，可在共创导出页操作。',
}) {
  const running = isGenerationProgressRunning(status)
  const [nowMs, setNowMs] = useState(() => Date.now())

  // 弹窗常驻在页面里，nowMs 初值是页面挂载时刻；打开后先补一拍再按秒走，避免首帧用旧时间。
  useEffect(() => {
    if (!open || !running) return undefined
    const catchUp = window.setTimeout(() => setNowMs(Date.now()), 0)
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => {
      window.clearTimeout(catchUp)
      window.clearInterval(timer)
    }
  }, [open, running])

  if (!open) return null

  const completed = status?.status === 'completed'
  const cancelled = status?.status === 'cancelled'
  const failed = isGenerationProgressFailed(status)
  const title = running
    ? `正在${taskTitle}`
    : completed ? `${taskTitle}完成` : cancelled ? `${taskTitle}已停止` : failed ? `${taskTitle}失败` : taskTitle
  const summary = summarizeGenerationProgress(status || {})
  const elapsedText = progressElapsedLine(
    generationElapsedSeconds(status || {}, nowMs),
    { finished: completed || cancelled || failed },
  )
  const {
    warningCount,
    formatCleanFailed,
    formatCleanMessage,
    captionNumberMessage,
    scoreIndexXrefMessage,
  } = technicalGenerationPresentation(status)

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
          tone={summary.tone}
          detail={summary.detail}
          elapsedText={elapsedText}
          percentage={generationDisplayPercentage(status || {}, nowMs)}
          running={running}
          icon={cancelled ? 'stop_circle' : ''}
        />
        {running ? (
          <p className="text-xs text-outline">任务在后台运行，可以关闭弹窗或离开页面。</p>
        ) : null}
        {completed ? (
          <div className="border border-secondary/25 bg-secondary-container/35 px-3 py-2 text-sm text-on-secondary-container">
            {completedMessage}
          </div>
        ) : null}
        {completed && warningCount > 0 ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
            生成结果包含 {warningCount} 项提示，可继续进入共创处理。
          </div>
        ) : null}
        {completed && formatCleanFailed ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm font-semibold text-on-tertiary-fixed-variant">
            {formatCleanMessage}
          </div>
        ) : null}
        {completed && captionNumberMessage ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
            {captionNumberMessage}
          </div>
        ) : null}
        {completed && scoreIndexXrefMessage ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
            {scoreIndexXrefMessage}
          </div>
        ) : null}
        {failed ? (
          <div className="border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
            {status?.error || summary.detail}
          </div>
        ) : null}
    </TechnicalTaskProgressDialog>
  )
}
