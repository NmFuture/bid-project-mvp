export default function FilterBar({ left, right, className = '' }) {
  const hasRight = Boolean(right)
  return (
    <section
      aria-label="筛选和操作"
      className={`flex min-w-0 flex-col items-stretch justify-between gap-3 border-0 bg-transparent px-0 py-0 lg:flex-row lg:items-center ${className}`.trim()}
    >
      <div className="flex min-w-0 w-full flex-wrap items-center gap-2 lg:w-auto">{left}</div>
      {hasRight && <div className="flex min-w-0 w-full flex-wrap items-center justify-start gap-2 lg:w-auto lg:justify-end">{right}</div>}
    </section>
  )
}
