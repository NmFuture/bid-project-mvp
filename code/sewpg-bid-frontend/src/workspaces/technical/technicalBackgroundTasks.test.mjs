import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clearTechnicalTask,
  markTechnicalTask,
  readTechnicalTasks,
  sortTechnicalTasks,
  technicalTaskKey,
  updateTechnicalTask,
} from './technicalBackgroundTasks.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

test('同一项目同一任务类型按稳定键去重', () => {
  const storage = memoryStorage()
  markTechnicalTask({
    taskType: 'outline-regenerate',
    projectId: 'P-1',
    projectName: '海上风电项目',
    taskName: '重新生成目录',
    percentage: 10,
    status: 'running',
    updatedAt: '2026-08-15T01:00:00Z',
  }, storage)
  markTechnicalTask({
    taskType: 'outline-regenerate',
    projectId: 'P-1',
    projectName: '海上风电项目',
    taskName: '重新生成目录',
    percentage: 48,
    status: 'running',
    updatedAt: '2026-08-15T01:01:00Z',
  }, storage)

  const tasks = readTechnicalTasks(storage, Date.parse('2026-08-15T01:02:00Z'))
  assert.equal(tasks.length, 1)
  assert.equal(tasks[0].key, technicalTaskKey('outline-regenerate', 'P-1'))
  assert.equal(tasks[0].percentage, 48)
})

test('运行中任务优先并按最近更新时间排序', () => {
  const tasks = sortTechnicalTasks([
    { key: 'done', status: 'completed', updatedAt: '2026-08-15T01:03:00Z' },
    { key: 'older', status: 'running', updatedAt: '2026-08-15T01:01:00Z' },
    { key: 'newer', status: 'running', updatedAt: '2026-08-15T01:02:00Z' },
  ])
  assert.deepEqual(tasks.map((task) => task.key), ['newer', 'older', 'done'])
})

test('任务支持局部更新、清除和过期清理', () => {
  const storage = memoryStorage()
  markTechnicalTask({
    taskType: 'body-generate',
    projectId: 'P-2',
    projectName: '陆上风电项目',
    taskName: '生成正文',
    status: 'running',
    percentage: 5,
    updatedAt: '2026-08-01T00:00:00Z',
  }, storage)
  updateTechnicalTask('body-generate', 'P-2', {
    percentage: 80,
    updatedAt: '2026-08-15T01:00:00Z',
  }, storage)
  assert.equal(readTechnicalTasks(storage, Date.parse('2026-08-15T01:01:00Z'))[0].percentage, 80)

  clearTechnicalTask('body-generate', 'P-2', storage)
  assert.deepEqual(readTechnicalTasks(storage), [])

  markTechnicalTask({
    taskType: 'parse',
    projectId: 'P-old',
    projectName: '过期项目',
    taskName: '技术标解析',
    status: 'failed',
    percentage: 100,
    updatedAt: '2026-08-01T00:00:00Z',
  }, storage)
  assert.deepEqual(readTechnicalTasks(storage, Date.parse('2026-08-15T00:00:00Z')), [])
})
