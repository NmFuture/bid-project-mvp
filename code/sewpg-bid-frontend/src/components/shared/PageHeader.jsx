export default function PageHeader({
  title,
  description,
  leftExtra,
  actions,
  actionsClassName = '',
  className = '',
  titleClassName = '',
  descriptionClassName = '',
}) {
  return (
    <header className={`flex flex-col md:flex-row justify-between items-start md:items-end gap-6 ${className}`.trim()}>
      <div className="flex flex-col gap-2">
        {leftExtra}
        {title && (
          <h1 className={`text-3xl md:text-4xl font-headline font-extrabold text-primary tracking-tight ${titleClassName}`.trim()}>
            {title}
          </h1>
        )}
        {description && (
          <p className={`text-on-surface-variant text-sm max-w-xl leading-relaxed ${descriptionClassName}`.trim()}>
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className={`page-header-actions flex flex-wrap gap-3 ${actionsClassName}`.trim()}>
          {actions}
        </div>
      )}
    </header>
  )
}
