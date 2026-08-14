// 空状态组件：柔和圆形图标底 + 标题 + 描述 + 引导操作，
// 纵向占满可用空间，避免小卡片悬浮在大片空白中。
export default function EmptyState({
  icon = 'inbox',
  title,
  description,
  action,
  className = '',
}) {
  return (
    <div
      className={`flex min-h-72 flex-col items-center justify-center px-6 py-12 text-center ${className}`}
    >
      <span aria-hidden="true" className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-surface-container-low">
        <span className="material-symbols-outlined text-[28px] text-outline">{icon}</span>
      </span>
      {title && <h3 className="mb-1.5 text-lg font-semibold text-on-surface">{title}</h3>}
      {description && (
        <p className="mb-5 max-w-md text-sm leading-6 text-on-surface-variant">{description}</p>
      )}
      {action}
    </div>
  )
}
