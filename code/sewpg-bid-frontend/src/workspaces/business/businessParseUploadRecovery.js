// 实现已合并到 shared/utils/parseUploadRecovery.js，这里只保留原路径的薄壳。
// 注意：商务标历史上的 mergeMonotonicParseProgress 不做计数单调合并，
// 薄壳用 monotonicCounters: false 固定这一行为，页面调用保持不变。
import { mergeMonotonicParseProgress as mergeSharedMonotonicParseProgress } from '../shared/utils/parseUploadRecovery.js'

export {
  isUploadAndRunTimeout,
  isParseProgressCompleted,
  isParseProgressFailed,
  isParseResultCompleted,
  shouldPollParseProgress,
  pollParseProgressOnce,
  recoverUploadAndRunTimeout,
} from '../shared/utils/parseUploadRecovery.js'

export const mergeMonotonicParseProgress = (previous = null, incoming = null) =>
  mergeSharedMonotonicParseProgress(previous, incoming, { monotonicCounters: false })
