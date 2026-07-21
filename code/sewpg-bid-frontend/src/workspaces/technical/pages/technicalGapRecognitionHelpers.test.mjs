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

test('目录标签：30~98分候选且无待填写素材判已匹配-待确认', () => {
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

test('目录标签：99分（文件名精确命中）豁免确认自动就绪', () => {
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'ready', matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }),
    'ready',
  )
})

test('目录标签：自动就绪也可人工撤销（产品反馈 2026-07-21：撤销要真正生效，不是无操作）', () => {
  // 未操作过：99 分自动就绪。
  const autoReady = { id: 'G1', decision: 'ready', matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }
  assert.equal(technicalGapTagOf(autoReady), 'ready')
  // 人工撤销（humanConfirmed 显式为 false）：跳过自动就绪判定，按分数回落到「已匹配-待确认」。
  assert.equal(technicalGapTagOf({ ...autoReady, humanConfirmed: false }), 'needs_refine')
  // 撤销后再次人工确认：恢复已就绪。
  assert.equal(technicalGapTagOf({ ...autoReady, humanConfirmed: true }), 'ready')
})

test('目录标签：除精确命中外，人工点「确认」是变已就绪的唯一途径（产品裁决 2026-07-21）', () => {
  // 选用素材/上传产物本身不再翻绿：点确认之前标签不变。
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'ready',
      candidateMaterials: [{ id: 'M1', name: '待填写-模板.docx', matchScore: 0.5 }],
      resolvedArtifacts: [{ id: 'ART-1', source: 'material_library' }],
    }),
    'needs_fill',
  )
  // AI 填写完成（含质检通过）也不翻绿。
  assert.equal(
    technicalGapTagOf({
      id: 'G3',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'completed' }],
      resolvedArtifacts: [{ id: 'ART-2', source: 'ai_fill', qualityGate: 'human_confirmed' }],
    }),
    'needs_fill',
  )
  // 后端 recompute 会把选材后的 decision 翻成 ready，不能据此判绿。
  assert.equal(
    technicalGapTagOf({
      id: 'G4',
      decision: 'ready',
      candidateMaterials: [{ id: 'M1', matchScore: 0.6 }],
      resolvedArtifacts: [{ id: 'ART-3', source: 'material_library' }],
    }),
    'needs_refine',
  )
  // 人工确认（humanConfirmed）无前置条件，确认即就绪；撤销后回到派生标签。
  assert.equal(
    technicalGapTagOf({ id: 'G5', decision: 'material_required', humanConfirmed: true }),
    'ready',
  )
  assert.equal(
    technicalGapTagOf({
      id: 'G6',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'pending' }],
      humanConfirmed: true,
    }),
    'ready',
  )
  assert.equal(
    technicalGapTagOf({ id: 'G7', decision: 'material_required', humanConfirmed: false }),
    'needs_material',
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
  // 子节自身被人工确认后不再跟随父章标签。
  const confirmedChild = { id: 'C3', decision: 'fill_required', coveredByParent: 'P2', humanConfirmed: true }
  assert.equal(technicalGapTagOf(confirmedChild, [fillParent, confirmedChild]), 'ready')
})
