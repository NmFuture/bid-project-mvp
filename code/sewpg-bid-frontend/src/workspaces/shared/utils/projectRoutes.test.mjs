import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createProjectParseResultRoutes,
  selectParseProjectId,
  shouldSyncProjectParseResultRoute,
} from './projectRoutes.js'

test('解析结果路由按工作区前缀绑定', () => {
  const technical = createProjectParseResultRoutes('/parse/technical')
  const business = createProjectParseResultRoutes('/parse/business')

  assert.equal(technical.projectParseResultRoute(), '/parse/technical')
  assert.equal(technical.projectParseResultRoute('PRJ-0088'), '/parse/technical?projectId=PRJ-0088')
  assert.equal(business.projectParseResultRoute('PRJ-0021'), '/parse/business?projectId=PRJ-0021')
  assert.equal(
    technical.projectParseResultRoute('PRJ 0088'),
    `/parse/technical?projectId=${encodeURIComponent('PRJ 0088')}`,
  )
})

test('菜单路由阻止行点击冒泡，导航对象固定 replace', () => {
  const { projectParseResultMenuRoute, projectParseResultNavigation } = createProjectParseResultRoutes('/parse/technical')

  let stopped = 0
  const event = { stopPropagation() { stopped += 1 } }
  assert.equal(projectParseResultMenuRoute('PRJ-0089', event), '/parse/technical?projectId=PRJ-0089')
  assert.equal(stopped, 1)

  assert.deepEqual(projectParseResultNavigation('PRJ-0088'), {
    to: '/parse/technical?projectId=PRJ-0088',
    options: { replace: true },
  })
})

test('裸解析入口不自动选中历史项目，带 projectId 精确选中', () => {
  assert.equal(
    selectParseProjectId({
      queryProjectId: '',
      currentProjectId: '',
      reviewItems: [{ id: 'PRJ-0088', reviewDecision: 'pending' }],
    }),
    '',
  )
  assert.equal(
    selectParseProjectId({
      queryProjectId: 'PRJ-0088',
      currentProjectId: '',
      reviewItems: [
        { id: 'PRJ-0088', reviewDecision: 'participate' },
        { id: 'PRJ-0087', reviewDecision: 'pending' },
      ],
    }),
    'PRJ-0088',
  )
  assert.equal(
    selectParseProjectId({
      queryProjectId: 'PRJ-0099',
      currentProjectId: 'PRJ-0088',
      reviewItems: [{ id: 'PRJ-0088' }],
    }),
    'PRJ-0088',
  )
})

test('解析完成后才把裸路由同步到选中项目', () => {
  assert.equal(shouldSyncProjectParseResultRoute({ projectId: 'PRJ-0088', queryProjectId: '', parseCompleted: true }), true)
  assert.equal(shouldSyncProjectParseResultRoute({ projectId: 'PRJ-0088', queryProjectId: 'PRJ-0088', parseCompleted: true }), false)
  assert.equal(shouldSyncProjectParseResultRoute({ projectId: 'PRJ-0088', queryProjectId: '', parseCompleted: false }), false)
})
