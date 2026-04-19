export default function StageProgress({
  stages = [],
  title = '项目进度概览',
  onStageClick,
  getStageLockReason,
}) {
  const activeStageIndex = stages.findIndex((stage) => stage.status === 'active')
  const denominator = Math.max(1, stages.length - 1)
  const progressWidth =
    activeStageIndex > 0 ? `${(activeStageIndex / denominator) * 100}%` : '0%'

  return (
    <section className="bg-surface-container-lowest p-6 rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.08)]">
      <h2 className="text-sm font-semibold text-on-surface-variant mb-6 font-headline tracking-wide uppercase">
        {title}
      </h2>
      <div className="relative">
        <div className="absolute top-4 left-0 w-full h-1 bg-surface-container-high -z-0 rounded-full"></div>
        <div
          className="absolute top-4 left-0 h-1 bg-secondary -z-0 rounded-full"
          style={{ width: progressWidth }}
        ></div>
        <div className="flex justify-between items-start relative z-10">
          {stages.map((stage) => {
            const isCompleted = stage.status === 'completed'
            const isActive = stage.status === 'active'
            const lockReason = getStageLockReason?.(stage.id) || ''
            const isLocked = Boolean(lockReason)
            return (
              <div
                key={stage.id}
                className={`flex flex-col items-center gap-2 w-20 relative group ${
                  isLocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
                }`}
                onClick={() => {
                  if (isLocked) return
                  onStageClick?.(stage)
                }}
                title={isLocked ? lockReason : ''}
              >
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                    isCompleted
                      ? 'bg-secondary text-on-secondary shadow-md shadow-secondary/20'
                      : isActive
                        ? 'bg-primary-container text-on-primary ring-4 ring-primary-fixed shadow-lg shadow-primary-container/30 animate-pulse-blue'
                        : 'bg-surface-container-high text-outline'
                  }`}
                >
                  {isCompleted ? (
                    <span
                      className="material-symbols-outlined text-sm"
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      check
                    </span>
                  ) : (
                    <span className="text-sm font-bold">{stage.id}</span>
                  )}
                </div>
                <span
                  className={`text-xs font-medium text-center tracking-wide ${
                    isActive
                      ? 'text-primary font-bold'
                      : isCompleted
                        ? 'text-on-surface'
                        : 'text-outline'
                  }`}
                >
                  {stage.isHuman && '['}
                  {stage.name}
                  {stage.isHuman && ']'}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
