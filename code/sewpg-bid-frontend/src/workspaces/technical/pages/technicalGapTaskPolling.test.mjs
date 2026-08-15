import test from 'node:test'
import assert from 'node:assert/strict'

import {
  backgroundTaskTerminalKey,
  runBackgroundTaskTick,
} from './technicalGapTaskPolling.js'

const TERMINAL = ['succeeded', 'partial', 'failed']

test('终态通知 key：非终态为 null，终态取 jobId+finishedAt', () => {
  assert.equal(backgroundTaskTerminalKey({ status: 'running' }, TERMINAL), null)
  assert.equal(backgroundTaskTerminalKey({ status: 'queued' }, TERMINAL), null)
  assert.equal(backgroundTaskTerminalKey(null, TERMINAL), null)
  assert.equal(
    backgroundTaskTerminalKey({ status: 'succeeded', jobId: 'JOB-1', finishedAt: '2026-08-15T00:00:00Z' }, TERMINAL),
    'JOB-1:2026-08-15T00:00:00Z',
  )
  // 缺 id 时退化为 ':'，同一轮空 id 终态仍然只通知一次
  assert.equal(backgroundTaskTerminalKey({ status: 'failed' }, TERMINAL), ':')
})

test('单拍轮询：每拍都回写 state，未到终态不出 notifyKey', async () => {
  const seen = []
  const result = await runBackgroundTaskTick({
    fetchStatus: async () => ({ bodyFillState: { status: 'running', done: 3 } }),
    extractState: (payload) => payload?.bodyFillState || null,
    terminalStatuses: TERMINAL,
    onState: (state) => seen.push(state),
    lastNotifiedKey: '',
  })
  assert.deepEqual(seen, [{ status: 'running', done: 3 }])
  assert.equal(result.notifyKey, null)
})

test('单拍轮询：终态首次给 notifyKey，同一 key 已通知过则不再给', async () => {
  const state = { status: 'succeeded', jobId: 'JOB-1', finishedAt: 'T1' }
  const tick = () => runBackgroundTaskTick({
    fetchStatus: async () => ({ bodyFillState: state }),
    extractState: (payload) => payload?.bodyFillState || null,
    terminalStatuses: TERMINAL,
    onState: () => {},
    lastNotifiedKey: '',
  })
  const first = await tick()
  assert.equal(first.notifyKey, 'JOB-1:T1')

  // 模拟 hook 的行为：ref 置位后下一拍同 key 被去重（收尾那一拍不重复弹 toast）
  const dup = await runBackgroundTaskTick({
    fetchStatus: async () => ({ bodyFillState: state }),
    extractState: (payload) => payload?.bodyFillState || null,
    terminalStatuses: TERMINAL,
    onState: () => {},
    lastNotifiedKey: first.notifyKey,
  })
  assert.equal(dup.notifyKey, null)

  // 新一轮任务（jobId 不同）必须能再通知
  const next = await runBackgroundTaskTick({
    fetchStatus: async () => ({ bodyFillState: { ...state, jobId: 'JOB-2' } }),
    extractState: (payload) => payload?.bodyFillState || null,
    terminalStatuses: TERMINAL,
    onState: () => {},
    lastNotifiedKey: first.notifyKey,
  })
  assert.equal(next.notifyKey, 'JOB-2:T1')
})

test('单拍轮询：取数失败原样抛出，由 hook 捕获后下个周期继续', async () => {
  await assert.rejects(
    runBackgroundTaskTick({
      fetchStatus: async () => { throw new Error('network down') },
      extractState: (payload) => payload?.bodyFillState || null,
      terminalStatuses: TERMINAL,
      onState: () => {},
      lastNotifiedKey: '',
    }),
    /network down/,
  )
})
