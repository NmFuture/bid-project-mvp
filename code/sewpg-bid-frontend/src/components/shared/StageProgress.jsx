export default function StageProgress({
  stages = [],
  onStageClick,
  getStageLockReason,
}) {
  const activeStageIndex = stages.findIndex((stage) => stage.status === 'active')
  const denominator = Math.max(1, stages.length - 1)
  const progressRatio = activeStageIndex > 0 ? activeStageIndex / denominator : 0
  const nodeSlotWidthPx = 94
  const nodeCenterOffsetPx = nodeSlotWidthPx / 2

  return (
    <section className="stage-progress-shell bg-white px-0 py-2">
      <div className="relative">
        <div
          className="absolute top-[14px] h-[2px] bg-[#cfd9e3] -z-0"
          style={{
            left: `${nodeCenterOffsetPx}px`,
            width: `calc(100% - ${nodeSlotWidthPx}px)`,
          }}
        ></div>
        <div
          className="absolute top-[14px] h-[2px] bg-[#14A83B] -z-0"
          style={{
            left: `${nodeCenterOffsetPx}px`,
            width: `calc((100% - ${nodeSlotWidthPx}px) * ${progressRatio})`,
          }}
        ></div>
        <div className="flex justify-between items-start relative z-10 gap-1">
          {stages.map((stage) => {
            const isCompleted = stage.status === 'completed'
            const isActive = stage.status === 'active'
            const lockReason = getStageLockReason?.(stage.id) || ''
            const isLocked = Boolean(lockReason)
            return (
              <div
                key={stage.id}
                className={`flex flex-col items-center gap-2 w-[94px] relative group ${
                  isLocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
                }`}
                onClick={() => {
                  if (isLocked) return
                  onStageClick?.(stage)
                }}
                title={isLocked ? lockReason : ''}
              >
                <div
                  className={`stage-node-circle w-7 h-7 border flex items-center justify-center text-[13px] font-semibold transition-colors ${
                    isCompleted
                      ? 'bg-[#14A83B] border-[#14A83B] text-white'
                      : isActive
                        ? 'bg-[#0067B6] border-[#0067B6] text-white'
                        : 'bg-white border-[#c7d3e0] text-[#8ca1b5]'
                  }`}
                >
                  {isCompleted ? '✓' : stage.id}
                </div>
                <span
                  className={`text-xs font-medium text-center leading-tight ${
                    isActive
                      ? 'text-[#0067B6] font-semibold'
                      : isCompleted
                        ? 'text-[#2f4a62]'
                        : 'text-[#8095aa]'
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
