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
  assert.match(
    outlineSource,
    /materialMatchTerminalHandledRef\.current\s*=\s*epoch[\s\S]*?status\s*===\s*['"]cancelled['"][\s\S]*?status\s*===\s*['"]failed['"][\s\S]*?technicalStagesAPI\.update[\s\S]*?navigate\(/,
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

  const regenerateCalls = [...outlineSource.matchAll(/technicalOutlineAPI\.regenerate\(id\)/g)]
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
