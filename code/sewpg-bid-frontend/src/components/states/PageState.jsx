import Button from '../ui/Button'
import Skeleton from '../shared/Skeleton'

// 页面加载态与真实页面同构：页头/工具条/内容区骨架占位、顶部对齐、全宽展开，
// 避免加载中居中卡片与真实内容之间的高度跳变（路由切换闪动治理）。
export function PageLoading({
  title = '加载中...',
  description = '正在获取最新数据。',
  containerClassName = '',
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={`flex w-full flex-col gap-4 ${containerClassName}`.trim()}
    >
      <span className="sr-only">{`${title} ${description}`}</span>
      <div className="flex items-center justify-between gap-3">
        <Skeleton className="h-8 w-44 rounded-md" />
        <Skeleton className="h-9 w-28 rounded-md" />
      </div>
      <Skeleton className="h-11 w-full rounded-md" />
      <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
        <div className="border-b border-surface-container-high bg-surface-container-low px-4 py-2.5">
          <Skeleton className="h-4 w-2/5 rounded" />
        </div>
        <div className="flex flex-col gap-3 p-4">
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-6 w-full rounded" />
          ))}
        </div>
      </div>
    </div>
  )
}

export function PageEmpty({
  title = '暂无数据',
  description = '当前筛选条件下没有可展示内容。',
  actionText,
  onAction,
  containerClassName = '',
  cardClassName = '',
  cardStyle,
}) {
  return (
    <div className={`min-h-[55vh] flex items-center justify-center ${containerClassName}`.trim()}>
      <div
        className={`w-full max-w-2xl rounded-lg border border-outline-variant bg-surface-container-lowest px-6 py-12 text-center sm:px-10 ${cardClassName}`.trim()}
        style={cardStyle}
      >
        <span aria-hidden="true" className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-surface-container-low">
          <span className="material-symbols-outlined text-[28px] text-outline">inbox</span>
        </span>
        <h3 className="mt-4 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-6 text-on-surface-variant">{description}</p>
        {actionText && onAction && (
          <Button onClick={onAction} className="mt-5">
            {actionText}
          </Button>
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
    <div role="alert" className="flex min-h-[55vh] items-center justify-center">
      <div className="w-full max-w-2xl rounded-lg border border-error/20 bg-surface-container-lowest px-6 py-12 text-center sm:px-10">
        <span aria-hidden="true" className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-error-container">
          <span className="material-symbols-outlined text-[28px] text-error">error</span>
        </span>
        <h3 className="mt-4 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-6 text-on-surface-variant">{description}</p>
        {onRetry && (
          <Button onClick={onRetry} className="mt-5">
            重新加载
          </Button>
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
    <div className="flex min-h-[55vh] items-center justify-center">
      <div className="w-full max-w-2xl rounded-lg border border-tertiary/30 bg-surface-container-lowest px-6 py-12 text-center sm:px-10">
        <span aria-hidden="true" className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-tertiary-fixed">
          <span className="material-symbols-outlined text-[28px] text-tertiary">lock</span>
        </span>
        <h3 className="mt-4 text-lg font-semibold text-on-surface">{title}</h3>
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-6 text-on-surface-variant">{description}</p>
      </div>
    </div>
  )
}
