import { useEffect, useState } from 'react'

export default function OnlyOfficeWorkspace({
  sidebar,
  documentTitle,
  documentSubtitle,
  documentMeta,
  children,
  className = '',
  heightClass = 'min-h-[640px]',
  gridClassName = 'xl:grid-cols-[minmax(20rem,28rem)_minmax(0,1fr)]',
  sidebarClassName = '',
  documentAreaClassName = '',
}) {
  const [fullscreen, setFullscreen] = useState(false)

  useEffect(() => {
    if (!fullscreen) return undefined

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setFullscreen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [fullscreen])

  const fullscreenLabel = fullscreen ? '退出全屏' : '全屏查看'

  return (
    <div
      className={[
        fullscreen
          ? 'fixed inset-0 z-[160] bg-surface p-3 sm:p-4'
          : `relative ${className}`,
      ].join(' ')}
    >
      <div
        className={[
          'grid grid-cols-1 overflow-hidden rounded-md border border-outline-variant/50 bg-surface-container-lowest shadow-[0_1px_3px_rgba(13,33,55,0.08)]',
          gridClassName,
          fullscreen ? 'h-full' : heightClass,
        ].join(' ')}
      >
        <aside
          className={[
            'min-h-0 overflow-hidden border-b border-surface-container-high bg-surface-container-lowest xl:border-b-0 xl:border-r',
            sidebarClassName,
          ].join(' ')}
        >
          {sidebar}
        </aside>

        <section className="flex min-h-0 flex-col bg-white">
          <div className="flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-on-surface">
                {documentTitle}
              </h3>
              {documentSubtitle ? (
                <p className="mt-1 truncate text-xs text-outline" title={typeof documentSubtitle === 'string' ? documentSubtitle : undefined}>
                  {documentSubtitle}
                </p>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {documentMeta}
              <button
                type="button"
                aria-label={fullscreenLabel}
                aria-pressed={fullscreen}
                title={fullscreenLabel}
                onClick={() => setFullscreen((value) => !value)}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-container-high text-on-surface-variant transition-colors hover:bg-surface-dim hover:text-on-surface"
              >
                <span className="material-symbols-outlined text-[20px]">
                  {fullscreen ? 'close_fullscreen' : 'open_in_full'}
                </span>
              </button>
            </div>
          </div>

          <div className={['min-h-0 flex-1 p-4', documentAreaClassName].join(' ')}>
            {children}
          </div>
        </section>
      </div>
    </div>
  )
}
