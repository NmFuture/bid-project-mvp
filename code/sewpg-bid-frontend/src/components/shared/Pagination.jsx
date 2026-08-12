export default function Pagination({ current, total, onPageChange, className = '' }) {
  const pageCount = Math.max(1, Number(total) || 1)
  const page = Math.min(Math.max(1, Number(current) || 1), pageCount)

  const start = Math.max(1, page - 2)
  const end = Math.min(pageCount, start + 4)
  const pages = []
  for (let i = start; i <= end; i += 1) pages.push(i)

  return (
    <nav aria-label="分页" className={`flex justify-end ${className}`.trim()}>
      <div className="flex flex-wrap items-center justify-end gap-1.5 text-xs text-on-surface-variant">
        <button
          type="button"
          aria-label="第一页"
          className="ui-pagination-control flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:text-outline"
          disabled={page <= 1}
          onClick={() => onPageChange(1)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">first_page</span>
        </button>
        <button
          type="button"
          aria-label="上一页"
          className="ui-pagination-control flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:text-outline"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">chevron_left</span>
        </button>

        {pages.map((p) => (
          <button
            key={p}
            type="button"
            aria-label={`第 ${p} 页`}
            aria-current={p === page ? 'page' : undefined}
            className={`ui-pagination-control h-8 min-w-8 rounded-md px-1.5 tabular-nums transition-colors ${
              p === page
                ? 'border border-primary/25 bg-primary-fixed text-on-primary-fixed-variant'
                : 'text-on-surface-variant hover:bg-surface-container-high'
            }`}
            onClick={() => onPageChange(p)}
          >
            {p}
          </button>
        ))}

        <button
          type="button"
          aria-label="下一页"
          className="ui-pagination-control flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:text-outline"
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">chevron_right</span>
        </button>
        <button
          type="button"
          aria-label="最后一页"
          className="ui-pagination-control flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:text-outline"
          disabled={page >= pageCount}
          onClick={() => onPageChange(pageCount)}
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">last_page</span>
        </button>
      </div>
    </nav>
  )
}
