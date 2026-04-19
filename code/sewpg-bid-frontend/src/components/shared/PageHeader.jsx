export default function PageHeader({
  title,
  description,
  leftExtra,
  actions,
  className = '',
}) {
  return (
    <header className={`flex flex-col md:flex-row justify-between items-start md:items-end gap-6 ${className}`.trim()}>
      <div className="flex flex-col gap-2">
        {leftExtra}
        <h1 className="text-3xl md:text-4xl font-headline font-extrabold text-primary tracking-tight">
          {title}
        </h1>
        {description && (
          <p className="text-on-surface-variant text-sm max-w-xl leading-relaxed">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex gap-3">{actions}</div>}
    </header>
  )
}

