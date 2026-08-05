import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  isTerminalDirectoryStatus,
  subscribeDirectoryProgress,
} from './technicalDirectoryProgressStream.js'

const createTimerHarness = () => {
  const timers = new Map()
  let nextId = 1
  return {
    setTimer: (fn, delay) => {
      const id = nextId
      nextId += 1
      timers.set(id, { fn, delay })
      return id
    },
    clearTimer: (id) => timers.delete(id),
    pending: () => [...timers.values()],
    run: async (id) => {
      const timer = timers.get(id)
      timers.delete(id)
      await timer.fn()
    },
    runNext: async () => {
      const [id] = [...timers.keys()]
      await timers.get(id).fn()
      timers.delete(id)
    },
    size: () => timers.size,
  }
}

const createFakeStream = () => {
  const stream = {
    handlers: null,
    closed: false,
    readyState: 1,
    close() {
      this.closed = true
      this.readyState = 2
    },
  }
  return {
    stream,
    openStream: (handlers) => {
      stream.handlers = handlers
      return stream
    },
  }
}

test('delivers pushed states without polling while the stream is healthy', () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()
  const received = []

  subscribeDirectoryProgress({
    openStream,
    fetchStatus: () => assert.fail('healthy stream must not poll'),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  stream.handlers.onState({ status: 'running', percentage: 20 })
  stream.handlers.onState({ status: 'running', percentage: 42 })

  assert.deepEqual(received.map((item) => item.percentage), [20, 42])
  assert.equal(timers.size(), 0)
  assert.equal(stream.closed, false)
})

test('closes the stream on terminal states so the browser does not reconnect', () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()
  const received = []

  subscribeDirectoryProgress({
    openStream,
    fetchStatus: () => assert.fail('terminal state must not start polling'),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  stream.handlers.onState({ status: 'completed', percentage: 100 })

  assert.equal(stream.closed, true)
  assert.equal(timers.size(), 0)

  // 关流后迟到的推送不再进入页面状态
  stream.handlers.onState({ status: 'running', percentage: 42 })
  assert.equal(received.length, 1)
})

test('treats failed generation as terminal as well', () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()

  subscribeDirectoryProgress({
    openStream,
    fetchStatus: () => assert.fail('failed state must not start polling'),
    onState: () => {},
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  stream.handlers.onState({ status: 'failed', percentage: 42 })

  assert.equal(stream.closed, true)
  assert.equal(timers.size(), 0)
})

test('falls back to polling immediately when the stream is closed for good', async () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()
  const received = []

  subscribeDirectoryProgress({
    openStream,
    fetchStatus: async () => ({ status: 'running', percentage: 55 }),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    pollIntervalMs: 1000,
  })

  stream.readyState = 2
  stream.handlers.onError(new Error('stream closed'))

  assert.equal(timers.pending()[0].delay, 1000)
  await timers.runNext()
  assert.deepEqual(received, [{ status: 'running', percentage: 55 }])
  assert.equal(timers.pending().length, 1)
})

test('waits out a transient stream blip instead of degrading immediately', async () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()
  const received = []

  subscribeDirectoryProgress({
    openStream,
    fetchStatus: () => assert.fail('recovered stream must not poll'),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    recoveryGraceMs: 5000,
  })

  stream.readyState = 0
  stream.handlers.onError(new Error('reconnecting'))
  assert.equal(timers.pending()[0].delay, 5000)

  stream.readyState = 1
  stream.handlers.onState({ status: 'running', percentage: 60 })

  assert.equal(timers.size(), 0)
  assert.equal(received.length, 1)
})

test('degrades to polling when a blip never recovers', async () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()
  const received = []

  subscribeDirectoryProgress({
    openStream,
    fetchStatus: async () => ({ status: 'running', percentage: 70 }),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    recoveryGraceMs: 5000,
  })

  stream.readyState = 0
  stream.handlers.onError(new Error('reconnecting'))
  await timers.runNext()

  assert.equal(stream.closed, true)
  await timers.runNext()
  assert.deepEqual(received, [{ status: 'running', percentage: 70 }])
})

test('polls when the stream cannot be opened at all', async () => {
  const timers = createTimerHarness()
  const received = []

  subscribeDirectoryProgress({
    openStream: () => {
      throw new Error('EventSource unavailable')
    },
    fetchStatus: async () => ({ status: 'running', percentage: 12 }),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await timers.runNext()
  assert.deepEqual(received, [{ status: 'running', percentage: 12 }])
})

test('keeps polling after a transient status request failure', async () => {
  const timers = createTimerHarness()
  const received = []
  let attempt = 0

  subscribeDirectoryProgress({
    openStream: () => null,
    fetchStatus: async () => {
      attempt += 1
      if (attempt === 1) throw new Error('network down')
      return { status: 'running', percentage: 33 }
    },
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  await timers.runNext()
  assert.deepEqual(received, [])
  await timers.runNext()
  assert.deepEqual(received, [{ status: 'running', percentage: 33 }])
})

test('stops delivering and clears timers once unsubscribed', async () => {
  const timers = createTimerHarness()
  const { stream, openStream } = createFakeStream()
  const received = []

  const stop = subscribeDirectoryProgress({
    openStream,
    fetchStatus: async () => ({ status: 'running' }),
    onState: (payload) => received.push(payload),
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })

  stop()
  stop()

  assert.equal(stream.closed, true)
  assert.equal(timers.size(), 0)
  stream.handlers.onState({ status: 'running', percentage: 90 })
  assert.deepEqual(received, [])
})

test('recognizes terminal directory statuses case-insensitively', () => {
  assert.equal(isTerminalDirectoryStatus({ status: 'completed' }), true)
  assert.equal(isTerminalDirectoryStatus({ status: 'FAILED' }), true)
  assert.equal(isTerminalDirectoryStatus({ status: 'error' }), true)
  assert.equal(isTerminalDirectoryStatus({ status: 'running' }), false)
  assert.equal(isTerminalDirectoryStatus(null), false)
})

test('technical directory page subscribes via the stream instead of hand-rolled polling', () => {
  const pageSource = readFileSync(new URL('./pages/TechnicalParseResult.jsx', import.meta.url), 'utf8')

  assert.match(pageSource, /subscribeDirectoryProgress/)
  assert.match(pageSource, /technicalDirectoryAPI\.stream/)
  assert.doesNotMatch(pageSource, /pollDirectoryStatus/)
})
