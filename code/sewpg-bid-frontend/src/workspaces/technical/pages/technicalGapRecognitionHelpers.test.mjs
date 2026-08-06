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

test('附表来源规则上传提示区分新增、清除和延后生效', () => {
  assert.equal(
    technicalHelpers.technicalAppendixSourceMatrixUploadMessage({
      rowCount: 3,
      applied: { routedItems: 2, clearedItems: 1, clearedTasks: 1 },
    }),
    '已解析 3 条附表来源规则，已应用到 2 个目录项的附表任务，并已清除 1 个目录项、1 个附表任务的旧规则关联',
  )
  assert.equal(
    technicalHelpers.technicalAppendixSourceMatrixUploadMessage({
      rowCount: 1,
      applied: { routedItems: 0, clearedItems: 1, clearedTasks: 2 },
    }),
    '已解析 1 条附表来源规则，未新增匹配，已清除 1 个目录项、2 个附表任务的旧规则关联',
  )
  assert.equal(
    technicalHelpers.technicalAppendixSourceMatrixUploadMessage({ rowCount: 4, applied: {} }),
    '已解析 4 条附表来源规则，将在下次缺口识别时生效',
  )
})

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

test('目录标签v4：无候选或全部低于30%判待人工补充', () => {
  assert.equal(technicalGapTagOf({ id: 'G1', decision: 'material_required' }), 'manual_supplement')
  assert.equal(
    technicalGapTagOf({ id: 'G2', decision: 'review_required', candidateMaterials: [{ id: 'M1', matchScore: 0.2 }] }),
    'manual_supplement',
  )
  // 低分待填写模板同样落待人工补充（<30 不分轨）。
  assert.equal(
    technicalGapTagOf({
      id: 'G3',
      decision: 'review_required',
      candidateMaterials: [{ id: 'M1', name: '待填写-模板.docx', matchScore: 0.2 }],
    }),
    'manual_supplement',
  )
})

test('目录标签v6：30~98分统一为待确认（needs_choice），确认后按所选素材形态分流', () => {
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'review_required', candidateMaterials: [{ id: 'M1', matchScore: 0.6 }] }),
    'needs_choice',
  )
  assert.equal(
    technicalGapTagOf({ id: 'G2', decision: 'review_required', candidateMaterials: [{ id: 'M1', matchScore: 0.98 }] }),
    'needs_choice',
  )
  // 填写模板候选同样是待确认；确认后进「待填写」而不是「已就绪」（后续用例覆盖）。
  assert.equal(
    technicalGapTagOf({
      id: 'G3',
      decision: 'review_required',
      candidateMaterials: [{ id: 'M1', name: '待填写-附表F31部件参数表.docx', matchScore: 0.5 }],
    }),
    'needs_choice',
  )
  // 形态跟最佳素材走：最佳是直用素材时，低分待填写候选不改轨。
  assert.equal(
    technicalGapTagOf({
      id: 'G4',
      decision: 'ready',
      matchedMaterials: [{ id: 'M1', matchScore: 0.99 }],
      candidateMaterials: [{ id: 'M2', name: '待填写-同名模板.docx', matchScore: 0.4 }],
    }),
    'material_ready',
  )
})

test('目录标签v4：解析生成的附表空表来源确定，直接判已就绪模板，不参与30分线', () => {
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'fill_required', appendixTasks: [{ id: 'APPX-C1' }] }),
    'template_ready',
  )
  // 模板 0.99 文件名精确命中：模板已定。
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'pending' }],
      candidateMaterials: [{ id: 'M1', name: '待填写-项目技术承诺函.docx', matchScore: 0.99 }],
    }),
    'template_ready',
  )
  // 人工选定模板（选定即定案落 humanConfirmed）：模板已定。
  assert.equal(
    technicalGapTagOf({
      id: 'G3',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'pending' }],
      candidateMaterials: [{ id: 'M1', name: '待填写-模板.docx', matchScore: 0.5 }],
      humanConfirmed: true,
    }),
    'template_ready',
  )
})

test('目录标签v6：99分（文件名精确命中）自动定案，人工撤销后回落待确认', () => {
  const autoReady = { id: 'G1', decision: 'ready', matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }
  assert.equal(technicalGapTagOf(autoReady), 'material_ready')
  assert.equal(technicalGapTagOf({ ...autoReady, humanConfirmed: false }), 'needs_choice')
  assert.equal(technicalGapTagOf({ ...autoReady, humanConfirmed: true }), 'material_ready')
})

