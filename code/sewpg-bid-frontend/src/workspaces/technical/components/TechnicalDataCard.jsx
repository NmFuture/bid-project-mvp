export default function TechnicalDataCard({
  children,
  className = '',
  padding = 'p-6',
  hover = false,
  onClick,
  style,
}) {
  const interactiveProps = onClick
    ? {
        role: 'button',
        tabIndex: 0,
        onKeyDown: (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onClick(event)
          }
        },
      }
    : {}

  return (
    <article
      onClick={onClick}
      style={style}
      className={`bg-white border border-outline-variant/55 rounded-lg shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)] ${padding} ${
        hover || onClick ? 'interactive-lift hover:border-primary/35' : ''
      } ${className}`.trim()}
      {...interactiveProps}
    >
      {children}
    </article>
  )
}
