import test from 'node:test'
import assert from 'node:assert/strict'

import { businessParseResultDisplayState } from './businessParseResultDisplay.js'

test('completed business parse result displays structured result even without source files', () => {
  assert.equal(
    businessParseResultDisplayState({
      isParseCompleted: true,
      sourceFiles: [],
    }),
    'result',
  )
})

test('unfinished business parse without source files displays no-source hint', () => {
  assert.equal(
    businessParseResultDisplayState({
      isParseCompleted: false,
      sourceFiles: [],
    }),
    'no-source',
  )
})

test('unfinished business parse with source files displays pending hint', () => {
  assert.equal(
    businessParseResultDisplayState({
      isParseCompleted: false,
      sourceFiles: [{ name: 'tender.pdf' }],
    }),
    'pending',
  )
})
