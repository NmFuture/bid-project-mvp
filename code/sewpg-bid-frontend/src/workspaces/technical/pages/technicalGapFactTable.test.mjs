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
