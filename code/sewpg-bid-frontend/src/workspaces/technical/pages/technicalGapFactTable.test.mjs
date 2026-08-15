import test from 'node:test'
import assert from 'node:assert/strict'

import {
  collectDefaultExpandedTreePaths,
  factRefFileName,
  factRefPath,
  factSpecSegment,
  hasFactSpecSeq,
  normalizeFactFieldStatus,
  normalizeMaterialTreeNodes,
} from './technicalGapFactTable.js'

test('事实字段状态归一：历史五态全部收敛到三态', () => {
  assert.equal(normalizeFactFieldStatus('extracted'), 'confirmed')
  assert.equal(normalizeFactFieldStatus('pending_confirmation'), 'confirmed')
  assert.equal(normalizeFactFieldStatus('conflict'), 'confirmed')
  assert.equal(normalizeFactFieldStatus('candidate'), 'confirmed')
  assert.equal(normalizeFactFieldStatus('missing'), 'unextracted')
  assert.equal(normalizeFactFieldStatus('missing_source'), 'unextracted')
  assert.equal(normalizeFactFieldStatus('not_applicable'), 'not_applicable')
  assert.equal(normalizeFactFieldStatus(''), 'unextracted')
  assert.equal(normalizeFactFieldStatus(undefined), 'unextracted')
  assert.equal(normalizeFactFieldStatus(null), 'unextracted')
})

test('清单进度分段：不适用优先于有值判定，空值为待填写', () => {
  assert.equal(factSpecSegment({ status: 'not_applicable', value: '有值也算不适用' }), 'notApplicable')
  assert.equal(factSpecSegment({ status: 'confirmed', value: ' 36 台 ' }), 'confirmed')
  assert.equal(factSpecSegment({ status: 'confirmed', value: '   ' }), 'unfilled')
  assert.equal(factSpecSegment({ status: 'unextracted', value: '' }), 'unfilled')
})

test('hasFactSpecSeq 只认非空 specSeq', () => {
  assert.equal(hasFactSpecSeq({ specSeq: 3 }), true)
  assert.equal(hasFactSpecSeq({ specSeq: 'A-1' }), true)
  assert.equal(hasFactSpecSeq({ specSeq: '' }), false)
  assert.equal(hasFactSpecSeq({ specSeq: null }), false)
  assert.equal(hasFactSpecSeq({}), false)
})

test('来源路径优先完整路径，退回目录/文件名与素材名', () => {
  assert.equal(factRefPath({ path: '/a/b.docx', name: 'b.docx' }), '/a/b.docx')
  assert.equal(factRefPath({ sourceFile: '招标文件.pdf' }), '招标文件.pdf')
  assert.equal(factRefPath({ folderPath: '/通用素材/风机/', name: '参数表.xlsx' }), '/通用素材/风机/参数表.xlsx')
  assert.equal(factRefPath({ name: '仅有名称.docx' }), '仅有名称.docx')
  assert.equal(factRefPath({ title: '兜底标题' }), '兜底标题')
  assert.equal(factRefPath({}), '')
})

test('来源列文件名取最后一段，空路径原样兜底', () => {
  assert.equal(factRefFileName('/通用素材/风机/参数表.xlsx'), '参数表.xlsx')
  assert.equal(factRefFileName('参数表.xlsx'), '参数表.xlsx')
  assert.equal(factRefFileName(''), '')
})

test('素材目录树归一：去首尾斜杠、补默认名、递归子级、丢弃空路径', () => {
  const nodes = normalizeMaterialTreeNodes([
    {
      path: '/标准文件/',
      children: [{ name: '风机', path: '标准文件/风机', fileCount: '4' }],
    },
    { name: '', path: '' },
    null,
  ])
  assert.deepEqual(nodes, [
    {
      path: '标准文件',
      name: '标准文件',
      fileCount: 0,
      children: [{ path: '标准文件/风机', name: '风机', fileCount: 4, children: [] }],
    },
  ])
})

