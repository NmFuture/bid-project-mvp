// 一键填写（正文+附表）跑在 Redis worker 队列里（job_type=technical_body_fill），
// 右下角后台任务卡片和缺口页的按钮必须用同一套算法，否则同一个任务两处显示两个数。

export const bodyFillRunning = (state) => (
  ['queued', 'running'].includes(String(state?.status || ''))
)

/** 进度百分比：按已完成的目录项数算，与按钮上的「填写中 done/total」同源。 */
export function bodyFillDisplayPercentage(state) {
  const status = String(state?.status || '')
  if (status === 'succeeded' || status === 'completed') return 100
  if (!bodyFillRunning(state)) return 0
  const total = Number(state?.total || 0)
  if (total <= 0) return 5
  const done = Math.max(0, Math.min(total, Number(state?.done || 0)))
  // 排到队里还没开跑时给 5%，别让卡片停在 0 看着像没提交成功
  return Math.max(5, Math.round((done / total) * 100))
}

export function summarizeBodyFill(state) {
  const total = Number(state?.total || 0)
  const current = String(state?.current || '')
  if (bodyFillRunning(state) && total > 0) {
    return `${Number(state?.done || 0)}/${total}${current ? ` · ${current}` : ''}`
  }
  return String(state?.message || '') || current || '处理中...'
}
