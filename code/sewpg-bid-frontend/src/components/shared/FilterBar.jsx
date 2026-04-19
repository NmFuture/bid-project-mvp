export default function FilterBar({ left, right, className = '' }) {
  const hasRight = Boolean(right)
  return (
    <section
      className={`bg-surface-container-low rounded-xl p-4 flex flex-col xl:flex-row gap-4 items-center justify-between shadow-[inset_0_1px_3px_rgba(0,0,0,0.02)] ${className}`.trim()}
    >
      <div className="flex flex-wrap items-center gap-3 w-full xl:w-auto">{left}</div>
      {hasRight && <div className="flex items-center gap-3 w-full xl:w-auto justify-end">{right}</div>}
    </section>
  )
}
