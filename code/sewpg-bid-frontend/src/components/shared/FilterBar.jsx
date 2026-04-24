export default function FilterBar({ left, right, className = '' }) {
  const hasRight = Boolean(right)
  return (
    <section
      className={`bg-transparent border-0 px-0 py-0 flex flex-col xl:flex-row gap-3 items-center justify-between ${className}`.trim()}
    >
      <div className="flex flex-wrap items-center gap-3 w-full xl:w-auto">{left}</div>
      {hasRight && <div className="flex items-center gap-3 w-full xl:w-auto justify-end">{right}</div>}
    </section>
  )
}
