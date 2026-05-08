import { useEffect, useState } from 'react'

// 多阶段假进度条。
// stages: [{ label, durationMs }]，按顺序点亮，最后一个完成后调用 onDone。
// 每阶段中间用条纹 + 流光动效，已完成阶段静态色块，未到达阶段灰色。
export default function FakeProgress({ stages = [], onDone, className = '', showPercent = true }) {
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    if (idx >= stages.length) return undefined
    const cur = stages[idx]
    const t = setTimeout(() => {
      const next = idx + 1
      setIdx(next)
      if (next >= stages.length) onDone?.()
    }, cur?.durationMs ?? 800)
    return () => clearTimeout(t)
  }, [idx, stages, onDone])

  const total = stages.length || 1
  const pct = Math.min(100, Math.round((idx / total) * 100))

  return (
    <div className={className}>
      <div className="flex items-center justify-between mb-2 text-xs">
        <span className="text-on-surface-variant">
          {idx >= stages.length ? '完成' : (stages[idx]?.label ?? '准备中')}
        </span>
        {showPercent && (
          <span className="font-mono font-medium text-on-surface tabular-nums">{pct}%</span>
        )}
      </div>
      <div className="relative h-2 w-full bg-surface-container-high rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-primary to-primary-container transition-all duration-500 ease-out relative overflow-hidden"
          style={{ width: `${pct}%` }}
        >
          {idx < stages.length && <div className="absolute inset-0 bg-stripes opacity-40" />}
        </div>
      </div>
      <ul className="mt-3 space-y-1.5 text-xs">
        {stages.map((stage, i) => {
          const active = i === idx
          const done = i < idx
          return (
            <li
              key={`${stage.label}-${i}`}
              className={`flex items-center gap-2 transition-colors ${
                active
                  ? 'text-on-surface font-medium'
                  : done
                    ? 'text-secondary'
                    : 'text-outline'
              }`}
            >
              <span
                className={`material-symbols-outlined text-[16px] ${
                  active ? 'animate-spin-slow' : ''
                }`}
                style={{ fontVariationSettings: done ? "'FILL' 1" : "'FILL' 0" }}
              >
                {done ? 'check_circle' : active ? 'progress_activity' : 'radio_button_unchecked'}
              </span>
              <span>{stage.label}</span>
              {active && (
                <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-primary animate-pulse-soft" />
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
