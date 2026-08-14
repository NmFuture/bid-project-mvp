import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../api/index.js', import.meta.url), 'utf8')

test('四类技术标长任务都暴露 cancel 客户端', () => {
  assert.match(source, /directory-generation\/cancel`,\s*\{\s*method:\s*'POST'\s*\}\)/)
  assert.match(source, /gaps-detection\/cancel`,\s*\{\s*method:\s*'POST'\s*\}\)/)
  assert.match(source, /fill-generation\/cancel`,\s*\{\s*method:\s*'POST'\s*\}\)/)
  assert.match(source, /score-index\/cancel`,\s*\{\s*method:\s*'POST'\s*\}\)/)
})
