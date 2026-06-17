import test from 'node:test'
import assert from 'node:assert/strict'

import {
  groupTechnicalInterpretationItems,
  technicalInterpretationDisplayGroup,
  technicalInterpretationEvidenceSummary,
  technicalInterpretationStatusLabel,
} from './technicalInterpretation.js'

test('maps checklist categories into the readable technical interpretation blocks', () => {
  assert.equal(technicalInterpretationDisplayGroup({ primaryCategory: '设备选型适配' }), '设备选型适配')
  assert.equal(technicalInterpretationDisplayGroup({ primaryCategory: '投标技术资料要求' }), '技术资料交付')
  assert.equal(
    technicalInterpretationDisplayGroup({ primaryCategory: 'CMS振动监测系统' }),
    'CMS / 一次调频 / 国产化 / 二次安防等',
  )
  assert.equal(
    technicalInterpretationDisplayGroup({ primaryCategory: '二次安防系统' }),
    'CMS / 一次调频 / 国产化 / 二次安防等',
  )
})

test('groups interpretation rows and keeps status counts per block', () => {
  const groups = groupTechnicalInterpretationItems([
    { rowNo: 3, primaryCategory: '设备选型适配', status: 'found' },
    { rowNo: 16, primaryCategory: '投标技术资料要求', status: 'needs_spec' },
    { rowNo: 49, primaryCategory: 'CMS振动监测系统', status: 'partial' },
    { rowNo: 58, primaryCategory: '二次安防系统', status: 'missing' },
  ])

  assert.deepEqual(groups.map((group) => group.groupName), [
    '设备选型适配',
    '技术资料交付',
    'CMS / 一次调频 / 国产化 / 二次安防等',
  ])
  assert.deepEqual(groups[2].counts, { partial: 1, missing: 1 })
})

test('labels technical interpretation statuses for table display', () => {
  assert.equal(technicalInterpretationStatusLabel('found'), '已找到')
  assert.equal(technicalInterpretationStatusLabel('partial'), '部分找到')
  assert.equal(technicalInterpretationStatusLabel('needs_spec'), '需补充核对')
  assert.equal(technicalInterpretationStatusLabel('missing'), '未找到')
  assert.equal(technicalInterpretationStatusLabel(''), '待解析')
})

test('summarizes evidence and dynamic needed source names', () => {
  assert.equal(
    technicalInterpretationEvidenceSummary({
      status: 'needs_spec',
      neededSourceName: '第三卷 技术规范书和技术规范专用部分',
      evidenceRefs: [],
    }),
    '需补充/核对：第三卷 技术规范书和技术规范专用部分',
  )

  assert.equal(
    technicalInterpretationEvidenceSummary({
      evidenceRefs: [
        {
          sourceFile: '招标文件.docx',
          section: '第一章 招标公告',
          evidenceLocation: '正文第3段',
        },
      ],
    }),
    '招标文件.docx / 第一章 招标公告 / 正文第3段',
  )
})
