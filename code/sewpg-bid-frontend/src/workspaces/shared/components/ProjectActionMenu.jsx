import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getProjectActionMenuPosition } from '../projectActionMenuPosition'

const MENU_WIDTH = 144
const ESTIMATED_MENU_HEIGHT = 76

export default function ProjectActionMenu({
  project,
  open,
  loading,
  onToggle,
  onClose,
  onViewParseResult,
  onDelete,
}) {
  const triggerRef = useRef(null)
  const menuRef = useRef(null)
  const [position, setPosition] = useState(null)
  const menuId = `project-actions-${project.id}`

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return
    const menuHeight = menuRef.current?.offsetHeight || ESTIMATED_MENU_HEIGHT
    setPosition(getProjectActionMenuPosition({
      triggerRect: trigger.getBoundingClientRect(),
      menuWidth: MENU_WIDTH,
      menuHeight,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    }))
  }, [])

  const captureMenuRef = useCallback((node) => {
    menuRef.current = node
    if (node) updatePosition()
  }, [updatePosition])

  useEffect(() => {
    if (!open) return undefined
    const handleViewportChange = () => updatePosition()
    const handlePointerDown = (event) => {
      if (triggerRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) return
      onClose()
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose()
        triggerRef.current?.focus()
      }
    }

    window.addEventListener('resize', handleViewportChange)
    window.addEventListener('scroll', handleViewportChange, true)
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('resize', handleViewportChange)
      window.removeEventListener('scroll', handleViewportChange, true)
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose, open, updatePosition])

  return (
    <>
      <button
        ref={triggerRef}
        className="px-1 py-0 !border-0 !bg-transparent text-on-surface-variant hover:text-primary transition-colors"
        type="button"
        aria-label={`打开 ${project.name || project.id} 的操作菜单`}
        aria-haspopup="menu"
        aria-controls={open ? menuId : undefined}
        aria-expanded={open}
        onClick={(event) => {
          event.stopPropagation()
          if (!open) updatePosition()
          onToggle()
        }}
      >
        <span className="material-symbols-outlined text-[20px]">more_vert</span>
      </button>
      {open && position && createPortal(
        <div
          ref={captureMenuRef}
          id={menuId}
          className="fixed w-36 bg-surface-container-lowest border border-surface-container-high z-[100] py-1 shadow-[0_1px_2px_rgba(11,27,44,0.08)]"
          style={{ left: position.left, top: position.top }}
          role="menu"
          data-placement={position.placement}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            className="w-full text-left px-3 py-1.5 text-sm text-on-surface hover:bg-surface-container-low transition-colors"
            onClick={onViewParseResult}
          >
            查看解析结果
          </button>
          <button
            type="button"
            role="menuitem"
            className="w-full text-left px-3 py-1.5 text-sm text-error hover:bg-error-container/20 transition-colors disabled:opacity-50"
            disabled={loading}
            onClick={onDelete}
          >
            {loading ? '删除中...' : '删除项目'}
          </button>
        </div>,
        document.body,
      )}
    </>
  )
}
