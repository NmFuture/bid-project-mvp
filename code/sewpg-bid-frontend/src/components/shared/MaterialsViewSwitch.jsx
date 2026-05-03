import { NavLink } from 'react-router-dom'

const ITEMS = [
  { key: 'structured', label: '原始素材', path: '/structured' },
  { key: 'wiki', label: 'Wiki', path: '/wiki' },
]

const BID_TYPE_ITEMS = [
  { value: '技术标', label: '技术标', icon: 'engineering' },
  { value: '商务标', label: '商务标', icon: 'request_quote' },
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
          <div className="flex flex-wrap gap-2">
            <div className="inline-flex w-fit rounded-lg border border-surface-container-high bg-surface-container-lowest p-1 text-sm">
              {BID_TYPE_ITEMS.map((item) => {
                const selected = bidType === item.value
                const disabled = Boolean(lockedBidType && lockedBidType !== item.value)
                return (
                  <button
                    key={item.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => onBidTypeChange?.(item.value)}
                    className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                      selected
                        ? 'bg-primary text-on-primary font-medium'
                        : 'text-on-surface-variant hover:bg-surface-container-high'
                    }`}
                  >
                    <span className="material-symbols-outlined text-[17px]">{item.icon}</span>
                    {item.label}
                  </button>
                )
              })}
            </div>
            <div className="inline-flex w-fit rounded-lg border border-surface-container-high bg-surface-container-lowest p-1 text-sm">
              {ITEMS.map((item) => {
                const selected = active === item.key
                return (
                  <NavLink
                    key={item.key}
                    to={`${normalizedBasePath}${item.path}${bidTypeQuery}`}
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
          </div>
          {meta ? <div className="min-w-0">{meta}</div> : null}
        </div>
      </div>
    </div>
  )
}
