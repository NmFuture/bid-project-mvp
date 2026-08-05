import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  directoryDisplayPercentage,
  directoryElapsedSeconds,
  formatDirectoryDuration,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  mergeMonotonicDirectoryProgress,
  normalizeDecisionProgress,
  summarizeDirectoryProgress,
} from './technicalDirectoryProgress.js'

const runningTasks = [
  { id: 'task-1', label: '准备目录输入', status: 'done' },
  { id: 'task-2', label: 'Opencode 生成目录', status: 'running' },
  { id: 'task-3', label: '保存目录结果', status: 'pending' },
]

test('shows real decision counts as the running detail line', () => {
  const summary = summarizeDirectoryProgress({
    status: 'running',
    percentage: 42,
    summary: 'futurecode 正在执行 S2 目录生成和语义审核，请稍候。',
    decisionProgress: { phase: 'chapters', decided: 120, total: 240, chaptersDone: 5, chaptersTotal: 12 },
    tasks: runningTasks,
  })

  assert.equal(summary.title, '智能生成目录')
  assert.equal(summary.stepText, '第 2/3 步')
  assert.equal(summary.summary, '已判定目录条款 120/240 项')
  assert.equal(summary.statusText, '生成中')
  assert.equal(summary.tone, 'running')
  assert.doesNotMatch(
    `${summary.title}${summary.summary}${summary.steps.map((step) => step.label).join('')}`,
    /futurecode|opencode|S2|Skill|session|provider|model/i,
  )
})

test('labels appendix decision counts distinctly', () => {
  const summary = summarizeDirectoryProgress({
    status: 'running',
    percentage: 80,
    decisionProgress: { phase: 'appendix', decided: 3, total: 12 },
    tasks: runningTasks,
  })

  assert.equal(summary.summary, '已判定技术附表 3/12 项')
})

test('falls back to phase copy when decision counts are unavailable', () => {
  const preparing = summarizeDirectoryProgress({
    status: 'running',
    percentage: 2,
    tasks: [
      { id: 'task-1', label: '准备目录输入', status: 'running' },
      { id: 'task-2', label: 'Opencode 生成目录', status: 'pending' },
      { id: 'task-3', label: '保存目录结果', status: 'pending' },
    ],
  })
  const generating = summarizeDirectoryProgress({
    status: 'running',
    percentage: 40,
    tasks: runningTasks,
  })
  const saving = summarizeDirectoryProgress({
    status: 'running',
    percentage: 90,
    tasks: [
      { id: 'task-1', label: '准备目录输入', status: 'done' },
      { id: 'task-2', label: 'Opencode 生成目录', status: 'done' },
      { id: 'task-3', label: '保存目录结果', status: 'running' },
    ],
  })

  assert.equal(preparing.title, '准备生成资料')
  assert.equal(preparing.summary, '正在整理招标文件与投标模板，为目录生成做准备。')
  assert.equal(generating.summary, '正在分析招标要求并组织目录结构，请稍候。')
  assert.equal(saving.title, '保存目录结果')
  assert.equal(saving.summary, '目录结构已经生成，正在整理并保存结果。')
})

test('ignores invalid decision progress payloads', () => {
  assert.equal(normalizeDecisionProgress({}), null)
  assert.equal(normalizeDecisionProgress({ decisionProgress: { decided: 3, total: 0 } }), null)
  assert.deepEqual(
    normalizeDecisionProgress({ decisionProgress: { phase: 'chapters', decided: 500, total: 240 } }),
    { phase: 'chapters', decided: 240, total: 240 },
  )
})

test('anchors displayed percentage on backend progress and creeps between batches', () => {
  const startMs = Date.parse('2026-07-17T10:00:00Z')
  const running = {
    status: 'running',
    percentage: 42,
    percentageUpdatedAt: startMs,
    startedAt: '2026-07-17T10:00:00Z',
  }

  assert.equal(directoryDisplayPercentage(running, startMs), 42)
  assert.equal(directoryDisplayPercentage(running, startMs + 60 * 1000), 45)
  assert.equal(directoryDisplayPercentage(running, startMs + 30 * 60 * 1000), 48)
  assert.equal(directoryDisplayPercentage({ status: 'completed', percentage: 100 }, startMs), 100)
  assert.equal(directoryDisplayPercentage({ status: 'failed', percentage: 42 }, startMs), 42)
})

