import { useEffect, useState } from 'react'

export default function OnlyOfficeWorkspace({
  sidebar,
  documentTitle,
  documentSubtitle,
  documentMeta,
  children,
  className = '',
  heightClass = 'onlyoffice-workspace-height',
  gridClassName = 'xl:grid-cols-[minmax(20rem,28rem)_minmax(0,1fr)]',
  sidebarClassName = '',
  documentAreaClassName = '',
  headerClassName = '',
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
    <div className={['relative', className].join(' ')}>
      <div
        className={[
          'grid min-w-0 grid-cols-1 overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest',
          gridClassName,
          heightClass,
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

        <section
          aria-label={documentTitle || '文档工作区'}
          className={[
            fullscreen
              ? 'fixed inset-0 z-[160] flex min-h-0 flex-col bg-white'
              : 'flex min-h-0 flex-col bg-white',
          ].join(' ')}
        >
          <div className={[
            'flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3',
            headerClassName,
          ].join(' ')}>
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-on-surface">
                {documentTitle}
              </h3>
              {documentSubtitle ? (
                <p className="mt-1 truncate text-xs text-on-surface-variant" title={typeof documentSubtitle === 'string' ? documentSubtitle : undefined}>
                  {documentSubtitle}
                </p>
              ) : null}
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
              {documentMeta}
              <button
                type="button"
                aria-label={fullscreenLabel}
                aria-pressed={fullscreen}
                title={fullscreenLabel}
                onClick={() => setFullscreen((value) => !value)}
                className="ui-icon-control flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-container-low text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[20px]">
                  {fullscreen ? 'close_fullscreen' : 'open_in_full'}
                </span>
              </button>
            </div>
          </div>

          <div className={[
            'min-h-0 flex-1',
            fullscreen ? 'p-2 sm:p-3' : 'p-4',
            documentAreaClassName,
          ].join(' ')}>
            {children}
          </div>
        </section>
      </div>
    </div>
  )
}
