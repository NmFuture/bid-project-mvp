import Button from '../ui/Button'

export default function MaterialMatchProgressModal({
  open,
  running,
  error,
  onClose,
}) {
  if (!open) return null

  const failed = Boolean(error)
  const title = failed ? '素材匹配失败' : running ? '正在执行素材匹配' : '素材匹配已完成'
  const progress = failed ? 100 : running ? 68 : 100

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="w-full max-w-xl rounded-lg bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">{title}</h3>
          </div>
          {!running ? (
            <Button type="button" onClick={onClose} size="sm" variant="quiet">
              关闭
            </Button>
          ) : null}
        </div>
        <div className="space-y-4 p-5">
          <div className="flex items-center gap-3">
            <div
              className="h-3 flex-1 overflow-hidden rounded-full bg-surface-container-high"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress}
            >
              <div
                className={`h-full transition-all duration-300 ${failed ? 'bg-error' : 'bg-primary'}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-12 text-right text-xs font-semibold text-outline">{progress}%</span>
          </div>
          {failed ? (
            <div className="rounded-md border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
              {error}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
