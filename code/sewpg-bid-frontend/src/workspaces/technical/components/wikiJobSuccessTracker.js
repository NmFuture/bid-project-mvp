// 跟踪流水线 Wiki 任务的「运行 → 成功」跳变，供进度组件通知页面刷新。
// 进度条每 5 秒轮询一次同一份快照，必须按 jobId 去重：同一任务成功后
// 只通知一次；页面打开时任务已是成功终态（未见过运行中）不补通知，
// 避免进入页面就重复拉取目录树。
export const createWikiJobSuccessTracker = () => {
  let runningJobId = ''
  let notifiedJobId = ''

  // 传入最新快照的 wiki 段，返回本次新检测到成功的 jobId；无需通知时返回 ''。
  return (wiki) => {
    const status = String(wiki?.status || '')
    const jobId = String(wiki?.jobId || '')
    if (!jobId) return ''
    if (status === 'running') {
      runningJobId = jobId
      return ''
    }
    if (status === 'succeeded' && jobId === runningJobId && jobId !== notifiedJobId) {
      notifiedJobId = jobId
      return jobId
    }
    return ''
  }
}
