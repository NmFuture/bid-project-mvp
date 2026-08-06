import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendDismissedKey,
  collectStageFailures,
  DISMISSED_KEYS_LIMIT,
  firstUndismissedStageFailure,
  loadDismissedKeys,
} from './materialPipelineFailures.js'

// R10-B07-05：失败横幅的数据来源是后端记忆的各阶段最近终态，不再要求
// 组件本次会话先轮询到 running。这里锁定快照 → 横幅数据源的推导规则。

test('Wiki 快速失败（两次轮询之间）：仅凭终态快照也能得出失败横幅', () => {
  const failures = collectStageFailures({
    cleaning: { active: 0, lastTerminal: null },
    deepParse: { active: 0, lastTerminal: null },
    wiki: { jobId: 'wiki-1', status: 'failed', message: '生成超时', error: '生成超时' },
  })
  assert.equal(failures.length, 1)
  assert.equal(failures[0].stageLabel, 'Wiki 增量构建')
  assert.equal(failures[0].status, 'failed')
  assert.equal(failures[0].jobId, 'wiki-1')
  assert.equal(failures[0].message, '生成超时')
  assert.equal(failures[0].retryable, true)
  assert.equal(failures[0].dismissKey, '技术标:wiki:wiki-1')
})

test('清洗失败：从 lastTerminal 得出失败横幅，且不带自动重试入口', () => {
  const failures = collectStageFailures({
    cleaning: {
      active: 0,
      lastTerminal: { jobId: 'clean-9', status: 'failed', message: '清洗失败：未生成 Word 文件。', finishedAt: '2026-08-06T01:00:00Z' },
    },
    deepParse: { active: 0, lastTerminal: null },
    wiki: { status: 'idle' },
  })
  assert.equal(failures.length, 1)
  assert.equal(failures[0].stageLabel, '素材清洗')
  assert.equal(failures[0].retryable, false)
  assert.equal(failures[0].dismissKey, '技术标:cleaning:clean-9')
})

test('深度解析失败与 Wiki cancelled 都会进入横幅数据源', () => {
  const failures = collectStageFailures({
    cleaning: { active: 0, lastTerminal: null },
    deepParse: {
      active: 0,
      lastTerminal: { jobId: 'dp-3', status: 'failed', message: '转换超时' },
    },
    wiki: { jobId: 'wiki-2', status: 'cancelled', message: '任务锁已失效或已被新任务替代。' },
  })
  assert.deepEqual(
    failures.map((item) => item.dismissKey),
    ['技术标:deepParse:dp-3', '技术标:wiki:wiki-2'],
  )
  assert.ok(failures.every((item) => item.retryable))
})

test('最近终态为成功或进行中时不产生失败横幅', () => {
  const failures = collectStageFailures({
    cleaning: { active: 1, lastTerminal: { jobId: 'clean-1', status: 'succeeded' } },
    deepParse: { active: 0, lastTerminal: { jobId: 'dp-1', status: 'succeeded' } },
    wiki: { jobId: 'wiki-3', status: 'running' },
  })
  assert.equal(failures.length, 0)
})

test('快照为空或字段缺失时不抛错、不产生失败横幅', () => {
  assert.equal(collectStageFailures(null).length, 0)
  assert.equal(collectStageFailures({}).length, 0)
  assert.equal(collectStageFailures({ wiki: { status: 'succeeded' } }).length, 0)
})

test('技术标横幅忽略商务标与显式非法的终态，缺失 bidType 按历史技术标兼容', () => {
  const failures = collectStageFailures({
    cleaning: {
      lastTerminal: { jobId: 'legacy-tech', status: 'failed', message: '历史任务' },
    },
    deepParse: {
      lastTerminal: { jobId: 'business-1', bidType: '商务标', status: 'failed' },
    },
    wiki: { jobId: 'invalid-1', bidType: 'unknown', status: 'failed' },
  })

  assert.deepEqual(failures.map((item) => item.jobId), ['legacy-tech'])

  for (const invalidBidType of ['', null, 0, 'unknown', '非技术标', '技术资料', '商务资料']) {
    assert.equal(collectStageFailures({
      wiki: { jobId: invalidBidType, bidType: invalidBidType, status: 'failed' },
    }).length, 0)
  }
})

test('关闭多条失败后不会在之前的提示间循环重现', () => {
  const payload = {
    cleaning: { lastTerminal: { jobId: 'clean-1', status: 'failed' } },
    deepParse: { lastTerminal: { jobId: 'deep-1', status: 'cancelled' } },
    wiki: { jobId: 'wiki-1', status: 'failed' },
  }

  const first = firstUndismissedStageFailure(payload)
  const second = firstUndismissedStageFailure(payload, [first.dismissKey])
  const third = firstUndismissedStageFailure(payload, [first.dismissKey, second.dismissKey])
  const none = firstUndismissedStageFailure(
    payload,
    [first.dismissKey, second.dismissKey, third.dismissKey],
  )

  assert.equal(first.jobId, 'clean-1')
  assert.equal(second.jobId, 'deep-1')
  assert.equal(third.jobId, 'wiki-1')
  assert.equal(none, null)
})

test('加载关闭记录时安全处理异常 JSON、非数组与污染条目', () => {
  assert.deepEqual(loadDismissedKeys(null), [])
  assert.deepEqual(loadDismissedKeys('{bad json'), [])
  assert.deepEqual(loadDismissedKeys(JSON.stringify({ key: 'not-array' })), [])
  assert.deepEqual(
    loadDismissedKeys(JSON.stringify([' a ', 42, '', 'b', 'a', 'x'.repeat(301)])),
    ['b', 'a'],
  )
})

test('追加关闭记录会去重、保留最新顺序并限制会话容量', () => {
  assert.deepEqual(appendDismissedKey(['a', 'b'], 'a'), ['b', 'a'])

  const oversized = Array.from(
    { length: DISMISSED_KEYS_LIMIT + 5 },
    (_, index) => `key-${index}`,
  )
  const loaded = loadDismissedKeys(JSON.stringify(oversized))
  assert.equal(loaded.length, DISMISSED_KEYS_LIMIT)
  assert.equal(loaded[0], 'key-5')
  assert.equal(loaded.at(-1), `key-${DISMISSED_KEYS_LIMIT + 4}`)

  const appended = appendDismissedKey(loaded, 'latest')
  assert.equal(appended.length, DISMISSED_KEYS_LIMIT)
  assert.equal(appended[0], 'key-6')
  assert.equal(appended.at(-1), 'latest')
})