test('caps running display percentage below completion', () => {
  const startMs = Date.parse('2026-07-17T10:00:00Z')
  const nearlyDone = {
    status: 'running',
    percentage: 95,
    percentageUpdatedAt: startMs,
  }

  assert.equal(directoryDisplayPercentage(nearlyDone, startMs + 60 * 60 * 1000), 96)
})

test('stamps percentage anchors and keeps progress monotonic across merges', () => {
  const nowMs = Date.parse('2026-07-17T10:05:00Z')
  const first = mergeMonotonicDirectoryProgress(null, { status: 'running', percentage: 5 }, nowMs)
  assert.equal(first.percentageUpdatedAt, nowMs)

  const advanced = mergeMonotonicDirectoryProgress(
    first,
    { status: 'running', percentage: 42 },
    nowMs + 60 * 1000,
  )
  assert.equal(advanced.percentage, 42)
  assert.equal(advanced.percentageUpdatedAt, nowMs + 60 * 1000)

  const stale = mergeMonotonicDirectoryProgress(
    advanced,
    { status: 'running', percentage: 30 },
    nowMs + 120 * 1000,
  )
  assert.equal(stale.percentage, 42)
  assert.equal(stale.percentageUpdatedAt, nowMs + 60 * 1000)
})

test('keeps decision counts and start time from moving backwards', () => {
  const previous = {
    status: 'running',
    percentage: 42,
    startedAt: '2026-07-17T10:00:00Z',
    decisionProgress: { phase: 'chapters', decided: 120, total: 240 },
    tasks: runningTasks,
  }
  const staleCounts = mergeMonotonicDirectoryProgress(
    previous,
    { status: 'running', percentage: 42, decisionProgress: { phase: 'chapters', decided: 60, total: 240 }, tasks: runningTasks },
  )
  assert.equal(staleCounts.decisionProgress.decided, 120)
  assert.equal(staleCounts.startedAt, '2026-07-17T10:00:00Z')

  const phaseSwitch = mergeMonotonicDirectoryProgress(
    previous,
    { status: 'running', percentage: 78, decisionProgress: { phase: 'appendix', decided: 0, total: 12 }, tasks: runningTasks },
  )
  assert.equal(phaseSwitch.decisionProgress.phase, 'appendix')
  assert.equal(phaseSwitch.decisionProgress.decided, 0)
})

test('keeps terminal directory state when a delayed running response arrives', () => {
  const completed = { status: 'completed', percentage: 100, summary: '目录生成完成。' }
  const failed = { status: 'failed', percentage: 42, summary: '目录生成失败。' }

  assert.equal(mergeMonotonicDirectoryProgress(completed, { status: 'running', percentage: 70 }), completed)
  assert.equal(mergeMonotonicDirectoryProgress(failed, { status: 'processing', percentage: 65 }), failed)
})

test('shares running and failed directory status predicates across page behavior', () => {
  assert.equal(isDirectoryProgressRunning({ status: 'running' }), true)
  assert.equal(isDirectoryProgressRunning({ status: 'processing' }), true)
  assert.equal(isDirectoryProgressRunning({ status: 'queued' }), true)
  assert.equal(isDirectoryProgressRunning({ status: 'completed' }), false)
  assert.equal(isDirectoryProgressFailed({ status: 'failed' }), true)
  assert.equal(isDirectoryProgressFailed({ status: 'error' }), true)
  assert.equal(isDirectoryProgressFailed({ status: 'running' }), false)
})

test('derives one continuous total runtime from the run start', () => {
  const startMs = Date.parse('2026-07-17T10:00:00Z')
  const running = { status: 'running', startedAt: '2026-07-17T10:00:00Z' }

  assert.equal(directoryElapsedSeconds(running, startMs + 10 * 60 * 1000), 600)
  assert.equal(directoryElapsedSeconds(running, startMs + 10 * 60 * 1000 + 1000), 601)
})

test('falls back to the first event when startedAt is missing', () => {
  const startMs = Date.parse('2026-07-17T10:00:00Z')
  const progress = {
    status: 'running',
    events: [
      { at: '2026-07-17T10:00:00Z', message: '开始生成。' },
      { at: '2026-07-17T10:01:00Z', message: '准备完成。' },
    ],
  }

  assert.equal(directoryElapsedSeconds(progress, startMs + 10 * 60 * 1000), 600)
})

