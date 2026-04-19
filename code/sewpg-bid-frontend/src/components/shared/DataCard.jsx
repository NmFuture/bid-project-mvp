export default function DataCard({
  children,
  className = '',
  padding = 'p-6',
  hover = false,
  onClick,
}) {
  return (
    <article
      onClick={onClick}
      className={`bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] ${padding} ${hover ? 'transition-all duration-300 hover:shadow-[0_12px_32px_-12px_rgba(0,62,111,0.1)]' : ''} ${onClick ? 'cursor-pointer' : ''} ${className}`.trim()}
    >
      {children}
    </article>
  )
}

