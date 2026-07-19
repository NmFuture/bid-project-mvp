import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  directoryElapsedSeconds,
  estimateDirectoryDisplayPercentage,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  mergeMonotonicDirectoryProgress,
  summarizeDirectoryProgress,
} from './technicalDirectoryProgress.js'

test('summarizes intelligent directory generation with user-facing elapsed time and steps', () => {
  const summary = summarizeDirectoryProgress({
    status: 'running',
    percentage: 70,
    summary: 'futurecode 正在执行 S2 目录生成和语义审核，请稍候。',
    opencodeOutput: {
      status: 'streaming',
      elapsedSeconds: 261,
      providerId: 'openai',
      modelId: 'gpt-5',
    },
    tasks: [
      { id: 'task-1', label: '准备目录输入', status: 'done' },
      { id: 'task-2', label: 'Opencode 生成目录', status: 'running' },
      { id: 'task-3', label: '保存目录结果', status: 'pending' },
    ],
  })

  assert.equal(summary.title, '智能生成目录')
  assert.equal(summary.summary, '正在分析招标要求并组织目录结构，已执行 4 分 21 秒。')
  assert.equal(summary.statusText, '生成中')
  assert.equal(summary.percentage, 70)
  assert.equal(summary.tone, 'running')
  assert.deepEqual(summary.steps, [
    { id: 'task-1', label: '准备生成资料', status: 'done' },
    { id: 'task-2', label: '智能生成目录', status: 'running' },
    { id: 'task-3', label: '保存目录结果', status: 'pending' },
  ])
  assert.doesNotMatch(
    `${summary.title}${summary.summary}${summary.steps.map((step) => step.label).join('')}`,
    /futurecode|opencode|S2|Skill|session|provider|model/i,
  )
})

test('keeps displayed directory percentage from moving backwards while retaining fresh details', () => {
  const previous = {
    status: 'running',
    percentage: 70,
    summary: '正在生成目录。',
    opencodeOutput: { elapsedSeconds: 120 },
  }
  const incoming = {
    status: 'running',
    percentage: 65,
    summary: '收到新的目录生成进度。',
    opencodeOutput: { elapsedSeconds: 150 },
  }

  const merged = mergeMonotonicDirectoryProgress(previous, incoming)

  assert.equal(merged.percentage, 70)
  assert.equal(merged.summary, incoming.summary)
  assert.equal(merged.opencodeOutput.elapsedSeconds, 150)
})

test('keeps running directory phase and elapsed time from moving backwards', () => {
  const previous = {
    status: 'running',
    percentage: 85,
    opencodeOutput: { elapsedSeconds: 300, idleSeconds: 20 },
    tasks: [
      { id: 'task-1', status: 'done' },
      { id: 'task-2', status: 'done' },
      { id: 'task-3', status: 'running' },
    ],
  }
  const delayed = {
    status: 'running',
    percentage: 70,
    opencodeOutput: { elapsedSeconds: 240, idleSeconds: 10 },
    tasks: [
      { id: 'task-1', status: 'done' },
      { id: 'task-2', status: 'running' },
      { id: 'task-3', status: 'pending' },
    ],
  }

  const merged = mergeMonotonicDirectoryProgress(previous, delayed)

  assert.equal(merged.percentage, 85)
  assert.deepEqual(merged.tasks, previous.tasks)
  assert.equal(merged.opencodeOutput.elapsedSeconds, 300)
  assert.equal(merged.opencodeOutput.idleSeconds, 20)
  assert.equal(summarizeDirectoryProgress(merged).title, '保存目录结果')
})

