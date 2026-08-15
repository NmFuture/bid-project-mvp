// 实现已合并到 shared/utils/parseUploadRecovery.js（技术标为全量超集），
// 这里只保留原路径的薄壳，页面与测试的 import 不变。
export {
  isUploadAndRunTimeout,
  isParseProgressCompleted,
  isParseProgressFailed,
  isParseResultCompleted,
  formatParseDuration,
  parseElapsedSeconds,
  parseDisplayPercentage,
  mergeMonotonicParseProgress,
  summarizeParseProgress,
  shouldPollParseProgress,
  pollParseProgressOnce,
  recoverUploadAndRunTimeout,
} from '../shared/utils/parseUploadRecovery.js'
