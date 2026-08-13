import assert from 'node:assert/strict'
import test from 'node:test'

import { parseValidationSummary, validationErrorText } from './parseValidationSummary.js'

test('没有 workflow 的解析结果不产出横幅数据', () => {
  assert.equal(parseValidationSummary(undefined), null)
  assert.equal(parseValidationSummary({}), null)
  assert.equal(parseValidationSummary({ workflow: null }), null)
})

test('没跑过校验的结果（无 stage）不展示横幅', () => {
  // 本地兜底解析和历史数据都没有 stage，此时无从判断，不能误报成"未通过"
  assert.equal(parseValidationSummary({ workflow: { mode: 'opencode-skill' } }), null)
})

test('校验通过时标记为 passed', () => {
  const summary = parseValidationSummary({
    workflow: { stage: 'finalized', validationErrors: [], missingTargets: [] },
  })
  assert.equal(summary.passed, true)
})

test('stage 是 finalized 但仍带未通过项时不算通过', () => {
  const summary = parseValidationSummary({
    workflow: {
      stage: 'finalized',
      validationErrors: [{ fieldKey: 'projectUnit', message: '提交值与引用证据文本不一致。' }],
    },
  })
  assert.equal(summary.passed, false)
  assert.deepEqual(summary.errors, ['projectUnit：提交值与引用证据文本不一致。'])
})

test('未通过时整理出各类明细', () => {
  const summary = parseValidationSummary({
    workflow: {
      stage: 'failed',
      validationErrors: [
        { fieldKey: 'projectUnit', message: '提交值与引用证据文本不一致。' },
        { rowNo: 12, message: '引用了不存在的证据编号。' },
      ],
      missingTargets: ['technicalInterpretation'],
      repairedShards: ['projectBasics'],
      failedShards: ['grid_documents'],
    },
  })

  assert.equal(summary.passed, false)
  assert.equal(summary.stage, 'failed')
  assert.deepEqual(summary.errors, [
    'projectUnit：提交值与引用证据文本不一致。',
    '清单第 12 行：引用了不存在的证据编号。',
  ])
  assert.deepEqual(summary.missingTargets, ['technicalInterpretation'])
  assert.deepEqual(summary.repairedShards, ['projectBasics'])
  assert.deepEqual(summary.failedShards, ['grid_documents'])
})

test('validationErrors 是纯字符串时原样保留', () => {
  const summary = parseValidationSummary({
    workflow: { stage: 'failed', validationErrors: ['技术清单缺少第 1 行'] },
  })
  assert.deepEqual(summary.errors, ['技术清单缺少第 1 行'])
})

test('validationErrorText 覆盖各种形状', () => {
  assert.equal(validationErrorText('纯字符串'), '纯字符串')
  assert.equal(validationErrorText({ rowNo: 3, message: '越界' }), '清单第 3 行：越界')
  assert.equal(validationErrorText({ fieldKey: 'tenderer', message: '不一致' }), 'tenderer：不一致')
  assert.equal(validationErrorText({ code: 'some_code' }), 'some_code')
  assert.equal(validationErrorText({}), '')
  assert.equal(validationErrorText(null), '')
})
