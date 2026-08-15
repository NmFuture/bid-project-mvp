import { useMemo } from 'react'
import { technicalGapsAPI } from '../../../api'
import {
  asObjectArray,
  currentResolvedArtifact,
  latestResolvedArtifact,
  technicalGapQualityFlag,
  technicalGapTagOf,
} from './technicalGapRecognitionHelpers'

// 复核队列族 hook（从 TechnicalGapRecognition.jsx 第二轮拆分抽出）：
// 待审核队列派生、队列内上一条/下一条跳转、逐条与批量复核通过、弹窗内复核通过后顶位续审。
export const useGapReviewQueue = ({
  projectId,
  items,
  selected,
  effectiveSelectedId,
  setSelectedId,
  runAction,
  busyAction,
  loadData,
  showToast,
  setPreviewChoiceKey,
  setPreviewSession,
  setPreviewError,
  setManualPreviewChoice,
  setPreviewOpen,
}) => {
  // 待审核队列：一键填完是一批产物，逐条点目录再点预览太慢，对比弹窗里直接连着审。
  const reviewQueue = useMemo(
    () => items.filter((item) => technicalGapTagOf(item, items) === 'template_review'),
    [items],
  )
  const reviewIndex = reviewQueue.findIndex((item) => item.id === effectiveSelectedId)

  // 批量复核通过：放行与否是人的决定，带未填字段的产物同样可批量定案（产品裁决 2026-08-09）。
  // 黄标条数仍在按钮 title 里点出来，让人知道自己在放过什么；口径与逐条徽标一致
  // （technicalGapQualityFlag：needs_review 或有未填字段）。
  const batchReviewables = reviewQueue
  const flaggedReviewCount = useMemo(
    () => reviewQueue.filter((item) => technicalGapQualityFlag(item)).length,
    [reviewQueue],
  )

  // 跳到队列中某一条并把它最新的 AI 产物挂到预览上。
  const jumpToReviewItem = (next) => {
    setSelectedId(next.id)
    const artifact = latestResolvedArtifact(next)
    setPreviewChoiceKey(artifact?.id ? `artifact:${String(artifact.id)}` : '')
    setPreviewSession(null)
    setPreviewError('')
    setManualPreviewChoice(null)
  }

  // 「复核通过」（产品裁决 2026-08-04 行为①）：确认全部 AI 填写产物，本条收口为已就绪素材。
  const handleReviewPassAiFill = (item) => {
    const artifact = asObjectArray(item?.resolvedArtifacts)
      .filter((entry) => currentResolvedArtifact(entry) && String(entry?.source || '') === 'ai_fill')
      .pop()
    if (!artifact?.id) return null
    return runAction(
      `review-pass:${item.id}`,
      () => technicalGapsAPI.confirmAiFillArtifact(projectId, item.id, artifact.id, { operator: '当前用户' }),
      (result) => result?.message || '复核通过，本条已定案',
    )
  }

  const handleReviewStep = (step) => {
    if (reviewQueue.length < 2) return
    const from = reviewIndex >= 0 ? reviewIndex : 0
    const next = reviewQueue[(from + step + reviewQueue.length) % reviewQueue.length]
    if (!next) return
    jumpToReviewItem(next)
  }

  // 弹窗内复核通过：定案后当前项离开待审核队列，原位置就是下一条，直接顶上继续审；
  // 审完最后一条时关掉弹窗。
  const handleReviewPassInModal = async () => {
    if (!selected) return
    const index = reviewIndex >= 0 ? reviewIndex : 0
    const result = await handleReviewPassAiFill(selected)
    if (!result) return
    const rest = reviewQueue.filter((item) => item.id !== selected.id)
    const next = rest[Math.min(index, rest.length - 1)]
    if (!next) {
      setPreviewOpen(false)
      return
    }
    jumpToReviewItem(next)
  }

  const handleBatchReviewPass = async () => {
    if (busyAction || !batchReviewables.length) return
    let passed = 0
    for (const item of batchReviewables) {
      const artifact = asObjectArray(item?.resolvedArtifacts)
        .filter((entry) => currentResolvedArtifact(entry) && String(entry?.source || '') === 'ai_fill')
        .pop()
      if (!artifact?.id) continue
      try {
        await technicalGapsAPI.confirmAiFillArtifact(projectId, item.id, artifact.id, { operator: '当前用户' })
        passed += 1
      } catch {
        // 单条失败不中断整批，最终按实际通过数提示
      }
    }
    await loadData({ silent: true })
    showToast?.(`已复核通过 ${passed}/${batchReviewables.length} 条`)
  }

  return {
    reviewQueue,
    batchReviewables,
    flaggedReviewCount,
    handleReviewStep,
    handleReviewPassAiFill,
    handleReviewPassInModal,
    handleBatchReviewPass,
  }
}
