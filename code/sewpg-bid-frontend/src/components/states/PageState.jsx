export function PageLoading({
  title = '加载中...',
  description = '正在获取最新数据。',
  containerClassName = 'min-h-[40vh]',
}) {
  return (
    <div className={`flex items-center justify-center ${containerClassName}`.trim()}>
      <div className="w-full max-w-xl rounded-xl bg-surface-container-lowest border border-surface-container-high p-8 text-center">
        <div className="mx-auto h-10 w-10 rounded-full border-2 border-outline-variant border-t-primary animate-spin" />
        <h3 className="mt-4 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
      </div>
    </div>
  )
}

export function PageEmpty({
  title = '暂无数据',
  description = '当前筛选条件下没有可展示内容。',
  actionText,
  onAction,
  showActionIcon = true,
  containerClassName = '',
  cardClassName = '',
  cardStyle,
}) {
  return (
    <div className={`min-h-[40vh] flex items-center justify-center ${containerClassName}`.trim()}>
      <div
        className={`w-full max-w-xl rounded-xl bg-surface-container-lowest border border-surface-container-high p-8 text-center ${cardClassName}`.trim()}
        style={cardStyle}
      >
        <span className="material-symbols-outlined text-5xl text-outline/50">inbox</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        {actionText && onAction && (
          <button
            onClick={onAction}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:bg-primary-container transition-colors"
          >
            {showActionIcon ? <span className="material-symbols-outlined text-base">refresh</span> : null}
            {actionText}
          </button>
        )}
      </div>
    </div>
  )
}

export function PageError({
  title = '加载失败',
  description = '请求未成功，请重试或联系管理员。',
  onRetry,
}) {
  return (
    <div className="min-h-[40vh] flex items-center justify-center">
      <div className="w-full max-w-xl rounded-xl bg-surface-container-lowest border border-error/20 p-8 text-center">
        <span className="material-symbols-outlined text-5xl text-error">error</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:bg-primary-container transition-colors"
          >
            <span className="material-symbols-outlined text-base">refresh</span>
            重新加载
          </button>
        )}
      </div>
    </div>
  )
}

export function PagePermissionDenied({
  title = '无权限访问',
  description = '请联系管理员开通该模块权限。',
}) {
  return (
    <div className="min-h-[40vh] flex items-center justify-center">
      <div className="w-full max-w-xl rounded-xl bg-surface-container-lowest border border-tertiary/30 p-8 text-center">
        <span className="material-symbols-outlined text-5xl text-tertiary">lock</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
      </div>
    </div>
  )
}
