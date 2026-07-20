import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
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
