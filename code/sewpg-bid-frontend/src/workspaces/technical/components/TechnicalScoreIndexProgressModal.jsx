import { useEffect, useState } from 'react'
import BidProgressPanel from '../../../components/shared/BidProgressPanel'
import TechnicalTaskProgressDialog from './TechnicalTaskProgressDialog'
import { progressElapsedLine } from '../../../utils/progressDuration'
import {
  isScoreIndexProgressFailed,
  isScoreIndexProgressRunning,
  scoreIndexDisplayPercentage,
  scoreIndexElapsedSeconds,
  summarizeScoreIndexProgress,
} from '../technicalScoreIndexProgress'

// 重新生成索引的进度弹窗，版式与重新生成目录一致：
// 卡片第一行是量化明细（已建立章节索引 X/Y 项），第二行是耗时，右侧只留百分比。
export default function TechnicalScoreIndexProgressModal({ open, status, onClose, onStop, stopping = false }) {
  const running = isScoreIndexProgressRunning(status)
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
  const failed = isScoreIndexProgressFailed(status)
  const title = running
    ? '正在重新生成章节索引'
    : completed ? '章节索引重新生成完成' : cancelled ? '章节索引重新生成已停止' : failed ? '章节索引重新生成失败' : '重新生成章节索引'
  const summary = summarizeScoreIndexProgress(status || {})
  const elapsedText = progressElapsedLine(
    scoreIndexElapsedSeconds(status || {}, nowMs),
    { finished: completed || cancelled || failed },
  )
  const output = status?.output && typeof status.output === 'object' ? status.output : null
  const applied = Boolean(output?.applied)
  const pageNumbersPending = applied && output?.pageNumbersResolved === false
  const unresolvedCount = Math.max(0, Number(output?.unresolvedCount) || 0)

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
          percentage={scoreIndexDisplayPercentage(status || {}, nowMs)}
          running={running}
          icon={cancelled ? 'stop_circle' : ''}
        />
        {running ? (
          <p className="text-xs text-outline">任务在后台运行，可以关闭弹窗或离开页面。</p>
        ) : null}
        {completed && applied ? (
          <div className="border border-secondary/25 bg-secondary-container/35 px-3 py-2 text-sm text-on-secondary-container">
            成稿中的评分索引表已更新，预览已刷新。
          </div>
        ) : null}
        {completed && !applied ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
            未找到技术评分标准索引表，本次未改动成稿。
          </div>
        ) : null}
        {completed && pageNumbersPending ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
            页码需在 Word/WPS 中全选后按 F9 刷新。
          </div>
        ) : null}
        {completed && unresolvedCount > 0 ? (
          <div className="border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
            有 {unresolvedCount} 条索引未能定位到正文章节，建议人工复核。
          </div>
        ) : null}
        {failed ? (
          <div className="border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
            当前成稿未被修改，可关闭后重试。
          </div>
        ) : null}
    </TechnicalTaskProgressDialog>
  )
}
