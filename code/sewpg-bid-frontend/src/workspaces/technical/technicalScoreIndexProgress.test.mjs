import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  isScoreIndexProgressFailed,
  isScoreIndexProgressRunning,
  normalizeIndexProgress,
  scoreIndexDetailText,
  scoreIndexDisplayPercentage,
  scoreIndexElapsedSeconds,
  summarizeScoreIndexProgress,
} from './technicalScoreIndexProgress.js'

test('运行中的量化明细按「已建立章节索引 X/Y 项」展示', () => {
  const detail = summarizeScoreIndexProgress({
    status: 'running',
    percentage: 25,
    summary: '正在判断 26 项评审因素应索引的章节，请稍候。',
    indexProgress: { done: 12, total: 26, updatedAt: '2026-08-13T10:00:00Z' },
  }).detail

  assert.equal(detail, '已建立章节索引 12/26 项')
})

test('章节判断阶段计数停在 0，改用后端那句带数量的说明', () => {
  const judging = summarizeScoreIndexProgress({
    status: 'running',
    percentage: 25,
    summary: '正在判断 26 项评审因素应索引的章节，请稍候。',
    indexProgress: { done: 0, total: 26, phase: 'probed', updatedAt: '2026-08-13T10:00:00Z' },
  }).detail
  assert.equal(judging, '正在判断 26 项评审因素应索引的章节，请稍候。')

  // 进入逐行建引用后即使还是 0 条，也切回计数口径
  const building = summarizeScoreIndexProgress({
    status: 'running',
    percentage: 90,
    summary: '已建立章节索引 0/26 项，正在写回成稿。',
    indexProgress: { done: 0, total: 26, phase: 'built', updatedAt: '2026-08-13T10:00:00Z' },
  }).detail
  assert.equal(building, '已建立章节索引 0/26 项')
})

test('没有量化计数时回落到后端摘要，摘要含内部词时再回落到固定文案', () => {
  assert.equal(
    summarizeScoreIndexProgress({ status: 'running', summary: '正在定位成稿中的技术评分标准索引表。' }).detail,
    '正在定位成稿中的技术评分标准索引表。',
  )
  assert.equal(
    summarizeScoreIndexProgress({ status: 'running', summary: '调用 opencode session 判断章节' }).detail,
    '正在定位评分索引表，请稍候。',
  )
})

test('计数被 total 夹紧，total 为 0 时不产出量化明细', () => {
  assert.deepEqual(
    normalizeIndexProgress({ indexProgress: { done: 99, total: 26, updatedAt: '' } }),
    { done: 26, total: 26, phase: '', updatedAtMs: null },
  )
  assert.equal(normalizeIndexProgress({ indexProgress: { done: 3, total: 0 } }), null)
  assert.equal(scoreIndexDetailText(null), '')
})

test('运行中百分比按时间爬升但封顶 96，完成态固定 100', () => {
  const anchor = Date.parse('2026-08-13T10:00:00Z')
  const running = {
    status: 'running',
    percentage: 25,
    indexProgress: { done: 0, total: 26, updatedAt: '2026-08-13T10:00:00Z' },
  }

  assert.equal(scoreIndexDisplayPercentage(running, anchor), 25)
  // 60 秒后爬升 3 个点，不越过锚点之后的下一阶段
  assert.equal(scoreIndexDisplayPercentage(running, anchor + 60_000), 28)
  // 爬升有上限，长时间无新事件也不会顶到 100
  assert.equal(scoreIndexDisplayPercentage(running, anchor + 3_600_000), 31)
  assert.equal(scoreIndexDisplayPercentage({ status: 'completed', percentage: 100 }, anchor), 100)
})

test('耗时在终态冻结在完成时刻，运行中按当前时间走', () => {
  const state = {
    status: 'running',
    startedAt: '2026-08-13T10:00:00Z',
    finishedAt: '',
  }
  assert.equal(scoreIndexElapsedSeconds(state, Date.parse('2026-08-13T10:00:30Z')), 30)

  const finished = { ...state, status: 'completed', finishedAt: '2026-08-13T10:01:00Z' }
  assert.equal(scoreIndexElapsedSeconds(finished, Date.parse('2026-08-13T10:30:00Z')), 60)
})

test('失败摘要不泄露内部实现，并说明成稿未被改动', () => {
  assert.ok(isScoreIndexProgressFailed({ status: 'failed' }))
  assert.ok(isScoreIndexProgressRunning({ status: 'queued' }))
  assert.equal(
    summarizeScoreIndexProgress({ status: 'failed', summary: 'xref manifest 执行异常' }).detail,
    '章节索引生成未完成，成稿未被改动，请稍后重试。',
  )
  assert.equal(
    summarizeScoreIndexProgress({ status: 'failed', summary: '请求超时' }).detail,
    '章节索引服务暂时不可用，成稿未被改动，请稍后重试。',
  )
})

test('请求停止仍轮询，已停止冻结耗时并使用中性文案', () => {
  assert.equal(isScoreIndexProgressRunning({ status: 'cancel_requested' }), true)
  const cancelled = {
    status: 'cancelled',
    startedAt: '2026-08-13T10:00:00Z',
    cancelledAt: '2026-08-13T10:01:10Z',
    percentage: 47,
  }
  assert.equal(scoreIndexElapsedSeconds(cancelled, Date.parse('2026-08-13T10:30:00Z')), 70)
  assert.deepEqual(summarizeScoreIndexProgress(cancelled), {
    status: 'cancelled',
    tone: 'neutral',
    detail: '章节索引重新生成已停止。',
  })
})

test('索引弹窗把已停止展示为中性停止态', () => {
  const source = readFileSync(new URL('./components/TechnicalScoreIndexProgressModal.jsx', import.meta.url), 'utf8')
  assert.match(source, /stop_circle/)
  assert.match(source, /已停止/)
})
