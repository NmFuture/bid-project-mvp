import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
import { technicalGenerationPresentation } from '../pages/technicalGapRecognitionHelpers'

export default function TechnicalGenerationProgressModal({
  open,
  status,
  progress,
  onClose,
  completedMessage = '技术标正文已生成。可进入共创导出；后续如需重新生成，可在共创导出页操作。',
}) {
  if (!open) return null
  const running = status?.status === 'running'
  const completed = status?.status === 'completed'
  const failed = status?.status === 'failed'
  const title = running ? '正在生成技术标正文' : completed ? '技术标正文已生成' : failed ? '技术标正文生成失败' : '技术标正文生成'
  const summary = status?.summary || (running ? '系统正在根据当前素材匹配结果生成正文。' : completed ? '技术标正文已生成。' : failed ? '请检查任务状态后重新生成。' : '准备生成技术标正文。')
  const { warningCount, formatCleanFailed, formatCleanMessage } = technicalGenerationPresentation(status)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="w-full max-w-xl rounded-lg bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">{title}</h3>
            <p className="mt-1 text-sm text-on-surface-variant">{summary}</p>
          </div>
          {!running ? <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" /> : null}
        </div>
        <div className="space-y-4 p-5">
          <div className="flex items-center gap-3">
            <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-container-high">
              <div
                className={`h-full transition-all duration-700 ${failed ? 'bg-error' : 'bg-primary'}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-12 text-right text-xs font-semibold text-outline">{progress}%</span>
          </div>
          {completed ? (
            <div className="rounded-md border border-secondary/20 bg-secondary-container/40 px-3 py-2 text-sm text-on-secondary-container">
              {completedMessage}
            </div>
          ) : null}
          {completed && warningCount > 0 ? (
            <div className="rounded-md border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
              生成结果包含 {warningCount} 项提示，可继续进入共创处理。
            </div>
          ) : null}
          {completed && formatCleanFailed ? (
            <div className="rounded-md border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm font-semibold text-on-tertiary-fixed-variant">
              {formatCleanMessage}
            </div>
          ) : null}
          {failed ? (
            <div className="rounded-md border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
              {status?.error || '生成失败，请稍后重试。'}
            </div>
          ) : null}
        </div>
        <div className="flex justify-end border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <Button type="button" onClick={onClose} disabled={running} variant={completed ? 'primary' : 'quiet'}>
            {running ? '生成中...' : '关闭'}
          </Button>
        </div>
      </div>
    </div>
  )
}
