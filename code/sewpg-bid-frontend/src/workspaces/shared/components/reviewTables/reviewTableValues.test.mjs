import test from 'node:test'
import assert from 'node:assert/strict'

import {
  PROJECT_BASIC_FIELDS,
  displayValue,
  formatBidDeadline,
  resolveBusinessProjectBasicValue,
  resolveTechnicalProjectBasicValue,
  sourceValue,
} from './reviewTableValues.js'

test('项目基础信息固定六项字段', () => {
  assert.deepEqual(PROJECT_BASIC_FIELDS.map(([key]) => key), [
    'projectName',
    'tenderNo',
    'projectUnit',
    'tenderer',
    'tenderAgency',
    'bidDeadline',
  ])
})

test('displayValue 拼接数组并兜底空值', () => {
  assert.equal(displayValue(['招标文件.pdf', ' 第三章 ']), '招标文件.pdf，第三章')
  assert.equal(displayValue([], '空'), '空')
  assert.equal(displayValue('  '), '-')
  assert.equal(displayValue(null), '-')
})

test('sourceValue 只使用文件、章节和证据位置', () => {
  assert.equal(
    sourceValue({ sourceFile: 'a.pdf', section: '第三章', evidenceLocation: 'P.12' }),
    'a.pdf，第三章，P.12',
  )
  assert.equal(sourceValue({}), '-')
})

test('formatBidDeadline 归一化 ISO 与中文日期写法', () => {
  assert.equal(formatBidDeadline('2026-08-20T09:30:00'), '2026-08-20 09:30')
  assert.equal(formatBidDeadline('2026-08-20'), '2026-08-20')
  assert.equal(formatBidDeadline('2026年8月20日9时30分'), '2026-08-20 09:30')
  assert.equal(formatBidDeadline('2026 年 8 月 5 日'), '2026-08-05')
  assert.equal(formatBidDeadline('以招标文件为准'), '以招标文件为准')
  assert.equal(formatBidDeadline('', '未识别'), '未识别')
})

test('技术标取值：按原始值是否为空判断未识别', () => {
  assert.deepEqual(resolveTechnicalProjectBasicValue('projectName', { value: '某项目' }), {
    text: '某项目',
    found: true,
  })
  assert.deepEqual(resolveTechnicalProjectBasicValue('projectName', { value: '  ' }), {
    text: '未识别',
    found: false,
  })
  assert.deepEqual(resolveTechnicalProjectBasicValue('bidDeadline', { value: '2026-08-20T09:30:00' }), {
    text: '2026-08-20T09:30:00',
    found: true,
  })
})

test('商务标取值：截止时间归一化，按展示文案判断未识别', () => {
  assert.deepEqual(resolveBusinessProjectBasicValue('bidDeadline', { value: '2026-08-20T09:30:00' }), {
    text: '2026-08-20 09:30',
    found: true,
  })
  assert.deepEqual(resolveBusinessProjectBasicValue('bidDeadline', {}), {
    text: '未识别',
    found: false,
  })
  assert.deepEqual(resolveBusinessProjectBasicValue('projectName', { value: '某项目' }), {
    text: '某项目',
    found: true,
  })
})