test('freezes terminal runtime at completion or failure across refreshes', () => {
  const completed = {
    status: 'completed',
    startedAt: '2026-07-17T10:00:00Z',
    generatedAt: '2026-07-17T10:07:30Z',
  }
  const failed = {
    status: 'failed',
    startedAt: '2026-07-17T10:00:00Z',
    events: [
      { at: '2026-07-17T10:00:00Z', step: 'bootstrap', message: '开始生成。' },
      { at: '2026-07-17T10:10:00Z', step: 'failed', level: 'error', message: '生成失败。' },
    ],
  }

  assert.equal(directoryElapsedSeconds(completed, Date.parse('2026-07-17T11:00:00Z')), 450)
  assert.equal(directoryElapsedSeconds(failed, Date.parse('2026-07-17T10:10:00Z')), 600)
  assert.equal(directoryElapsedSeconds(failed, Date.parse('2026-07-17T11:10:00Z')), 600)
})

test('formats durations for people, hiding zero and negative values', () => {
  assert.equal(formatDirectoryDuration(0), '')
  assert.equal(formatDirectoryDuration(-5), '')
  assert.equal(formatDirectoryDuration(42), '42 秒')
  assert.equal(formatDirectoryDuration(372), '6 分 12 秒')
})

test('summarizes completed and failed directory generation without internal terms', () => {
  const completed = summarizeDirectoryProgress({
    status: 'completed',
    percentage: 100,
    summary: 'S2 Skill 通过 opencode 完成目录生成，共 18 条目录项。',
  })
  const failed = summarizeDirectoryProgress({
    status: 'failed',
    percentage: 42,
    summary: 'futurecode/opencode 目录生成失败，S2 Skill 执行异常。',
    tasks: [
      { id: 'task-1', status: 'done' },
      { id: 'task-2', status: 'failed' },
      { id: 'task-3', status: 'pending' },
    ],
  })

  assert.equal(completed.title, '目录生成完成')
  assert.equal(completed.summary, '目录生成完成，可进入目录确认。')
  assert.equal(completed.statusText, '已完成')
  assert.equal(completed.tone, 'success')
  assert.equal(failed.title, '目录生成失败（第 2/3 步：智能生成目录）')
  assert.equal(failed.summary, '目录生成未完成，请稍后重试；如仍失败请联系管理员。')
  assert.equal(failed.statusText, '生成失败')
  assert.equal(failed.tone, 'danger')
  assert.doesNotMatch(`${failed.title}${failed.summary}`, /futurecode|opencode|S2|Skill/i)
})

test('maps internal directory failures to actionable user-facing reasons', () => {
  const serviceFailure = summarizeDirectoryProgress({
    status: 'failed',
    percentage: 60,
    summary: 'opencode 服务连接超时。',
  })
  const inputFailure = summarizeDirectoryProgress({
    status: 'failed',
    percentage: 2,
    summary: 'futurecode 未找到投标模板文件。',
  })
  const resultFailure = summarizeDirectoryProgress({
    status: 'failed',
    percentage: 90,
    summary: 'S2 Skill 输出结果格式异常。',
  })

  assert.equal(serviceFailure.summary, '目录生成服务暂时不可用，请稍后重试。')
  assert.equal(inputFailure.summary, '未能读取招标文件或投标模板，请检查文件后重试。')
  assert.equal(resultFailure.summary, '目录结果处理失败，请重新生成；如仍失败请联系管理员。')
})

test('technical directory page keeps a single status badge, no step rail, and a total runtime line', () => {
  const pageSource = readFileSync(new URL('./pages/TechnicalParseResult.jsx', import.meta.url), 'utf8')
  const visibleStatusBindings = pageSource.match(/directoryProgressSummary\.statusText/g) || []

  assert.doesNotMatch(pageSource, /summarizeDirectorySource|directorySourceMeta|directoryStatusLabel/)
  assert.doesNotMatch(pageSource, /directoryProgressSummary\.steps\.map/)
  assert.doesNotMatch(pageSource, /estimateDirectoryDisplayPercentage/)
  assert.equal(visibleStatusBindings.length, 1)
  assert.match(pageSource, /已运行/)
  assert.match(pageSource, /总耗时/)
})