test('目录标签v4：甲方已填附表全覆盖判已就绪素材，部分覆盖回到已就绪模板', () => {
  const clientProvidedTask = { id: 'APPX-1', sourceRouting: { status: 'client_provided' } }
  const fillTask = { id: 'APPX-2', sourceRouting: {} }
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'ready', status: 'resolved', appendixTasks: [clientProvidedTask] }),
    'material_ready',
  )
  // 部分覆盖：剩余空表仍要填，空表来源确定 → 已就绪模板。
  assert.equal(
    technicalGapTagOf({ id: 'G2', decision: 'fill_required', appendixTasks: [clientProvidedTask, fillTask] }),
    'template_ready',
  )
  // 人工撤销豁免后回落到已就绪模板（改为自己填），再次确认恢复。
  const covered = { id: 'G3', decision: 'ready', status: 'resolved', appendixTasks: [clientProvidedTask] }
  assert.equal(technicalGapTagOf({ ...covered, humanConfirmed: false }), 'template_ready')
  assert.equal(technicalGapTagOf({ ...covered, humanConfirmed: true }), 'material_ready')
})

test('目录标签v4：AI填写完成变待复核模板，复核通过收口已就绪素材（行为改动① 2026-08-04）', () => {
  const filled = {
    id: 'G1',
    decision: 'fill_required',
    fillTasks: [{ id: 'T1', status: 'completed' }],
    resolvedArtifacts: [{ id: 'ART-1', source: 'ai_fill' }],
  }
  assert.equal(technicalGapTagOf(filled), 'template_review')
  // 复核通过：qualityStatus=human_confirmed → 绿色终态。
  assert.equal(technicalGapTagOf({ ...filled, qualityStatus: 'human_confirmed' }), 'material_ready')
  // 质检报告存在但未人工复核，仍是待复核。
  assert.equal(technicalGapTagOf({ ...filled, qualityStatus: 'passed' }), 'template_review')
})

test('目录标签v6：选定即定案——人工选材/上传直接变已就绪（行为改动② 2026-08-04）', () => {
  // 后端 register 已在人工选材/上传时落 humanConfirmed + resolvedArtifacts。
  assert.equal(
    technicalGapTagOf({
      id: 'G1',
      decision: 'ready',
      candidateMaterials: [{ id: 'M1', matchScore: 0.6 }],
      resolvedArtifacts: [{ id: 'ART-1', source: 'material_library' }],
      humanConfirmed: true,
    }),
    'material_ready',
  )
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'material_required',
      resolvedArtifacts: [{ id: 'ART-2', source: 'manual_upload' }],
      humanConfirmed: true,
    }),
    'material_ready',
  )
  // 「确认」确认的是系统预选素材（matchedMaterials），确认即定案。
  assert.equal(
    technicalGapTagOf({
      id: 'G3',
      decision: 'review_required',
      matchedMaterials: [{ id: 'M1', matchScore: 0.6 }],
      humanConfirmed: true,
    }),
    'material_ready',
  )
  assert.equal(
    technicalGapTagOf({ id: 'G4', decision: 'material_required', humanConfirmed: false }),
    'manual_supplement',
  )
  // 人工定案的是待填写模板：进入蓝色待填写，不是绿色。
  assert.equal(
    technicalGapTagOf({
      id: 'G5',
      decision: 'fill_required',
      fillTasks: [{ id: 'T1', status: 'pending' }],
      humanConfirmed: true,
    }),
    'template_ready',
  )
})

test('目录标签v6：空确认防御——没有素材实体证据时确认不变绿（产品反馈 2026-08-04）', () => {
  // 空项（无预选/无候选/无产物）即使 humanConfirmed 也不变绿，维持待补充。
  assert.equal(
    technicalGapTagOf({ id: 'G1', decision: 'material_required', humanConfirmed: true }),
    'manual_supplement',
  )
  // 只有候选、没有系统预选（matchedMaterials 为空）：确认标记不生效，仍是待确认。
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'review_required',
      candidateMaterials: [{ id: 'M1', matchScore: 0.6 }],
      humanConfirmed: true,
    }),
    'needs_choice',
  )
})

