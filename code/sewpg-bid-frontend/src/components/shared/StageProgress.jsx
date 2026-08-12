export default function StageProgress({
  stages = [],
  onStageClick,
  getStageLockReason,
}) {
  const activeStageIndex = stages.findIndex((stage) => stage.status === 'active')
  const denominator = Math.max(1, stages.length - 1)
  const completedFallbackIndex = stages.reduce((highest, stage, index) => (
    stage.status === 'completed' ? index : highest
  ), -1)
  const progressIndex = activeStageIndex >= 0 ? activeStageIndex : completedFallbackIndex
  const progressRatio = progressIndex > 0 ? progressIndex / denominator : 0
  const nodeSlotWidthPx = stages.length <= 4 ? 132 : stages.length <= 6 ? 112 : 94
  const nodeCenterOffsetPx = nodeSlotWidthPx / 2
  const progressWidthPx = Math.max(nodeSlotWidthPx * stages.length, 560)

  return (
    <section aria-label="项目阶段" className="stage-progress-shell overflow-x-auto bg-transparent px-0 py-3">
      <div className="relative" style={{ width: `max(100%, ${progressWidthPx}px)` }}>
        <div
          aria-hidden="true"
          className="absolute top-[15px] -z-0 h-[2px] bg-outline-variant"
          style={{
            left: `${nodeCenterOffsetPx}px`,
            width: `calc(100% - ${nodeSlotWidthPx}px)`,
          }}
        ></div>
        <div
          aria-hidden="true"
          className="absolute top-[15px] -z-0 h-[2px] bg-secondary"
          style={{
            left: `${nodeCenterOffsetPx}px`,
            width: `calc((100% - ${nodeSlotWidthPx}px) * ${progressRatio})`,
          }}
        ></div>
        <div className="relative z-10 flex items-start justify-between gap-1">
          {stages.map((stage, index) => {
            const isCompleted = stage.status === 'completed'
            const isActive = stage.status === 'active'
            const lockReason = getStageLockReason?.(stage.id) || ''
            const isLocked = Boolean(lockReason)
            return (
              <button
                type="button"
                key={stage.id}
                className={`group relative flex shrink-0 flex-col items-center gap-1.5 rounded-md bg-transparent py-0.5 ${
                  isLocked ? 'cursor-not-allowed' : 'cursor-pointer'
                }`}
                style={{ width: `${nodeSlotWidthPx}px` }}
                aria-current={isActive ? 'step' : undefined}
                aria-label={`${stage.name}${isCompleted ? '，已完成' : isActive ? '，当前阶段' : ''}${isLocked ? `，${lockReason}` : ''}`}
                disabled={isLocked}
                onClick={() => {
                  if (isLocked) return
                  onStageClick?.(stage)
                }}
                title={isLocked ? lockReason : ''}
              >
                <div
                  aria-hidden="true"
                  className={`stage-node-circle flex h-8 w-8 items-center justify-center border text-sm font-semibold transition-colors ${
                    isCompleted
                      ? 'border-on-secondary-fixed bg-on-secondary-fixed text-white'
                      : isActive
                        ? 'border-primary bg-primary text-white'
                        : 'border-outline-variant bg-white text-on-surface-variant'
                  }`}
                >
                  {isCompleted ? '✓' : index + 1}
                </div>
                <span
                  className={`text-center text-xs font-medium leading-[18px] ${
                    isActive
                      ? 'font-semibold text-primary'
                      : isCompleted
                        ? 'text-on-surface'
                        : 'text-on-surface-variant'
                  }`}
                >
                  {stage.name}
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}
