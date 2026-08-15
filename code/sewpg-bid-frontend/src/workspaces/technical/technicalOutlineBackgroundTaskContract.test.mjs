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
  assert.match(outlineSource, /technicalDirectoryAPI\.cancel\(id\)/)
  assert.match(outlineSource, /const handleStopMaterialMatch/)
  assert.match(outlineSource, /technicalGapsAPI\.cancelDetection\(id\)/)
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
  const runIndex = handlerSource.indexOf('technicalGapsAPI.runDetection(id)')
  assert.notEqual(runIndex, -1)
  assert.doesNotMatch(handlerSource.slice(runIndex), /technicalStagesAPI\.update/)
  assert.doesNotMatch(handlerSource.slice(runIndex), /navigate\(/)

  assert.match(outlineSource, /technicalGapsAPI\.detectionStatus\(id\)/)
  assert.match(
    outlineSource,
    /materialMatchTerminalHandledRef\.current\s*=\s*epoch[\s\S]*?status\s*===\s*['"]cancelled['"][\s\S]*?status\s*===\s*['"]failed['"][\s\S]*?technicalStagesAPI\.update[\s\S]*?navigate\(/,
  )
})

test('恢复参数只读取后台状态，不会自动启动目录或素材匹配', () => {
  assert.match(outlineSource, /useSearchParams/)
  assert.match(outlineSource, /searchParams\.get\(\s*['"]progressTask['"]\s*\)/)
  assert.match(outlineSource, /['"]outline-regenerate['"]/)
  assert.match(outlineSource, /['"]material-match['"]/)

  const regenerateCalls = [...outlineSource.matchAll(/technicalOutlineAPI\.regenerate\(id\)/g)]
  const detectionCalls = [...outlineSource.matchAll(/technicalGapsAPI\.runDetection\(id\)/g)]
  assert.equal(regenerateCalls.length, 1, '恢复目录弹窗不得重新提交任务')
  assert.equal(detectionCalls.length, 1, '恢复素材匹配不得重新提交任务')
  assert.ok(regenerateCalls[0].index > outlineSource.indexOf('const handleRegenerateDirectory'))
  assert.ok(detectionCalls[0].index > outlineSource.indexOf('const handleConfirm'))
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
