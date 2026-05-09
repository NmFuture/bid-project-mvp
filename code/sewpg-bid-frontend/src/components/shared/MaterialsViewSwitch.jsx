import { NavLink } from 'react-router-dom'

const ITEMS = [
  { key: 'structured', label: '原始素材', path: '/structured' },
  { key: 'wiki', label: 'Wiki', path: '/wiki' },
]

const BID_TYPE_ITEMS = [
  { value: '技术标', label: '技术标', shortLabel: '技' },
  { value: '商务标', label: '商务标', shortLabel: '商' },
]

export default function MaterialsViewSwitch({
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
    <div className="rounded-xl border border-surface-container-high bg-white">
      <div className="grid min-h-[92px] grid-cols-1 gap-3 px-5 py-4 xl:grid-cols-[auto,minmax(0,1fr),auto] xl:items-center">
        <div className="flex flex-wrap items-center gap-2 xl:flex-nowrap">
          <div className="inline-flex h-10 w-fit rounded-lg border border-surface-container-high bg-surface-container-lowest p-0.5 text-sm">
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
                  className={`inline-flex h-9 min-w-[92px] items-center justify-center gap-1.5 rounded-md px-3 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                    selected
                      ? 'bg-primary text-on-primary font-medium'
                      : 'text-on-surface-variant hover:bg-surface-container-high'
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-xs ${
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
          <div className="inline-flex h-10 w-fit rounded-lg border border-surface-container-high bg-surface-container-lowest p-0.5 text-sm">
            {ITEMS.map((item) => {
              const selected = active === item.key
              return (
                <NavLink
                  key={item.key}
                  to={`${normalizedBasePath}${item.path}${bidTypeQuery}`}
                  className={`inline-flex h-9 min-w-[88px] items-center justify-center rounded-md px-3 transition-colors ${
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

        <div className="min-w-0 xl:px-3">
          <h1 className="truncate text-lg font-headline font-bold text-on-surface">{title}</h1>
          {subtitle ? <p className="mt-1 truncate text-xs text-outline">{subtitle}</p> : null}
        </div>

        <div className="flex min-w-0 flex-col gap-2 xl:items-end">
          {actions ? <div className="min-w-0 max-w-full overflow-x-auto">{actions}</div> : null}
          {meta ? <div className="min-h-7 min-w-0 max-w-full overflow-hidden">{meta}</div> : null}
        </div>
      </div>
    </div>
  )
}
