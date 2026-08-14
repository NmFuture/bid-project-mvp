import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const tenderReviewSource = readFileSync(
  new URL('./pages/TechnicalTenderReview.jsx', import.meta.url),
  'utf8',
)
const parseResultSource = readFileSync(
  new URL('./pages/TechnicalParseResult.jsx', import.meta.url),
  'utf8',
)
const backgroundStackSource = readFileSync(
  new URL('./components/TechnicalBackgroundTaskStack.jsx', import.meta.url),
  'utf8',
)

test('技术标解析启动后登记后台任务并持续同步进度', () => {
  assert.match(tenderReviewSource, /markTechnicalTask/)
  assert.match(tenderReviewSource, /updateTechnicalTask/)
  assert.match(tenderReviewSource, /taskType:\s*['"]parse['"]/)
  assert.match(tenderReviewSource, /taskName:\s*['"]技术标解析['"]/)
  assert.match(tenderReviewSource, /projectName:/)
  assert.match(tenderReviewSource, /updateTechnicalTask\(\s*['"]parse['"]\s*,/)
  assert.match(tenderReviewSource, /parseProgress[\s\S]*?status:[\s\S]*?percentage:[\s\S]*?summary:/)
})

test('技术标解析在完成跳转前显式同步终态', () => {
  const syncStart = tenderReviewSource.indexOf('const syncParsedProject')
  const syncEnd = tenderReviewSource.indexOf('const navigateToParseResult', syncStart)
  const syncSource = tenderReviewSource.slice(syncStart, syncEnd)
  assert.match(syncSource, /updateTechnicalTask\(\s*['"]parse['"]\s*,/)

  assert.match(
    tenderReviewSource,
    /if \(snapshot\.completed\) \{[\s\S]*?updateTechnicalTask\([\s\S]*?navigateToParseResult/,
  )
})

test('解析停止失败恢复轮询，成功后继续轮询但保留请求 guard', () => {
  const handlerStart = tenderReviewSource.indexOf('const handleStopParse')
  const handlerEnd = tenderReviewSource.indexOf('useEffect(() => () =>', handlerStart)
  const handlerSource = tenderReviewSource.slice(handlerStart, handlerEnd)

  assert.match(handlerSource, /technicalParseAPI\.cancel/)
  assert.match(handlerSource, /cancelled\?\.error[\s\S]*?parseStoppedRef\.current\s*=\s*false/)
  assert.match(handlerSource, /cancelled\?\.error[\s\S]*?setParseStopRequested\(false\)/)
  assert.match(handlerSource, /updateTechnicalTask\(\s*['"]parse['"]\s*,/)
  assert.doesNotMatch(handlerSource, /buildStoppedParseProgress\(\{\s*\.\.\.previous,\s*\.\.\.cancelled/)

  const successStart = handlerSource.indexOf('if (cancelled) {')
  const successSource = handlerSource.slice(successStart)
  assert.match(successSource, /setParseStopRequested\(false\)/)
  assert.doesNotMatch(successSource, /parseStoppedRef\.current\s*=\s*false/)
  assert.match(
    tenderReviewSource,
    /disabled=\{parseStopRequested\s*\|\|\s*parseProgressStatus\s*===\s*['"]cancel_requested['"]\}/,
  )
})

test('重新解析可中止且晚到响应不会登记 marker 或跳转', () => {
  const handlerStart = tenderReviewSource.indexOf('const handleRerunParse')
  const handlerEnd = tenderReviewSource.indexOf('const handleDecision', handlerStart)
  const handlerSource = tenderReviewSource.slice(handlerStart, handlerEnd)

  assert.match(handlerSource, /const abortController = new AbortController\(\)/)
  assert.match(handlerSource, /technicalParseAPI\.run\(targetProjectId,\s*\{\s*signal:\s*abortController\.signal\s*\}\)/)
  assert.match(handlerSource, /parseRequestEpochRef\.current\s*!==\s*requestEpoch/)

  const requestIndex = handlerSource.indexOf('technicalParseAPI.run')
  const firstGuardIndex = handlerSource.indexOf('parseRequestEpochRef.current !== requestEpoch', requestIndex)
  const markerIndex = handlerSource.indexOf('markParseRunning', requestIndex)
  assert.ok(requestIndex >= 0 && firstGuardIndex > requestIndex && firstGuardIndex < markerIndex)

  const syncIndex = handlerSource.indexOf('await syncParsedProject', requestIndex)
  const secondGuardIndex = handlerSource.indexOf('parseRequestEpochRef.current !== requestEpoch', syncIndex)
  const navigateIndex = handlerSource.indexOf('navigateToParseResult', syncIndex)
  assert.ok(syncIndex > requestIndex && secondGuardIndex > syncIndex && secondGuardIndex < navigateIndex)
})

test('首次目录页面读取恢复参数但只由用户操作启动任务', () => {
  assert.match(parseResultSource, /useSearchParams/)
  assert.match(parseResultSource, /searchParams\.get\(\s*['"]progressTask['"]\s*\)/)
  assert.match(parseResultSource, /const handleGenerateDirectory/)
  assert.match(parseResultSource, /markTechnicalTask\([\s\S]*?taskType:\s*['"]directory-generate['"]/)
  assert.match(parseResultSource, /taskName:\s*['"]生成目录['"]/)
  assert.match(parseResultSource, /updateTechnicalTask\(\s*['"]directory-generate['"]\s*,/)

  const runCalls = [...parseResultSource.matchAll(/technicalDirectoryAPI\.run\(/g)]
  assert.equal(runCalls.length, 1, '目录生成只能由 handleGenerateDirectory 主动发起')
  assert.ok(runCalls[0].index > parseResultSource.indexOf('const handleGenerateDirectory'))
})

test('首次目录生成提供真实停止操作与停止中状态', () => {
  assert.match(parseResultSource, /const handleStopDirectory/)
  assert.match(parseResultSource, /technicalDirectoryAPI\.cancel\(id\)/)
  assert.match(parseResultSource, /setDirectoryStopRequested\(false\)/)
  assert.match(parseResultSource, /variant=['"]dangerQuiet['"]/)
  assert.match(parseResultSource, /size=['"]stage['"]/)
  assert.match(parseResultSource, /停止中\.\.\./)
})

test('首次目录新任务和终态都会复位停止请求状态', () => {
  const handlerStart = parseResultSource.indexOf('const handleGenerateDirectory')
  const handlerEnd = parseResultSource.indexOf('const handleStopDirectory', handlerStart)
  const handlerSource = parseResultSource.slice(handlerStart, handlerEnd)
  const resetIndex = handlerSource.indexOf('setDirectoryStopRequested(false)')
  const runIndex = handlerSource.indexOf('technicalDirectoryAPI.run(id)')

  assert.ok(resetIndex >= 0 && resetIndex < runIndex)
  assert.match(
    parseResultSource,
    /if \(!isDirectoryRunning\)[\s\S]*?setDirectoryStopRequested\(false\)/,
  )
})

test('旧解析标记轮询不会用项目 id 覆盖已登记的项目名', () => {
  assert.match(backgroundStackSource, /currentTask\?\.projectName/)
  assert.match(
    backgroundStackSource,
    /marker\.projectName\s*\|\|\s*currentTask\?\.projectName\s*\|\|\s*marker\.projectId/,
  )
})
