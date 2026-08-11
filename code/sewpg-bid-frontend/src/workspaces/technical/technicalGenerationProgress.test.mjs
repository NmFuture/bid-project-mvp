import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  generationDisplayPercentage,
  generationElapsedSeconds,
  normalizeAssemblyProgress,
  summarizeGenerationProgress,
} from './technicalGenerationProgress.js'

const at = (iso) => Date.parse(iso)

// PRJ-0004 实测：12:39:50 起，准备 64 秒 → 组装 168 秒 → 格式化 44 秒 → 12:44:30 完成。
const RUN = {
  startedAt: '2026-08-09T12:39:50Z',
  bootstrap: '2026-08-09T12:39:50Z',
  inputsReady: '2026-08-09T12:40:54Z',
  assemblyStart: '2026-08-09T12:40:55Z',
  assemblingResult: '2026-08-09T12:43:43Z',
  formatStart: '2026-08-09T12:43:45Z',
  formatDone: '2026-08-09T12:44:29Z',
  done: '2026-08-09T12:44:30Z',
}

const runningState = (events, extra = {}) => ({
  status: 'running',
  startedAt: RUN.startedAt,
  events,
  ...extra,
})

test('进度条按实测耗时分配区间，不再前 60% 一分钟、后 40% 好几分钟', () => {
  const prepare = runningState([{ at: RUN.bootstrap, step: 'bootstrap' }], { percentage: 5 })
  const assembling = runningState(
    [
      { at: RUN.bootstrap, step: 'bootstrap' },
      { at: RUN.inputsReady, step: 'inputs_ready' },
      { at: RUN.assemblyStart, step: 'assembly_waiting' },
    ],
    { percentage: 60 },
  )
  const formatting = runningState(
    [
      { at: RUN.assemblingResult, step: 'assembling' },
      { at: RUN.formatStart, step: 'format_cleaning' },
    ],
    { percentage: 90 },
  )

  // 准备阶段占实测 23% 的时间，进度也停在 23% 附近，而不是后端锚点的 30%
  const afterPrepare = generationDisplayPercentage(prepare, at(RUN.inputsReady))
  assert.ok(afterPrepare > 18 && afterPrepare < 23, `准备阶段收尾应接近 23%，实际 ${afterPrepare}`)

  // 后端在 1 秒内把 percentage 从 30 拉到 60；展示进度不能跟着跳
  const assemblyStart = generationDisplayPercentage(assembling, at(RUN.assemblyStart))
  assert.equal(Math.floor(assemblyStart), 25)

  // 组装占实测 60% 的时间，结束时进度才走到 80% 上下
  const assemblyEnd = generationDisplayPercentage(assembling, at(RUN.assemblingResult))
  assert.ok(assemblyEnd > 70 && assemblyEnd < 82, `组装收尾应在 70~82%，实际 ${assemblyEnd}`)

  // 格式化这段实测 44 秒，留了 12 个百分点，不会「卡在 96% 好几分钟」
  const formatEnd = generationDisplayPercentage(formatting, at(RUN.formatDone))
  assert.ok(formatEnd > 90 && formatEnd <= 97, `格式化收尾应在 90~97%，实际 ${formatEnd}`)

  assert.equal(generationDisplayPercentage({ status: 'completed', percentage: 100 }), 100)
})

test('展示进度随时间单调递增，不会回退', () => {
  const state = runningState([
    { at: RUN.bootstrap, step: 'bootstrap' },
    { at: RUN.inputsReady, step: 'inputs_ready' },
    { at: RUN.assemblyStart, step: 'assembly_waiting' },
  ])
  let previous = -1
  for (let second = 0; second <= 170; second += 5) {
    const value = generationDisplayPercentage(state, at(RUN.assemblyStart) + second * 1000)
    assert.ok(value >= previous, `第 ${second} 秒进度回退：${value} < ${previous}`)
    previous = value
  }
  assert.ok(previous <= 82)
})

test('组装阶段以后端逐条计数为准，并在两次计数之间小步平滑', () => {
  const state = runningState(
    [
      { at: RUN.bootstrap, step: 'bootstrap' },
      { at: RUN.assemblyStart, step: 'assembly_waiting' },
    ],
    {
      summary: '正在组装技术标正文，已处理目录项 27/54 项。',
      assemblyProgress: { done: 27, total: 54, updatedAt: RUN.assemblingResult },
    },
  )

  const atAnchor = generationDisplayPercentage(state, at(RUN.assemblingResult))
  assert.equal(Math.round(atAnchor), 54) // 25 + 57 * 27/54

  const later = generationDisplayPercentage(state, at(RUN.assemblingResult) + 30_000)
  assert.ok(later > atAnchor, '两次计数之间应继续小步前进')
  assert.ok(later < 25 + (57 * 28) / 54 + 0.01, '平滑不得越过下一条目录项的刻度')

  assert.equal(summarizeGenerationProgress(state).detail, '已组装目录项 27/54 项')
})

test('计数缺失或非法时退回阶段估算，不编造数字', () => {
  assert.equal(normalizeAssemblyProgress({ assemblyProgress: { done: 3, total: 0 } }), null)
  assert.equal(normalizeAssemblyProgress({}), null)
  assert.deepEqual(
    normalizeAssemblyProgress({ assemblyProgress: { done: 99, total: 10, updatedAt: '' } }),
    { done: 10, total: 10, updatedAtMs: null },
  )
})

test('耗时以本次启动为起点，终态冻结在完成时刻', () => {
  const running = runningState([{ at: RUN.bootstrap, step: 'bootstrap' }])
  assert.equal(generationElapsedSeconds(running, at(RUN.inputsReady)), 64)

  const completed = {
    status: 'completed',
    startedAt: RUN.startedAt,
    filledAt: RUN.done,
    events: [{ at: RUN.done, step: 'done' }],
  }
  assert.equal(generationElapsedSeconds(completed, at(RUN.done) + 600_000), 280)

  // 历史数据没有 startedAt 时退回最早一条事件
  const legacy = { status: 'running', events: [{ at: RUN.bootstrap, step: 'bootstrap' }] }
  assert.equal(generationElapsedSeconds(legacy, at(RUN.inputsReady)), 64)
})

test('对外文案不泄露内部实现名词', () => {
  const failed = summarizeGenerationProgress({
    status: 'failed',
    summary: 'futurecode session 超时',
  })
  assert.doesNotMatch(failed.detail, /futurecode|session/i)
  assert.equal(failed.tone, 'danger')

  const running = summarizeGenerationProgress(
    runningState([{ at: RUN.assemblyStart, step: 'assembler_session_ready' }], {
      summary: '正在调用 futurecode 执行 skill。',
    }),
  )
  assert.doesNotMatch(running.detail, /futurecode/i)
})

test('正文弹窗只渲染百分比徽标，并复用共享进度卡片', () => {
  const source = readFileSync(new URL('./components/TechnicalGenerationProgressModal.jsx', import.meta.url), 'utf8')

  assert.match(source, /BidProgressPanel/)
  assert.match(source, /generationDisplayPercentage/)
  assert.match(source, /progressElapsedLine/)
  assert.match(source, /warningCount/)
  // 旧版把后端 percentage 直接当进度用，且标题下重复写了一遍 summary
  assert.doesNotMatch(source, /progress=\{progress\}/)
  assert.doesNotMatch(source, /status\?\.percentage/)
})
