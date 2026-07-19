import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const prefillModule = await import('./technicalProjectPrefill.js').catch(() => ({}))
const buildInitialForm = prefillModule.buildTechnicalProjectInitialForm

test('技术标解析暂存项目优先使用识别结果并在起始日期为空时填写当天', () => {
  assert.equal(typeof buildInitialForm, 'function')

  const form = buildInitialForm({
    project: {
      id: 'PRJ-0001',
      name: '技术标解析暂存-20260717-1530',
      projectCode: 'PRJ-0001',
      bidType: '技术标',
      startDate: '',
      endDate: '',
      isParseDraft: true,
    },
    prefill: {
      name: '华能甘肃100MW风电项目',
      projectCode: 'HN-GS-2026-001',
      endDate: '2026-08-06',
      deadline: '2026-08-06',
    },
    today: '2026-07-17',
  })

  assert.equal(form.name, '华能甘肃100MW风电项目')
  assert.equal(form.projectCode, 'HN-GS-2026-001')
  assert.equal(form.startDate, '2026-07-17')
  assert.equal(form.endDate, '2026-08-06')
})

test('没有识别结果时保留解析暂存项目的原有默认值', () => {
  assert.equal(typeof buildInitialForm, 'function')

  const form = buildInitialForm({
    project: {
      id: 'PRJ-0002',
      name: '技术标解析暂存-20260717-1540',
      projectCode: 'PRJ-0002',
      bidType: '技术标',
      startDate: '',
      endDate: '2026-08-08',
      isParseDraft: true,
    },
    prefill: {},
    today: '2026-07-17',
  })

  assert.equal(form.name, '技术标解析暂存-20260717-1540')
  assert.equal(form.projectCode, 'PRJ-0002')
  assert.equal(form.startDate, '2026-07-17')
  assert.equal(form.endDate, '2026-08-08')
})

test('正式项目忽略解析预填且已有起始日期不被当天覆盖', () => {
  assert.equal(typeof buildInitialForm, 'function')

  const form = buildInitialForm({
    project: {
      id: 'PRJ-0003',
      name: '人工确认项目',
      projectCode: 'MANUAL-001',
      bidType: '技术标',
      startDate: '2026-07-01',
      endDate: '2026-08-01',
      isParseDraft: false,
    },
    prefill: {
      name: '不应覆盖的解析名称',
      projectCode: 'PARSED-001',
      endDate: '2026-09-01',
    },
    today: '2026-07-17',
  })

  assert.equal(form.name, '人工确认项目')
  assert.equal(form.projectCode, 'MANUAL-001')
  assert.equal(form.startDate, '2026-07-01')
  assert.equal(form.endDate, '2026-08-01')
})

test('技术标完善项目信息隐藏标书类型并接入解析预填数据', () => {
  const modalSource = readFileSync(resolve(__dirname, 'pages/TechnicalProjectWizardModal.jsx'), 'utf8')
  const reviewSource = readFileSync(resolve(__dirname, 'pages/TechnicalTenderReview.jsx'), 'utf8')

  assert.doesNotMatch(modalSource, />标书类型</)
  assert.match(modalSource, /bidType:\s*TECHNICAL_BID_TYPE/)
  assert.match(modalSource, /isParseDraft:\s*false/)
  assert.match(reviewSource, /isParseDraft:\s*true/)
  assert.match(reviewSource, /prefill=\{parseData\?\.projectPrefill\}/)
})
