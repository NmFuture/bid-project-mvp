import assert from 'node:assert/strict'
import test from 'node:test'

import { createFulltextRequestGuard } from './fulltextRequestGuard.js'

test('begin 返回递增序号，且新请求作废旧请求', () => {
  const guard = createFulltextRequestGuard()
  const first = guard.begin()
  assert.equal(guard.isCurrent(first), true)
  const second = guard.begin()
  assert.notEqual(first, second)
  assert.equal(guard.isCurrent(first), false)
  assert.equal(guard.isCurrent(second), true)
})

test('invalidate 使在途序号失效，模拟弹窗关闭后旧响应不再落地', () => {
  const guard = createFulltextRequestGuard()
  const seq = guard.begin()
  guard.invalidate()
  assert.equal(guard.isCurrent(seq), false)
})

test('invalidate 后再打开的新请求不受影响', () => {
  const guard = createFulltextRequestGuard()
  const stale = guard.begin()
  guard.invalidate()
  const fresh = guard.begin()
  assert.equal(guard.isCurrent(stale), false)
  assert.equal(guard.isCurrent(fresh), true)
})