test('目录标签v6：人工选中未填写的「待填写-」模板进待填写，不进已就绪（R10-B07-01）', () => {
  // 后端 register 对空模板产物落 s7Ready=false：它只是定下要填的模板，不算成稿。
  assert.equal(
    technicalGapTagOf({
      id: 'G1',
      decision: 'fill_required',
      status: 'needs_input',
      fillTasks: [{ id: 'FILL-G1-RAW-TPL1', status: 'pending', blankSource: { materialId: 'RAW-TPL1', sourceType: 'material_fill_template' } }],
      resolvedArtifacts: [{ id: 'ART-1', source: 'material_library', fileName: '01-待填写-投标说明函.docx', s7Ready: false }],
      humanConfirmed: true,
    }),
    'template_ready',
  )
  // 对照：s7Ready 的人工选材产物（成稿）仍是已就绪。
  assert.equal(
    technicalGapTagOf({
      id: 'G2',
      decision: 'ready',
      status: 'resolved',
      resolvedArtifacts: [{ id: 'ART-2', source: 'material_library', fileName: '01-性能保证.docx', s7Ready: true }],
      humanConfirmed: true,
    }),
    'material_ready',
  )
})

test('目录标签v6：树状冻结——未忽略的活动祖先冻结整棵子树（父章覆盖）', () => {
  const chapter = { id: 'P1', number: '第3章', level: 1, matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }
  const mid = { id: 'C1', number: '3.1', level: 2, candidateMaterials: [{ id: 'M2', matchScore: 0.6 }] }
  const leaf = { id: 'C2', number: '3.1.1', level: 3, candidateMaterials: [{ id: 'M3', matchScore: 0.5 }] }
  const items = [chapter, mid, leaf]

  // 结构项与空骨架无标签。
  assert.equal(technicalGapTagOf({ id: 'S1', usage: 'structural', decision: 'ready' }), '')
  assert.equal(technicalGapTagOf({ id: 'S2', decision: 'ready' }), '')
  // 父章活动（无论已定还是待确认还是缺素材）：所有后代冻结。
  assert.equal(technicalGapTagOf(chapter, items), 'material_ready')
  assert.equal(technicalGapTagOf(mid, items), 'parent_covered')
  assert.equal(technicalGapTagOf(leaf, items), 'parent_covered')
  // 缺素材的父章同样冻结子级（决策①：红色也冻结，先补或忽略）。
  const emptyChapter = { id: 'P2', number: '第4章', level: 1, decision: 'material_required' }
  const emptyChild = { id: 'C3', number: '4.1', level: 2, candidateMaterials: [{ id: 'M4', matchScore: 0.7 }] }
  assert.equal(technicalGapTagOf(emptyChild, [emptyChapter, emptyChild]), 'parent_covered')
})

test('目录标签v6：忽略（仅留标题）释放子级，逐级递归', () => {
  const chapter = { id: 'P1', number: '第3章', level: 1, titleOnly: true, matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] }
  const mid = { id: 'C1', number: '3.1', level: 2, candidateMaterials: [{ id: 'M2', matchScore: 0.6 }] }
  const leaf = { id: 'C2', number: '3.1.1', level: 3, candidateMaterials: [{ id: 'M3', matchScore: 0.99 }] }
  const items = [chapter, mid, leaf]

  // 忽略的父章自己显示仅留标题。
  assert.equal(technicalGapTagOf(chapter, items), 'title_only')
  // 一级忽略后二级释放、按自身候选派生；二级活动继续冻结三级。
  assert.equal(technicalGapTagOf(mid, items), 'needs_choice')
  assert.equal(technicalGapTagOf(leaf, items), 'parent_covered')
  // 二级也忽略：三级释放（0.99 自动定案）。
  const midIgnored = { ...mid, titleOnly: true }
  const itemsBothIgnored = [chapter, midIgnored, leaf]
  assert.equal(technicalGapTagOf(midIgnored, itemsBothIgnored), 'title_only')
  assert.equal(technicalGapTagOf(leaf, itemsBothIgnored), 'material_ready')
  // 结构性祖先不冻结子级。
  const structuralRoot = { id: 'P9', number: '第9章', level: 1, usage: 'structural', decision: 'ready' }
  const structuralChild = { id: 'C9', number: '9.1', level: 2, candidateMaterials: [{ id: 'M9', matchScore: 0.6 }] }
  assert.equal(technicalGapTagOf(structuralChild, [structuralRoot, structuralChild]), 'needs_choice')
})

