import { createContext, useContext, useEffect, useId, useRef } from 'react'
import { cx } from './utils'
import IconButton from './IconButton'

const SIZES = {
  sm: 'max-w-md',
  md: 'max-w-2xl',
  lg: 'max-w-3xl',
  xl: 'max-w-5xl',
  full: 'max-w-[calc(100vw-2rem)]',
}

const DialogContext = createContext(null)
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function Dialog({
  children,
  className = '',
  onClose,
  open = true,
  size = 'md',
}) {
  const dialogRef = useRef(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return undefined

    const dialog = dialogRef.current
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const focusTarget = dialog?.querySelector(FOCUSABLE_SELECTOR) || dialog
    focusTarget?.focus()

    return () => {
      document.body.style.overflow = previousOverflow
      previousFocus?.focus?.()
    }
  }, [open])

  if (!open) return null

  const handleKeyDown = (event) => {
    if (event.key === 'Escape' && onClose) {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return

    const focusable = Array.from(dialogRef.current?.querySelectorAll(FOCUSABLE_SELECTOR) || [])
    if (!focusable.length) {
      event.preventDefault()
      dialogRef.current?.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-4 sm:py-6" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx('dialog-surface flex w-full flex-col overflow-hidden rounded-lg border border-outline-variant bg-surface shadow-[0_12px_28px_rgba(13,33,55,0.14)]', SIZES[size] || SIZES.md, className)}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <DialogContext.Provider value={{ titleId }}>{children}</DialogContext.Provider>
      </div>
    </div>
  )
}

export function DialogHeader({
  children,
  className = '',
  onClose,
}) {
  const context = useContext(DialogContext)
  return (
    <div className={cx('flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4', className)}>
      <div id={context?.titleId} className="min-w-0 text-lg font-semibold text-on-surface">{children}</div>
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
