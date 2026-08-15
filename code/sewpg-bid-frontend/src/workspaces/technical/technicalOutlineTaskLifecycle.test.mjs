import test from 'node:test'
import assert from 'node:assert/strict'

import {
  scopeTechnicalTaskPayload,
  technicalTaskBelongsToProject,
  technicalTaskResponseMatchesProject,
} from './technicalOutlineTaskLifecycle.js'
import * as taskLifecycle from './technicalOutlineTaskLifecycle.js'

test('任务状态写入项目归属标识且不修改原对象', () => {
  const payload = { status: 'running', percentage: 20 }
  const scoped = scopeTechnicalTaskPayload(42, payload)

  assert.deepEqual(scoped, { status: 'running', percentage: 20, _projectId: '42' })
  assert.notEqual(scoped, payload)
  assert.equal(payload._projectId, undefined)
})

test('任务状态只属于相同项目', () => {
  assert.equal(technicalTaskBelongsToProject({ _projectId: 'project-a' }, 'project-a'), true)
  assert.equal(technicalTaskBelongsToProject({ _projectId: 'project-a' }, 'project-b'), false)
  assert.equal(technicalTaskBelongsToProject(null, 'project-a'), false)
})

test('异步响应只允许写回发起请求时的项目', () => {
  assert.equal(technicalTaskResponseMatchesProject(7, '7'), true)
  assert.equal(technicalTaskResponseMatchesProject('7', '8'), false)
  assert.equal(technicalTaskResponseMatchesProject(null, ''), false)
})

test('仅允许当前项目未处理且未收口中的 completed epoch 启动收口', () => {
  assert.equal(typeof taskLifecycle.canStartTechnicalTaskFinalize, 'function')
  const base = {
    payload: { _projectId: 'project-a' },
    projectId: 'project-a',
    shouldFinalize: true,
    epoch: 3,
    handledEpoch: 0,
    finalizingEpoch: 0,
  }

  assert.equal(taskLifecycle.canStartTechnicalTaskFinalize(base), true)
  assert.equal(taskLifecycle.canStartTechnicalTaskFinalize({ ...base, projectId: 'project-b' }), false)
  assert.equal(taskLifecycle.canStartTechnicalTaskFinalize({ ...base, shouldFinalize: false }), false)
  assert.equal(taskLifecycle.canStartTechnicalTaskFinalize({ ...base, epoch: 0 }), false)
  assert.equal(taskLifecycle.canStartTechnicalTaskFinalize({ ...base, handledEpoch: 3 }), false)
  assert.equal(taskLifecycle.canStartTechnicalTaskFinalize({ ...base, finalizingEpoch: 3 }), false)
})

test('START 异常后 active 状态无需时间戳即可恢复', () => {
  assert.equal(typeof taskLifecycle.recoverableTechnicalTaskState, 'function')
  const requestStartedAt = Date.parse('2026-08-15T10:00:00Z')

  for (const status of ['queued', 'running', 'processing', 'cancel_requested']) {
    assert.equal(
      taskLifecycle.recoverableTechnicalTaskState({ status }, requestStartedAt),
      true,
      `${status} 应可恢复`,
    )
  }
})

test('START 异常后只恢复本轮请求产生的 terminal 状态', () => {
  const requestStartedAt = Date.parse('2026-08-15T10:00:00Z')

  for (const status of ['completed', 'failed', 'cancelled']) {
    assert.equal(
      taskLifecycle.recoverableTechnicalTaskState(
        { status, updatedAt: '2026-08-15T10:00:00Z' },
        requestStartedAt,
      ),
      true,
      `${status} 的本轮状态应可恢复`,
    )
    assert.equal(
      taskLifecycle.recoverableTechnicalTaskState(
        { status, completedAt: '2026-08-15T09:59:59Z' },
        requestStartedAt,
      ),
      false,
      `${status} 的历史状态不应恢复`,
    )
  }

  assert.equal(
    taskLifecycle.recoverableTechnicalTaskState(
      { status: 'completed', generatedAt: '2026-08-15T10:00:01Z' },
      requestStartedAt,
    ),
    true,
  )
  assert.equal(taskLifecycle.recoverableTechnicalTaskState({ status: 'idle' }, requestStartedAt), false)
  assert.equal(taskLifecycle.recoverableTechnicalTaskState(null, requestStartedAt), false)
})
