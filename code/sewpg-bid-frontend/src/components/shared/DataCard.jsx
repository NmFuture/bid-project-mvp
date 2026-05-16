export default function DataCard({
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
      className={`bg-surface-container-lowest border border-outline-variant/50 rounded-md shadow-[0_1px_3px_rgba(13,33,55,0.08)] ${padding} ${hover ? 'transition-colors duration-150 hover:border-primary/40' : ''} ${className}`.trim()}
      {...interactiveProps}
    >
      {children}
    </article>
  )
}
