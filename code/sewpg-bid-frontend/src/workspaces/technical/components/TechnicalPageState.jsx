export function PageLoading({ title = '加载中...', description = '正在获取最新数据。' }) {
  return (
    <div className="min-h-[40vh] flex items-center justify-center">
      <div className="w-full max-w-xl rounded-lg bg-white border border-surface-container-high p-8 text-center shadow-[0_18px_40px_-32px_rgba(13,33,55,0.35)]">
        <div className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-primary-fixed text-primary">
          <span className="material-symbols-outlined animate-spin-slow text-[22px]">progress_activity</span>
        </div>
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
        className={`w-full max-w-xl rounded-lg bg-white border border-surface-container-high p-8 text-center shadow-[0_18px_40px_-32px_rgba(13,33,55,0.35)] ${cardClassName}`.trim()}
        style={cardStyle}
      >
        <span className="material-symbols-outlined text-5xl text-outline/55">inbox</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        {actionText && onAction && (
          <button
            onClick={onAction}
            className="command-button command-button-primary mt-4"
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
      <div className="w-full max-w-xl rounded-lg bg-white border border-error/20 p-8 text-center shadow-[0_18px_40px_-32px_rgba(13,33,55,0.35)]">
        <span className="material-symbols-outlined text-5xl text-error">error</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="command-button command-button-primary mt-4"
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
      <div className="w-full max-w-xl rounded-lg bg-white border border-tertiary/30 p-8 text-center shadow-[0_18px_40px_-32px_rgba(13,33,55,0.35)]">
        <span className="material-symbols-outlined text-5xl text-tertiary">lock</span>
        <h3 className="mt-3 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mt-1 text-sm text-on-surface-variant">{description}</p>
      </div>
    </div>
  )
}
