import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const modalSource = readFileSync(
  resolve(__dirname, 'pages/BusinessProjectWizardModal.jsx'),
  'utf8',
)

test('商务标项目弹窗保留商务客户逻辑，不引入技术标风机机型必填', () => {
  assert.match(modalSource, /客户来源/)
  assert.match(modalSource, /重点客户/)
  assert.match(modalSource, /普通客户/)
  assert.match(modalSource, /normalizeCustomers/)
  assert.match(modalSource, /turbineModel:\s*\{\}/)

  assert.doesNotMatch(modalSource, /风机机型明细/)
  assert.doesNotMatch(modalSource, /businessProjectInfoOptionsAPI/)
  assert.doesNotMatch(modalSource, /projectInfoForm/)
  assert.doesNotMatch(modalSource, /cleanTurbineModelRows/)
})
