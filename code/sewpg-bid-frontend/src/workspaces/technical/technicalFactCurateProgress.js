// 事实表 AI 填写（fact_curate）跟解析、目录生成一样跑在 Redis worker 队列里，
// 右下角后台任务卡片和事实表弹窗的进度条必须用同一套算法，否则同一个任务两处显示两个数。

// 与后端 technical_fact_curate_job.FACT_CURATE_PHASES 一一对应，改动需同步
export const FACT_CURATE_PHASES = [
  '保存当前编辑',
  '刷新事实表',
  '组装素材清单',
  'AI 分析素材',
  '回收建议落表',
]

export const factCurateRunning = (state) => (
  ['queued', 'running'].includes(String(state?.status || ''))
)

/** 进度百分比：AI 分析阶段有真实批次数就按批次算，其余阶段按阶段序号粗估。 */
export function factCurateDisplayPercentage(state) {
  const status = String(state?.status || '')
  if (status === 'succeeded') return 100
  if (!factCurateRunning(state)) return 0

  const batchTotal = Number(state?.batchTotal || 0)
  if (batchTotal > 0) {
    const done = Math.max(0, Math.min(batchTotal, Number(state?.batchDone || 0)))
    // 批次进度落在「AI 分析素材」这一阶段内部：前两阶段已过，末阶段还没开始，
    // 所以映射到 40%~90% 而不是 0%~100%，免得批次跑完显示 100% 却还在落表。
    return Math.round(40 + (done / batchTotal) * 50)
  }

  const index = FACT_CURATE_PHASES.indexOf(String(state?.phase || ''))
  if (index < 0) return 5
  return Math.round(((index + 1) / (FACT_CURATE_PHASES.length + 1)) * 100)
}

export const summarizeFactCurate = (state) => (
  String(state?.message || '') || String(state?.phase || '') || '处理中...'
)
