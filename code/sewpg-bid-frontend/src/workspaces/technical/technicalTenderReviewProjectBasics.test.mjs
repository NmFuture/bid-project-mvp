import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(
  resolve(__dirname, 'pages/TechnicalTenderReview.jsx'),
  'utf8',
)

test('技术标解析结果使用商务标一致的六项项目基础信息字段', () => {
  for (const field of ['projectName', 'tenderNo', 'projectUnit', 'tenderer', 'tenderAgency', 'bidDeadline']) {
    assert.match(source, new RegExp(`['"]${field}['"]`))
  }
  assert.match(source, /项目名称/)
  assert.match(source, /招标编号/)
  assert.match(source, /项目单位/)
  assert.match(source, /招标人/)
  assert.match(source, /招标代理机构/)
  assert.match(source, /递交截止时间/)
})

test('技术标解析结果优先展示项目基础信息且不被技术解读清单隐藏', () => {
  assert.match(source, /function ProjectBasicsTable/)
  assert.match(source, /<ProjectBasicsTable title="项目基础信息" fields=\{projectBasics\} \/>/)

  const projectBasicsRenderIndex = source.indexOf('<ProjectBasicsTable title="项目基础信息" fields={projectBasics} />')
  const interpretationRenderIndex = source.indexOf('{hasTechnicalInterpretation ? (')

  assert.ok(projectBasicsRenderIndex > -1)
  assert.ok(interpretationRenderIndex > -1)
  assert.ok(projectBasicsRenderIndex < interpretationRenderIndex)
})

test('技术标项目基础信息表展示字段内容来源三列且不展示状态栏', () => {
  const start = source.indexOf('function ProjectBasicsTable')
  const end = source.indexOf('export default function TechnicalTenderReview')
  assert.ok(start > -1)
  assert.ok(end > start)

  const tableSource = source.slice(start, end)
  assert.match(tableSource, />字段</)
  assert.match(tableSource, />解析内容</)
  assert.match(tableSource, />来源</)
  assert.doesNotMatch(tableSource, />状态</)
  assert.doesNotMatch(tableSource, /已识别/)
  assert.doesNotMatch(tableSource, /待补充/)
})

test('技术标项目基础信息来源列与商务标一致使用文件章节和可读证据位置', () => {
  const start = source.indexOf('const sourceValue =')
  const end = source.indexOf('const presenceLabel')
  assert.ok(start > -1)
  assert.ok(end > start)

  const sourceValueSource = source.slice(start, end)
  assert.match(sourceValueSource, /\[row\.sourceFile, row\.section, row\.evidenceLocation\]\.filter\(Boolean\)/)
  assert.doesNotMatch(sourceValueSource, /row\.sourceText \|\| row\.sourceLabel \|\| row\.source/)
  assert.doesNotMatch(sourceValueSource, /row\.evidence\)/)
  assert.doesNotMatch(sourceValueSource, /row\.evidence\]/)
})

test('technical parse detail load keeps running progress monotonic', () => {
  const start = source.indexOf('const loadCurrentProject = useCallback')
  const end = source.indexOf('}, [selectedProjectId])', start)
  assert.ok(start > -1)
  assert.ok(end > start)

  const loadCurrentProjectSource = source.slice(start, end)
  assert.doesNotMatch(loadCurrentProjectSource, /setParseProgress\(progressResult\)/)
  assert.match(
    loadCurrentProjectSource,
    /setParseProgress\(\(previous\) => mergeMonotonicParseProgress\(previous, progressResult\)\)/,
  )
})
