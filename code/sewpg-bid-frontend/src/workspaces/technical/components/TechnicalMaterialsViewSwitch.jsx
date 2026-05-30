import { NavLink } from 'react-router-dom'

const ITEMS = [
  { key: 'raw', label: '原始素材', path: '/raw' },
  { key: 'wiki', label: 'Wiki', path: '/wiki' },
]

export default function TechnicalMaterialsViewSwitch({
  active = 'raw',
  activeBidType = '技术标',
  title = '',
  subtitle = '',
  actions = null,
  meta = null,
  basePath = '/workspace/tech/materials',
}) {
  const normalizedBasePath = String(basePath || '/workspace/tech/materials').replace(/\/+$/, '')

  return (
    <div className="overflow-hidden rounded-lg border border-outline-variant/55 bg-white shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
      <div className="flex flex-col gap-3 px-4 py-3 lg:px-5 xl:min-h-[64px] xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-1 flex-col gap-3 lg:flex-row lg:items-center">
          <div className="min-w-0 lg:w-[240px] xl:w-[270px]">
            <div className="flex min-w-0 items-center gap-2">
              <span aria-hidden="true" className="h-5 w-1 shrink-0 rounded-full bg-primary/80" />
              <h1 className="truncate text-base font-headline font-bold text-on-surface">{title || '技术标素材库'}</h1>
            </div>
            {subtitle ? (
              <p className="mt-1 truncate pl-3 text-xs text-outline" title={typeof subtitle === 'string' ? subtitle : undefined}>
                {subtitle}
              </p>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/20 bg-primary/10 px-3 text-xs font-semibold text-primary">
              <span aria-hidden="true" className="material-symbols-outlined text-[16px]">engineering</span>
              {activeBidType}
            </span>
            <div className="inline-flex h-8 w-fit rounded-md border border-outline-variant/65 bg-surface-container-low p-0.5 text-xs">
              {ITEMS.map((item) => {
                const selected = active === item.key
                return (
                  <NavLink
                    key={item.key}
                    to={`${normalizedBasePath}${item.path}`}
                    className={`inline-flex h-7 min-w-[74px] items-center justify-center rounded px-2.5 transition-colors ${
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
          </div>
        </div>

        {actions ? (
          <div className="flex shrink-0 items-center justify-start xl:justify-end">
            {actions}
          </div>
        ) : null}
      </div>

      {meta ? (
        <div className="border-t border-surface-container-high bg-surface-container-lowest/80 px-4 py-2 lg:px-5">
          <div className="flex min-h-7 min-w-0 items-center overflow-x-auto">
            {meta}
          </div>
        </div>
      ) : null}
    </div>
  )
}
