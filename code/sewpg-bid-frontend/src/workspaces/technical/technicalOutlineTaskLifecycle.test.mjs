import test from 'node:test'
import assert from 'node:assert/strict'

import {
  scopeTechnicalTaskPayload,
  technicalTaskBelongsToProject,
  technicalTaskResponseMatchesProject,
} from './technicalOutlineTaskLifecycle.js'

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
