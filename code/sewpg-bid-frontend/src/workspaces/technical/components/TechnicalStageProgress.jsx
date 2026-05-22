export default function TechnicalStageProgress({
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
  const nodeSlotWidthPx = stages.length <= 4 ? 112 : stages.length <= 6 ? 100 : 88
  const nodeCenterOffsetPx = nodeSlotWidthPx / 2
  const shellClassName = 'stage-progress-shell min-h-[74px] rounded-md border border-outline-variant/45 bg-[#f7fbff] px-4 py-3'

  return (
    <section className={shellClassName}>
      <div className="relative">
        <div
          className="absolute top-[12px] h-[2px] bg-[#d7e1ea] -z-0"
          style={{
            left: `${nodeCenterOffsetPx}px`,
            width: `calc(100% - ${nodeSlotWidthPx}px)`,
          }}
        ></div>
        <div
          className="absolute top-[12px] h-[2px] bg-[#14A83B] -z-0 transition-all duration-500"
          style={{
            left: `${nodeCenterOffsetPx}px`,
            width: `calc((100% - ${nodeSlotWidthPx}px) * ${progressRatio})`,
          }}
        ></div>
        <div className="flex justify-between items-start relative z-10 gap-1">
          {stages.map((stage, index) => {
            const isCompleted = stage.status === 'completed'
            const isActive = stage.status === 'active'
            const lockReason = getStageLockReason?.(stage.id) || ''
            const isLocked = Boolean(lockReason)
            return (
              <div
                key={stage.id}
                className={`flex flex-col items-center gap-1 relative group rounded-md px-1 py-0.5 transition-opacity ${
                  isLocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
                }`}
                style={{ width: `${nodeSlotWidthPx}px` }}
                onClick={() => {
                  if (isLocked) return
                  onStageClick?.(stage)
                }}
                title={isLocked ? lockReason : ''}
              >
                <div
                  className={`stage-node-circle w-6 h-6 border flex items-center justify-center text-[12px] font-semibold transition-all duration-200 ${
                    isCompleted
                      ? 'bg-[#14A83B] border-[#14A83B] text-white shadow-[0_8px_18px_-14px_rgba(20,168,59,0.7)]'
                      : isActive
                        ? 'bg-[#0067B6] border-[#0067B6] text-white ring-4 ring-primary/12 shadow-[0_8px_18px_-14px_rgba(0,104,183,0.7)]'
                        : 'bg-white border-[#c7d3e0] text-[#8ca1b5]'
                  }`}
                >
                  {isCompleted ? '✓' : index + 1}
                </div>
                <span
                  className={`max-w-[96px] text-xs font-medium text-center leading-tight ${
                    isActive
                      ? 'text-[#0067B6] font-semibold'
                      : isCompleted
                        ? 'text-[#2f4a62]'
                        : 'text-[#8095aa]'
                  }`}
                >
                  {stage.name}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
