import test from 'node:test'
import assert from 'node:assert/strict'

import {
  isUploadAndRunTimeout,
  isParseProgressCompleted,
  pollParseProgressOnce,
  shouldPollParseProgress,
  recoverUploadAndRunTimeout,
  mergeMonotonicParseProgress,
  summarizeParseProgress,
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

test('stops technical timeout recovery polling when abort signal is raised', async () => {
  const controller = new AbortController()
  let progressCalls = 0
  const parseClient = {
    progress: async () => {
      progressCalls += 1
      controller.abort()
      return { status: 'running', percentage: 25, summary: 'AI parsing' }
    },
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0087',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
    signal: controller.signal,
  })

  assert.equal(recovered.stopped, true)
  assert.equal(progressCalls, 1)
})

test('continues polling after technical upload request ends while backend is running', () => {
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

test('keeps displayed technical progress from moving backwards', () => {
  const previous = {
    status: 'running',
    percentage: 78,
    phaseLabel: 'Opencode 结构化解析',
    summary: 'opencode 正在返回解析输出。',
  }
  const incoming = {
    status: 'running',
    percentage: 72,
    phaseLabel: 'Opencode 结构化解析',
    summary: 'Opencode 仍在执行 S1 解析，已等待约 30 秒。',
  }

  const merged = mergeMonotonicParseProgress(previous, incoming)

  assert.equal(merged.percentage, 78)
  assert.equal(merged.summary, incoming.summary)
  assert.equal(merged.phaseLabel, incoming.phaseLabel)
})

test('keeps displayed technical phase progress from moving backwards within same phase', () => {
  const previous = {
    status: 'running',
    percentage: 78,
    phaseKey: 'opencode',
    phaseLabel: 'Opencode 结构化解析',
    phasePercent: 85,
    summary: 'Opencode 仍在执行 S1 解析，已等待约 160 秒。',
  }
  const incoming = {
    status: 'running',
    percentage: 78,
    phaseKey: 'opencode',
    phaseLabel: 'Opencode 结构化解析',
    phasePercent: 40,
    summary: '收到 opencode 解析输出片段。',
  }

  const merged = mergeMonotonicParseProgress(previous, incoming)

  assert.equal(merged.percentage, 78)
  assert.equal(merged.phasePercent, 85)
  assert.equal(merged.summary, incoming.summary)
})

test('summarizes structured parse phase with user-facing elapsed time', () => {
  const running = summarizeParseProgress({
    status: 'running',
    percentage: 95,
    phaseKey: 'opencode',
    phaseLabel: 'Opencode 结构化解析',
    phasePercent: 99,
    summary: 'Opencode 仍在执行 S1 解析，已等待约 30 秒。',
    opencodeOutput: {
      elapsedSeconds: 261,
      parts: [{ type: 'text', text: 'internal chunk' }],
    },
  })

  assert.equal(running.title, '结构化解析中')
  assert.equal(running.summary, '正在识别招标文件中的技术要求和原文依据，已执行 4 分 21 秒。')
  assert.equal(running.detail, '')
  assert.doesNotMatch(`${running.title}${running.summary}${running.detail}`, /AI|Opencode|opencode|S1|输出片段|阶段 99%/)
})

test('summarizes stale structured parse phase without internal implementation terms', () => {
  const stale = summarizeParseProgress({
    status: 'stale',
    percentage: 95,
    phaseKey: 'opencode',
    phaseLabel: 'Opencode 结构化解析',
    phasePercent: 99,
    summary: 'Opencode 仍在执行 S1 解析，已等待约 300 秒。',
  })

  assert.equal(stale.title, '结构化解析中')
  assert.equal(stale.statusText, '可能中断')
  assert.equal(stale.tone, 'warning')
  assert.equal(stale.detail, '')
  assert.doesNotMatch(`${stale.title}${stale.summary}${stale.detail}`, /AI|Opencode|opencode|S1|输出片段|阶段 99%/)
})

test('summarizes technical parse phase as two visible lines and stale status', () => {
  const running = summarizeParseProgress({
    status: 'running',
    percentage: 52,
    phaseLabel: '提取附表中',
    phasePercent: 35,
    current: 12,
    total: 80,
    summary: '正在提取附表，已生成 12 / 80。',
  })

  assert.equal(running.statusText, '解析中')
  assert.equal(running.title, '提取附表中')
  assert.equal(running.summary, '正在提取附表，已生成 12 / 80。')
  assert.equal(running.detail, '')
  assert.equal(running.percentage, 52)

  const stale = summarizeParseProgress({
    status: 'stale',
    percentage: 40,
    phaseLabel: 'PDF 处理中',
    summary: '解析长时间没有更新。',
  })

  assert.equal(stale.statusText, '可能中断')
  assert.equal(stale.tone, 'warning')
})

test('failed or cancelled progress at 100 percent is not treated as completed', () => {
  assert.equal(isParseProgressCompleted({ status: 'failed', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'error', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'stale', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'cancelled', percentage: 100 }), false)
  assert.equal(isParseProgressCompleted({ status: 'completed', percentage: 100 }), true)
  assert.equal(isParseProgressCompleted({ status: 'running', percentage: 100 }), true)
})

test('failed progress is handled as failure without reading stale results', async () => {
  let resultsCalled = 0
  const parseClient = {
    progress: async () => ({ status: 'failed', percentage: 100, summary: 'parse failed: post-processing error' }),
    results: async () => {
      resultsCalled += 1
      return { status: 'completed', itemCount: 453 }
    },
  }

  const snapshot = await pollParseProgressOnce({ projectId: 'PRJ-0087', parseClient })

  assert.equal(snapshot.completed, false)
  assert.equal(snapshot.failed, true)
  assert.equal(snapshot.result, null)
  assert.equal(resultsCalled, 0)
})

test('cancelled progress is handled as failure without reading stale results', async () => {
  let resultsCalled = 0
  const parseClient = {
    progress: async () => ({ status: 'cancelled', percentage: 100, summary: 'parse stop requested' }),
    results: async () => {
      resultsCalled += 1
      return { status: 'completed', itemCount: 453 }
    },
  }

  const snapshot = await pollParseProgressOnce({ projectId: 'PRJ-0087', parseClient })

  assert.equal(snapshot.completed, false)
  assert.equal(snapshot.failed, true)
  assert.equal(snapshot.result, null)
  assert.equal(resultsCalled, 0)
})

test('timeout recovery reports failure instead of stale result when re-parse fails', async () => {
  const parseClient = {
    progress: async () => ({ status: 'failed', percentage: 100, summary: 'parse failed: post-processing error' }),
    results: async () => ({ status: 'completed', itemCount: 453 }),
  }

  const recovered = await recoverUploadAndRunTimeout({
    projectId: 'PRJ-0087',
    parseClient,
    pollIntervalMs: 0,
    maxPollMs: 1000,
  })

  assert.equal(recovered.completed, false)
  assert.equal(recovered.failed, true)
  assert.equal(recovered.result, null)
})
