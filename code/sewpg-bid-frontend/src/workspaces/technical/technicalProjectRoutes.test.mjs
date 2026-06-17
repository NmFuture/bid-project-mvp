import test from 'node:test'
import assert from 'node:assert/strict'

import {
  selectTechnicalParseProjectId,
  shouldSyncTechnicalProjectParseResultRoute,
  technicalProjectParseResultMenuRoute,
  technicalProjectParseResultNavigation,
  technicalProjectParseResultRoute,
} from './technicalProjectRoutes.js'

test('technical parse result route points back to the parse page for the project', () => {
  assert.equal(
    technicalProjectParseResultRoute('PRJ-0088'),
    '/parse/technical?projectId=PRJ-0088',
  )
})

test('upload-and-run completion navigates to the target technical parse result page', () => {
  assert.deepEqual(
    technicalProjectParseResultNavigation('PRJ-0088'),
    {
      to: '/parse/technical?projectId=PRJ-0088',
      options: { replace: true },
    },
  )
})

test('technical parse result menu route stops row click bubbling', () => {
  let stopped = 0
  const event = {
    stopPropagation() {
      stopped += 1
    },
  }

  assert.equal(
    technicalProjectParseResultMenuRoute('PRJ-0089', event),
    '/parse/technical?projectId=PRJ-0089',
  )
  assert.equal(stopped, 1)
})

test('completed technical parse result syncs a bare parse route to the selected project', () => {
  assert.equal(
    shouldSyncTechnicalProjectParseResultRoute({
      projectId: 'PRJ-0088',
      queryProjectId: '',
      parseCompleted: true,
    }),
    true,
  )
  assert.equal(
    shouldSyncTechnicalProjectParseResultRoute({
      projectId: 'PRJ-0088',
      queryProjectId: 'PRJ-0088',
      parseCompleted: true,
    }),
    false,
  )
  assert.equal(
    shouldSyncTechnicalProjectParseResultRoute({
      projectId: 'PRJ-0088',
      queryProjectId: '',
      parseCompleted: false,
    }),
    false,
  )
})

test('bare technical parse route does not auto-select historical pending projects', () => {
  assert.equal(
    selectTechnicalParseProjectId({
      queryProjectId: '',
      currentProjectId: '',
      reviewItems: [
        { id: 'PRJ-0088', reviewDecision: 'pending' },
      ],
    }),
    '',
  )
})

test('technical parse route with projectId selects the exact project', () => {
  assert.equal(
    selectTechnicalParseProjectId({
      queryProjectId: 'PRJ-0088',
      currentProjectId: '',
      reviewItems: [
        { id: 'PRJ-0088', reviewDecision: 'participate' },
        { id: 'PRJ-0087', reviewDecision: 'pending' },
      ],
    }),
    'PRJ-0088',
  )
})
