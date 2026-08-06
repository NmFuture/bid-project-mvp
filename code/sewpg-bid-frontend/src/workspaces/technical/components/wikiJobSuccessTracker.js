const VALID_WIKI_JOB_STATUSES = new Set([
  'idle',
  'queued',
  'running',
  'succeeded',
  'failed',
  'cancelled',
])

// 跟踪页面打开后新完成的 Wiki 任务，供进度组件通知页面刷新。
// 第一次有效快照只建立基准，避免进入页面时为已有成功任务重复拉取目录树；
// 后续每个成功 jobId 只通知一次。不能要求先观察到 running：任务可能在
// 5 秒轮询间隔内完成，补跑任务也会让 latest jobId 从上一任务切到新任务。
export const createWikiJobSuccessTracker = () => {
  let initialized = false
  const handledSucceededJobIds = new Set()

  // 传入最新快照的 wiki 段，返回本次新检测到成功的 jobId；无需通知时返回 ''。
  return (wiki) => {
    const status = String(wiki?.status || '')
    const jobId = String(wiki?.jobId || '')
    // idle 是无 jobId 的合法基准；其余状态缺少 jobId 时视为无效快照，不建立基准。
    if (!VALID_WIKI_JOB_STATUSES.has(status) || (!jobId && status !== 'idle')) return ''

    if (!initialized) {
      initialized = true
      if (status === 'succeeded') handledSucceededJobIds.add(jobId)
      return ''
    }

    if (status !== 'succeeded' || handledSucceededJobIds.has(jobId)) return ''
    handledSucceededJobIds.add(jobId)
    return jobId
  }
}
