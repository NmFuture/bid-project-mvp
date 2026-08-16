import test from 'node:test'
import assert from 'node:assert/strict'

import {
  bodyFillDisplayPercentage,
  bodyFillRunning,
  summarizeBodyFill,
} from './technicalBodyFillProgress.js'
import {
  FACT_CURATE_PHASES,
  factCurateDisplayPercentage,
  factCurateRunning,
  summarizeFactCurate,
} from './technicalFactCurateProgress.js'
import { readFileSync } from 'node:fs'

// definitions 链到 api/index.js 再链到 Vite 别名 src/config/env，node 直接 import 会挂，
// 故按现有 UI 契约测试的做法读源码断言（同 technicalExportToolbarContract.test.mjs）。
const DEFINITIONS_SOURCE = readFileSync(
  new URL('./technicalBackgroundTaskDefinitions.js', import.meta.url),
  'utf-8',
)

// 事实表 AI 填写与一键填写都跑在 Redis worker 队列里（fact_curate / technical_body_fill），
// 右下角卡片与页面必须显示同一个数，故算法收在这两个模块里由两处共用。

test('两个 worker 任务都登记进了后台任务栈', () => {
  for (const taskType of ['fact-curate', 'body-fill']) {
    assert.ok(
      DEFINITIONS_SOURCE.includes(`'${taskType}': {`),
      `${taskType} 缺少定义，右下角不会有卡片`,
    )
  }
  // 状态接口把进度包在一层 xxxState 里，取值时必须多剥一层，否则卡片恒为 0%
  assert.ok(DEFINITIONS_SOURCE.includes('progress?.factCurateState'))
  assert.ok(DEFINITIONS_SOURCE.includes('progress?.bodyFillState'))
})

test('剥掉外层 xxxState 后能算出百分比', () => {
  const unwrapCurate = (progress) => factCurateDisplayPercentage(progress?.factCurateState || progress || {})
  const unwrapBodyFill = (progress) => bodyFillDisplayPercentage(progress?.bodyFillState || progress || {})
  assert.equal(unwrapCurate({ factCurateState: { status: 'running', batchTotal: 4, batchDone: 2 } }), 65)
  assert.equal(unwrapBodyFill({ bodyFillState: { status: 'running', total: 10, done: 5 } }), 50)
})

test('事实表填写：有批次数按批次算，落在 AI 分析这一阶段内部', () => {
  // 40%~90%：前两阶段已过、末阶段还没开始，批次跑完不能显示 100% 却还在落表
  assert.equal(factCurateDisplayPercentage({ status: 'running', batchTotal: 4, batchDone: 0 }), 40)
  assert.equal(factCurateDisplayPercentage({ status: 'running', batchTotal: 4, batchDone: 4 }), 90)
})

test('事实表填写：没有批次数时按阶段序号粗估，且单调递增', () => {
  const percentages = FACT_CURATE_PHASES.map((phase) => (
    factCurateDisplayPercentage({ status: 'running', phase })
  ))
  for (let index = 1; index < percentages.length; index += 1) {
    assert.ok(percentages[index] > percentages[index - 1], `${FACT_CURATE_PHASES[index]} 没有递增`)
  }
  assert.ok(percentages.at(-1) < 100, '最后一个阶段不能显示 100%，那时还没落表')
})

test('未知阶段给 5% 而不是 0%，别让人以为没提交成功', () => {
  assert.equal(factCurateDisplayPercentage({ status: 'queued', phase: '' }), 5)
  assert.equal(bodyFillDisplayPercentage({ status: 'queued', total: 0 }), 5)
  assert.equal(bodyFillDisplayPercentage({ status: 'running', total: 10, done: 0 }), 5)
})

test('终态与非运行态', () => {
  assert.equal(factCurateDisplayPercentage({ status: 'succeeded' }), 100)
  assert.equal(factCurateDisplayPercentage({ status: 'idle' }), 0)
  assert.equal(bodyFillDisplayPercentage({ status: 'succeeded' }), 100)
  assert.equal(bodyFillDisplayPercentage({ status: 'idle' }), 0)
  assert.equal(factCurateRunning({ status: 'running' }), true)
  assert.equal(factCurateRunning({ status: 'failed' }), false)
  assert.equal(bodyFillRunning({ status: 'queued' }), true)
})

test('卡片摘要优先给人看得懂的进展', () => {
  assert.equal(summarizeFactCurate({ status: 'running', phase: 'AI 分析素材' }), 'AI 分析素材')
  assert.equal(summarizeFactCurate({ status: 'running', message: '第 2/4 批' }), '第 2/4 批')
  assert.equal(
    summarizeBodyFill({ status: 'running', total: 10, done: 3, current: '塔筒设计方案' }),
    '3/10 · 塔筒设计方案',
  )
})
