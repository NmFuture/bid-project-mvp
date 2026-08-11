// 状态徽章。语义色 + 可选图标。
const VARIANTS = {
  pending: 'bg-surface-container-high text-on-surface-variant',
  running: 'bg-primary-fixed text-on-primary-fixed-variant',
  done: 'bg-secondary-container text-on-secondary-container',
  warn: 'bg-tertiary-container text-on-tertiary-container',
  error: 'bg-error-container text-error',
  info: 'bg-ai-accent-light text-on-tertiary-container',
}

const DEFAULT_ICONS = {
  pending: 'schedule',
  running: 'progress_activity',
  done: 'check_circle',
  warn: 'warning',
  error: 'error',
  info: 'info',
}

export default function StatusBadge({
  variant = 'pending',
  icon,
  spin = false,
  children,
  className = '',
}) {
  const cls = VARIANTS[variant] || VARIANTS.pending
  const ico = icon === null ? null : icon || DEFAULT_ICONS[variant]
  const isRunning = variant === 'running'
  return (
    <span
      className={`inline-flex min-h-6 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums ${cls} ${className}`}
    >
      {ico && (
        <span
          className={`material-symbols-outlined text-[14px] ${spin || isRunning ? 'animate-spin-slow' : ''}`}
          aria-hidden="true"
          style={{ fontVariationSettings: variant === 'done' ? "'FILL' 1" : "'FILL' 0" }}
        >
          {ico}
        </span>
      )}
      {children}
    </span>
  )
}