test('默认展开只到第二层目录', () => {
  const nodes = normalizeMaterialTreeNodes([
    {
      path: 'a',
      children: [
        { path: 'a/b', children: [{ path: 'a/b/c', children: [{ path: 'a/b/c/d' }] }] },
      ],
    },
    { path: 'leaf' },
  ])
  const expanded = collectDefaultExpandedTreePaths(nodes)
  assert.deepEqual([...expanded].sort(), ['a', 'a/b'])
})

// ===== 第二轮拆分抽出的字段编辑纯逻辑（原 TechnicalGapRecognition.jsx 内联） =====

import {
  applyFactFieldChange,
  createManualFactField,
  factFieldsToSave,
  hasUnnamedManualFactValue,
} from './technicalGapFactTable.js'

test('字段编辑：改值打 manualEdit 标记并按有无值定三态', () => {
  const fields = [
    { label: '装机容量', value: '', sourceRefs: [{ type: 'ai', title: 'AI 抽取' }] },
    { label: '机型', value: 'GWH-1' },
  ]
  const next = applyFactFieldChange(fields, 0, 'value', '100MW')
  assert.equal(next[0].value, '100MW')
  assert.equal(next[0].status, 'confirmed')
  assert.equal(next[0].sourceRefs[0].type, 'manualEdit')
  assert.equal(next[0].sourceRefs[0].field, '装机容量')
  assert.equal(next[0].sourceRefs.length, 2)
  // 已有 manualEdit 标记时不重复打
  const again = applyFactFieldChange(next, 0, 'value', '200MW')
  assert.equal(again[0].sourceRefs.filter((ref) => ref.type === 'manualEdit').length, 1)
  // 清空值回落待填写
  const cleared = applyFactFieldChange(next, 0, 'value', '  ')
  assert.equal(cleared[0].status, 'unextracted')
  // 改非 value 键（如 label）按当前值重判状态，不打 manualEdit
  const relabeled = applyFactFieldChange(fields, 1, 'label', '风机机型')
  assert.equal(relabeled[1].label, '风机机型')
  assert.equal(relabeled[1].status, 'confirmed')
  assert.equal(relabeled[1].sourceRefs, undefined)
  // 未触及的行原样保留
  assert.equal(next[1], fields[1])
})

test('字段编辑：status 分支只改状态（「不适用」路径）', () => {
  const fields = [{ label: '备件', value: '有' }]
  const next = applyFactFieldChange(fields, 0, 'status', 'not_applicable')
  assert.deepEqual(next[0], { label: '备件', value: '有', status: 'not_applicable' })
})

test('createManualFactField：人工新增骨架', () => {
  const field = createManualFactField({ id: 'FACT-MANUAL-1', createdAt: '2026-08-15T00:00:00.000Z' })
  assert.equal(field.id, 'FACT-MANUAL-1')
  assert.equal(field.category, '人工补充事实')
  assert.equal(field.status, 'unextracted')
  assert.equal(field.sourceRefs[0].type, 'manualFact')
  assert.equal(field.updatedAt, '2026-08-15T00:00:00.000Z')
  assert.equal(field.updatedBy, '当前用户')
})

test('hasUnnamedManualFactValue：人工新增字段有值无名才拦截', () => {
  assert.equal(hasUnnamedManualFactValue([
    { label: '', value: '100MW', sourceRefs: [{ type: 'manualFact' }] },
  ]), true)
  assert.equal(hasUnnamedManualFactValue([
    { label: '装机容量', value: '100MW', sourceRefs: [{ type: 'manualFact' }] },
  ]), false)
  // AI 来源的字段有值无名不拦截
  assert.equal(hasUnnamedManualFactValue([
    { label: '', value: '100MW', sourceRefs: [{ type: 'ai' }] },
  ]), false)
  // 人工字段没值不拦截
  assert.equal(hasUnnamedManualFactValue([
    { label: '', value: '', sourceRefs: [{ type: 'manualFact' }] },
  ]), false)
})

test('factFieldsToSave：只保留有字段名或有值的行', () => {
  assert.deepEqual(factFieldsToSave([
    { label: '装机容量', value: '' },
    { label: '', value: '100MW' },
    { label: ' ', value: ' ' },
  ]), [{ label: '装机容量', value: '' }, { label: '', value: '100MW' }])
  assert.deepEqual(factFieldsToSave(null), [])
})
