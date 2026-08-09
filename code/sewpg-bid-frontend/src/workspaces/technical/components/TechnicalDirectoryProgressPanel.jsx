import BidProgressPanel from '../../../components/shared/BidProgressPanel'
import { progressElapsedLine } from '../../../utils/progressDuration'
import {
  directoryDisplayPercentage,
  directoryElapsedSeconds,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  summarizeDirectoryProgress,
} from '../technicalDirectoryProgress'

// 目录生成 / 重新生成目录：把目录进度状态折算成共享卡片的展示字段。
export default function TechnicalDirectoryProgressPanel({ state, nowMs, className = '' }) {
  const summary = summarizeDirectoryProgress(state || {})
  const running = isDirectoryProgressRunning(state)
  const finished = state?.status === 'completed' || isDirectoryProgressFailed(state)
  const elapsedLineText = progressElapsedLine(directoryElapsedSeconds(state || {}, nowMs), { finished })

  return (
    <BidProgressPanel
      tone={summary.tone}
      detail={summary.summary}
      elapsedText={elapsedLineText}
      percentage={directoryDisplayPercentage(state || {}, nowMs)}
      running={running}
      className={className}
    />
  )
}
