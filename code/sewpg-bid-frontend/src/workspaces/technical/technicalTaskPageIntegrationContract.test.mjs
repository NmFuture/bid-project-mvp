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
const gapRecognitionSource = readFileSync(
  new URL('./pages/TechnicalGapRecognition.jsx', import.meta.url),
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

test('首次正文页面恢复后台任务但只由用户操作启动生成', () => {
  assert.match(gapRecognitionSource, /useSearchParams/)
  assert.match(gapRecognitionSource, /searchParams\.get\(\s*['"]progressTask['"]\s*\)/)
  assert.match(gapRecognitionSource, /progressTask\s*===\s*['"]body-generate['"]/)
  assert.match(gapRecognitionSource, /technicalProjectsAPI\.get\(requestProjectId\)/)
  assert.match(gapRecognitionSource, /markTechnicalTask\([\s\S]*?taskType:\s*['"]body-generate['"]/)
  assert.match(gapRecognitionSource, /taskName:\s*['"]生成正文['"]/)
  assert.match(gapRecognitionSource, /projectName:/)
  assert.match(gapRecognitionSource, /updateTechnicalTask\(\s*['"]body-generate['"]\s*,/)

  const runCalls = [...gapRecognitionSource.matchAll(/technicalGenerateAPI\.run\(/g)]
  assert.equal(runCalls.length, 1, '正文生成只能由 runTechnicalAssembly 主动发起')
  assert.ok(runCalls[0].index > gapRecognitionSource.indexOf('const runTechnicalAssembly'))
})

test('首次正文提供真实停止，并把停止控件交给统一弹窗', () => {
  const handlerStart = gapRecognitionSource.indexOf('const handleStopGeneration')
  const handlerEnd = gapRecognitionSource.indexOf('const advanceToTechnicalEditor', handlerStart)
  const handlerSource = gapRecognitionSource.slice(handlerStart, handlerEnd)

  assert.ok(handlerStart >= 0)
  assert.match(handlerSource, /technicalGenerateAPI\.cancel\(requestProjectId\)/)
  assert.match(handlerSource, /setGenerationStopping\(true\)/)
  assert.match(handlerSource, /setGenerationStopping\(false\)/)
  assert.match(handlerSource, /setGenerationStatus\(/)
  assert.match(gapRecognitionSource, /onStop=\{handleStopGeneration\}/)
  assert.match(gapRecognitionSource, /stopping=\{generationStopping\}/)

  const closeStart = gapRecognitionSource.indexOf('onClose={() => {', gapRecognitionSource.indexOf('<TechnicalGenerationProgressModal'))
  const closeEnd = gapRecognitionSource.indexOf('}}', closeStart)
  assert.doesNotMatch(gapRecognitionSource.slice(closeStart, closeEnd), /technicalGenerateAPI\.cancel/)
})

test('首次正文把请求失败同步成后台失败态', () => {
  const handlerStart = gapRecognitionSource.indexOf('const runTechnicalAssembly')
  const handlerEnd = gapRecognitionSource.indexOf('const handleStopGeneration', handlerStart)
  const handlerSource = gapRecognitionSource.slice(handlerStart, handlerEnd)

  assert.match(handlerSource, /markTechnicalTask\([\s\S]*?status:\s*['"]queued['"]/)
  assert.match(handlerSource, /catch \(e\) \{[\s\S]*?updateTechnicalTask\([\s\S]*?status:\s*['"]failed['"]/)
})

test('首次正文异步响应按当前项目隔离且项目切换立即重置任务 UI', () => {
  assert.match(gapRecognitionSource, /const currentProjectIdRef = useRef\(String\(id\)\)/)
  assert.match(gapRecognitionSource, /currentProjectIdRef\.current\s*=\s*String\(id\)/)
  assert.match(
    gapRecognitionSource,
    /useEffect\(\(\) => \{[\s\S]*?setGenerationStatus\(null\)[\s\S]*?setGenerationOwnerId\(['"]['"]\)[\s\S]*?setGenerationModalOpen\(false\)[\s\S]*?setGenerationStopping\(false\)[\s\S]*?setGenerationModalDismissed\(false\)[\s\S]*?setBusyAction\(['"]['"]\)[\s\S]*?setProjectName\(id\)[\s\S]*?\}, \[id\]\)/,
  )
  assert.match(
    gapRecognitionSource,
    /open=\{generationBelongsToProject\s*&&\s*\(generationModalOpen\s*\|\|\s*generationRunning\)\s*&&\s*!generationModalDismissed\}/,
  )

  for (const [startMarker, endMarker] of [
    ['const loadGenerationStatus', 'useEffect(() => {'],
    ['const runTechnicalAssembly', 'const handleStopGeneration'],
    ['const handleStopGeneration', 'const advanceToTechnicalEditor'],
  ]) {
    const start = gapRecognitionSource.indexOf(startMarker)
    const end = gapRecognitionSource.indexOf(endMarker, start + startMarker.length)
    const handlerSource = gapRecognitionSource.slice(start, end)
    assert.match(handlerSource, /const requestProjectId = id/)
    assert.match(handlerSource, /technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)/)
  }
})

test('首次正文在主加载结束前取得真实项目名且晚到响应不能覆盖', () => {
  const loadStart = gapRecognitionSource.indexOf('const loadData')
  const loadEnd = gapRecognitionSource.indexOf('const loadGenerationStatus', loadStart)
  const loadSource = gapRecognitionSource.slice(loadStart, loadEnd)

  assert.match(loadSource, /Promise\.all\(\[[\s\S]*?technicalProjectsAPI\.get\(requestProjectId\)\.catch\(\(\) => null\)/)
  assert.match(loadSource, /technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)/)
  assert.match(loadSource, /setProjectName\(projectPayload\?\.name \|\| requestProjectId\)/)
})

test('首次正文晚到的活动响应先保留原项目后台追踪再阻断页面回写', () => {
  const loadStart = gapRecognitionSource.indexOf('const loadGenerationStatus')
  const loadEnd = gapRecognitionSource.indexOf('useEffect(() => {', loadStart)
  const loadSource = gapRecognitionSource.slice(loadStart, loadEnd)
  const markIndex = loadSource.indexOf('markTechnicalTask({')
  const guardIndex = loadSource.indexOf(
    'technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)',
  )
  const projectNameIndex = loadSource.indexOf('setProjectName(resolvedProjectName)')

  assert.ok(markIndex >= 0 && markIndex < guardIndex, '旧项目 active 响应必须先登记后台任务')
  assert.ok(guardIndex >= 0 && guardIndex < projectNameIndex, '当前项目 guard 必须挡在 UI 回写之前')
  assert.match(
    loadSource.slice(markIndex, guardIndex),
    /projectId:\s*requestProjectId[\s\S]*?projectName:\s*resolvedProjectName/,
  )
})

test('首次正文停止接口返回业务错误时不覆盖后台任务并恢复停止按钮', () => {
  const handlerStart = gapRecognitionSource.indexOf('const handleStopGeneration')
  const handlerEnd = gapRecognitionSource.indexOf('const advanceToTechnicalEditor', handlerStart)
  const handlerSource = gapRecognitionSource.slice(handlerStart, handlerEnd)
  const responseIndex = handlerSource.indexOf('await technicalGenerateAPI.cancel(requestProjectId)')
  const errorCheckIndex = handlerSource.indexOf('if (payload?.error)')
  const taskPatchIndex = handlerSource.indexOf('generationTaskPatch(payload)')

  assert.ok(responseIndex >= 0 && responseIndex < errorCheckIndex)
  assert.ok(errorCheckIndex >= 0 && errorCheckIndex < taskPatchIndex)
  assert.match(handlerSource, /if \(payload\?\.error\) throw new Error\(payload\.error\)/)
  assert.match(handlerSource, /catch \(e\) \{[\s\S]*?setGenerationStopping\(false\)/)
})
