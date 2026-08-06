import assert from 'node:assert/strict'
import test from 'node:test'

import { startWikiJobStatusPolling } from './technicalWikiJobPolling.js'

const flush = () => new Promise((resolve) => setImmediate(resolve))

const createTimerHarness = () => {
  const scheduled = []
  const cleared = []
  return {
    scheduled,
    cleared,
    setTimer: (callback, delay) => {
      const timer = { callback, delay }
      scheduled.push(timer)
      return timer
    },
    clearTimer: (timer) => cleared.push(timer),
  }
}

test('上一请求完成后才安排下一轮，慢请求不会重叠', async () => {
  const timers = createTimerHarness()
  let resolveFirst
  let fetchCount = 0
  const firstResponse = new Promise((resolve) => {
    resolveFirst = resolve
  })

  const stop = startWikiJobStatusPolling({
    fetchStatus: () => {
      fetchCount += 1
      return fetchCount === 1 ? firstResponse : Promise.resolve({ status: 'running' })
    },
    onStatus: () => true,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  assert.equal(fetchCount, 1)
  assert.equal(timers.scheduled.length, 0)

  resolveFirst({ status: 'running' })
  await flush()
  assert.equal(timers.scheduled.length, 1)
  assert.equal(timers.scheduled[0].delay, 8000)

  timers.scheduled.shift().callback()
  assert.equal(fetchCount, 2)
  stop()
})

test('连续三次非 404 失败后停止轮询并上报最后一次错误', async () => {
  const timers = createTimerHarness()
  const errors = []
  let fetchCount = 0

  startWikiJobStatusPolling({
    fetchStatus: async () => {
      fetchCount += 1
      throw new Error(`network-${fetchCount}`)
    },
    onStatus: () => true,
    onUnavailable: (error) => errors.push(error.message),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await flush()
  assert.equal(timers.scheduled.length, 1)
  timers.scheduled.shift().callback()
  await flush()
  assert.equal(timers.scheduled.length, 1)
  timers.scheduled.shift().callback()
  await flush()

  assert.equal(fetchCount, 3)
  assert.deepEqual(errors, ['network-3'])
  assert.equal(timers.scheduled.length, 0)
})

test('一次成功响应会清零连续失败计数', async () => {
  const timers = createTimerHarness()
  const outcomes = [
    new Error('network-1'),
    { status: 'running' },
    new Error('network-2'),
    new Error('network-3'),
  ]
  const errors = []

  startWikiJobStatusPolling({
    fetchStatus: async () => {
      const outcome = outcomes.shift()
      if (outcome instanceof Error) throw outcome
      return outcome
    },
    onStatus: () => true,
    onUnavailable: (error) => errors.push(error.message),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await flush()
  for (let index = 0; index < 3; index += 1) {
    assert.equal(timers.scheduled.length, 1)
    timers.scheduled.shift().callback()
    await flush()
  }

  assert.deepEqual(errors, [])
  assert.equal(timers.scheduled.length, 1)
})

test('404 立即结束跟踪，不计入连续失败', async () => {
  const timers = createTimerHarness()
  let notFoundCount = 0
  let unavailableCount = 0

  startWikiJobStatusPolling({
    fetchStatus: async () => {
      const error = new Error('missing')
      error.status = 404
      throw error
    },
    onStatus: () => true,
    onNotFound: () => { notFoundCount += 1 },
    onUnavailable: () => { unavailableCount += 1 },
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await flush()
  assert.equal(notFoundCount, 1)
  assert.equal(unavailableCount, 0)
  assert.equal(timers.scheduled.length, 0)
})

test('组件卸载时忽略在途请求结果', async () => {
  const timers = createTimerHarness()
  let resolveStatus
  let receivedSignal
  let statusCount = 0
  const response = new Promise((resolve) => {
    resolveStatus = resolve
  })

  const stop = startWikiJobStatusPolling({
    fetchStatus: (signal) => {
      receivedSignal = signal
      return response
    },
    onStatus: () => {
      statusCount += 1
      return true
    },
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  stop()
  assert.equal(receivedSignal.aborted, true)
  resolveStatus({ status: 'running' })
  await flush()

  assert.equal(statusCount, 0)
  assert.equal(timers.scheduled.length, 0)
})

test('组件卸载时清理已排队计时器，旧回调不能重新请求', async () => {
  const timers = createTimerHarness()
  let fetchCount = 0
  const stop = startWikiJobStatusPolling({
    fetchStatus: async () => {
      fetchCount += 1
      return { status: 'running' }
    },
    onStatus: () => true,
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await flush()
  assert.equal(timers.scheduled.length, 1)
  const staleTimer = timers.scheduled[0]
  stop()

  assert.deepEqual(timers.cleared, [staleTimer])
  staleTimer.callback()
  await flush()
  assert.equal(fetchCount, 1)
})

test('组件卸载会中断终态回调，并阻止异步回调后的页面更新', async () => {
  const timers = createTimerHarness()
  let resolveRefresh
  let callbackContext
  let pageUpdateCount = 0
  const refresh = new Promise((resolve) => {
    resolveRefresh = resolve
  })

  const stop = startWikiJobStatusPolling({
    fetchStatus: async () => ({ status: 'succeeded' }),
    onStatus: async (_status, context) => {
      callbackContext = context
      await refresh
      if (!context.isCancelled()) pageUpdateCount += 1
      return false
    },
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await flush()
  stop()
  assert.equal(callbackContext.signal.aborted, true)
  resolveRefresh()
  await flush()

  assert.equal(pageUpdateCount, 0)
  assert.equal(timers.scheduled.length, 0)
})
