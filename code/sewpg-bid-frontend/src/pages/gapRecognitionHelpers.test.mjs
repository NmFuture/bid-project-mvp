import assert from 'node:assert/strict'
import test from 'node:test'

import {
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
} from './gapRecognitionHelpers.js'

test('manual material selection wins for AI fill references', () => {
  const selected = {
    matchedMaterials: [{ id: 'RAW-0001' }],
    appendixTasks: [
      { id: 'APP-1', recommendedMaterials: [{ id: 'RAW-0002' }] },
    ],
  }

  assert.deepEqual(defaultAiFillReferenceMaterialIds(selected, ['RAW-0099']), ['RAW-0099'])
})

test('AI fill falls back to one top recommended material for each blank appendix', () => {
  const selected = {
    matchedMaterials: [],
    appendixTasks: [
      {
        id: 'APP-1',
        recommendedMaterials: [{ id: 'RAW-0473' }, { id: 'RAW-0471' }],
      },
      {
        id: 'APP-2',
        recommendedMaterials: [{ id: 'RAW-0473' }, { id: 'RAW-0478' }],
      },
    ],
  }

  assert.deepEqual(defaultAiFillReferenceMaterialIds(selected, []), ['RAW-0473'])
})

test('AI fill parse fields include the blank source and appendix fields', () => {
  const selected = {
    appendixTasks: [
      {
        id: 'APP-1',
        availableParseFields: [{ id: 'FIELD-POWER' }, { id: 'FIELD-ROTOR' }],
      },
    ],
  }
  const task = { blankSource: { id: 'APP-1' } }

  assert.deepEqual(
    defaultAiFillParseFieldIds(selected, task),
    ['APP-1', 'FIELD-POWER', 'FIELD-ROTOR'],
  )
})
