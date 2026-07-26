import { createElement, useId, useState } from 'react'
import { createPortal } from 'react-dom'

const actionClassName = (action) => {
  if (action === '必要') return 'border-primary/20 bg-primary/10 text-primary'
  if (action === '建议增加') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (action === '建议删除') return 'border-red-200 bg-red-50 text-red-800'
  if (action === '待确认') return 'border-amber-200 bg-amber-50 text-amber-950'
  return 'border-secondary/20 bg-secondary-container text-on-secondary-container'
}

export const getImmediateTooltipPosition = (trigger, bounds, viewport) => {
  const gap = 4
  const spaceBelow = bounds.bottom - trigger.bottom
  const spaceAbove = trigger.top - bounds.top
  const showAbove = spaceBelow < 80 && spaceAbove > spaceBelow
  const availableHeight = showAbove ? spaceAbove - gap : spaceBelow - gap
  return {
    top: showAbove ? null : Math.max(8, trigger.bottom + gap),
    bottom: showAbove ? Math.max(8, viewport.height - trigger.top + gap) : null,
    right: Math.max(8, viewport.width - Math.min(trigger.right, bounds.right - 8)),
    maxWidth: Math.max(120, Math.min(320, bounds.width - 16)),
    maxHeight: Math.max(40, Math.min(240, availableHeight)),
  }
}

export default function OutlineActionTag({ action, basis, reason, onFocusBasis }) {
  const className = `shrink-0 rounded border px-2 py-1 text-[11px] font-semibold ${actionClassName(action)}`
  const canFocusBasis = Boolean(basis) && (action === '必要' || action === '建议增加')
  const tooltip = canFocusBasis
    ? (reason ? `${reason}；点击定位招标依据` : '点击定位招标依据')
    : reason
  const tooltipId = useId()
  const [tooltipPosition, setTooltipPosition] = useState(null)

  const trigger = canFocusBasis
    ? createElement('button', {
        type: 'button',
        className: `${className} transition-colors hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-secondary/30`,
        'aria-describedby': tooltip ? tooltipId : undefined,
        onClick: (event) => {
          event.stopPropagation()
          onFocusBasis?.(basis)
        },
      }, action)
    : createElement('span', {
        className,
        'aria-label': tooltip ? `${action}：${tooltip}` : undefined,
      }, action)

  if (!tooltip) return trigger

  const showTooltip = (event) => {
    const element = event.currentTarget
    const view = element.ownerDocument?.defaultView
    if (!view) return
    const triggerRect = element.getBoundingClientRect()
    const scrollContainer = element.closest('[data-outline-scroll]')
    const boundsRect = scrollContainer?.getBoundingClientRect() || {
      top: 8,
      right: view.innerWidth - 8,
      bottom: view.innerHeight - 8,
      left: 8,
      width: view.innerWidth - 16,
      height: view.innerHeight - 16,
    }
    setTooltipPosition(getImmediateTooltipPosition(
      triggerRect,
      boundsRect,
      { width: view.innerWidth, height: view.innerHeight },
    ))
  }

  const tooltipNode = tooltipPosition && typeof document !== 'undefined'
    ? createPortal(createElement('span', {
        id: tooltipId,
        role: 'tooltip',
        className: 'pointer-events-none fixed z-[100] w-max whitespace-normal rounded-sm border border-outline-variant bg-surface px-2 py-1 text-xs font-normal leading-4 text-on-surface shadow-sm',
        style: {
          top: tooltipPosition.top == null ? undefined : `${tooltipPosition.top}px`,
          bottom: tooltipPosition.bottom == null ? undefined : `${tooltipPosition.bottom}px`,
          right: `${tooltipPosition.right}px`,
          maxWidth: `${tooltipPosition.maxWidth}px`,
          maxHeight: `${tooltipPosition.maxHeight}px`,
          overflowY: 'auto',
        },
      }, tooltip), document.body)
    : null

  return createElement('span', {
    className: 'shrink-0',
    'data-tooltip-text': tooltip,
    onMouseEnter: showTooltip,
    onMouseLeave: () => setTooltipPosition(null),
  }, trigger, tooltipNode)
}
