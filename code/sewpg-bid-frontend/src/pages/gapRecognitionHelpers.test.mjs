import assert from 'node:assert/strict'
import test from 'node:test'

import {
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
  matchedMaterialForItem,
  previewChoicesForItem,
  resultSummaryForItem,
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

test('covered child resolves preview material from parent chapter', () => {
  const parent = {
    id: 'GAP-0013',
    number: '第3章',
    title: '风资源评估与机位排布方案',
    matchedMaterials: [{ id: 'RAW-0473', name: '整章方案.docx' }],
  }
  const child = {
    id: 'GAP-0014',
    coveredByParent: 'GAP-0013',
    matchedMaterials: [],
  }

  const match = matchedMaterialForItem(child, [parent, child])
  assert.equal(match.inherited, true)
  assert.equal(match.material.id, 'RAW-0473')
})

test('preview choices prefer the filled artifact while keeping blank and material previews available', () => {
  const selected = {
    resolvedArtifacts: [{ id: 'ART-1', fileName: '填写结果.docx', onlyoffice: { fileUrl: '/artifact.docx' } }],
    fillTasks: [{ blankSource: { id: 'APPX-1', title: '空表' } }],
    matchedMaterials: [{ id: 'RAW-1', name: '素材.docx' }],
  }

  assert.deepEqual(
    previewChoicesForItem(selected).map((choice) => choice.kind),
    ['artifact', 'appendix', 'material'],
  )
})

test('preview choices use blank appendix before AI fill result exists', () => {
  const selected = {
    fillTasks: [{ blankSource: { id: 'APPX-1', title: '空表' } }],
    matchedMaterials: [{ id: 'RAW-1', name: '素材.docx' }],
  }

  assert.deepEqual(
    previewChoicesForItem(selected).map((choice) => choice.kind),
    ['appendix', 'material'],
  )
})

test('result summary labels AI-filled items as filled', () => {
  assert.deepEqual(
    resultSummaryForItem({
      decision: 'fill_required',
      resolvedArtifacts: [{ id: 'ART-1', source: 'ai_fill', fileName: '填写结果.docx' }],
    }),
    { label: 'AI已填写', tone: 'resolved' },
  )
})

test('result summary exposes strict AI fill quality state when available', () => {
  assert.deepEqual(
    resultSummaryForItem({
      decision: 'fill_required',
      resolvedArtifacts: [
        {
          id: 'ART-1',
          source: 'ai_fill',
          fileName: '填写结果.docx',
          qualityReport: { status: 'passed' },
        },
      ],
    }),
    { label: 'AI已填写 · 验收通过', tone: 'resolved' },
  )
  assert.deepEqual(
    resultSummaryForItem({
      decision: 'fill_required',
      resolvedArtifacts: [
        {
          id: 'ART-2',
          source: 'ai_fill',
          fileName: '填写结果.docx',
          qualityReport: { status: 'needs_review' },
        },
      ],
    }),
    { label: 'AI已填写 · 待复核', tone: 'fill' },
  )
})

test('preview choices route fill-template blank source through material preview', () => {
  const selected = {
    fillTasks: [
      {
        blankSource: {
          id: 'RAW-0453',
          materialId: 'RAW-0453',
          title: '待填写-技术评分标准索引表.docx',
          sourceType: 'material_fill_template',
          folderPath: '技术标/客户素材/华能集团/技术标-标前概述',
        },
      },
    ],
  }

  const [choice] = previewChoicesForItem(selected)
  assert.equal(choice.kind, 'blankMaterial')
  assert.equal(choice.material.id, 'RAW-0453')
})

test('result summary labels material-required items as waiting for upload or selection', () => {
  assert.deepEqual(
    resultSummaryForItem({ decision: 'material_required' }),
    { label: '等待上传或选择素材', tone: 'missing' },
  )
})
