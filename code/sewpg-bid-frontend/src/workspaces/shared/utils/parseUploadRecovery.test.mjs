import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isParseProgressCompleted,
  isParseProgressFailed,
  mergeMonotonicParseProgress,
  shouldPollParseProgress,
} from './parseUploadRecovery.js'

test('percentage=100 的失败态不算完成', () => {
  assert.equal(isParseProgressCompleted({ status: 'failed', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'completed', percentage: 100 }), true)
  assert.equal(isParseProgressFailed({ status: 'stale', percentage: 100 }), true)
})

test('进度轮询在停止标记或结果完成后不再继续', () => {
  assert.equal(shouldPollParseProgress({ stopped: true, uploading: true }), false)
  assert.equal(shouldPollParseProgress({ uploading: true }), true)
  assert.equal(shouldPollParseProgress({ result: { status: 'completed' } }), false)
  assert.equal(shouldPollParseProgress({ progress: { status: 'running' } }), true)
})

test('默认（技术标）计数单调合并：乱序响应不回退条款计数', () => {
  const previous = {
    status: 'running',
    percentage: 80,
    phaseKey: 'opencode',
    opencodeOutput: { completedItems: 27, totalItems: 64 },
  }
  const incoming = {
    status: 'running',
    percentage: 75,
    phaseKey: 'opencode',
    opencodeOutput: { completedItems: 15, totalItems: 64 },
  }

  const merged = mergeMonotonicParseProgress(previous, incoming)
  assert.equal(merged.percentage, 80)
  assert.deepEqual(merged.opencodeOutput, { completedItems: 27, totalItems: 64 })
})

test('monotonicCounters=false（商务标历史行为）只做百分比单调，不回填计数', () => {
  const previous = {
    status: 'running',
    percentage: 80,
    phaseKey: 'opencode',
    opencodeOutput: { completedItems: 27, totalItems: 64 },
  }
  const incoming = {
    status: 'running',
    percentage: 75,
    phaseKey: 'opencode',
    opencodeOutput: { completedItems: 15, totalItems: 64 },
  }

  const merged = mergeMonotonicParseProgress(previous, incoming, { monotonicCounters: false })
  assert.equal(merged.percentage, 80)
  assert.deepEqual(merged.opencodeOutput, { completedItems: 15, totalItems: 64 })
})

test('非运行态直接采用新快照', () => {
  const previous = { status: 'running', percentage: 40 }
  const incoming = { status: 'completed', percentage: 100 }
  assert.equal(mergeMonotonicParseProgress(previous, incoming), incoming)
  assert.equal(mergeMonotonicParseProgress(null, incoming), incoming)
})
