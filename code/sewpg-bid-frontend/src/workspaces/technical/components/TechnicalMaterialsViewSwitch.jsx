import { NavLink } from 'react-router-dom'

const ITEMS = [
  { key: 'structured', label: '原始素材', path: '/structured' },
  { key: 'wiki', label: 'Wiki', path: '/wiki' },
]

const BID_TYPE_ITEMS = [
  { value: '技术标', label: '技术标', shortLabel: '技' },
  { value: '商务标', label: '商务标', shortLabel: '商' },
]

export default function TechnicalMaterialsViewSwitch({
  active = 'structured',
  activeBidType = '技术标',
  onBidTypeChange = null,
  lockedBidType = '',
  title = '',
  subtitle = '',
  actions = null,
  meta = null,
  basePath = '/materials',
}) {
  const normalizedBasePath = String(basePath || '/materials').replace(/\/+$/, '')
  const bidType = activeBidType === '商务标' ? '商务标' : '技术标'
  const bidTypeQuery = `?bidType=${encodeURIComponent(bidType)}`
  return (
    <div className="overflow-hidden rounded-lg border border-outline-variant/55 bg-white shadow-[0_12px_28px_-24px_rgba(13,33,55,0.35)]">
      <div className="flex flex-col gap-3 px-4 py-3 lg:px-5 xl:min-h-[64px] xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-1 flex-col gap-3 lg:flex-row lg:items-center">
          <div className="min-w-0 lg:w-[240px] xl:w-[270px]">
            <div className="flex min-w-0 items-center gap-2">
              <span aria-hidden="true" className="h-5 w-1 shrink-0 rounded-full bg-primary/80" />
              <h1 className="truncate text-base font-headline font-bold text-ink-strong">{title}</h1>
            </div>
            {subtitle ? (
              <p className="mt-1 truncate pl-3 text-xs text-outline" title={typeof subtitle === 'string' ? subtitle : undefined}>
                {subtitle}
              </p>
            ) : null}
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="inline-flex h-8 w-fit rounded-md border border-outline-variant/65 bg-surface-container-low p-0.5 text-xs">
              {BID_TYPE_ITEMS.map((item) => {
                const selected = bidType === item.value
                const disabled = Boolean(lockedBidType && lockedBidType !== item.value)
                return (
                  <button
                    key={item.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => onBidTypeChange?.(item.value)}
                    title={item.label}
                    className={`inline-flex h-7 min-w-[76px] items-center justify-center gap-1.5 rounded px-2.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                      selected
                        ? 'bg-primary text-on-primary font-medium'
                        : 'text-on-surface-variant hover:bg-surface-container-high'
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded text-[11px] ${
                        selected ? 'bg-white/20 text-on-primary' : 'bg-surface-container-high text-primary'
                      }`}
                    >
                      {item.shortLabel}
                    </span>
                    <span>{item.label}</span>
                  </button>
                )
              })}
            </div>
            <div className="inline-flex h-8 w-fit rounded-md border border-outline-variant/65 bg-surface-container-low p-0.5 text-xs">
              {ITEMS.map((item) => {
                const selected = active === item.key
                return (
                  <NavLink
                    key={item.key}
                    to={`${normalizedBasePath}${item.path}${bidTypeQuery}`}
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
