export function PageLoading({
  title = '加载中...',
  description = '正在获取最新数据。',
  containerClassName = 'min-h-[40vh]',
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className={`flex items-center justify-center ${containerClassName}`.trim()}>
      <div className="w-full max-w-xl rounded-lg border border-outline-variant bg-surface-container-lowest p-6 text-center sm:p-8">
        <div aria-hidden="true" className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-outline-variant border-t-primary" />
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
        className={`w-full max-w-xl rounded-lg border border-outline-variant bg-surface-container-lowest p-6 text-center sm:p-8 ${cardClassName}`.trim()}
        style={cardStyle}
      >
        <span aria-hidden="true" className="material-symbols-outlined text-4xl text-outline">inbox</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        {actionText && onAction && (
          <button
            type="button"
            onClick={onAction}
            className="ui-control mt-4 inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-on-primary transition-colors hover:bg-on-primary-fixed-variant"
          >
            {showActionIcon ? <span aria-hidden="true" className="material-symbols-outlined text-base">refresh</span> : null}
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
    <div role="alert" className="flex min-h-[40vh] items-center justify-center">
      <div className="w-full max-w-xl rounded-lg border border-error/20 bg-surface-container-lowest p-6 text-center sm:p-8">
        <span aria-hidden="true" className="material-symbols-outlined text-4xl text-error">error</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="ui-control mt-4 inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-on-primary transition-colors hover:bg-on-primary-fixed-variant"
          >
            <span aria-hidden="true" className="material-symbols-outlined text-base">refresh</span>
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
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="w-full max-w-xl rounded-lg border border-tertiary/30 bg-surface-container-lowest p-6 text-center sm:p-8">
        <span aria-hidden="true" className="material-symbols-outlined text-4xl text-tertiary">lock</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
      </div>
    </div>
  )
}
