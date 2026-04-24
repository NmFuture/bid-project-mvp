export default function DataCard({
  children,
  className = '',
  padding = 'p-6',
  hover = false,
  onClick,
  style,
}) {
  return (
    <article
      onClick={onClick}
      style={style}
      className={`bg-surface-container-lowest border border-outline-variant/50 rounded-md shadow-[0_1px_3px_rgba(13,33,55,0.08)] ${padding} ${hover ? 'transition-all duration-200 hover:shadow-[0_10px_18px_-14px_rgba(12,46,82,0.45)] hover:border-primary/40' : ''} ${onClick ? 'cursor-pointer' : ''} ${className}`.trim()}
    >
      {children}
    </article>
  )
}