test('目录标签v6：附表按 level 归入技术附表根，冻结/忽略同样适用（产品反馈 2026-08-04）', () => {
  // 附表编号不成目录号链（附表A.1 的“父号”附表A 不存在），层级由顺序 + level 决定。
  const appendixRoot = { id: 'R1', number: '附录', title: '技术附表', level: 1, appendixTasks: [{ id: 'APPX-0' }] }
  const tableA = { id: 'A1', number: '附表A.1', level: 2, appendixTasks: [{ id: 'APPX-1' }] }
  const tableB = { id: 'B1', number: '附表B.1.1', level: 2, appendixTasks: [{ id: 'APPX-2' }] }
  const items = [appendixRoot, tableA, tableB]

  assert.deepEqual(
    technicalHelpers.technicalGapDescendants(appendixRoot, items).map((item) => item.id),
    ['A1', 'B1'],
  )
  // 附录根活动（待填写）：附表子级冻结。
  assert.equal(technicalGapTagOf(appendixRoot, items), 'template_ready')
  assert.equal(technicalGapTagOf(tableA, items), 'parent_covered')
  // 附录根被忽略：附表各自按空表任务派生（待填写）。
  const rootIgnored = { ...appendixRoot, titleOnly: true }
  const itemsIgnored = [rootIgnored, tableA, tableB]
  assert.equal(technicalGapTagOf(rootIgnored, itemsIgnored), 'title_only')
  assert.equal(technicalGapTagOf(tableA, itemsIgnored), 'template_ready')
  assert.equal(technicalGapTagOf(tableB, itemsIgnored), 'template_ready')
})

test('目录标签v6：冻结子级继承冻结源素材（树派生优先于 coveredByParent 提示）', () => {
  const chapter = { id: 'P1', number: '第3章', level: 1, matchedMaterials: [{ id: 'M1', name: '整章素材.docx', matchScore: 0.99 }] }
  const leaf = { id: 'C1', number: '3.2', level: 2, candidateMaterials: [] }
  const match = technicalHelpers.matchedMaterialForItem(leaf, [chapter, leaf])
  assert.equal(match.inherited, true)
  assert.equal(match.material.id, 'M1')
  assert.equal(match.sourceItem.id, 'P1')
})

test('父章节覆盖：目录号归一化与 level 后代识别', () => {
  assert.equal(technicalHelpers.technicalGapNumberKey('第3章'), '3')
  assert.equal(technicalHelpers.technicalGapNumberKey('第十二章'), '12')
  assert.equal(technicalHelpers.technicalGapNumberKey('5.8.2'), '5.8.2')

  const chapter = { id: 'P1', number: '第3章', level: 1 }
  const items = [
    chapter,
    { id: 'C1', number: '3.1', level: 2 },
    { id: 'C2', number: '3.1.1', level: 3 },
    // 后代识别按顺序 + level：遇到同级或更高级即截断，第4章不被误吞。
    { id: 'X1', number: '第4章', level: 1 },
    { id: 'X2', number: '4.1', level: 2 },
  ]
  const descendants = technicalHelpers.technicalGapDescendants(chapter, items)
  assert.deepEqual(descendants.map((item) => item.id), ['C1', 'C2'])
})

test('父章节覆盖：本节点没素材时不可设置，设置后可撤销', () => {
  const items = [
    { id: 'P1', number: '第3章', level: 1 },
    { id: 'C1', number: '3.1', level: 2 },
  ]
  const empty = technicalHelpers.technicalGapParentCoverageState(items[0], items)
  assert.equal(empty.descendantCount, 1)
  assert.equal(empty.hasMaterial, false)
  assert.equal(empty.canApply, false)

  const withMaterial = [
    { id: 'P1', number: '第3章', level: 1, matchedMaterials: [{ id: 'M1' }] },
    { id: 'C1', number: '3.1', level: 2 },
  ]
  const ready = technicalHelpers.technicalGapParentCoverageState(withMaterial[0], withMaterial)
  assert.equal(ready.canApply, true)
  assert.equal(ready.applied, false)

  const applied = [
    { id: 'P1', number: '第3章', level: 1, matchedMaterials: [{ id: 'M1' }] },
    { id: 'C1', number: '3.1', level: 2, coveredByParent: 'P1', parentCoverageSource: 'manual' },
    // planner 自动判定的覆盖不计入人工态，不由这个按钮撤销。
    { id: 'C2', number: '3.2', level: 2, coveredByParent: 'P1' },
  ]
  const state = technicalHelpers.technicalGapParentCoverageState(applied[0], applied)
  assert.equal(state.applied, true)
  assert.equal(state.coveredCount, 1)
})
