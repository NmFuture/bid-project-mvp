export default function Toast({ message, type = 'success', onClose }) {
  const isError = type !== 'success'
  return (
    <div
      className={`toast ${isError ? 'toast-error' : 'toast-success'}`}
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? 'assertive' : 'polite'}
      aria-atomic="true"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span aria-hidden="true" className={`material-symbols-outlined text-lg ${isError ? 'text-error' : 'text-secondary'}`}
          style={{ fontVariationSettings: "'FILL' 1" }}>
          {isError ? 'error' : 'check_circle'}
        </span>
        <span className="min-w-0 flex-1 break-words">{message}</span>
        {onClose ? (
          <button type="button" className="toast-close" aria-label="关闭提示" onClick={onClose}>
            <span aria-hidden="true" className="material-symbols-outlined text-[18px]">close</span>
          </button>
        ) : null}
      </div>
    </div>
  )
}
