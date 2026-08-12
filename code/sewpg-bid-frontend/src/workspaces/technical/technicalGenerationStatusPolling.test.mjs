import test from 'node:test'
import assert from 'node:assert/strict'

import {
  subscribeTechnicalGenerationStatus,
} from './technicalGenerationStatusPolling.js'

const deferred = () => {
  let resolve
  const promise = new Promise((next) => {
    resolve = next
  })
  return { promise, resolve }
}

const flushPromises = () => new Promise((resolve) => setImmediate(resolve))

test('waits for the active status request before scheduling the next poll', async () => {
  const timers = []
  const first = deferred()
  const second = deferred()
  let calls = 0
  let active = 0
  let maxActive = 0

  const stop = subscribeTechnicalGenerationStatus({
    fetchStatus: async () => {
      calls += 1
      active += 1
      maxActive = Math.max(maxActive, active)
      const result = await (calls === 1 ? first.promise : second.promise)
      active -= 1
      return result
    },
    onStatus: () => {},
    setTimer: (callback) => {
      timers.push(callback)
      return timers.length
    },
    clearTimer: () => {},
  })

  assert.equal(timers.length, 1)
  timers.shift()()
  assert.equal(calls, 1)
  assert.equal(timers.length, 0)

  first.resolve({ status: 'running' })
  await flushPromises()
  assert.equal(timers.length, 1)

  timers.shift()()
  assert.equal(calls, 2)
  assert.equal(maxActive, 1)
  second.resolve({ status: 'completed' })
  await flushPromises()
  stop()
})

test('stops polling after a terminal status', async () => {
  const timers = []
  const statuses = []

  subscribeTechnicalGenerationStatus({
    fetchStatus: async () => ({ status: 'completed', percentage: 100 }),
    onStatus: (status) => statuses.push(status),
    setTimer: (callback) => {
      timers.push(callback)
      return timers.length
    },
    clearTimer: () => {},
  })

  timers.shift()()
  await flushPromises()

  assert.deepEqual(statuses, [{ status: 'completed', percentage: 100 }])
  assert.equal(timers.length, 0)
})

test('ignores an in-flight response after cancellation', async () => {
  const timers = []
  const request = deferred()
  const statuses = []

  const stop = subscribeTechnicalGenerationStatus({
    fetchStatus: async () => request.promise,
    onStatus: (status) => statuses.push(status),
    setTimer: (callback) => {
      timers.push(callback)
      return timers.length
    },
    clearTimer: () => {},
  })

  timers.shift()()
  stop()
  request.resolve({ status: 'running' })
  await flushPromises()

  assert.deepEqual(statuses, [])
  assert.equal(timers.length, 0)
})
