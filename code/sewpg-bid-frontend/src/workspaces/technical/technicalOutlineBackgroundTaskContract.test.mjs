import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const outlineSource = readFileSync(
  new URL('./pages/TechnicalOutlineReview.jsx', import.meta.url),
  'utf8',
)
const materialModalSource = readFileSync(
  new URL('./components/TechnicalMaterialMatchProgressModal.jsx', import.meta.url),
  'utf8',
)

const sourceBetween = (startMarker, endMarker) => {
  const start = outlineSource.indexOf(startMarker)
  const end = outlineSource.indexOf(endMarker, start)
  assert.notEqual(start, -1, `缺少 ${startMarker}`)
  assert.notEqual(end, -1, `缺少 ${endMarker}`)
  return outlineSource.slice(start, end)
}

test('重新生成目录和素材匹配都会登记并同步技术标后台任务', () => {
  assert.match(outlineSource, /markTechnicalTask/)
  assert.match(outlineSource, /updateTechnicalTask/)
  assert.match(outlineSource, /taskType:\s*['"]outline-regenerate['"]/)
  assert.match(outlineSource, /taskName:\s*['"]重新生成目录['"]/)
  assert.match(outlineSource, /taskType:\s*['"]material-match['"]/)
  assert.match(outlineSource, /taskName:\s*['"]素材匹配['"]/)
  assert.match(outlineSource, /projectName:/)
  assert.match(outlineSource, /updateTechnicalTask\(\s*['"]outline-regenerate['"]\s*,/)
  assert.match(outlineSource, /updateTechnicalTask\(\s*['"]material-match['"]\s*,/)
})

test('目录与素材匹配都接入真实停止 API 和统一弹窗停止操作', () => {
  assert.match(outlineSource, /const handleStopDirectory/)
  assert.match(outlineSource, /technicalDirectoryAPI\.cancel\(requestProjectId\)/)
  assert.match(outlineSource, /const handleStopMaterialMatch/)
  assert.match(outlineSource, /technicalGapsAPI\.cancelDetection\(requestProjectId\)/)
  assert.match(outlineSource, /<DirectoryGenerationProgressModal[\s\S]*?onStop=\{handleStopDirectory\}/)
  assert.match(outlineSource, /<TechnicalMaterialMatchProgressModal[\s\S]*?onStop=\{handleStopMaterialMatch\}/)
})

test('恢复 cancel_requested 时保持停止中并继续轮询', () => {
  assert.match(
    outlineSource,
    /incomingStatus\s*===\s*['"]cancel_requested['"][\s\S]*?setMaterialMatchStopping\(true\)/,
  )
  assert.match(
    outlineSource,
    /payload\?\.status\s*===\s*['"]cancel_requested['"][\s\S]*?setDirectoryStopping\(true\)/,
  )
  assert.match(outlineSource, /MATERIAL_MATCH_ACTIVE_STATUSES\.has/)
  assert.match(outlineSource, /isDirectoryProgressRunning/)
})

test('素材匹配提交后不直接完成阶段或跳转，终态由 effect 处理', () => {
  const handlerSource = sourceBetween('const handleConfirm = async () => {', 'const handleAddRoot')
  const runIndex = handlerSource.indexOf('technicalGapsAPI.runDetection(requestProjectId)')
  assert.notEqual(runIndex, -1)
  assert.doesNotMatch(handlerSource.slice(runIndex), /technicalStagesAPI\.update/)
  assert.doesNotMatch(handlerSource.slice(runIndex), /navigate\(/)

  assert.match(outlineSource, /technicalGapsAPI\.detectionStatus\(requestProjectId\)/)
  const effectSource = sourceBetween(
    'if (!technicalTaskBelongsToProject(materialMatchStatus, id)) return undefined',
    'if (!pendingSearchText) return undefined',
  )
  assert.match(effectSource, /status\s*===\s*['"]cancelled['"]/)
  assert.match(effectSource, /status\s*===\s*['"]failed['"]/)
  assert.match(effectSource, /technicalStagesAPI\.update[\s\S]*?materialMatchTerminalHandledRef\.current\s*=\s*epoch[\s\S]*?navigate\(/)
})

test('completed 收口成功前保持 finalizing，失败后限次延迟重试', () => {
  const effectSource = sourceBetween(
    'if (!technicalTaskBelongsToProject(materialMatchStatus, id)) return undefined',
    'if (!pendingSearchText) return undefined',
  )
  const completedSource = effectSource.slice(effectSource.indexOf('const requestProjectId = id'))
  const updateIndex = completedSource.indexOf('technicalStagesAPI.update')
  const handledIndex = completedSource.indexOf('materialMatchTerminalHandledRef.current = epoch')
  const navigateIndex = completedSource.indexOf('navigate(nextRoute)')
  const finalizeCatchSource = completedSource.slice(completedSource.indexOf('} catch (error) {'))
  const retryDecisionIndex = finalizeCatchSource.indexOf('if (materialMatchFinalizeAttempt < 3)')
  const retryExhaustedIndex = finalizeCatchSource.indexOf('} else {', retryDecisionIndex)

  assert.match(outlineSource, /canStartTechnicalTaskFinalize/)
  assert.match(outlineSource, /materialMatchFinalizingEpochRef/)
  assert.match(outlineSource, /materialMatchFinalizeAttempt/)
  assert.match(completedSource.slice(0, updateIndex), /materialMatchFinalizingEpochRef\.current\s*=\s*epoch/)
  assert.doesNotMatch(completedSource.slice(0, updateIndex), /materialMatchTerminalHandledRef\.current\s*=\s*epoch/)
  assert.ok(handledIndex > updateIndex, '阶段更新成功后才能标记 handled')
  assert.ok(navigateIndex > handledIndex, '标记 handled 后只能导航一次')
  assert.match(effectSource, /materialMatchFinalizingEpochRef\.current\s*=\s*0/)
  assert.match(effectSource, /materialMatchFinalizeAttempt\s*<\s*3/)
  assert.match(effectSource, /2000/)
  assert.doesNotMatch(
    finalizeCatchSource.slice(0, retryExhaustedIndex),
    /setMaterialMatchFinalizing\(false\)/,
    '等待重试时必须继续保持 finalizing',
  )
  assert.match(
    finalizeCatchSource.slice(retryExhaustedIndex),
    /setMaterialMatchFinalizing\(false\)/,
    '重试耗尽后才能退出 finalizing',
  )
})

test('再次发起素材匹配会在请求前建立新的 queued epoch', () => {
  const handlerSource = sourceBetween('const handleConfirm = async () => {', 'const handleStopMaterialMatch')
  const queuedIndex = handlerSource.indexOf("status: 'queued'")
  const resetStateIndex = handlerSource.indexOf('setMaterialMatchStatus(scopeTechnicalTaskPayload(requestProjectId, queuedState))')
  const epochIndex = handlerSource.indexOf('materialMatchEpochRef.current = epoch')
  const markIndex = handlerSource.indexOf('markTechnicalTask({')
  const runIndex = handlerSource.indexOf('technicalGapsAPI.runDetection(requestProjectId)')
  const applyIndex = handlerSource.indexOf('applyMaterialMatchPayload(payload, requestProjectId)', runIndex)

  assert.ok(queuedIndex >= 0, '新一轮请求前应创建 queued 状态')
  assert.ok(resetStateIndex > queuedIndex && resetStateIndex < runIndex, 'queued 状态必须在请求前覆盖历史终态')
  assert.ok(epochIndex >= 0 && epochIndex < runIndex, 'epoch 必须在请求前建立')
  assert.ok(markIndex >= 0 && markIndex < runIndex, 'queued 后台任务必须在请求前登记')
  assert.ok(applyIndex > runIndex, '启动响应只应用到已经建立的新 epoch')
  assert.match(handlerSource.slice(0, runIndex), /materialMatchTerminalHandledRef\.current\s*=\s*0/)
  assert.match(handlerSource.slice(0, runIndex), /materialMatchStopRequestedRef\.current\s*=\s*false/)
})

test('素材匹配启动失败会收口新 epoch 和后台任务为 failed', () => {
  const handlerSource = sourceBetween('const handleConfirm = async () => {', 'const handleStopMaterialMatch')
  const catchSource = handlerSource.slice(handlerSource.indexOf('} catch (e) {'))

  assert.match(catchSource, /submittedEpoch\s*>\s*0/)
  assert.match(catchSource, /status:\s*['"]failed['"]/)
  assert.match(catchSource, /setMaterialMatchStatus\(scopeTechnicalTaskPayload\(requestProjectId, failedState\)\)/)
  assert.match(catchSource, /updateTechnicalTask\(\s*['"]material-match['"]\s*,/)
})

test('START 请求异常后回查目录与素材任务，可信状态继续原任务', () => {
  const regenerateSource = sourceBetween('const handleRegenerateDirectory = async () => {', 'const handleStopDirectory')
  const regenerateCatch = regenerateSource.slice(regenerateSource.indexOf('} catch (e) {'))
  const confirmSource = sourceBetween('const handleConfirm = async () => {', 'const handleStopMaterialMatch')
  const confirmCatch = confirmSource.slice(confirmSource.indexOf('} catch (e) {'))

  assert.match(outlineSource, /recoverableTechnicalTaskState/)
  assert.match(regenerateSource, /requestStartedAt\s*=\s*Date\.now\(\)/)
  assert.match(regenerateCatch, /technicalDirectoryAPI\.status\(requestProjectId\)/)
  assert.match(regenerateCatch, /recoverableTechnicalTaskState\(recoveredPayload, requestStartedAt\)/)
  assert.match(regenerateCatch, /setRegenerationModalOpen\(true\)/)
  assert.match(confirmSource, /requestStartedAt\s*=\s*Date\.now\(\)/)
  assert.match(confirmCatch, /technicalGapsAPI\.detectionStatus\(requestProjectId\)/)
  assert.match(confirmCatch, /recoverableTechnicalTaskState\(recoveredPayload, requestStartedAt\)/)
  assert.match(confirmCatch, /applyMaterialMatchPayload\(recoveredPayload, requestProjectId\)/)
})

test('恢复 material-match completed 时建立新 epoch 并进入收口但不重发检测', () => {
  const loadSource = sourceBetween('const loadData = useCallback(async () => {', 'const directoryRunning =')

  assert.match(loadSource, /progressTask\s*===\s*['"]material-match['"]/)
  assert.match(loadSource, /detectionStatus\s*===\s*['"]completed['"]/)
  assert.match(loadSource, /materialMatchEpochRef\.current\s*\+=\s*1/)
  assert.match(loadSource, /materialMatchTerminalHandledRef\.current\s*=\s*0/)
  assert.match(loadSource, /materialMatchShouldFinalizeRef\.current\s*=\s*true/)
  assert.match(loadSource, /materialMatchFinalizingEpochRef\.current\s*=\s*0/)
  assert.match(loadSource, /setMaterialMatchFinalizeAttempt\(0\)/)
  assert.doesNotMatch(loadSource, /technicalGapsAPI\.runDetection/)
})

test('目录 START 回查到 completed 时先刷新目录和项目再解锁', () => {
  const regenerateSource = sourceBetween('const handleRegenerateDirectory = async () => {', 'const handleStopDirectory')
  const regenerateCatch = regenerateSource.slice(regenerateSource.indexOf('} catch (e) {'))
  const recoverySource = regenerateCatch.slice(
    regenerateCatch.indexOf('if (recoverableTechnicalTaskState(recoveredPayload, requestStartedAt))'),
    regenerateCatch.indexOf('const failedState'),
  )
  const hydrateIndex = recoverySource.indexOf('technicalOutlineAPI.get(requestProjectId)')
  const ownerGuardIndex = recoverySource.indexOf('technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)', hydrateIndex)
  const applyIndex = recoverySource.indexOf('applyOutlinePayload(outlinePayload)')

  assert.match(recoverySource, /recoveredStatus\s*===\s*['"]completed['"]/)
  assert.notEqual(hydrateIndex, -1, 'completed 恢复必须重新读取最新目录')
  assert.match(recoverySource, /technicalProjectsAPI\.get\(requestProjectId\)/)
  assert.ok(ownerGuardIndex > hydrateIndex, 'hydration 响应必须再次校验项目 owner')
  assert.ok(applyIndex > ownerGuardIndex, 'owner 校验后才能应用最新目录')
  assert.match(recoverySource, /setCurrentStage\(/)
})

test('目录 START recovered completed hydration 失败时保存终态并进入可重试错误页', () => {
  const regenerateSource = sourceBetween('const handleRegenerateDirectory = async () => {', 'const handleStopDirectory')
  const recoverySource = regenerateSource.slice(
    regenerateSource.indexOf('if (recoverableTechnicalTaskState(recoveredPayload, requestStartedAt))'),
    regenerateSource.indexOf('const failedState'),
  )
  const hydrateIndex = recoverySource.indexOf('technicalOutlineAPI.get(requestProjectId)')
  const stateIndex = recoverySource.indexOf('setDirectoryState(recoveredState)')
  const taskIndex = recoverySource.indexOf("updateTechnicalTask('outline-regenerate', requestProjectId")
  const hydrationCatch = recoverySource.slice(recoverySource.indexOf('} catch (hydrationError) {'))

  assert.ok(stateIndex >= 0 && stateIndex < hydrateIndex, 'hydration 前必须保存 recovered terminal 页面状态')
  assert.ok(taskIndex >= 0 && taskIndex < hydrateIndex, 'hydration 前必须保存 recovered terminal 后台任务状态')
  assert.match(hydrationCatch, /technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)/)
  assert.match(hydrationCatch, /setError\(/)
  assert.match(outlineSource, /if \(error\)[\s\S]*?<PageError[\s\S]*?onRetry=\{loadData\}/)
})

test('目录 START 回查采纳 cancel_requested 时恢复停止标记，其他状态清理标记', () => {
  const regenerateSource = sourceBetween('const handleRegenerateDirectory = async () => {', 'const handleStopDirectory')
  const recoverySource = regenerateSource.slice(
    regenerateSource.indexOf('if (recoverableTechnicalTaskState(recoveredPayload, requestStartedAt))'),
    regenerateSource.indexOf('const failedState'),
  )

  assert.match(recoverySource, /const recoveredStopRequested\s*=\s*recoveredStatus\s*===\s*['"]cancel_requested['"]/)
  assert.match(recoverySource, /directoryStopRequestedRef\.current\s*=\s*recoveredStopRequested/)
  assert.match(recoverySource, /setDirectoryStopping\(recoveredStopRequested\)/)
})

test('completed 写入时同步进入 finalizing，覆盖恢复、轮询和 START 响应窗口', () => {
  const applySource = sourceBetween('const applyMaterialMatchPayload', 'const loadData')
  const loadSource = sourceBetween('const loadData = useCallback(async () => {', 'const directoryRunning =')
  const shouldFinalizeIndex = loadSource.indexOf('materialMatchShouldFinalizeRef.current = true')
  const applyIndex = loadSource.indexOf('applyMaterialMatchPayload(detectionPayload, requestProjectId)')
  const pollSource = sourceBetween('const pollMaterialMatchStatus = async () => {', 'timer = window.setTimeout(pollMaterialMatchStatus, 1000)')
  const confirmSource = sourceBetween('const handleConfirm = async () => {', 'const handleStopMaterialMatch')
  const runIndex = confirmSource.indexOf('technicalGapsAPI.runDetection(requestProjectId)')

  assert.match(
    applySource,
    /incomingStatus\s*===\s*['"]completed['"]\s*&&\s*materialMatchShouldFinalizeRef\.current[\s\S]*?setMaterialMatchFinalizing\(true\)/,
  )
  assert.ok(shouldFinalizeIndex >= 0 && shouldFinalizeIndex < applyIndex, '恢复 completed 必须先建立 finalize 再 apply')
  assert.doesNotMatch(loadSource.slice(shouldFinalizeIndex, applyIndex), /setMaterialMatchFinalizing\(false\)/)
  assert.match(pollSource, /applyMaterialMatchPayload\(payload, requestProjectId\)/)
  assert.match(confirmSource.slice(runIndex), /applyMaterialMatchPayload\(payload, requestProjectId\)/)
})

test('START 回查提示区分 active 与 terminal，素材 terminal 由统一 effect 单次提示', () => {
  const regenerateSource = sourceBetween('const handleRegenerateDirectory = async () => {', 'const handleStopDirectory')
  const directoryRecovery = regenerateSource.slice(
    regenerateSource.indexOf('if (recoverableTechnicalTaskState(recoveredPayload, requestStartedAt))'),
    regenerateSource.indexOf('const failedState'),
  )
  const confirmSource = sourceBetween('const handleConfirm = async () => {', 'const handleStopMaterialMatch')
  const materialRecovery = confirmSource.slice(
    confirmSource.indexOf('if (recoverableTechnicalTaskState(recoveredPayload, requestStartedAt))'),
    confirmSource.indexOf('const failedState'),
  )

  assert.match(directoryRecovery, /recoveredStatus\s*===\s*['"]completed['"][\s\S]*?目录重新生成完成，请重新审核/)
  assert.match(directoryRecovery, /recoveredStatus\s*===\s*['"]failed['"][\s\S]*?showToast\?\.[\s\S]*?['"]error['"]/)
  assert.match(directoryRecovery, /recoveredStatus\s*===\s*['"]cancelled['"][\s\S]*?目录重新生成已停止/)
  assert.match(directoryRecovery, /else[\s\S]*?目录重新生成任务已在后台启动，已恢复进度/)
  assert.match(materialRecovery, /MATERIAL_MATCH_ACTIVE_STATUSES\.has\(recoveredStatus\)[\s\S]*?素材匹配任务已在后台启动，已恢复进度/)
  assert.equal((materialRecovery.match(/showToast\?\./g) || []).length, 1, '素材 terminal 不得在 catch 和 effect 重复提示')
})

test('确认入口在素材任务提交、运行或收口期间拒绝重复触发', () => {
  const handlerSource = sourceBetween('const handleConfirm = async () => {', 'const handleStopMaterialMatch')

  assert.match(
    handlerSource,
    /if \(directoryLocked \|\| materialMatchRunning \|\| materialMatchSubmitting \|\| materialMatchFinalizing\) return/,
  )
  assert.match(
    outlineSource,
    /disabled=\{confirming \|\| directoryLocked \|\| materialMatchRunning \|\| materialMatchSubmitting \|\| materialMatchFinalizing\}/,
  )
})

test('素材匹配仍拒绝历史终态之后的晚到 active 响应', () => {
  const applySource = sourceBetween('const applyMaterialMatchPayload', 'const loadData')

  assert.match(applySource, /MATERIAL_MATCH_TERMINAL_STATUSES\.has\(previousStatus\)/)
  assert.match(applySource, /MATERIAL_MATCH_ACTIVE_STATUSES\.has\(materialMatchStatusName\(scopedPayload\)\)/)
  assert.match(applySource, /return previous/)
})

test('恢复参数只读取后台状态，不会自动启动目录或素材匹配', () => {
  assert.match(outlineSource, /useSearchParams/)
  assert.match(outlineSource, /searchParams\.get\(\s*['"]progressTask['"]\s*\)/)
  assert.match(outlineSource, /['"]outline-regenerate['"]/)
  assert.match(outlineSource, /['"]material-match['"]/)

  const regenerateCalls = [...outlineSource.matchAll(/technicalOutlineAPI\.regenerate\(requestProjectId\)/g)]
  const detectionCalls = [...outlineSource.matchAll(/technicalGapsAPI\.runDetection\(requestProjectId\)/g)]
  assert.equal(regenerateCalls.length, 1, '恢复目录弹窗不得重新提交任务')
  assert.equal(detectionCalls.length, 1, '恢复素材匹配不得重新提交任务')
  assert.ok(regenerateCalls[0].index > outlineSource.indexOf('const handleRegenerateDirectory'))
  assert.ok(detectionCalls[0].index > outlineSource.indexOf('const handleConfirm'))
})

test('目录与素材匹配任务状态带项目 owner 并拒绝跨项目异步回写', () => {
  assert.match(outlineSource, /scopeTechnicalTaskPayload/)
  assert.match(outlineSource, /technicalTaskBelongsToProject/)
  assert.match(outlineSource, /technicalTaskResponseMatchesProject/)
  assert.match(outlineSource, /currentProjectIdRef\.current\s*=\s*String\(id\)/)
  assert.match(
    outlineSource,
    /const directoryRunning\s*=\s*technicalTaskBelongsToProject\(directoryState, id\)[\s\S]*?isDirectoryProgressRunning\(directoryState\)/,
  )
  assert.match(
    outlineSource,
    /const materialMatchRunning\s*=\s*technicalTaskBelongsToProject\(materialMatchStatus, id\)[\s\S]*?MATERIAL_MATCH_ACTIVE_STATUSES\.has/,
  )
  assert.match(
    outlineSource,
    /if \(!technicalTaskBelongsToProject\(directoryState, id\) \|\| !directoryState\?\.status\) return/,
  )
  assert.match(
    outlineSource,
    /if \(!technicalTaskBelongsToProject\(materialMatchStatus, id\) \|\| !materialMatchStatus\?\.status\) return/,
  )
  assert.match(
    outlineSource,
    /if \(!technicalTaskBelongsToProject\(materialMatchStatus, id\)\) return undefined[\s\S]*?MATERIAL_MATCH_TERMINAL_STATUSES/,
  )
  assert.match(
    outlineSource,
    /technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)/,
  )
})

test('切换项目先清空任务 UI 状态和任务 refs 再加载新项目', () => {
  const resetStart = outlineSource.indexOf('setDirectoryState(null)')
  const loadStart = outlineSource.indexOf('const loadData', resetStart)
  assert.ok(resetStart >= 0 && loadStart > resetStart, '任务状态重置 effect 必须声明在 loadData 前')
  const resetSource = outlineSource.slice(resetStart, loadStart)
  assert.match(resetSource, /setMaterialMatchStatus\(null\)/)
  assert.match(resetSource, /setRegenerationModalOpen\(false\)/)
  assert.match(resetSource, /setMaterialMatchModalOpen\(false\)/)
  assert.match(resetSource, /setDirectoryStopping\(false\)/)
  assert.match(resetSource, /setMaterialMatchStopping\(false\)/)
  assert.match(resetSource, /setMaterialMatchSubmitting\(false\)/)
  assert.match(resetSource, /setConfirming\(false\)/)
  assert.match(resetSource, /setRegenerating\(false\)/)
  assert.match(resetSource, /setRegenerationPendingState\(null\)/)
  assert.match(resetSource, /directoryStopRequestedRef\.current\s*=\s*false/)
  assert.match(resetSource, /materialMatchStopRequestedRef\.current\s*=\s*false/)
  assert.match(resetSource, /materialMatchEpochRef\.current\s*=\s*0/)
  assert.match(resetSource, /materialMatchTerminalHandledRef\.current\s*=\s*0/)
  assert.match(resetSource, /materialMatchShouldFinalizeRef\.current\s*=\s*false/)
  assert.match(resetSource, /materialMatchFinalizingEpochRef\.current\s*=\s*0/)
  assert.match(resetSource, /setMaterialMatchFinalizeAttempt\(0\)/)
  assert.match(resetSource, /\}, \[id\]\)/)
})

test('同项目加载才合并旧目录进度，素材状态写入 owner', () => {
  const loadSource = sourceBetween('const loadData', 'const directoryRunning')
  assert.match(
    loadSource,
    /technicalTaskBelongsToProject\(previous, requestProjectId\) \? previous : null/,
  )
  assert.match(loadSource, /scopeTechnicalTaskPayload\([\s\S]*?generationPayload/)
  assert.match(loadSource, /applyMaterialMatchPayload\(detectionPayload, requestProjectId\)/)
})

test('项目切换首帧在操作区渲染前阻止显示旧项目目录', () => {
  assert.match(outlineSource, /const \[loadedProjectId, setLoadedProjectId\] = useState\(['"]['"]\)/)
  const loadingGuardIndex = outlineSource.indexOf('if (loading || loadedProjectId !== id)')
  const pageHeaderIndex = outlineSource.indexOf('<PageHeader')
  const saveHandlerIndex = outlineSource.indexOf('const handleSave')

  assert.notEqual(loadingGuardIndex, -1, '必须按已加载项目 ID 守住切换后的首帧')
  assert.ok(loadingGuardIndex < pageHeaderIndex, '加载 guard 必须位于操作 UI 前')
  assert.ok(loadingGuardIndex > saveHandlerIndex, '加载 guard 应在 hooks 与事件处理器声明完成后执行')
})

test('项目切换同步清空旧项目内容且加载收口标记对应项目', () => {
  const resetStart = outlineSource.indexOf('setDirectoryState(null)')
  const loadStart = outlineSource.indexOf('const loadData', resetStart)
  const resetSource = outlineSource.slice(resetStart, loadStart)
  const loadSource = sourceBetween('const loadData', 'const directoryRunning')

  assert.match(resetSource, /setLoading\(true\)/)
  assert.match(resetSource, /setLoadedProjectId\(['"]['"]\)/)
  assert.match(resetSource, /setNodes\(\[\]\)/)
  assert.match(resetSource, /setActiveNodeId\(['"]['"]\)/)
  assert.match(resetSource, /setDirty\(false\)/)
  assert.match(resetSource, /setProjectName\(id\)/)
  assert.match(resetSource, /setReviewStatus\(['"]draft['"]\)/)
  assert.match(
    loadSource,
    /technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)[\s\S]*?setLoadedProjectId\(requestProjectId\)/,
  )
  assert.match(
    loadSource,
    /catch \(e\)[\s\S]*?technicalTaskResponseMatchesProject\(requestProjectId, currentProjectIdRef\.current\)[\s\S]*?setLoadedProjectId\(requestProjectId\)/,
  )
})

test('关闭两个进度弹窗都只隐藏弹窗，不会隐式取消任务', () => {
  const directoryClose = outlineSource.match(/onClose=\{\(\) => setRegenerationModalOpen\(false\)\}/)?.[0] || ''
  const materialClose = outlineSource.match(/onClose=\{\(\) => setMaterialMatchModalOpen\(false\)\}/)?.[0] || ''
  assert.ok(directoryClose)
  assert.ok(materialClose)
  assert.doesNotMatch(directoryClose, /cancel/)
  assert.doesNotMatch(materialClose, /cancel/)
})

test('目录和素材匹配取消态明确显示已停止而非完成或失败', () => {
  assert.match(outlineSource, /state\?\.status\s*===\s*['"]cancelled['"]/)
  assert.match(outlineSource, /目录重新生成已停止/)
  assert.match(materialModalSource, /rawStatus\s*===\s*['"]cancelled['"]/)
  assert.match(materialModalSource, /素材匹配已停止/)
  assert.match(materialModalSource, /tone=\{[\s\S]*?['"]neutral['"]/)
})
