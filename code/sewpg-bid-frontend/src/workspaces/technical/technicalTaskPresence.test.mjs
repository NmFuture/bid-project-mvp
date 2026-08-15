import test from 'node:test'
import assert from 'node:assert/strict'

import {
  acquireTechnicalTaskPresence,
  isTechnicalTaskForeground,
  isTechnicalTaskTracked,
  resetTechnicalTaskPresence,
  subscribeTechnicalTaskPresence,
  technicalForegroundTaskKeys,
  technicalTaskPresenceKey,
} from './technicalTaskPresence.js'

const parseTask = { taskType: 'parse', projectId: 'P-1' }

test('presence key 由任务类型和项目 id 组成', () => {
  assert.equal(technicalTaskPresenceKey('parse', 'P-1'), 'technical:parse:P-1')
})

test('没有页面登记时任务既不算被跟踪也不算前台', () => {
  resetTechnicalTaskPresence()
  assert.equal(isTechnicalTaskTracked(parseTask), false)
  assert.equal(isTechnicalTaskForeground(parseTask), false)
  assert.deepEqual([...technicalForegroundTaskKeys()], [])
})

test('登记为前台后既算被跟踪也算前台，释放后一并归零', () => {
  resetTechnicalTaskPresence()
  const release = acquireTechnicalTaskPresence('parse', 'P-1', { foreground: true })
  assert.equal(isTechnicalTaskTracked(parseTask), true)
  assert.equal(isTechnicalTaskForeground(parseTask), true)
  assert.deepEqual([...technicalForegroundTaskKeys()], ['technical:parse:P-1'])

  release()
  assert.equal(isTechnicalTaskTracked(parseTask), false)
  assert.equal(isTechnicalTaskForeground(parseTask), false)
})

test('只跟踪不前台：任务栈不再轮询它，但卡片照常显示', () => {
  resetTechnicalTaskPresence()
  const release = acquireTechnicalTaskPresence('parse', 'P-1')
  assert.equal(isTechnicalTaskTracked(parseTask), true)
  assert.equal(isTechnicalTaskForeground(parseTask), false, '关掉弹窗后仍在跟踪，但不再占着前台')
  release()
})

test('同一任务被两个页面登记时按引用计数释放', () => {
  resetTechnicalTaskPresence()
  const releaseA = acquireTechnicalTaskPresence('body-generate', 'P-2', { foreground: true })
  const releaseB = acquireTechnicalTaskPresence('body-generate', 'P-2', { foreground: true })
  const task = { taskType: 'body-generate', projectId: 'P-2' }

  releaseA()
  assert.equal(isTechnicalTaskForeground(task), true, '还有一个页面在显示，就不能算已经离开')
  releaseB()
  assert.equal(isTechnicalTaskForeground(task), false)
  assert.equal(isTechnicalTaskTracked(task), false)
})

test('重复调用同一个释放函数不会把计数扣穿', () => {
  resetTechnicalTaskPresence()
  const releaseA = acquireTechnicalTaskPresence('parse', 'P-3', { foreground: true })
  const releaseB = acquireTechnicalTaskPresence('parse', 'P-3', { foreground: true })
  releaseA()
  releaseA()
  const task = { taskType: 'parse', projectId: 'P-3' }
  assert.equal(isTechnicalTaskForeground(task), true)
  releaseB()
  assert.equal(isTechnicalTaskForeground(task), false)
})

test('缺任务类型或项目 id 时登记为空操作', () => {
  resetTechnicalTaskPresence()
  const release = acquireTechnicalTaskPresence('', '', { foreground: true })
  assert.deepEqual([...technicalForegroundTaskKeys()], [])
  release()
})

test('登记与释放都会通知订阅者', () => {
  resetTechnicalTaskPresence()
  let notified = 0
  const unsubscribe = subscribeTechnicalTaskPresence(() => { notified += 1 })
  const release = acquireTechnicalTaskPresence('parse', 'P-4', { foreground: true })
  assert.equal(notified, 2, 'tracked 和 foreground 各通知一次')
  release()
  assert.equal(notified, 4)
  unsubscribe()
  acquireTechnicalTaskPresence('parse', 'P-5')()
  assert.equal(notified, 4, '取消订阅后不再收到通知')
})

test('前台键集合每次返回新对象，便于当作 state 触发重算', () => {
  resetTechnicalTaskPresence()
  const release = acquireTechnicalTaskPresence('parse', 'P-6', { foreground: true })
  const first = technicalForegroundTaskKeys()
  const second = technicalForegroundTaskKeys()
  assert.notEqual(first, second)
  assert.deepEqual([...first], [...second])
  release()
})
