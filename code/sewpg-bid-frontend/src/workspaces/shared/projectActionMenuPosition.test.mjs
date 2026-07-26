import test from 'node:test'
import assert from 'node:assert/strict'
import { getProjectActionMenuPosition } from './projectActionMenuPosition.js'

test('底部空间不足时，项目操作菜单向上展开', () => {
  const position = getProjectActionMenuPosition({
    triggerRect: { top: 700, right: 1180, bottom: 730 },
    menuWidth: 144,
    menuHeight: 76,
    viewportWidth: 1200,
    viewportHeight: 768,
  })

  assert.equal(position.placement, 'top')
  assert.equal(position.top, 618)
  assert.equal(position.left, 1036)
})

test('空间充足时，项目操作菜单向下展开且不会超出视口', () => {
  const position = getProjectActionMenuPosition({
    triggerRect: { top: 100, right: 90, bottom: 130 },
    menuWidth: 144,
    menuHeight: 76,
    viewportWidth: 1200,
    viewportHeight: 768,
  })

  assert.equal(position.placement, 'bottom')
  assert.equal(position.top, 136)
  assert.equal(position.left, 8)
})
