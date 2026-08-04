import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  aiFillComparisonPair,
  appendixTaskForFillTask,
  defaultAiFillReferenceMaterialIds,
  isFillTemplateMaterial,
  technicalGapTagOf,
} from './technicalGapRecognitionHelpers.js'

import * as technicalHelpers from './technicalGapRecognitionHelpers.js'

test('生成完成提示展示 warning 数量且格式清洗失败时明确回退', () => {
  const presentation = technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: {
      summary: { warningCount: 2 },
      warnings: [
        { code: 'MISSING_SECTION', message: '缺少章节' },
        { code: 'FORMAT_RISK', message: '存在格式风险' },
      ],
      formatClean: { status: 'failed', error: 'cleaner exited 1' },
    },
  })

  assert.equal(presentation.warningCount, 2)
  assert.equal(presentation.formatCleanFailed, true)
  assert.equal(presentation.formatCleanMessage, '格式清洗失败，当前使用组装稿')
})

test('AI 填写结果优先与待填写模板形成左右对比', () => {
  const result = { key: 'artifact:A1', kind: 'artifact', artifact: { source: 'ai_fill' } }
  const material = { key: 'material:M1', kind: 'material' }
  const blank = { key: 'blank-material:B1', kind: 'blankMaterial' }

  assert.deepEqual(aiFillComparisonPair([result, material, blank], result), {
    reference: blank,
    result,
  })
  assert.equal(aiFillComparisonPair([result], result), null)
  assert.equal(aiFillComparisonPair([material, blank], material), null)
})

test('生成提示在 summary 未给数量时累计 warning count', () => {
  const presentation = technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: {
      summary: {},
      warnings: [{ code: 'A', count: 3 }, { code: 'B', count: 2 }],
    },
  })

  assert.equal(presentation.warningCount, 5)
})

test('生成提示不把 null warningCount 当作零', () => {
  const presentation = technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: {
      summary: { warningCount: null },
      warnings: [{ code: 'A', count: 3 }, { code: 'B', count: 2 }],
    },
  })

  assert.equal(presentation.warningCount, 5)
})

test('生成提示不让 summary 零值隐藏 warning 派生数量', () => {
  const presentation = technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: {
      summary: { warningCount: 0 },
      warnings: [{ code: 'A', count: 3 }, { code: 'B', count: 2 }],
    },
  })

  assert.equal(presentation.warningCount, 5)
})

test('生成提示采用 summary 与 warning 派生数量的较大值', () => {
  const presentation = technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: {
      summary: { warningCount: 2 },
      warnings: [{ code: 'A', count: 3 }, { code: 'B', count: 2 }],
    },
  })

  assert.equal(presentation.warningCount, 5)
})

test('共创格式状态从 document payload 恢复，标准版不携带历史自定义值', () => {
  const restored = technicalHelpers.technicalFormatStateFromDocument({
    technicalFormatPreset: 'custom',
    technicalFormatStyleOverrides: { bodyZhFont: '宋体', bodySizePt: 14 },
  }, {
    bodyZhFont: '等线',
    bodySizePt: 12,
    insertToc: true,
  })

  assert.equal(restored.preset, 'custom')
  assert.deepEqual(restored.styleOverrides, {
    bodyZhFont: '宋体',
    bodySizePt: 14,
    insertToc: true,
  })
  assert.deepEqual(technicalHelpers.technicalFormatRequest('standard', restored.styleOverrides), { preset: 'standard' })
  assert.deepEqual(technicalHelpers.technicalFormatRequest('custom', restored.styleOverrides), {
    preset: 'custom',
    styleOverrides: restored.styleOverrides,
  })
})

test('格式应用响应缺 document 时按本次请求推进本地格式状态', () => {
  const currentDocument = {
    fileName: '技术标.docx',
    technicalFormatPreset: 'standard',
    technicalFormatStyleOverrides: { bodyZhFont: '等线' },
  }
  const styleOverrides = { bodyZhFont: '宋体', bodySizePt: 14 }

  const customDocument = technicalHelpers.technicalFormatDocumentAfterApply(
    currentDocument,
    'custom',
    styleOverrides,
    null,
  )
  assert.equal(customDocument.technicalFormatPreset, 'custom')
  assert.deepEqual(customDocument.technicalFormatStyleOverrides, styleOverrides)

  const standardDocument = technicalHelpers.technicalFormatDocumentAfterApply(
    customDocument,
    'standard',
    styleOverrides,
    undefined,
  )
  assert.equal(standardDocument.technicalFormatPreset, 'standard')
  assert.deepEqual(standardDocument.technicalFormatStyleOverrides, {})
})

test('页面 warning 不阻断进入共创，下载与 technicalFormat 调用路径保持不变', async () => {
  const gapSource = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')
  const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

  assert.match(gapSource, /warningCount/)
  assert.match(gapSource, /disabled=\{Boolean\(busyAction\) \|\| !generationCompleted\}/)
  assert.match(editorSource, /technicalDocumentAPI\.technicalFormat\(id, payload\)/)
  assert.match(editorSource, /download=\{finalData\?\.fileName \|\| data\?\.fileName \|\| defaultWordFileName\}/)
  assert.match(editorSource, /technicalDocumentAPI\.finalPdf\(id\)/)
})

