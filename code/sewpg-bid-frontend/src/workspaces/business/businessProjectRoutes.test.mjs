import test from 'node:test'
import assert from 'node:assert/strict'

import {
  businessProjectParseResultMenuRoute,
  businessProjectParseResultNavigation,
  businessProjectParseResultRoute,
} from './businessProjectRoutes.js'

test('商务标项目操作菜单的查看解析结果入口跳回指定项目解析页', () => {
  assert.equal(
    businessProjectParseResultRoute('PRJ-0021'),
    '/parse/business?projectId=PRJ-0021',
  )
})

test('upload-and-run completion navigates to the target business parse result page', () => {
  assert.deepEqual(
    businessProjectParseResultNavigation('PRJ-0024'),
    {
      to: '/parse/business?projectId=PRJ-0024',
      options: { replace: true },
    },
  )
})

test('查看解析结果菜单点击会阻止项目行点击冒泡', () => {
  let stopped = 0
  const event = {
    stopPropagation() {
      stopped += 1
    },
  }

  assert.equal(
    businessProjectParseResultMenuRoute('PRJ-0025', event),
    '/parse/business?projectId=PRJ-0025',
  )
  assert.equal(stopped, 1)
})
