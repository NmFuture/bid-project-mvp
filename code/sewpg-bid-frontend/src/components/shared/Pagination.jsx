export default function Pagination({ current, total, onPageChange }) {
  return (
    <div className="flex justify-center mt-8">
      <div className="flex items-center gap-4 text-sm text-on-surface-variant">
        <button
          className="p-2 hover:bg-surface-container-highest rounded-md transition-colors text-outline disabled:opacity-40"
          disabled={current <= 1}
          onClick={() => onPageChange(current - 1)}
        >
          <span className="material-symbols-outlined text-lg">chevron_left</span>
        </button>
        <span className="font-medium">{current} / {total} 页</span>
        <button
          className="p-2 hover:bg-surface-container-highest rounded-md transition-colors text-primary disabled:opacity-40"
          disabled={current >= total}
          onClick={() => onPageChange(current + 1)}
        >
          <span className="material-symbols-outlined text-lg">chevron_right</span>
        </button>
      </div>
    </div>
  )
}
