import { createElement } from 'react'

const actionClassName = (action) => {
  if (action === '必要') return 'border-primary/20 bg-primary/10 text-primary'
  if (action === '建议增加') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (action === '建议删除') return 'border-red-200 bg-red-50 text-red-800'
  if (action === '待确认') return 'border-amber-200 bg-amber-50 text-amber-950'
  return 'border-secondary/20 bg-secondary-container text-on-secondary-container'
}

export default function OutlineActionTag({ action, basis, reason, onFocusBasis }) {
  const className = `shrink-0 rounded border px-2 py-1 text-[11px] font-semibold ${actionClassName(action)}`

  if (!basis) {
    return createElement('span', { className, title: reason || '' }, action)
  }

  const title = reason ? `${reason}；点击定位招标依据` : '点击定位招标依据'
  return createElement('button', {
    type: 'button',
    className: `${className} transition-colors hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-secondary/30`,
    title,
    onClick: (event) => {
      event.stopPropagation()
      onFocusBasis?.(basis)
    },
  }, action)
}
