import test from 'node:test'
import assert from 'node:assert/strict'

import {
  appendixTaskForFillTask,
  defaultAiFillReferenceMaterialIds,
} from './technicalGapRecognitionHelpers.js'

test('技术标 AI 填表默认选中来源矩阵推荐素材', () => {
  const selected = {
    sourceRouting: { source: 'appendix_source_matrix' },
    sourceRoutedMaterials: [{ id: 'RAW-RULE-ITEM' }],
    matchedMaterials: [{ id: 'RAW-MATCHED' }],
    appendixTasks: [
      {
        id: 'APPX-C1',
        sourceRouting: { source: 'appendix_source_matrix' },
        recommendedMaterials: [{ id: 'RAW-RULE-APPX' }],
      },
    ],
  }
  const task = { blankSource: { id: 'APPX-C1' } }

  assert.equal(appendixTaskForFillTask(selected, task)?.id, 'APPX-C1')
  assert.deepEqual(defaultAiFillReferenceMaterialIds(selected, [], task), ['RAW-RULE-ITEM'])
  assert.deepEqual(defaultAiFillReferenceMaterialIds(selected, ['RAW-MANUAL'], task), ['RAW-MANUAL'])
})

test('技术标 AI 填表在仅附表任务有规则时使用对应空表推荐素材', () => {
  const selected = {
    matchedMaterials: [{ id: 'RAW-MATCHED' }],
    appendixTasks: [
      {
        id: 'APPX-C1',
        sourceRouting: { source: 'appendix_source_matrix' },
        recommendedMaterials: [{ id: 'RAW-C1' }],
      },
      {
        id: 'APPX-D1',
        sourceRouting: { source: 'appendix_source_matrix' },
        recommendedMaterials: [{ id: 'RAW-D1' }],
      },
    ],
  }

  assert.deepEqual(
    defaultAiFillReferenceMaterialIds(selected, [], { blankSource: { id: 'APPX-D1' } }),
    ['RAW-D1'],
  )
})
