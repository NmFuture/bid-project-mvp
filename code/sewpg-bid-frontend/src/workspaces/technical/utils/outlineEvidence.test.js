import assert from 'node:assert/strict'
import test from 'node:test'

import {
  markOutlineNodeEdited,
  pickTenderBasis,
  shouldPreserveOutlineNumber,
  tenderBasisSearchText,
} from './outlineEvidence.js'

test('读取最小招标依据并使用 OnlyOffice 搜索文本', () => {
  const basis = {
    evidenceId: 'TEN-2:B000321',
    fileId: 'TEN-2',
    searchText: '投标人应编制叶片专题',
  }
  const node = {
    tenderBasis: basis,
  }

  assert.equal(pickTenderBasis(node), basis)
  assert.equal(pickTenderBasis(node).evidenceId, 'TEN-2:B000321')
  assert.equal(tenderBasisSearchText(basis), '投标人应编制叶片专题')
})

test('技术附表编号在目录保存重排时保持不变', () => {
  assert.equal(shouldPreserveOutlineNumber({ tocNumber: '附表D.7' }), true)
  assert.equal(shouldPreserveOutlineNumber({ number: '技术附表 B.2' }), true)
  assert.equal(shouldPreserveOutlineNumber({ tocNumber: '5.8' }), false)
})

test('没有招标依据时不返回跳转目标', () => {
  const node = { title: '企业能力介绍' }

  assert.equal(pickTenderBasis(node), null)
})

test('人工修改标题后统一标记为待确认并保留原依据', () => {
  const node = {
    id: 'OL-1',
    title: '原标题',
    suggestionAction: '必要',
    suggestionReason: '',
    tenderBasis: { fileId: 'TEN-1', searchText: '原文' },
  }

  assert.deepEqual(markOutlineNodeEdited(node, '新标题'), {
    ...node,
    title: '新标题',
    suggestionAction: '待确认',
    suggestionReason: '目录标题已人工修改，请确认现有招标依据仍然适用。',
  })
})
