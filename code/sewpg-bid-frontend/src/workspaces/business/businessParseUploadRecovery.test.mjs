import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isUploadAndRunTimeout,
  isParseProgressCompleted,
  pollParseProgressOnce,
  shouldPollParseProgress,
  recoverUploadAndRunTimeout,
} from './businessParseUploadRecovery.js'

test('识别上传解析请求超时错误', () => {
  assert.equal(isUploadAndRunTimeout({ code: 'TIMEOUT' }), true)
  assert.equal(isUploadAndRunTimeout({ code: 'NETWORK_ERROR', message: '请求超时，请稍后重试。' }), false)
  assert.equal(isUploadAndRunTimeout(null), false)
})

test('上传解析请求超时后轮询到 completed 并读取最终结果', async () => {
  const progressSnapshots = [
    { status: 'running', percentage: 98, summary: '正在合成结果。' },
    { status: 'completed', percentage: 100, summary: '解析完成。' },
  ]
  const observed = []
  const parseClient = {
    progress: async () => progressSnapshots.shift(),
    results: async () => ({ status: 'completed', itemCount: 1070 }),
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0021',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
    onProgress: (progress) => observed.push(progress),
  })

  assert.equal(recovered.completed, true)
  assert.deepEqual(recovered.result, { status: 'completed', itemCount: 1070 })
  assert.deepEqual(observed.map((item) => item.status), ['running', 'completed'])
})

test('进度完成但结果暂未就绪时继续轮询直到最终结果可展示', async () => {
  const progressSnapshots = [
    { status: 'completed', percentage: 100, summary: '解析完成。' },
    { status: 'completed', percentage: 100, summary: '解析完成。' },
  ]
  const resultSnapshots = [
    { status: 'idle' },
    { status: 'completed', itemCount: 1070 },
  ]
  const parseClient = {
    progress: async () => progressSnapshots.shift(),
    results: async () => resultSnapshots.shift(),
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0021',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
  })

  assert.equal(recovered.completed, true)
  assert.deepEqual(recovered.result, { status: 'completed', itemCount: 1070 })
})

test('completed progress poll reads result before publishing progress state', async () => {
  const calls = []
  const parseClient = {
    progress: async () => {
      calls.push('progress')
      return { status: 'completed', percentage: 100, summary: '解析完成。' }
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

test('上传解析请求超时后仍在 running 时返回可继续展示的进度', async () => {
  const parseClient = {
    progress: async () => ({ status: 'running', percentage: 75, summary: 'AI 审查中。' }),
    results: async () => {
      throw new Error('不应读取最终结果')
    },
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0021',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 0,
  })

  assert.equal(recovered.completed, false)
  assert.equal(recovered.progress.status, 'running')
  assert.equal(recovered.progress.percentage, 75)
})

test('上传解析超时恢复轮询收到停止信号后结束', async () => {
  const controller = new AbortController()
  let progressCalls = 0
  const parseClient = {
    progress: async () => {
      progressCalls += 1
      controller.abort()
      return { status: 'running', percentage: 25, summary: 'AI 审查中。' }
    },
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0021',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
    signal: controller.signal,
  })

  assert.equal(recovered.stopped, true)
  assert.equal(progressCalls, 1)
})

test('上传请求结束后只要后端仍 running 就继续轮询进度', () => {
  assert.equal(shouldPollParseProgress({ uploading: false, progress: { status: 'running', percentage: 40 } }), true)
  assert.equal(shouldPollParseProgress({
    uploading: true,
    stopped: true,
    progress: { status: 'running', percentage: 40 },
  }), false)
  assert.equal(shouldPollParseProgress({ uploading: false, progress: { status: 'completed', percentage: 100 } }), true)
  assert.equal(shouldPollParseProgress({
    uploading: false,
    progress: { status: 'completed', percentage: 100 },
    result: { status: 'completed' },
  }), false)
  assert.equal(shouldPollParseProgress({ uploading: false, progress: { status: 'idle' } }), false)
  assert.equal(shouldPollParseProgress({ uploading: true, progress: null }), true)
})

test('失败/停止态进度即使 percentage=100 也不算完成', () => {
  assert.equal(isParseProgressCompleted({ status: 'failed', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'error', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'stale', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'cancelled', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'completed', percentage: 100 }), true)
  assert.equal(isParseProgressCompleted({ status: 'running', percentage: 100 }), true)
})

test('进度失败时不拉取旧结果，直接按失败处理', async () => {
  let resultsCalled = 0
  const parseClient = {
    progress: async () => ({ status: 'failed', percentage: 100, summary: '解析失败：磁盘已满。' }),
    results: async () => {
      resultsCalled += 1
      return { status: 'completed', itemCount: 1070 }
    },
  }

  const snapshot = await pollParseProgressOnce({ projectId: 'PRJ-0021', parseClient })

  assert.equal(snapshot.completed, false)
  assert.equal(snapshot.failed, true)
  assert.equal(snapshot.result, null)
  assert.equal(resultsCalled, 0)
})

test('已停止进度同样不拉取旧结果，按失败处理', async () => {
  let resultsCalled = 0
  const parseClient = {
    progress: async () => ({ status: 'cancelled', percentage: 100, summary: '已请求停止解析任务。' }),
    results: async () => {
      resultsCalled += 1
      return { status: 'completed', itemCount: 1070 }
    },
  }

  const snapshot = await pollParseProgressOnce({ projectId: 'PRJ-0021', parseClient })

  assert.equal(snapshot.completed, false)
  assert.equal(snapshot.failed, true)
  assert.equal(snapshot.result, null)
  assert.equal(resultsCalled, 0)
})

test('重解析失败且残留旧成功结果时恢复流程返回失败而不是旧结果', async () => {
  const parseClient = {
    progress: async () => ({ status: 'failed', percentage: 100, summary: '解析失败：后处理异常。' }),
    results: async () => ({ status: 'completed', itemCount: 1070 }),
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0021',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
  })

  assert.equal(recovered.completed, false)
  assert.equal(recovered.failed, true)
  assert.equal(recovered.result, null)
})
