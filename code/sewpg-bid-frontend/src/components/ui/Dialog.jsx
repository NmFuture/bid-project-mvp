import { cx } from './utils'
import IconButton from './IconButton'

const SIZES = {
  sm: 'max-w-md',
  md: 'max-w-2xl',
  lg: 'max-w-3xl',
  xl: 'max-w-5xl',
  full: 'max-w-[calc(100vw-2rem)]',
}

export function Dialog({
  children,
  className = '',
  onClose,
  open = true,
  size = 'md',
}) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6" onClick={onClose}>
      <div
        className={cx('flex max-h-[88vh] w-full flex-col overflow-hidden rounded-lg border border-surface-container-high bg-surface shadow-2xl', SIZES[size] || SIZES.md, className)}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}

export function DialogHeader({
  children,
  className = '',
  onClose,
}) {
  return (
    <div className={cx('flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4', className)}>
      <div className="min-w-0">{children}</div>
      {onClose ? <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" /> : null}
    </div>
  )
}

export function DialogBody({ children, className = '' }) {
  return <div className={cx('min-h-0 flex-1 overflow-auto p-4', className)}>{children}</div>
}

export function DialogFooter({ children, className = '' }) {
  return (
    <div className={cx('flex flex-wrap items-center justify-end gap-2 border-t border-surface-container-high bg-surface-container-low px-5 py-4', className)}>
      {children}
    </div>
  )
}
