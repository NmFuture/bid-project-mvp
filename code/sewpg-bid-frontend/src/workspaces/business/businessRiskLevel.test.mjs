import test from 'node:test'
import assert from 'node:assert/strict'

import { businessRiskLevelLabel } from './businessRiskLevel.js'

test('商务废标项 riskLevel 使用中文风险级别展示', () => {
  assert.equal(businessRiskLevelLabel('high'), '高风险')
  assert.equal(businessRiskLevelLabel('medium'), '中风险')
  assert.equal(businessRiskLevelLabel('low'), '低风险')
})

test('未知 riskLevel 保留原始值，空值显示未识别', () => {
  assert.equal(businessRiskLevelLabel('否决投标'), '否决投标')
  assert.equal(businessRiskLevelLabel(''), '未识别')
  assert.equal(businessRiskLevelLabel(null), '未识别')
})