test('keeps terminal directory state when a delayed running response arrives', () => {
  const completed = {
    status: 'completed',
    percentage: 100,
    summary: '目录生成完成。',
  }
  const failed = {
    status: 'failed',
    percentage: 70,
    summary: '目录生成失败。',
  }

  assert.equal(
    mergeMonotonicDirectoryProgress(completed, { status: 'running', percentage: 70 }),
    completed,
  )
  assert.equal(
    mergeMonotonicDirectoryProgress(failed, { status: 'processing', percentage: 65 }),
    failed,
  )
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

test('uses preparation and saving copy for the surrounding directory phases', () => {
  const preparing = summarizeDirectoryProgress({
    status: 'running',
    percentage: 5,
    tasks: [
      { id: 'task-1', label: '准备目录输入', status: 'running' },
      { id: 'task-2', label: 'Opencode 生成目录', status: 'pending' },
      { id: 'task-3', label: '保存目录结果', status: 'pending' },
    ],
  })
  const saving = summarizeDirectoryProgress({
    status: 'running',
    percentage: 85,
    tasks: [
      { id: 'task-1', label: '准备目录输入', status: 'done' },
      { id: 'task-2', label: 'Opencode 生成目录', status: 'done' },
      { id: 'task-3', label: '保存目录结果', status: 'running' },
    ],
  })

  assert.equal(preparing.title, '准备生成资料')
  assert.equal(preparing.summary, '正在整理招标文件与投标模板，为目录生成做准备。')
  assert.equal(saving.title, '保存目录结果')
  assert.equal(saving.summary, '目录结构已经生成，正在整理并保存结果。')
})

test('summarizes completed and failed directory generation without internal terms', () => {
  const completed = summarizeDirectoryProgress({
    status: 'completed',
    percentage: 100,
    summary: 'S2 Skill 通过 opencode 完成目录生成，共 18 条目录项。',
  })
  const failed = summarizeDirectoryProgress({
    status: 'failed',
    percentage: 60,
    summary: 'futurecode/opencode 目录生成失败，S2 Skill 执行异常。',
    tasks: [
      { id: 'task-1', status: 'done' },
      { id: 'task-2', status: 'failed' },
      { id: 'task-3', status: 'pending' },
    ],
  })

  assert.deepEqual(
    {
      title: completed.title,
      summary: completed.summary,
      statusText: completed.statusText,
      tone: completed.tone,
    },
    {
      title: '目录生成完成',
      summary: '目录生成完成，可进入目录确认。',
      statusText: '已完成',
      tone: 'success',
    },
  )
  assert.equal(failed.title, '目录生成失败')
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
    percentage: 5,
    summary: 'futurecode 未找到投标模板文件。',
  })
  const resultFailure = summarizeDirectoryProgress({
    status: 'failed',
    percentage: 85,
    summary: 'S2 Skill 输出结果格式异常。',
  })

  assert.equal(serviceFailure.summary, '目录生成服务暂时不可用，请稍后重试。')
  assert.equal(inputFailure.summary, '未能读取招标文件或投标模板，请检查文件后重试。')
  assert.equal(resultFailure.summary, '目录结果处理失败，请重新生成；如仍失败请联系管理员。')
})

test('falls back safely for invalid directory percentage and elapsed values', () => {
  const summary = summarizeDirectoryProgress({
    status: 'running',
    percentage: 'invalid',
    opencodeOutput: { elapsedSeconds: 'invalid', idleSeconds: Number.NaN },
    tasks: [{ id: 'task-2', status: 'running' }],
  })

  assert.equal(summary.percentage, 0)
  assert.equal(summary.summary, '正在分析招标要求并组织目录结构，请稍候。')
  assert.doesNotMatch(summary.summary, /NaN/)
})

test('spreads running directory progress evenly across the first fifteen minutes', () => {
  assert.equal(estimateDirectoryDisplayPercentage({ status: 'running', elapsedSeconds: 0 }), 5)
  assert.equal(estimateDirectoryDisplayPercentage({ status: 'running', elapsedSeconds: 60 }), 11)
  assert.equal(estimateDirectoryDisplayPercentage({ status: 'running', elapsedSeconds: 600 }), 65)
  assert.equal(estimateDirectoryDisplayPercentage({ status: 'running', elapsedSeconds: 900 }), 95)
})

test('approaches ninety-nine after fifteen minutes and reserves one hundred for completion', () => {
  const prolonged = estimateDirectoryDisplayPercentage({ status: 'running', elapsedSeconds: 1500 })

  assert.ok(prolonged > 97)
  assert.ok(prolonged < 99)
  assert.equal(estimateDirectoryDisplayPercentage({ status: 'completed', elapsedSeconds: 10 }), 100)
  assert.equal(estimateDirectoryDisplayPercentage({ status: 'failed', elapsedSeconds: 600, fallbackPercentage: 64 }), 64)
})

test('derives continuous elapsed time from the first directory event', () => {
  const startedAt = Date.parse('2026-07-17T10:00:00Z')
  const progress = {
    events: [
      { at: '2026-07-17T10:00:00Z', message: '开始生成。' },
      { at: '2026-07-17T10:01:00Z', message: '准备完成。' },
    ],
    opencodeOutput: { elapsedSeconds: 30 },
  }

  assert.equal(directoryElapsedSeconds(progress, startedAt + 10 * 60 * 1000), 600)
})

test('freezes failed directory elapsed time at the terminal event across refreshes', () => {
  const progress = {
    status: 'failed',
    events: [
      { at: '2026-07-17T10:00:00Z', step: 'bootstrap', message: '开始生成。' },
      { at: '2026-07-17T10:10:00Z', step: 'failed', level: 'error', message: '生成失败。' },
    ],
  }

  assert.equal(directoryElapsedSeconds(progress, Date.parse('2026-07-17T10:10:00Z')), 600)
  assert.equal(directoryElapsedSeconds(progress, Date.parse('2026-07-17T11:10:00Z')), 600)
})

test('technical directory page omits duplicate badges and the step rail', () => {
  const pageSource = readFileSync(new URL('./pages/TechnicalParseResult.jsx', import.meta.url), 'utf8')
  const visibleStatusBindings = pageSource.match(/directoryProgressSummary\.statusText/g) || []

  assert.doesNotMatch(pageSource, /summarizeDirectorySource|directorySourceMeta|directoryStatusLabel/)
  assert.doesNotMatch(pageSource, /directoryProgressSummary\.steps\.map/)
  assert.equal(visibleStatusBindings.length, 1)
})
