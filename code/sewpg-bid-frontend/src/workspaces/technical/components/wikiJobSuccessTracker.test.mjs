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
  assert.equal(track({ status: 'succeeded', jobId: 'job-old' }), '')
})

test('任务在轮询间隔内完成时，即使未观察到运行中也通知', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'idle' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-fast' }), 'job-fast')
  assert.equal(track({ status: 'succeeded', jobId: 'job-fast' }), '')
})

test('补跑切换 latest jobId 时通知最终成功的新任务', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'running', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-2' }), 'job-2')
  assert.equal(track({ status: 'succeeded', jobId: 'job-2' }), '')
})

test('补跑任务的运行态被轮询到时仍只在成功后通知', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'running', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'running', jobId: 'job-2' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-2' }), 'job-2')
})

test('已有成功基准之后出现的新成功任务仍通知一次', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track({ status: 'succeeded', jobId: 'job-old' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-new' }), 'job-new')
  assert.equal(track({ status: 'succeeded', jobId: 'job-old' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-new' }), '')
})

test('无效快照不抢占首次有效成功基准', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track(undefined), '')
  assert.equal(track({ status: 'unknown', jobId: 'job-invalid' }), '')
  assert.equal(track({ status: 'succeeded' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-old' }), '')
  assert.equal(track({ status: 'succeeded', jobId: 'job-new' }), 'job-new')
})

test('缺 jobId 或失败/空闲状态不触发成功通知', () => {
  const track = createWikiJobSuccessTracker()

  assert.equal(track(undefined), '')
  assert.equal(track({ status: 'succeeded' }), '')
  assert.equal(track({ status: 'idle' }), '')
  assert.equal(track({ status: 'failed', jobId: 'job-1' }), '')
  assert.equal(track({ status: 'cancelled', jobId: 'job-2' }), '')
  assert.equal(track({ status: 'succeeded' }), '')
  assert.equal(track({ status: 'idle' }), '')
})
