import test from 'node:test'
import assert from 'node:assert/strict'

import { createWikiJobSuccessTracker } from './wikiJobSuccessTracker.js'

test('Wiki 任务从运行变为成功时通知一次，重复成功快照不重复通知', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'running', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'running', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-1' }), 'job-1')
  // 进度条继续轮询，同一 jobId 的成功快照不再触发
  assert.equal(track({ status: 'succeeded', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-1' }), '')
})

test('页面打开时任务已是成功终态（未见过运行中）不补通知', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'succeeded', jobId: 'job-old' }), '')
})

test('新任务成功后再次通知，且与已通知过的旧任务互不影响', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'running', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-1' }), 'job-1')
  assert.equal(track({ status: 'running', jobId: 'job-2' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-2' }), 'job-2')
})

test('缺 jobId 或失败/空闲状态不触发成功通知', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'running', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'failed', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'succeeded' }), '')
  assert.equal(track(undefined), '')
  assert.equal(track({ status: 'idle' }), '')
})
