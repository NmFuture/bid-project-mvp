export default function Pagination({ current, total, onPageChange, className = '' }) {
  const pageCount = Math.max(1, Number(total) || 1)
  const page = Math.min(Math.max(1, Number(current) || 1), pageCount)

  const start = Math.max(1, page - 2)
  const end = Math.min(pageCount, start + 4)
  const pages = []
  for (let i = start; i <= end; i += 1) pages.push(i)

  return (
    <div className={`flex justify-end ${className}`.trim()}>
      <div className="flex items-center gap-1.5 text-xs text-on-surface-variant">
        <button
          className="w-7 h-7 flex items-center justify-center rounded-sm hover:bg-surface-container-high transition-colors text-outline disabled:opacity-35"
          disabled={page <= 1}
          onClick={() => onPageChange(1)}
        >
          <span className="material-symbols-outlined text-[15px]">first_page</span>
        </button>
        <button
          className="w-7 h-7 flex items-center justify-center rounded-sm hover:bg-surface-container-high transition-colors text-outline disabled:opacity-35"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <span className="material-symbols-outlined text-[15px]">chevron_left</span>
        </button>

        {pages.map((p) => (
          <button
            key={p}
            className={`w-7 h-7 rounded-sm transition-colors ${
              p === page
                ? 'bg-[#0BAFFF] text-white border border-[#0BAFFF]'
                : 'text-outline hover:bg-surface-container-high'
            }`}
            onClick={() => onPageChange(p)}
          >
            {p}
          </button>
        ))}

        <button
          className="w-7 h-7 flex items-center justify-center rounded-sm hover:bg-surface-container-high transition-colors text-outline disabled:opacity-35"
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        >
          <span className="material-symbols-outlined text-[15px]">chevron_right</span>
        </button>
        <button
          className="w-7 h-7 flex items-center justify-center rounded-sm hover:bg-surface-container-high transition-colors text-outline disabled:opacity-35"
          disabled={page >= pageCount}
          onClick={() => onPageChange(pageCount)}
        >
          <span className="material-symbols-outlined text-[15px]">last_page</span>
        </button>
      </div>
    </div>
  )
}
