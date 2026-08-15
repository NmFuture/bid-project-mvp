import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clearTechnicalTask,
  markTechnicalTask,
  restoreTechnicalTask,
  TECHNICAL_TASK_STORAGE_KEY,
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

test('运行中任务优先，同组内按先来后到排序', () => {
  const tasks = sortTechnicalTasks([
    { key: 'done', status: 'completed', startedAt: '2026-08-15T01:00:00Z' },
    { key: 'second', status: 'running', startedAt: '2026-08-15T01:02:00Z' },
    { key: 'first', status: 'running', startedAt: '2026-08-15T01:01:00Z' },
  ])
  assert.deepEqual(tasks.map((task) => task.key), ['first', 'second', 'done'])
})

test('轮询刷新 updatedAt 不会让两条同时在跑的任务互换位次', () => {
  const running = [
    { key: 'first', status: 'running', startedAt: '2026-08-15T01:01:00Z', updatedAt: '2026-08-15T01:05:00Z' },
    { key: 'second', status: 'running', startedAt: '2026-08-15T01:02:00Z', updatedAt: '2026-08-15T01:04:00Z' },
  ]
  assert.deepEqual(sortTechnicalTasks(running).map((task) => task.key), ['first', 'second'])

  // 第二条刚被轮询刷新，updatedAt 变成最新——顺序仍须不变
  running[1].updatedAt = '2026-08-15T01:06:00Z'
  assert.deepEqual(sortTechnicalTasks(running).map((task) => task.key), ['first', 'second'])
})

test('缺开始时间的任务排在最后且顺序稳定', () => {
  const tasks = sortTechnicalTasks([
    { key: 'b', status: 'running' },
    { key: 'a', status: 'running' },
    { key: 'timed', status: 'running', startedAt: '2026-08-15T01:01:00Z' },
  ])
  assert.deepEqual(tasks.map((task) => task.key), ['timed', 'a', 'b'])
})

test('已请求停止仍算运行中，排在终态通知之前', () => {
  const tasks = sortTechnicalTasks([
    { key: 'done', status: 'completed', startedAt: '2026-08-15T01:00:00Z' },
    { key: 'stopping', status: 'cancel_requested', startedAt: '2026-08-15T01:03:00Z' },
  ])
  assert.deepEqual(tasks.map((task) => task.key), ['stopping', 'done'])
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

test('恢复登记只补进度，不改写发起页写下的任务名和回跳页', () => {
  const storage = memoryStorage()
  markTechnicalTask({
    taskType: 'body-generate',
    projectId: 'P-9',
    projectName: '陆上风电项目',
    taskName: '生成正文',
    page: 'gaps',
    status: 'running',
    percentage: 20,
  }, storage)

  // 共创页读到同一个后端任务：只更新进度，不能把它改名成「重新生成正文」
  restoreTechnicalTask({
    taskType: 'body-generate',
    projectId: 'P-9',
    projectName: '陆上风电项目',
    taskName: '重新生成正文',
    page: 'editor',
    status: 'running',
    percentage: 55,
  }, storage)

  const [restored] = readTechnicalTasks(storage)
  assert.equal(restored.taskName, '生成正文')
  assert.equal(restored.page, 'gaps')
  assert.equal(restored.percentage, 55)
  assert.equal(readTechnicalTasks(storage).length, 1)

  // 本地登记丢了才补建，这时按当前页的标题和回跳页登记
  clearTechnicalTask('body-generate', 'P-9', storage)
  restoreTechnicalTask({
    taskType: 'body-generate',
    projectId: 'P-9',
    projectName: '陆上风电项目',
    taskName: '重新生成正文',
    page: 'editor',
    status: 'running',
    percentage: 60,
  }, storage)
  const [rebuilt] = readTechnicalTasks(storage)
  assert.equal(rebuilt.taskName, '重新生成正文')
  assert.equal(rebuilt.page, 'editor')
})

test('idle 或状态缺失的登记在读取时被剔除，不会渲染成已完成通知', () => {
  const storage = memoryStorage()
  markTechnicalTask({
    taskType: 'body-generate', projectId: 'P-10', projectName: '甲项目',
    taskName: '生成正文', status: 'idle', percentage: 0,
  }, storage)
  markTechnicalTask({
    taskType: 'index-regenerate', projectId: 'P-10', projectName: '甲项目',
    taskName: '重新生成索引', status: '', percentage: 0,
  }, storage)
  markTechnicalTask({
    taskType: 'parse', projectId: 'P-10', projectName: '甲项目',
    taskName: '技术标解析', status: 'completed', percentage: 100,
  }, storage)

  const tasks = readTechnicalTasks(storage)
  assert.deepEqual(tasks.map((task) => task.taskName), ['技术标解析'])
  // 剔除后要落盘，避免每次读取都重算
  assert.equal(JSON.parse(storage.getItem(TECHNICAL_TASK_STORAGE_KEY)).length, 1)
})

test('运行中和各类终态都保留在登记表里', () => {
  const storage = memoryStorage()
  for (const [index, status] of ['queued', 'running', 'processing', 'cancel_requested', 'completed', 'failed', 'cancelled', 'stale'].entries()) {
    markTechnicalTask({
      taskType: 'parse', projectId: `P-${index}`, projectName: `项目${index}`,
      taskName: '技术标解析', status, percentage: 10,
    }, storage)
  }
  assert.equal(readTechnicalTasks(storage).length, 8)
})
