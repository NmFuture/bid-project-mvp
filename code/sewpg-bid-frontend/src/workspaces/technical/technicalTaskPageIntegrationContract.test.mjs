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
const coCreationEditorSource = readFileSync(
  new URL('./pages/TechnicalCoCreationEditor.jsx', import.meta.url),
  'utf8',
)
const outlineReviewSource = readFileSync(
  new URL('./pages/TechnicalOutlineReview.jsx', import.meta.url),
  'utf8',
)
const definitionsSource = readFileSync(
  new URL('./technicalBackgroundTaskDefinitions.js', import.meta.url),
  'utf8',
)
const parseMarkerSource = readFileSync(
  new URL('../shared/parseRunningMarker.js', import.meta.url),
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

test('解析运行标记只用于补建丢失的登记，不覆盖已登记的进度和项目名', () => {
  // 已有登记就整条跳过：解析页每秒写真实进度，这里再盖一次会让卡片来回跳、也会让关掉的卡片复活
  assert.match(backgroundStackSource, /if \(currentTask\) return/)
  assert.match(backgroundStackSource, /const resolvedName = marker\.projectName/)
  // 旧标记没存项目名，补查一次，别让卡片只显示项目编号
  assert.match(backgroundStackSource, /technicalProjectsAPI\.get\(marker\.projectId\)[\s\S]*?\|\|\s*marker\.projectId/)
  // 标记里带上项目名，补建出来的卡片才不会只显示项目编号
  assert.match(parseMarkerSource, /projectName: String\(projectName \|\| ''\)\.trim\(\)/)
  assert.match(tenderReviewSource, /markParseRunning\(targetProjectId, 'tech', targetProjectName/)
  assert.match(tenderReviewSource, /markParseRunning\(targetProjectId, 'tech', project\?\.name/)
})

test('解析停止和终态都撤掉运行标记，卡片不会被标记补回来', () => {
  const stopStart = tenderReviewSource.indexOf('const handleStopParse')
  const stopEnd = tenderReviewSource.indexOf('const handleUploadAndParse', stopStart)
  assert.match(tenderReviewSource.slice(stopStart, stopEnd), /clearParseRunning\(targetProjectId, 'tech'\)/)
  assert.match(backgroundStackSource, /if \(task\.taskType === 'parse'\) clearParseRunning\(task\.projectId, 'tech'\)/)
  assert.match(
    backgroundStackSource,
    /if \(task\.taskType === 'parse' && !technicalTaskIsActive\(\{ status \}\)\) \{[\s\S]*?clearParseRunning/,
  )
})

test('页面在跟踪或正显示的任务不由任务栈重复轮询和挂卡片', () => {
  assert.match(backgroundStackSource, /if \(isTechnicalTaskTracked\(task\)\) return/)
  assert.match(backgroundStackSource, /!foregroundKeys\.has\(technicalTaskPresenceKey\(task\.taskType, task\.projectId\)\)/)
  // 解析和首次目录没有弹窗：停留在页面上就算前台
  assert.match(tenderReviewSource, /useTechnicalTaskPresence\('parse', selectedProjectId, true\)/)
  assert.match(parseResultSource, /useTechnicalTaskPresence\('directory-generate', id, true\)/)
  // 其余四处按弹窗是否打开决定
  assert.match(outlineReviewSource, /useTechnicalTaskPresence\('outline-regenerate', id, regenerationModalOpen\)/)
  assert.match(outlineReviewSource, /useTechnicalTaskPresence\('material-match', id, materialMatchModalOpen\)/)
  assert.match(gapRecognitionSource, /useTechnicalTaskPresence\('body-generate', id, generationModalVisible\)/)
  assert.match(coCreationEditorSource, /useTechnicalTaskPresence\('body-generate', id, generationModalVisible\)/)
  assert.match(coCreationEditorSource, /useTechnicalTaskPresence\('index-regenerate', id, scoreIndexModalVisible\)/)
})

test('卡片百分比与页面内进度条同一算法', () => {
  assert.match(tenderReviewSource, /percentage: Math\.round\(parseDisplayPercentage\(parseProgress\)\)/)
  assert.match(parseResultSource, /percentage: Math\.round\(directoryDisplayPercentage\(directoryState, directoryProgressClock\)\)/)
  assert.match(definitionsSource, /displayPercentage: \(progress\) => parseDisplayPercentage/)
  assert.match(definitionsSource, /displayPercentage: \(progress\) => directoryDisplayPercentage/)
  assert.match(definitionsSource, /displayPercentage: \(progress\) => generationDisplayPercentage/)
  assert.match(definitionsSource, /displayPercentage: \(progress\) => scoreIndexDisplayPercentage/)
  assert.match(backgroundStackSource, /definition\.displayPercentage[\s\S]*?\?\s*definition\.displayPercentage\(progress\)/)
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
  // 弹窗可见条件收敛成一个常量，弹窗开关和「是否算前台」必须用同一个判断
  assert.match(
    gapRecognitionSource,
    /const generationModalVisible = generationBelongsToProject[\s\S]*?&& \(generationModalOpen \|\| generationRunning\)[\s\S]*?&& !generationModalDismissed/,
  )
  assert.match(gapRecognitionSource, /open=\{generationModalVisible\}/)

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
  // 恢复走 restoreTechnicalTask：已有登记只补进度，不改写发起页写下的任务名
  const markIndex = loadSource.indexOf('restoreTechnicalTask({')
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

test('共创页恢复正文和索引后台任务但不会自动重新发起', () => {
  assert.match(coCreationEditorSource, /useSearchParams/)
  assert.match(coCreationEditorSource, /searchParams\.get\(\s*['"]progressTask['"]\s*\)/)
  assert.match(coCreationEditorSource, /progressTask\s*===\s*['"]body-generate['"]/)
  assert.match(coCreationEditorSource, /progressTask\s*===\s*['"]index-regenerate['"]/)
  assert.match(coCreationEditorSource, /taskType:\s*['"]body-generate['"]/)
  assert.match(coCreationEditorSource, /taskName:\s*['"]重新生成正文['"]/)
  assert.match(coCreationEditorSource, /taskType:\s*['"]index-regenerate['"]/)
  assert.match(coCreationEditorSource, /taskName:\s*['"]重新生成索引['"]/)
  assert.match(coCreationEditorSource, /updateTechnicalTask\(\s*['"]body-generate['"]\s*,/)
  assert.match(coCreationEditorSource, /updateTechnicalTask\(\s*['"]index-regenerate['"]\s*,/)

  assert.equal([...coCreationEditorSource.matchAll(/technicalGenerateAPI\.run\(/g)].length, 1)
  assert.equal([...coCreationEditorSource.matchAll(/technicalScoreIndexAPI\.run\(/g)].length, 1)
})

test('共创页主加载取得真实项目名并隔离跨项目任务 UI', () => {
  assert.match(coCreationEditorSource, /technicalProjectsAPI\.get\(requestProjectId\)/)
  assert.match(coCreationEditorSource, /const currentProjectIdRef = useRef\(String\(id\)\)/)
  assert.match(coCreationEditorSource, /currentProjectIdRef\.current\s*=\s*String\(id\)/)
  assert.match(
    coCreationEditorSource,
    /setGenerationStatus\(null\)[\s\S]*?setGenerationOwnerId\(['"]['"]\)[\s\S]*?setScoreIndexStatus\(null\)[\s\S]*?setScoreIndexOwnerId\(['"]['"]\)/,
  )
  assert.match(
    coCreationEditorSource,
    /const generationModalVisible = generationBelongsToProject[\s\S]*?const scoreIndexModalVisible = scoreIndexBelongsToProject/,
  )
  assert.match(coCreationEditorSource, /open=\{generationModalVisible\}[\s\S]*?open=\{scoreIndexModalVisible\}/)
  assert.match(coCreationEditorSource, /technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)/)
})

test('共创页正文和索引都提供真实停止且业务错误不覆盖任务', () => {
  for (const [handlerName, nextHandler, apiName, stoppingSetter, taskType] of [
    ['handleStopGeneration', 'handleStopScoreIndex', 'technicalGenerateAPI', 'setGenerationStopping', 'body-generate'],
    ['handleStopScoreIndex', 'handleApplyTechnicalFormat', 'technicalScoreIndexAPI', 'setScoreIndexStopping', 'index-regenerate'],
  ]) {
    const start = coCreationEditorSource.indexOf(`const ${handlerName}`)
    const end = coCreationEditorSource.indexOf(`const ${nextHandler}`, start)
    const handlerSource = coCreationEditorSource.slice(start, end)
    const responseIndex = handlerSource.indexOf(`await ${apiName}.cancel(requestProjectId)`)
    const errorIndex = handlerSource.indexOf('if (payload?.error)')
    const updateIndex = handlerSource.indexOf(`updateTechnicalTask('${taskType}'`)
    assert.ok(start >= 0 && responseIndex >= 0 && responseIndex < errorIndex && errorIndex < updateIndex)
    assert.match(handlerSource, new RegExp(`${stoppingSetter}\\(false\\)`))
  }

  assert.match(coCreationEditorSource, /taskTitle=['"]重新生成正文['"]/)
  assert.match(coCreationEditorSource, /onStop=\{handleStopGeneration\}[\s\S]*?stopping=\{generationStopping\}/)
  assert.match(coCreationEditorSource, /onStop=\{handleStopScoreIndex\}[\s\S]*?stopping=\{scoreIndexStopping\}/)
})

test('共创页取消任务保持互斥，终止后清请求标记且不刷新文档', () => {
  assert.match(coCreationEditorSource, /const generationRunning = generationBelongsToProject && isGenerationProgressRunning\(generationStatus\)/)
  assert.match(coCreationEditorSource, /const scoreIndexRunning = scoreIndexBelongsToProject && isScoreIndexProgressRunning\(scoreIndexStatus\)/)
  assert.match(
    coCreationEditorSource,
    /generationStatus\?\.status === ['"]cancelled['"][\s\S]*?regenerationRequestedRef\.current = false[\s\S]*?return/,
  )
  assert.match(
    coCreationEditorSource,
    /scoreIndexStatus\?\.status === ['"]cancelled['"][\s\S]*?scoreIndexRequestedRef\.current = false[\s\S]*?return/,
  )
})

test('首次正文停止请求不会被晚到的活动响应覆盖', () => {
  assert.match(gapRecognitionSource, /const generationStopRequestedRef = useRef\(false\)/)

  const applyStart = gapRecognitionSource.indexOf('const applyGenerationPayload')
  const applyEnd = gapRecognitionSource.indexOf('useEffect(() => {', applyStart)
  const applySource = gapRecognitionSource.slice(applyStart, applyEnd)
  assert.ok(applyStart >= 0)
  assert.match(applySource, /generationStopRequestedRef\.current\s*&&\s*active/)
  assert.match(applySource, /incomingStatus\s*!==\s*['"]cancel_requested['"]/)
  assert.match(applySource, /status:\s*['"]cancel_requested['"]/)
  assert.match(applySource, /generationStopRequestedRef\.current\s*=\s*false/)

  for (const [startMarker, endMarker] of [
    ['const loadGenerationStatus', 'useEffect(() => {'],
    ['onStatus: (payload) => {', '},\n    })'],
    ['const runTechnicalAssembly', 'const handleStopGeneration'],
  ]) {
    const start = gapRecognitionSource.indexOf(startMarker)
    const end = gapRecognitionSource.indexOf(endMarker, start + startMarker.length)
    assert.match(gapRecognitionSource.slice(start, end), /applyGenerationPayload\(payload/)
  }

  const runStart = gapRecognitionSource.indexOf('const runTechnicalAssembly')
  const runEnd = gapRecognitionSource.indexOf('const handleStopGeneration', runStart)
  const runSource = gapRecognitionSource.slice(runStart, runEnd)
  assert.ok(runSource.indexOf('generationStopRequestedRef.current = false') < runSource.indexOf('technicalGenerateAPI.run'))

  const stopStart = gapRecognitionSource.indexOf('const handleStopGeneration')
  const stopEnd = gapRecognitionSource.indexOf('const advanceToTechnicalEditor', stopStart)
  const stopSource = gapRecognitionSource.slice(stopStart, stopEnd)
  assert.ok(stopSource.indexOf('generationStopRequestedRef.current = true') < stopSource.indexOf('technicalGenerateAPI.cancel'))
  assert.match(stopSource, /catch \(e\) \{[\s\S]*?generationStopRequestedRef\.current\s*=\s*false/)
  assert.match(
    gapRecognitionSource,
    /setGenerationStopping\(false\)[\s\S]*?generationStopRequestedRef\.current\s*=\s*false[\s\S]*?\}, \[id\]\)/,
  )
})

test('共创页正文停止请求不会被 load、run 或 poll 的晚到活动响应覆盖', () => {
  assert.match(coCreationEditorSource, /const generationStopRequestedRef = useRef\(false\)/)

  const applyStart = coCreationEditorSource.indexOf('const applyGenerationPayload')
  const applyEnd = coCreationEditorSource.indexOf('const applyScoreIndexPayload', applyStart)
  const applySource = coCreationEditorSource.slice(applyStart, applyEnd)
  assert.ok(applyStart >= 0)
  assert.match(applySource, /generationStopRequestedRef\.current\s*&&\s*active/)
  assert.match(applySource, /status:\s*['"]cancel_requested['"]/)
  assert.match(applySource, /generationStopRequestedRef\.current\s*=\s*false/)

  for (const [startMarker, endMarker] of [
    ['const loadGenerationStatus', 'const loadScoreIndexStatus'],
    ['fetchStatus: () => technicalGenerateAPI.status(id)', '},\n    })'],
    ['const handleConfirmRegenerate', 'const handleStopGeneration'],
  ]) {
    const start = coCreationEditorSource.indexOf(startMarker)
    const end = coCreationEditorSource.indexOf(endMarker, start + startMarker.length)
    assert.match(coCreationEditorSource.slice(start, end), /applyGenerationPayload\(payload/)
  }

  const runStart = coCreationEditorSource.indexOf('const handleConfirmRegenerate')
  const runEnd = coCreationEditorSource.indexOf('const handleStopGeneration', runStart)
  const runSource = coCreationEditorSource.slice(runStart, runEnd)
  assert.ok(runSource.indexOf('generationStopRequestedRef.current = false') < runSource.indexOf('technicalGenerateAPI.run'))

  const stopStart = coCreationEditorSource.indexOf('const handleStopGeneration')
  const stopEnd = coCreationEditorSource.indexOf('const handleStopScoreIndex', stopStart)
  const stopSource = coCreationEditorSource.slice(stopStart, stopEnd)
  assert.ok(stopSource.indexOf('generationStopRequestedRef.current = true') < stopSource.indexOf('technicalGenerateAPI.cancel'))
  assert.match(stopSource, /catch \(e\) \{[\s\S]*?generationStopRequestedRef\.current\s*=\s*false/)
})

test('共创页索引停止请求不会被 load、run 或 poll 的晚到活动响应覆盖', () => {
  assert.match(coCreationEditorSource, /const scoreIndexStopRequestedRef = useRef\(false\)/)

  const applyStart = coCreationEditorSource.indexOf('const applyScoreIndexPayload')
  const applyEnd = coCreationEditorSource.indexOf('useEffect(() => {', applyStart)
  const applySource = coCreationEditorSource.slice(applyStart, applyEnd)
  assert.ok(applyStart >= 0)
  assert.match(applySource, /scoreIndexStopRequestedRef\.current\s*&&\s*active/)
  assert.match(applySource, /status:\s*['"]cancel_requested['"]/)
  assert.match(applySource, /scoreIndexStopRequestedRef\.current\s*=\s*false/)

  for (const [startMarker, endMarker] of [
    ['const loadScoreIndexStatus', 'useEffect(() => {'],
    ['fetchStatus: () => technicalScoreIndexAPI.status(id)', '},\n    })'],
    ['const handleRegenerateScoreIndex', 'const handleRequestRegenerate'],
  ]) {
    const start = coCreationEditorSource.indexOf(startMarker)
    const end = coCreationEditorSource.indexOf(endMarker, start + startMarker.length)
    assert.match(coCreationEditorSource.slice(start, end), /applyScoreIndexPayload\(payload/)
  }

  const runStart = coCreationEditorSource.indexOf('const handleRegenerateScoreIndex')
  const runEnd = coCreationEditorSource.indexOf('const handleRequestRegenerate', runStart)
  const runSource = coCreationEditorSource.slice(runStart, runEnd)
  assert.ok(runSource.indexOf('scoreIndexStopRequestedRef.current = false') < runSource.indexOf('technicalScoreIndexAPI.run'))

  const stopStart = coCreationEditorSource.indexOf('const handleStopScoreIndex')
  const stopEnd = coCreationEditorSource.indexOf('const handleApplyTechnicalFormat', stopStart)
  const stopSource = coCreationEditorSource.slice(stopStart, stopEnd)
  assert.ok(stopSource.indexOf('scoreIndexStopRequestedRef.current = true') < stopSource.indexOf('technicalScoreIndexAPI.cancel'))
  assert.match(stopSource, /catch \(e\) \{[\s\S]*?scoreIndexStopRequestedRef\.current\s*=\s*false/)
})

test('解析与首次目录没有弹窗，恢复时把页面内进度滚进视野且只滚一次', () => {
  assert.match(tenderReviewSource, /progressTask['"]\s*\)\s*\|\|\s*['"]{2}\)\.trim\(\)\s*===\s*['"]parse['"]/)
  assert.match(tenderReviewSource, /ref=\{parseProgressRef\}/)
  assert.match(
    tenderReviewSource,
    /if \(parseProgressScrolledRef\.current === selectedProjectId\) return[\s\S]*?parseProgressRef\.current\?\.scrollIntoView/,
  )

  assert.match(parseResultSource, /const restoringDirectoryTask = progressTask === ['"]directory-generate['"]/)
  assert.match(parseResultSource, /ref=\{directoryProgressRef\}/)
  assert.match(
    parseResultSource,
    /if \(directoryProgressScrolledRef\.current === id\) return[\s\S]*?directoryProgressRef\.current\?\.scrollIntoView/,
  )
})
