import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  aiFillComparisonPair,
  appendixTaskForFillTask,
  defaultAiFillReferenceMaterialIds,
  isFillTemplateMaterial,
  tenderDocumentStateForAiFill,
  technicalBodyFillCounts,
  technicalGapProgressCounts,
  technicalGapTagBucketOf,
  technicalGapTagOf,
  technicalGapTaskCount,
  TECHNICAL_TABLE_FILL_SKILL,
  TECHNICAL_WORD_FILL_SKILL,
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

test('评分索引交叉引用的跳过、失败与待刷新页码各自给出提示', () => {
  const present = (scoreIndexXref) => technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: { scoreIndexXref },
  }).scoreIndexXrefMessage

  assert.equal(present({ status: 'skipped' }), '未找到技术评分标准索引表，已跳过交叉引用')
  assert.equal(present({ status: 'failed', error: 'boom' }), '评分索引表交叉引用失败，当前使用格式清洗稿')
  assert.equal(
    present({ status: 'completed', summary: { pageNumbersResolved: false } }),
    '评分索引表已建立交叉引用，页码需在 Word/WPS 中全选后按 F9 刷新',
  )
  assert.equal(present({ status: 'completed', summary: { pageNumbersResolved: true } }), '')
  assert.equal(present(undefined), '')
})

