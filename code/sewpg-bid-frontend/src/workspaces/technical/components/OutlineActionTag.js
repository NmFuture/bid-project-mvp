import { createElement } from 'react'

const actionClassName = (action) => {
  if (action === '必要') return 'border-primary/20 bg-primary/10 text-primary'
  if (action === '建议增加') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (action === '建议删除') return 'border-red-200 bg-red-50 text-red-800'
  if (action === '待确认') return 'border-amber-200 bg-amber-50 text-amber-950'
  return 'border-secondary/20 bg-secondary-container text-on-secondary-container'
}

const withImmediateTooltip = (trigger, text) => {
  if (!text) return trigger
  return createElement('span', { className: 'group relative shrink-0' },
    trigger,
    createElement('span', {
      role: 'tooltip',
      className: 'pointer-events-none absolute right-0 top-full z-30 mt-1 hidden w-max max-w-80 whitespace-normal rounded-sm border border-outline-variant bg-surface px-2 py-1 text-xs font-normal leading-4 text-on-surface shadow-sm group-hover:block',
    }, text))
}

export default function OutlineActionTag({ action, basis, reason, onFocusBasis }) {
  const className = `shrink-0 rounded border px-2 py-1 text-[11px] font-semibold ${actionClassName(action)}`
  const canFocusBasis = Boolean(basis) && (action === '必要' || action === '建议增加')

  if (!canFocusBasis) {
    return withImmediateTooltip(createElement('span', { className }, action), reason)
  }

  const tooltip = reason ? `${reason}；点击定位招标依据` : '点击定位招标依据'
  const button = createElement('button', {
    type: 'button',
    className: `${className} transition-colors hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-secondary/30`,
    onClick: (event) => {
      event.stopPropagation()
      onFocusBasis?.(basis)
    },
  }, action)
  return withImmediateTooltip(button, tooltip)
}
