// 空状态组件。
export default function EmptyState({
  icon = 'inbox',
  title,
  description,
  action,
  className = '',
}) {
  return (
    <div
      className={`flex min-h-48 flex-col items-center justify-center px-4 py-10 text-center ${className}`}
    >
      <span aria-hidden="true" className="material-symbols-outlined mb-3 text-4xl text-outline">{icon}</span>
      {title && <h3 className="mb-1 text-lg font-semibold text-on-surface">{title}</h3>}
      {description && (
        <p className="mb-4 max-w-sm text-sm leading-[22px] text-on-surface-variant">{description}</p>
      )}
      {action}
    </div>
  )
}
