export default function Toast({ message, type = 'success', onClose }) {
  return (
    <div className={`toast ${type === 'success' ? 'toast-success' : 'toast-error'}`} onClick={onClose}>
      <div className="flex items-center gap-3">
        <span className={`material-symbols-outlined text-lg ${type === 'success' ? 'text-secondary' : 'text-error'}`}
          style={{ fontVariationSettings: "'FILL' 1" }}>
          {type === 'success' ? 'check_circle' : 'error'}
        </span>
        <span>{message}</span>
      </div>
    </div>
  )
}
