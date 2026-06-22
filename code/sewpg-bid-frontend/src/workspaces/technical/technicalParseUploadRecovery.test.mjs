import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isUploadAndRunTimeout,
  pollParseProgressOnce,
  shouldPollParseProgress,
  recoverUploadAndRunTimeout,
} from './technicalParseUploadRecovery.js'

test('detects technical upload-and-run timeout errors', () => {
  assert.equal(isUploadAndRunTimeout({ code: 'TIMEOUT' }), true)
  assert.equal(isUploadAndRunTimeout({ code: 'NETWORK_ERROR', message: 'request timed out' }), false)
  assert.equal(isUploadAndRunTimeout(null), false)
})

test('recovers technical timeout by polling progress and reading completed result', async () => {
  const progressSnapshots = [
    { status: 'running', percentage: 80, summary: 'agent is returning parse output' },
    { status: 'completed', percentage: 100, summary: 'parse completed' },
  ]
  const observed = []
  const parseClient = {
    progress: async () => progressSnapshots.shift(),
    results: async () => ({ status: 'completed', itemCount: 453 }),
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0087',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
    onProgress: (progress) => observed.push(progress),
  })

  assert.equal(recovered.completed, true)
  assert.deepEqual(recovered.result, { status: 'completed', itemCount: 453 })
  assert.deepEqual(observed.map((item) => item.status), ['running', 'completed'])
})

test('keeps polling when technical progress is complete but result is not ready', async () => {
  const progressSnapshots = [
    { status: 'completed', percentage: 100, summary: 'parse completed' },
    { status: 'completed', percentage: 100, summary: 'parse completed' },
  ]
  const resultSnapshots = [
    { status: 'idle' },
    { status: 'completed', itemCount: 453 },
  ]
  const parseClient = {
    progress: async () => progressSnapshots.shift(),
    results: async () => resultSnapshots.shift(),
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0087',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
  })

  assert.equal(recovered.completed, true)
  assert.deepEqual(recovered.result, { status: 'completed', itemCount: 453 })
})

test('technical completed progress reads result before publishing progress', async () => {
  const calls = []
  const parseClient = {
    progress: async () => {
      calls.push('progress')
      return { status: 'completed', percentage: 100, summary: 'parse completed' }
    },
    results: async () => {
      calls.push('results')
      return { status: 'completed', itemCount: 94 }
    },
  }

  const snapshot = await pollParseProgressOnce({
    projectId: 'PRJ-0051',
    parseClient,
    onProgress: () => calls.push('onProgress'),
  })

  assert.equal(snapshot.completed, true)
  assert.deepEqual(snapshot.result, { status: 'completed', itemCount: 94 })
  assert.deepEqual(calls, ['progress', 'results', 'onProgress'])
})

test('returns visible progress when technical timeout recovery is still running', async () => {
  const parseClient = {
    progress: async () => ({ status: 'running', percentage: 75, summary: 'AI parsing' }),
    results: async () => {
      throw new Error('final result should not be read')
    },
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0087',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 0,
  })

  assert.equal(recovered.completed, false)
  assert.equal(recovered.progress.status, 'running')
  assert.equal(recovered.progress.percentage, 75)
})

test('continues polling after technical upload request ends while backend is running', () => {
  assert.equal(shouldPollParseProgress({ uploading: false, progress: { status: 'running', percentage: 40 } }), true)
  assert.equal(shouldPollParseProgress({ uploading: false, progress: { status: 'completed', percentage: 100 } }), true)
  assert.equal(shouldPollParseProgress({
    uploading: false,
    progress: { status: 'completed', percentage: 100 },
    result: { status: 'completed' },
  }), false)
  assert.equal(shouldPollParseProgress({ uploading: false, progress: { status: 'idle' } }), false)
  assert.equal(shouldPollParseProgress({ uploading: true, progress: null }), true)
})