test('图表题注编号的跳过与失败各自给出提示', () => {
  const present = (captionNumber) => technicalHelpers.technicalGenerationPresentation({
    status: 'completed',
    assembly: { captionNumber },
  }).captionNumberMessage

  assert.equal(present({ status: 'skipped' }), '正文中没有需要编号的图片或表格，已跳过图表题注编号')
  assert.equal(present({ status: 'failed', error: 'boom' }), '图表题注编号失败，当前使用未编号的组装稿')
  assert.equal(present({ status: 'completed', summary: { captionCount: 12 } }), '')
  assert.equal(present(undefined), '')
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

test('页面 warning 不阻断进入共创，下载与 technicalFormat 调用路径保持可用', async () => {
  const gapSource = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')
  const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')
  const progressSource = await readFile(new URL('../components/TechnicalGenerationProgressModal.jsx', import.meta.url), 'utf8')

  assert.match(progressSource, /warningCount/)
  assert.match(gapSource, /disabled=\{Boolean\(busyAction\) \|\| !generationCompleted\}/)
  assert.match(editorSource, /technicalDocumentAPI\.technicalFormat\(id, payload\)/)
  assert.match(editorSource, /technicalDocumentAPI\.final\(id, exportVersion\)/)
  assert.match(editorSource, /technicalDocumentAPI\.finalPdf\(id, exportVersion\)/)
})

test('共创导出使用单一版本下拉同时控制 Word 和 PDF，默认标记版', async () => {
  const apiSource = await readFile(new URL('../../../api/index.js', import.meta.url), 'utf8')
  const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

  assert.match(editorSource, /const \[exportVersion, setExportVersion\] = useState\('marked'\)/)
  assert.match(editorSource, /<select[\s\S]*?value=\{exportVersion\}[\s\S]*?onChange=\{\(event\) => setExportVersion\(event\.target\.value\)\}/)
  assert.match(editorSource, /<option value="marked">标记版<\/option>/)
  assert.match(editorSource, /<option value="clean">清洁版<\/option>/)
  assert.match(editorSource, /technicalDocumentAPI\.final\(id, exportVersion\)/)
  assert.match(editorSource, /technicalDocumentAPI\.finalPdf\(id, exportVersion\)/)
  assert.match(apiSource, /final:\s*\(projectId, version = 'marked'\)[\s\S]*?version=\$\{version\}/)
  assert.match(apiSource, /finalPdf:\s*\(projectId, version = 'marked'\)[\s\S]*?version=\$\{version\}/)
})

test('PDF 每次下载都由后端校验当前文档，不复用页面内旧地址', async () => {
  const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

  assert.doesNotMatch(editorSource, /pdfData|setPdfData/)
  assert.match(editorSource, /onClick=\{handlePreparePdf\}/)
  assert.match(editorSource, /const response = await technicalDocumentAPI\.finalPdf\(id, exportVersion\)/)
})

test('重新生成正文只在共创导出页展示，并位于 Word、PDF 下载控件之后', async () => {
  const gapSource = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')
  const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')
  const wordIndex = editorSource.indexOf('onClick={handleDownloadWord}')
  const pdfIndex = editorSource.indexOf('onClick={handlePreparePdf}', wordIndex)
  const regenerateIndex = editorSource.indexOf('onClick={handleRequestRegenerate}', pdfIndex)

  assert.doesNotMatch(gapSource, /重新生成正文/)
  assert.ok(wordIndex >= 0)
  assert.ok(pdfIndex > wordIndex)
  assert.ok(regenerateIndex > pdfIndex)
})

test('共创导出页二次确认后沿用正文生成接口并刷新最新文档', async () => {
  const editorSource = await readFile(new URL('./TechnicalCoCreationEditor.jsx', import.meta.url), 'utf8')

  assert.match(editorSource, /确认重新生成正文？/)
  assert.match(editorSource, /尚未保存的共创修改可能丢失/)
  assert.match(editorSource, /const payload = await technicalGenerateAPI\.run\(id\)/)
  assert.match(editorSource, /loadDocument\(\{ silent: true \}\)/)
  assert.match(editorSource, /<TechnicalGenerationProgressModal/)
})

test('素材范围变更后自动重建事实表，不保留手动刷新入口', async () => {
  const source = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')
  const scopeStart = source.indexOf('const handleSaveMaterialPaths')
  const curateStart = source.indexOf('const handleCurateFacts')
  const scopeFlow = source.slice(scopeStart, curateStart)

  assert.ok(scopeStart >= 0 && curateStart > scopeStart)
  assert.ok(scopeFlow.indexOf('saveMaterialSources') < scopeFlow.indexOf('buildFacts'))
  // 没有独立的「生成/重建事实表」按钮：素材匹配完成后后端自动建一次，
  // 之后重建走保存参考范围与「刷新并 AI 填充」两条既有流程
  assert.doesNotMatch(source, /onBuild\b|handleBuildFacts/)
  // 清单只有全局一份，本页没有上传入口，只跳转到素材库 · 规则页
  assert.doesNotMatch(source, /uploadFactSpecs/)
  assert.match(source, /workspace\/tech\/materials\/rules/)
})

test('事实表弹窗使用动态视口高度并只滚动表格区域', async () => {
  const source = await readFile(new URL('./TechnicalGapRecognition.jsx', import.meta.url), 'utf8')

  assert.match(source, /h-\[calc\(100dvh-1rem\)\] max-h-\[860px\]/)
  assert.match(source, /sm:h-\[calc\(100dvh-2rem\)\]/)
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

test('招标文件来源规则允许零素材并展示项目完整招标文件', () => {
  const state = tenderDocumentStateForAiFill({
    sourceRouting: {
      useTenderParseFields: true,
      tenderDocumentStatus: 'available',
      tenderDocumentCount: 2,
      tenderDocuments: [
        { id: 'TEN-1', name: '技术规范.pdf' },
        { id: 'TEN-2', name: '招标附图.docx' },
      ],
    },
  })

  assert.equal(state.required, true)
  assert.equal(state.missingSource, false)
  assert.equal(state.documentCount, 2)
  assert.deepEqual(state.documentNames, ['技术规范.pdf', '招标附图.docx'])
})

test('招标文件来源规则在项目无源文件时阻止空跑', () => {
  const state = tenderDocumentStateForAiFill({
    sourceRouting: {
      useTenderParseFields: true,
      tenderDocumentStatus: 'missing_source',
      tenderDocumentCount: 0,
    },
  })

  assert.equal(state.required, true)
  assert.equal(state.missingSource, true)
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

test('目录标签v6：已取代产物不参与标签、预览和当前产物列表', () => {
  const item = {
    id: 'G1',
    decision: 'ready',
    status: 'resolved',
    humanConfirmed: true,
    resolvedArtifacts: [
      {
        id: 'ART-OLD',
        source: 'ai_fill',
        fileName: '旧AI填写.docx',
        active: false,
        supersededAt: '2026-08-06T00:00:00Z',
        onlyoffice: { fileUrl: '/old.docx' },
      },
      {
        id: 'ART-NEW',
        source: 'material_library',
        fileName: '新选素材.docx',
        materialId: 'RAW-NEW',
        s7Ready: true,
        active: true,
        onlyoffice: { fileUrl: '/new.docx' },
      },
    ],
  }

  assert.equal(technicalGapTagOf(item), 'material_ready')
  assert.equal(technicalHelpers.latestResolvedArtifact(item).id, 'ART-NEW')
  assert.deepEqual(technicalHelpers.currentResolvedArtifacts(item).map((artifact) => artifact.id), ['ART-NEW'])
  assert.deepEqual(technicalHelpers.previewChoicesForItem(item).map((choice) => choice.artifact.id), ['ART-NEW'])
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

  // 无下级的结构项与空骨架：系统判定本节不需要素材，直接已就绪（2026-08-11 口径）。
  assert.equal(technicalGapTagOf({ id: 'S1', usage: 'structural', decision: 'ready' }), 'material_ready')
  assert.equal(technicalGapTagOf({ id: 'S2', decision: 'ready' }), 'material_ready')
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

test('仅留标题三条来源等价：人工忽略、骨架章、历史 ignored 同标签', () => {
  const child = { id: 'C1', number: '3.1', level: 2, candidateMaterials: [{ id: 'M1', matchScore: 0.6 }] }
  const cases = [
    { id: 'P1', number: '第3章', level: 1, titleOnly: true },
    { id: 'P1', number: '第3章', level: 1, usage: 'structural', decision: 'ready' },
    { id: 'P1', number: '第3章', level: 1, status: 'ignored' },
  ]
  cases.forEach((chapter) => {
    const items = [chapter, child]
    assert.equal(technicalGapTagOf(chapter, items), 'title_only')
    // 三者都不冻结子级：内容由下级各自承接。
    assert.equal(technicalGapTagOf(child, items), 'needs_choice')
    // 都不产生任务，但各占一个目录格子（归已就绪桶）。
    assert.equal(technicalGapTaskCount(chapter, items), 1)
  })
})

test('统计不变量：五桶目录数求和恒等于目录总行数', () => {
  const items = [
    // 骨架章：放开子级，自己占一格
    { id: 'P1', number: '第1章', level: 1, usage: 'structural', decision: 'ready' },
    { id: 'C1', number: '1.1', level: 2, decision: 'material_required' },
    { id: 'C2', number: '1.2', level: 2, candidateMaterials: [{ id: 'M1', matchScore: 0.6 }] },
    // 配了整章素材的父章：冻结整棵子树
    { id: 'P2', number: '第2章', level: 1, matchedMaterials: [{ id: 'M2', matchScore: 0.99 }] },
    { id: 'C3', number: '2.1', level: 2, candidateMaterials: [{ id: 'M3', matchScore: 0.5 }] },
    { id: 'C4', number: '2.1.1', level: 3, candidateMaterials: [{ id: 'M4', matchScore: 0.5 }] },
    // 人工忽略章 + 释放出来的子级
    { id: 'P3', number: '第3章', level: 1, titleOnly: true },
    { id: 'C5', number: '3.1', level: 2, appendixTasks: [{ id: 'APPX-1' }] },
    // 空骨架叶子：系统判定不需要素材
    { id: 'L1', number: '4', level: 1, decision: 'ready' },
  ]
  const { tasks, tocs } = technicalGapProgressCounts(items)
  const tocSum = Object.values(tocs).reduce((total, count) => total + count, 0)
  assert.equal(tocSum, items.length, '目录数求和必须等于总行数，否则进度到不了 100%')

  // 第2章 1 个任务盖住自己 + 2.1 + 2.1.1 共 3 行
  assert.equal(tasks.material_ready, 4) // 第2章、第1章骨架、第3章忽略、空骨架叶子
  assert.equal(tocs.material_ready, 6) // 上述 4 行 + 被第2章冻结的 2 行
  assert.equal(tasks.manual_supplement, 1)
  assert.equal(tasks.needs_choice, 1)
  assert.equal(tasks.template_ready, 1)
})

test('一键填写待填数与「待填写」标签同口径：冻结行和待确认行不算', () => {
  // 父章用整章素材定案（自己已就绪，不占待填），从而冻结 5.1。
  const chapter = { id: 'P1', number: '第5章', level: 1, matchedMaterials: [{ id: 'M0', matchScore: 0.99 }] }
  const frozen = {
    id: 'C1',
    number: '5.1',
    level: 2,
    decision: 'fill_required',
    fillTasks: [{ id: 'F1', skill: TECHNICAL_WORD_FILL_SKILL, status: 'pending' }],
  }
  const unconfirmed = {
    id: 'C2',
    number: '6.1',
    level: 1,
    decision: 'fill_required',
    candidateMaterials: [{ id: 'M1', matchScore: 0.6 }],
    fillTasks: [{ id: 'F2', skill: TECHNICAL_WORD_FILL_SKILL, status: 'pending' }],
  }
  const fillable = {
    id: 'C3',
    number: '7.1',
    level: 1,
    decision: 'fill_required',
    appendixTasks: [{ id: 'APPX-1' }],
    fillTasks: [{ id: 'F3', skill: TECHNICAL_TABLE_FILL_SKILL, status: 'pending' }],
  }
  const items = [chapter, frozen, unconfirmed, fillable]

  // 5.1 被第5章冻结（页面只读），6.1 素材还没确认，都不进一键填写范围。
  assert.equal(technicalGapTagOf(frozen, items), 'parent_covered')
  assert.equal(technicalGapTagOf(unconfirmed, items), 'needs_choice')
  assert.equal(technicalGapTagOf(fillable, items), 'template_ready')

  const counts = technicalBodyFillCounts(items)
  const tagTasks = items.reduce(
    (sum, item) => sum + (technicalGapTagOf(item, items) === 'template_ready' ? technicalGapTaskCount(item, items) : 0),
    0,
  )
  assert.equal(counts.pending, 1, '只有 7.1 该填')
  assert.equal(counts.pending, tagTasks, '一键填写数字必须等于「待填写」标签上的任务数')
})

test('筛选桶与统计桶同源：点「已就绪」能筛出归入该桶的仅留标题行', () => {
  const items = [
    { id: 'P1', number: '第1章', level: 1, usage: 'structural', decision: 'ready' },
    { id: 'C1', number: '1.1', level: 2, matchedMaterials: [{ id: 'M1', matchScore: 0.99 }] },
    { id: 'P2', number: '第2章', level: 1, titleOnly: true },
    { id: 'C2', number: '2.1', level: 2, decision: 'material_required' },
  ]
  const { tasks } = technicalGapProgressCounts(items)
  // 页面筛选口径：按统计桶比对，而不是按行级标签。
  const filtered = items.filter(
    (item) => technicalGapTagBucketOf(technicalGapTagOf(item, items)) === 'material_ready',
  )
  assert.equal(filtered.length, 3, '两个仅留标题 + 一个已就绪')
  assert.equal(
    tasks.material_ready,
    filtered.length,
    '标签上的任务数必须等于点开后的行数，否则数字对不上账',
  )
})

test('任务数按待处理对象计：一行挂多个待填对象就是多个任务', () => {
  const item = {
    id: 'G1',
    decision: 'fill_required',
    appendixTasks: [{ id: 'APPX-1' }],
    fillTasks: [
      { id: 'F1', skill: TECHNICAL_WORD_FILL_SKILL, status: 'pending' },
      { id: 'F2', skill: TECHNICAL_WORD_FILL_SKILL, status: 'pending' },
      { id: 'F3', skill: TECHNICAL_TABLE_FILL_SKILL, status: 'pending' },
      { id: 'F4', skill: TECHNICAL_TABLE_FILL_SKILL, status: 'completed' },
      { id: 'F5', skill: 'bid-tech-other', status: 'pending' },
    ],
  }
  const items = [item]
  assert.equal(technicalGapTagOf(item, items), 'template_ready')
  // 已完成的和非填写类 skill 都不算，剩 3 个待填对象。
  assert.equal(technicalGapTaskCount(item, items), 3)
  // 目录数仍然只有 1 行。
  assert.equal(technicalGapProgressCounts(items).tocs.template_ready, 1)
})

test('待审核任务数按 AI 产出份数计，已取代的产物不算', () => {
  const item = {
    id: 'G1',
    resolvedArtifacts: [
      { id: 'A1', source: 'ai_fill' },
      { id: 'A2', source: 'ai_fill' },
      { id: 'A3', source: 'ai_fill', supersededAt: '2026-08-11T00:00:00Z' },
      { id: 'A4', source: 'manual_upload' },
    ],
  }
  const items = [item]
  assert.equal(technicalGapTagOf(item, items), 'template_review')
  assert.equal(technicalGapTaskCount(item, items), 2)
})

test('被父章冻结的子树不产生任务，只把目录格子记到冻结源所在的桶', () => {
  const chapter = { id: 'P1', number: '第3章', level: 1, appendixTasks: [{ id: 'APPX-1' }] }
  const mid = { id: 'C1', number: '3.1', level: 2, candidateMaterials: [{ id: 'M1', matchScore: 0.6 }] }
  const leaf = { id: 'C2', number: '3.1.1', level: 3, candidateMaterials: [{ id: 'M2', matchScore: 0.6 }] }
  const items = [chapter, mid, leaf]

  assert.equal(technicalGapTaskCount(mid, items), 0)
  assert.equal(technicalGapTaskCount(leaf, items), 0)
  const { tasks, tocs } = technicalGapProgressCounts(items)
  // 父章还在「待填写」，整棵子树就都不算已就绪。
  assert.equal(tasks.template_ready, 1)
  assert.equal(tocs.template_ready, 3)
  assert.equal(tocs.material_ready, 0)
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

test('一键填写汇总覆盖正文与附表，失败按目录项计', () => {
  const items = [
    // 待填数只认「待填写」标签，模板须已定案，这里用解析空表来源（appendixTasks）满足。
    {
      id: 'G1',
      decision: 'fill_required',
      appendixTasks: [{ id: 'APPX-1' }],
      fillTasks: [
        { id: 'T1', skill: 'bid-tech-word-placeholder-filler', status: 'completed' },
        { id: 'T2', skill: 'bid-tech-word-placeholder-filler', status: 'pending' },
        // 附表也进一键填写汇总，并单独拆出 pendingAppendix
        { id: 'T3', skill: 'bid-tech-table-filler', status: 'pending' },
      ],
    },
    {
      id: 'G2',
      decision: 'fill_required',
      appendixTasks: [{ id: 'APPX-2' }],
      fillTasks: [{ id: 'T4', skill: 'bid-tech-word-placeholder-filler', status: 'pending' }],
      fillError: { message: 'MinIO 取件失败' },
    },
    // 仅留标题与非填写轨不计入
    { id: 'G3', decision: 'fill_required', titleOnly: true, fillTasks: [{ id: 'T5', skill: 'bid-tech-word-placeholder-filler' }] },
    { id: 'G4', decision: 'ready', fillTasks: [{ id: 'T6', skill: 'bid-tech-word-placeholder-filler' }] },
  ]

  assert.deepEqual(technicalHelpers.technicalBodyFillCounts(items), { pending: 3, filled: 1, failed: 1, pendingBody: 2, pendingAppendix: 1 })
  assert.deepEqual(technicalHelpers.technicalBodyFillCounts(null), { pending: 0, filled: 0, failed: 0, pendingBody: 0, pendingAppendix: 0 })
})

test('目录项填写失败原因用于标红与重填提示', () => {
  assert.equal(technicalHelpers.technicalGapFillError({ fillError: { message: '素材缺失' } }), '素材缺失')
  assert.equal(technicalHelpers.technicalGapFillError({}), '')
  assert.equal(technicalHelpers.technicalGapFillError({ fillError: 'bad' }), '')
})

// 多机型项目 planner 会给每个机型一份推荐，已选区要整批展示，不能只留第一份。
const READY_MATERIAL = (id, folder) => ({
  id,
  name: '智能传感系统.docx',
  folderPath: folder,
  materialTier: 'standard',
  matchScore: 0.99,
})

test('多机型推荐整批进已选区，顺序沿用 planner 给的机型顺序', () => {
  const item = {
    id: 'GAP-1',
    matchedMaterials: [
      READY_MATERIAL('M-A', '技术标/标准文件/EW8.5-220上置/专题'),
      READY_MATERIAL('M-B', '技术标/标准文件/EW10.0-230下置/专题'),
    ],
  }

  const selections = technicalHelpers.recommendedSelectionsForItem(item, [item])

  assert.deepEqual(selections.map((s) => s.material.id), ['M-A', 'M-B'])
  assert.equal(selections.every((s) => s.inherited === false), true)
})

test('单机型推荐仍然只有一张卡', () => {
  const item = { id: 'GAP-1', matchedMaterials: [READY_MATERIAL('M-A', '技术标/标准文件/EW8.5-220上置/专题')] }

  assert.deepEqual(
    technicalHelpers.recommendedSelectionsForItem(item, [item]).map((s) => s.material.id),
    ['M-A'],
  )
})

test('主素材分数不到定案线时整批留在备选池', () => {
  const item = {
    id: 'GAP-1',
    matchedMaterials: [
      { ...READY_MATERIAL('M-A', '技术标/标准文件/EW8.5-220上置/专题'), matchScore: 0.6 },
      READY_MATERIAL('M-B', '技术标/标准文件/EW10.0-230下置/专题'),
    ],
  }

  assert.deepEqual(technicalHelpers.recommendedSelectionsForItem(item, [item]), [])
})

test('父章覆盖只继承一份素材，不做多机型展开', () => {
  const parent = {
    id: 'GAP-P',
    matchedMaterials: [
      READY_MATERIAL('M-A', '技术标/标准文件/EW8.5-220上置/专题'),
      READY_MATERIAL('M-B', '技术标/标准文件/EW10.0-230下置/专题'),
    ],
  }
  const child = { id: 'GAP-C', coveredByParent: 'GAP-P', matchedMaterials: [] }

  const selections = technicalHelpers.recommendedSelectionsForItem(child, [parent, child])

  assert.deepEqual(selections.map((s) => s.material.id), ['M-A'])
  assert.equal(selections[0].inherited, true)
})

test('没有匹配素材时已选区为空', () => {
  const item = { id: 'GAP-1', matchedMaterials: [] }
  assert.deepEqual(technicalHelpers.recommendedSelectionsForItem(item, [item]), [])
})

// 逐条质量警示（frontend-01）：needs_review 或有未填字段才亮标，
// 口径与后端 bid-fill-quality-report-v1 及批量复核黄标一致。
test('AI 填写仍有未填字段时亮出数量徽标与原因', () => {
  const item = {
    id: 'GAP-1',
    qualityStatus: 'needs_review',
    qualityReport: { status: 'needs_review', unfilledFieldCount: 3 },
  }

  const flag = technicalHelpers.technicalGapQualityFlag(item)

  assert.equal(flag.label, '3 项未填')
  assert.equal(flag.unfilledCount, 3)
  assert.equal(flag.needsReview, true)
  assert.match(flag.tip, /3 项未填字段/)
  assert.match(flag.tip, /质量验收未通过/)
})

test('needs_review 但没有未填字段时同样亮标（验收未达标）', () => {
  const item = {
    id: 'GAP-1',
    qualityStatus: 'needs_review',
    qualityReport: { status: 'needs_review', unfilledFieldCount: 0, sourceRuleMessage: '项目定制来源未命中' },
  }

  const flag = technicalHelpers.technicalGapQualityFlag(item)

  assert.equal(flag.label, '质量待复核')
  assert.match(flag.tip, /项目定制来源未命中/)
})

test('旧字段名 residualPlaceholderCount/unfilledPlaceholderCount 兜底计数', () => {
  assert.equal(
    technicalHelpers.technicalGapQualityFlag({ qualityReport: { residualPlaceholderCount: 2 } }).unfilledCount,
    2,
  )
  assert.equal(
    technicalHelpers.technicalGapQualityFlag({ qualityReport: { unfilledPlaceholderCount: 1 } }).unfilledCount,
    1,
  )
})

test('验收通过、无需填写与人工复核通过都不亮标', () => {
  assert.equal(
    technicalHelpers.technicalGapQualityFlag({ qualityStatus: 'passed', qualityReport: { status: 'passed', unfilledFieldCount: 0 } }),
    null,
  )
  assert.equal(
    technicalHelpers.technicalGapQualityFlag({ qualityStatus: 'no_fill_required', qualityReport: { status: 'no_fill_required' } }),
    null,
  )
  // human_confirmed 是复核通过的收口终态，历史 qualityReport.status 仍是 needs_review，也不许回弹示警
  assert.equal(
    technicalHelpers.technicalGapQualityFlag({ qualityStatus: 'human_confirmed', qualityReport: { status: 'needs_review', unfilledFieldCount: 2 } }),
    null,
  )
  assert.equal(technicalHelpers.technicalGapQualityFlag({}), null)
  assert.equal(technicalHelpers.technicalGapQualityFlag(null), null)
})
