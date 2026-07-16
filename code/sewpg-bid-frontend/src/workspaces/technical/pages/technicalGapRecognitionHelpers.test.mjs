import test from 'node:test'
import assert from 'node:assert/strict'

import {
  appendixTaskForFillTask,
  defaultAiFillReferenceMaterialIds,
  isFillTemplateMaterial,
  technicalGapTagOf,
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
  assert.deepEqual(defaultAiFillReferenceMaterialIds(selected, [], task), ['RAW-RULE-APPX', 'RAW-RULE-ITEM'])
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

test('待填写素材严格按「待填写-」前缀识别', () => {
  assert.equal(isFillTemplateMaterial({ name: '待填写-附表D3桨距角曲线.docx' }), true)
  assert.equal(isFillTemplateMaterial({ cleanedFileName: '待填写-项目技术承诺函.docx' }), true)
  assert.equal(isFillTemplateMaterial({ name: '技术服务及售后服务.docx' }), false)
  assert.equal(isFillTemplateMaterial({ name: '本表待填写内容清单.docx' }), false)
})

test('目录标签：无候选或全部低于30%判人工补充', () => {
  assert.equal(technicalGapTagOf({ id: 'G1', decision: 'material_required' }), 'needs_material')
  assert.equal(
    technicalGapTagOf({ id: 'G2', decision: 'review_required', candidateMaterials: [{ id: 'M1', matchScore: 0.2 }] }),
    'needs_material',
  )
})

test('目录标签：30~98分候选且无待填写素材判已匹配待完善', () => {
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'review_required', candidateMaterials: [{ id: 'M1', matchScore: 0.6 }] }),
    'needs_refine',
  )
  assert.equal(
    technicalGapTagOf({ id: 'G2', decision: 'review_required', candidateMaterials: [{ id: 'M1', matchScore: 0.98 }] }),
    'needs_refine',
  )
})

test('目录标签：匹配到待填写素材（附表/前缀/填写任务）判已匹配待填写', () => {
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'fill_required', appendixTasks: [{ id: 'APPX-C1' }] }),
    'needs_fill',
  )
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'review_required',
      candidateMaterials: [{ id: 'M1', name: '待填写-附表F31部件参数表.docx', matchScore: 0.5 }],
    }),
    'needs_fill',
  )
})

test('目录标签：同时命中99分素材与待填写素材时单独拉出为待填写', () => {
  assert.equal(
    technicalGapTagOf({
      id: 'G1',
      decision: 'ready',
      matchedMaterials: [{ id: 'M1', matchScore: 0.99 }],
      candidateMaterials: [{ id: 'M2', name: '待填写-同名模板.docx', matchScore: 0.4 }],
    }),
    'needs_fill',
  )
})

test('目录标签：99分（文件名精确命中）或人操作过判已就绪', () => {
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'ready', matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }),
    'ready',
  )
  // 人工选用素材后即已就绪（哪怕该项还挂着待填写模板候选）。
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'fill_required',
      candidateMaterials: [{ id: 'M1', name: '待填写-模板.docx', matchScore: 0.5 }],
      resolvedArtifacts: [{ id: 'ART-1', source: 'material_library' }],
    }),
    'ready',
  )
  // AI 填写产物经人工确认后就绪；未确认则仍待填写。
  assert.equal(
    technicalGapTagOf({
      id: 'G3',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'completed' }],
      resolvedArtifacts: [{ id: 'ART-2', source: 'ai_fill', qualityGate: 'human_confirmed' }],
    }),
    'ready',
  )
  assert.equal(
    technicalGapTagOf({
      id: 'G4',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'completed' }],
      resolvedArtifacts: [{ id: 'ART-3', source: 'ai_fill', qualityReport: { status: 'needs_review' } }],
    }),
    'needs_fill',
  )
})

test('目录标签：结构项无标签，被父章覆盖的子节跟随父章', () => {
  const parent = { id: 'P1', decision: 'ready', matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }
  const child = { id: 'C1', decision: 'ready', coveredByParent: 'P1' }
  const fillParent = { id: 'P2', decision: 'fill_required', fillTasks: [{ id: 'T1', status: 'pending' }] }
  const fillChild = { id: 'C2', decision: 'fill_required', coveredByParent: 'P2' }

  assert.equal(technicalGapTagOf({ id: 'S1', usage: 'structural', decision: 'ready' }), '')
  assert.equal(technicalGapTagOf({ id: 'S2', decision: 'ready' }), '')
  assert.equal(technicalGapTagOf(child, [parent, child]), 'ready')
  assert.equal(technicalGapTagOf(fillChild, [fillParent, fillChild]), 'needs_fill')
})