test('事实表清单和素材范围变更后自动重建，不保留手动刷新入口', async () => {
  const source = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')
  const uploadStart = source.indexOf('const handleFactSpecsUpload')
  const scopeStart = source.indexOf('const handleSaveMaterialPaths')
  const curateStart = source.indexOf('const handleCurateFacts')
  const uploadFlow = source.slice(uploadStart, scopeStart)
  const scopeFlow = source.slice(scopeStart, curateStart)

  assert.ok(uploadStart >= 0 && scopeStart > uploadStart && curateStart > scopeStart)
  assert.ok(uploadFlow.indexOf('uploadFactSpecs') < uploadFlow.indexOf('buildFacts'))
  assert.ok(scopeFlow.indexOf('saveMaterialSources') < scopeFlow.indexOf('buildFacts'))
  assert.doesNotMatch(source, /onBuild|刷新事实/)
})

test('事实表弹窗筛选时保持固定高度并只滚动表格区域', async () => {
  const source = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')

  assert.match(source, /h-\[calc\(100vh-64px\)\] max-h-\[860px\]/)
  assert.match(source, /mb-2 flex h-6 shrink-0 items-center/)
  assert.match(source, /h-full overflow-auto \[scrollbar-gutter:stable\]/)
  assert.match(source, /sticky top-0 z-10 grid items-center/)
})

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

test('目录标签：甲方已填附表豁免确认自动就绪（2026-08-02，与 0.99 精确命中同级）', () => {
  const clientProvidedTask = { id: 'APPX-1', sourceRouting: { status: 'client_provided' } }
  const fillTask = { id: 'APPX-2', sourceRouting: {} }
  // 全部附表任务命中甲方已填文件：豁免确认自动就绪。
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'ready', status: 'resolved', appendixTasks: [clientProvidedTask] }),
    'ready',
  )
  // 部分覆盖：仍有待填写任务，不豁免。
  assert.equal(
    technicalGapTagOf({ id: 'G2', decision: 'fill_required', appendixTasks: [clientProvidedTask, fillTask] }),
    'needs_fill',
  )
  // 人工撤销后回落到待填写，再次确认恢复已就绪。
  const covered = { id: 'G3', decision: 'ready', status: 'resolved', appendixTasks: [clientProvidedTask] }
  assert.equal(technicalGapTagOf({ ...covered, humanConfirmed: false }), 'needs_fill')
  assert.equal(technicalGapTagOf({ ...covered, humanConfirmed: true }), 'ready')
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

test('父章节覆盖：目录号归一化与后代识别', () => {
  assert.equal(technicalHelpers.technicalGapNumberKey('第3章'), '3')
  assert.equal(technicalHelpers.technicalGapNumberKey('第十二章'), '12')
  assert.equal(technicalHelpers.technicalGapNumberKey('5.8.2'), '5.8.2')

  const chapter = { id: 'P1', number: '第3章' }
  const items = [
    chapter,
    { id: 'C1', number: '3.1' },
    { id: 'C2', number: '3.1.1' },
    { id: 'X1', number: '4.1' },
    // 前缀相同但不是下级：30.1 不能被「3.」误吞。
    { id: 'X2', number: '30.1' },
  ]
  const descendants = technicalHelpers.technicalGapDescendants(chapter, items)
  assert.deepEqual(descendants.map((item) => item.id), ['C1', 'C2'])
})

test('父章节覆盖：本节点没素材时不可设置，设置后可撤销', () => {
  const items = [
    { id: 'P1', number: '第3章' },
    { id: 'C1', number: '3.1' },
  ]
  const empty = technicalHelpers.technicalGapParentCoverageState(items[0], items)
  assert.equal(empty.descendantCount, 1)
  assert.equal(empty.hasMaterial, false)
  assert.equal(empty.canApply, false)

  const withMaterial = [
    { id: 'P1', number: '第3章', matchedMaterials: [{ id: 'M1' }] },
    { id: 'C1', number: '3.1' },
  ]
  const ready = technicalHelpers.technicalGapParentCoverageState(withMaterial[0], withMaterial)
  assert.equal(ready.canApply, true)
  assert.equal(ready.applied, false)

  const applied = [
    { id: 'P1', number: '第3章', matchedMaterials: [{ id: 'M1' }] },
    { id: 'C1', number: '3.1', coveredByParent: 'P1', parentCoverageSource: 'manual' },
    // planner 自动判定的覆盖不计入人工态，不由这个按钮撤销。
    { id: 'C2', number: '3.2', coveredByParent: 'P1' },
  ]
  const state = technicalHelpers.technicalGapParentCoverageState(applied[0], applied)
  assert.equal(state.applied, true)
  assert.equal(state.coveredCount, 1)
})
