import {
  directoryDisplayPercentage,
  directoryElapsedSeconds,
  formatDirectoryDuration,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  summarizeDirectoryProgress,
} from '../technicalDirectoryProgress'

export default function TechnicalDirectoryProgressPanel({ state, nowMs, className = '' }) {
  const summary = summarizeDirectoryProgress(state || {})
  const running = isDirectoryProgressRunning(state)
  const completed = state?.status === 'completed'
  const failed = isDirectoryProgressFailed(state)
  const displayPercentage = directoryDisplayPercentage(state || {}, nowMs)
  const elapsedDurationText = formatDirectoryDuration(directoryElapsedSeconds(state || {}, nowMs))
  const elapsedLineText = elapsedDurationText
    ? `${completed ? '总耗时' : '已运行'} ${elapsedDurationText}`
    : ''
  const badgeClass = summary.tone === 'danger'
    ? 'bg-error-container text-error'
    : summary.tone === 'success'
      ? 'bg-secondary-container text-on-secondary-container'
      : summary.tone === 'running'
        ? 'bg-primary/10 text-primary'
        : 'bg-surface-container-high text-on-surface-variant'
  const progressBarClass = summary.tone === 'danger'
    ? 'bg-error'
    : summary.tone === 'success'
      ? 'bg-secondary'
      : 'bg-primary'

  return (
    <div className={[
      'w-full border-y px-4 py-4',
      failed
        ? 'border-error/30 bg-error-container/10'
        : 'border-surface-container-high bg-surface-container-low',
      className,
    ].filter(Boolean).join(' ')}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span
            aria-hidden="true"
            className={[
              'material-symbols-outlined mt-0.5 text-[20px]',
              failed
                ? 'text-error'
                : completed
                  ? 'text-secondary'
                  : 'animate-spin-slow text-primary',
            ].join(' ')}
          >
            {failed ? 'error' : completed ? 'check_circle' : 'progress_activity'}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold tabular-nums text-on-surface">
              {summary.summary}
            </p>
            {elapsedLineText ? (
              <p className="mt-1 text-xs leading-5 tabular-nums text-outline">{elapsedLineText}</p>
            ) : null}
          </div>
        </div>
        <span className={[
          'shrink-0 self-start rounded-md px-2.5 py-1 text-xs font-semibold tabular-nums',
          badgeClass,
        ].join(' ')}>
          {summary.statusText} · {Math.floor(displayPercentage)}%
        </span>
      </div>

      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-container-high">
        <div
          className={[
            'h-full rounded-full transition-all duration-1000 ease-linear',
            progressBarClass,
            running ? 'bg-stripes' : '',
          ].join(' ')}
          style={{ width: `${displayPercentage}%` }}
        />
      </div>
    </div>
  )
}
