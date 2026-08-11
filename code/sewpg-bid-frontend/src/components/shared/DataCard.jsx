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
      className={`min-w-0 rounded-lg border border-outline-variant bg-surface-container-lowest ${padding} ${hover ? 'transition-[background-color,border-color] duration-150 hover:border-primary/45 hover:bg-primary-fixed/20' : ''} ${className}`.trim()}
      {...interactiveProps}
    >
      {children}
    </article>
  )
}
