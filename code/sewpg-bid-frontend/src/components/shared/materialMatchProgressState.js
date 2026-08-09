// 素材匹配弹窗的状态由页面持有：技术标与商务标共用同一套记账，
// 保证两条线的耗时口径一致（起点是点击确认时刻，终点是接口返回时刻）。
export const idleMaterialMatchProgress = () => ({
  open: false,
  running: false,
  error: '',
  startedAtMs: 0,
  finishedAtMs: 0,
})

export const startedMaterialMatchProgress = (nowMs = Date.now()) => ({
  open: true,
  running: true,
  error: '',
  startedAtMs: nowMs,
  finishedAtMs: 0,
})

export const finishedMaterialMatchProgress = (previous, error = '', nowMs = Date.now()) => ({
  open: true,
  running: false,
  error,
  startedAtMs: Number(previous?.startedAtMs) || nowMs,
  finishedAtMs: nowMs,
})
