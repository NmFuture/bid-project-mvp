const VIEWPORT_MARGIN = 8

export const getProjectActionMenuPosition = ({
  triggerRect,
  menuWidth,
  menuHeight,
  viewportWidth,
  viewportHeight,
  gap = 6,
}) => {
  const maxLeft = Math.max(VIEWPORT_MARGIN, viewportWidth - menuWidth - VIEWPORT_MARGIN)
  const left = Math.min(
    Math.max(VIEWPORT_MARGIN, triggerRect.right - menuWidth),
    maxLeft,
  )
  const spaceBelow = viewportHeight - triggerRect.bottom - gap - VIEWPORT_MARGIN
  const spaceAbove = triggerRect.top - gap - VIEWPORT_MARGIN
  const opensUpward = spaceBelow < menuHeight && spaceAbove > spaceBelow
  const desiredTop = opensUpward
    ? triggerRect.top - gap - menuHeight
    : triggerRect.bottom + gap
  const maxTop = Math.max(VIEWPORT_MARGIN, viewportHeight - menuHeight - VIEWPORT_MARGIN)

  return {
    left,
    top: Math.min(Math.max(VIEWPORT_MARGIN, desiredTop), maxTop),
    placement: opensUpward ? 'top' : 'bottom',
  }
}
