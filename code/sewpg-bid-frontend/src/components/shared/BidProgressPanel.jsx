// 全流程共用的进度卡片（技术标目录生成 / 重新生成目录 / 正文生成 / 重新生成正文 / 素材匹配）。
// 版式固定两行：第一行是带量化计数的进程明细，第二行是耗时；右侧徽标只留百分比——
// 状态词由图标和明细表达，再写一遍「生成中」只是重复。
// 本组件是纯展示层，不含任何业务判断：各流程各自把状态折算成 detail/percentage/elapsedText。
// tone 只有四种语义色；解析链路多一个 warning（可能中断），停止态用 neutral + 自定义图标。
export default function BidProgressPanel({
  tone = 'running',
  detail,
  elapsedText = '',
  percentage = 0,
  running = false,
  icon = '',
  className = '',
}) {
  const safePercentage = Math.max(0, Math.min(100, Number(percentage) || 0))
  const failed = tone === 'danger'
  const completed = tone === 'success'
  const warning = tone === 'warning'
  const badgeClass = failed
    ? 'bg-error-container text-error'
    : completed
      ? 'bg-secondary-container text-on-secondary-container'
      : warning
        ? 'bg-tertiary-container text-on-tertiary-container'
        : tone === 'running'
          ? 'bg-primary/10 text-primary'
          : 'bg-surface-container-high text-on-surface-variant'
  const barClass = failed ? 'bg-error' : completed ? 'bg-secondary' : warning ? 'bg-tertiary' : 'bg-primary'

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
                  : warning
                    ? 'text-tertiary'
                    : icon
                      ? 'text-outline'
                      : 'animate-spin-slow text-primary',
            ].join(' ')}
          >
            {icon || (failed ? 'error' : completed ? 'check_circle' : 'progress_activity')}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold tabular-nums text-on-surface">{detail}</p>
            {elapsedText ? (
              <p className="mt-1 text-xs leading-5 tabular-nums text-outline">{elapsedText}</p>
            ) : null}
          </div>
        </div>
        <span className={[
          'shrink-0 self-start rounded-md px-2.5 py-1 text-sm font-bold tabular-nums',
          badgeClass,
        ].join(' ')}>
          {Math.floor(safePercentage)}%
        </span>
      </div>

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-surface-container-high"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.floor(safePercentage)}
      >
        <div
          className={[
            'h-full rounded-full transition-all duration-1000 ease-linear',
            barClass,
            running ? 'bg-stripes' : '',
          ].join(' ')}
          style={{ width: `${safePercentage}%` }}
        />
      </div>
    </div>
  )
}
