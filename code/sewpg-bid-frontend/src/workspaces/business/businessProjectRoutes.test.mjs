import test from 'node:test'
import assert from 'node:assert/strict'

import {
  businessProjectParseResultMenuRoute,
  businessProjectParseResultNavigation,
  businessProjectParseResultRoute,
  selectBusinessParseProjectId,
  shouldSyncBusinessProjectParseResultRoute,
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

test('completed parse result syncs a bare business parse route to the selected project', () => {
  assert.equal(
    shouldSyncBusinessProjectParseResultRoute({
      projectId: 'PRJ-0051',
      queryProjectId: '',
      parseCompleted: true,
    }),
    true,
  )
  assert.equal(
    shouldSyncBusinessProjectParseResultRoute({
      projectId: 'PRJ-0051',
      queryProjectId: 'PRJ-0051',
      parseCompleted: true,
    }),
    false,
  )
  assert.equal(
    shouldSyncBusinessProjectParseResultRoute({
      projectId: 'PRJ-0051',
      queryProjectId: '',
      parseCompleted: false,
    }),
    false,
  )
})

test('无 projectId 的商务解析入口不自动选中历史待处理项目', () => {
  assert.equal(
    selectBusinessParseProjectId({
      queryProjectId: '',
      currentProjectId: '',
      reviewItems: [
        { id: 'PRJ-0043', reviewDecision: 'pending' },
      ],
    }),
    '',
  )
})

test('带 projectId 的商务解析入口精确选中指定项目', () => {
  assert.equal(
    selectBusinessParseProjectId({
      queryProjectId: 'PRJ-0045',
      currentProjectId: '',
      reviewItems: [
        { id: 'PRJ-0045', reviewDecision: 'participate' },
        { id: 'PRJ-0043', reviewDecision: 'pending' },
      ],
    }),
    'PRJ-0045',
  )
})
