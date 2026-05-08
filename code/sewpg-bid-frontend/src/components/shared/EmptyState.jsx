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
      className={`flex flex-col items-center justify-center py-12 text-center ${className}`}
    >
      <span className="material-symbols-outlined text-5xl text-outline mb-3">{icon}</span>
      {title && <h3 className="text-base font-medium text-on-surface mb-1">{title}</h3>}
      {description && (
        <p className="text-sm text-on-surface-variant mb-4 max-w-sm">{description}</p>
      )}
      {action}
    </div>
  )
}
