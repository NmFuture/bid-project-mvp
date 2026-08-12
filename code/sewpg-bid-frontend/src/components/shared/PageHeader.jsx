export default function PageHeader({
  title,
  description,
  leftExtra,
  actions,
  variant = 'plain',
  actionsClassName = '',
  className = '',
  titleClassName = '',
  descriptionClassName = '',
}) {
  const panel = variant === 'panel'
  return (
    <header
      className={`flex min-w-0 flex-col items-start justify-between gap-4 md:flex-row ${
        panel
          ? 'min-h-[72px] rounded-lg border border-outline-variant/45 bg-surface-container-lowest px-4 py-4 sm:px-5 md:items-center'
          : 'md:items-end'
      } ${className}`.trim()}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        {leftExtra}
        {title && (
          <h1 className={`text-pretty break-words text-2xl font-headline font-semibold text-on-surface ${titleClassName}`.trim()}>
            {title}
          </h1>
        )}
        {description && (
          <p className={`max-w-2xl text-sm text-on-surface-variant ${descriptionClassName}`.trim()}>
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className={`page-header-actions flex min-h-10 w-full flex-wrap items-center gap-2 md:w-auto md:justify-end ${actionsClassName}`.trim()}>
          {actions}
        </div>
      )}
    </header>
  )
}
