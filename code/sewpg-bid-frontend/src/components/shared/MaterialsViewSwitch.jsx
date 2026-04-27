import { NavLink } from 'react-router-dom'

const ITEMS = [
  { key: 'structured', label: '原始素材', path: '/structured' },
  { key: 'wiki', label: 'Wiki', path: '/wiki' },
]

export default function MaterialsViewSwitch({
  active = 'structured',
  title = '',
  subtitle = '',
  actions = null,
  meta = null,
  basePath = '/materials',
}) {
  const normalizedBasePath = String(basePath || '/materials').replace(/\/+$/, '')
  return (
    <div className="rounded-2xl border border-surface-container-high bg-white">
      <div className="flex flex-col gap-4 px-6 py-5 md:px-8">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr),auto] xl:items-start">
          <div className="min-w-0">
            <h1 className="text-3xl font-headline font-bold text-primary">{title}</h1>
            {subtitle ? <p className="mt-2 text-sm text-outline break-words">{subtitle}</p> : null}
          </div>
          {actions ? <div className="min-w-0 w-full xl:w-auto">{actions}</div> : null}
        </div>
        <div className="flex flex-col gap-3 border-t border-surface-container-high pt-4 md:flex-row md:items-center md:justify-between">
          <div className="inline-flex w-fit rounded-lg border border-surface-container-high bg-surface-container-lowest p-1 text-sm">
            {ITEMS.map((item) => {
              const selected = active === item.key
              return (
                <NavLink
                  key={item.key}
                  to={`${normalizedBasePath}${item.path}`}
                  className={`px-4 py-2 rounded-md transition-colors ${
                    selected
                      ? 'bg-primary text-on-primary font-medium'
                      : 'text-on-surface-variant hover:bg-surface-container-high'
                  }`}
                >
                  {item.label}
                </NavLink>
              )
            })}
          </div>
          {meta ? <div className="min-w-0">{meta}</div> : null}
        </div>
      </div>
    </div>
  )
}
