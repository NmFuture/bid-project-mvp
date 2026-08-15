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
// ProjectBasicsTable 与其纯逻辑已共享化：技术标用默认导出（technical variant），
// 字段常量与取值/来源逻辑在 reviewTableValues.js。
const tableSource = readFileSync(
  resolve(__dirname, '../shared/components/reviewTables/ProjectBasicsTable.jsx'),
  'utf8',
)
const valuesSource = readFileSync(
  resolve(__dirname, '../shared/components/reviewTables/reviewTableValues.js'),
  'utf8',
)

test('技术标解析结果使用商务标一致的六项项目基础信息字段', () => {
  for (const field of ['projectName', 'tenderNo', 'projectUnit', 'tenderer', 'tenderAgency', 'bidDeadline']) {
    assert.match(valuesSource, new RegExp(`['"]${field}['"]`))
  }
  assert.match(valuesSource, /项目名称/)
  assert.match(valuesSource, /招标编号/)
  assert.match(valuesSource, /项目单位/)
  assert.match(valuesSource, /招标人/)
  assert.match(valuesSource, /招标代理机构/)
  assert.match(valuesSource, /递交截止时间/)
})

test('技术标解析结果优先展示项目基础信息且不被技术解读清单隐藏', () => {
  assert.match(source, /import ProjectBasicsTable from '\.\.\/\.\.\/shared\/components\/reviewTables\/ProjectBasicsTable'/)
  assert.match(source, /<ProjectBasicsTable title="项目基础信息" fields=\{projectBasics\} \/>/)

  const projectBasicsRenderIndex = source.indexOf('<ProjectBasicsTable title="项目基础信息" fields={projectBasics} />')
  const interpretationRenderIndex = source.indexOf('{hasTechnicalInterpretation ? (')

  assert.ok(projectBasicsRenderIndex > -1)
  assert.ok(interpretationRenderIndex > -1)
  assert.ok(projectBasicsRenderIndex < interpretationRenderIndex)
})

test('技术标项目基础信息表展示字段内容来源三列且不展示状态栏', () => {
  assert.match(tableSource, />字段</)
  assert.match(tableSource, /解析内容/)
  assert.match(tableSource, />来源</)
  assert.doesNotMatch(tableSource, />状态</)
  assert.doesNotMatch(tableSource, /已识别/)
  assert.doesNotMatch(tableSource, /待补充/)
})

test('技术标项目基础信息来源列与商务标一致使用文件章节和可读证据位置', () => {
  const start = valuesSource.indexOf('export const sourceValue =')
  const end = valuesSource.indexOf('export const formatBidDeadline')
  assert.ok(start > -1)
  assert.ok(end > start)

  const sourceValueSource = valuesSource.slice(start, end)
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
