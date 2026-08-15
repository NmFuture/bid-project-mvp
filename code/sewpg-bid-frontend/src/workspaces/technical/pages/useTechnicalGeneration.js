import { useCallback, useEffect, useState } from 'react'
import { technicalGenerateAPI, technicalStagesAPI } from '../../../api'
import { projectRoute } from '../../../utils/workspace'
import { subscribeTechnicalGenerationStatus } from '../technicalGenerationStatusPolling'

// 技术标正文生成族 hook（从 TechnicalGapRecognition.jsx 第二轮拆分抽出）：
// 生成状态加载与运行期订阅、生成进度弹窗开关（允许关掉且不被重新弹出）、
// 生成入口与「进入共创导出」晋级。
export const useTechnicalGeneration = ({
  projectId,
  hasTechnicalGapPlan,
  busyAction,
  setBusyAction,
  showToast,
  navigate,
  workspaceSlug,
}) => {
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationModalOpen, setGenerationModalOpen] = useState(false)
  // 生成在后台跑，弹窗允许关掉；关掉后不因为「还在运行」被重新弹出来。
  const [generationModalDismissed, setGenerationModalDismissed] = useState(false)

  const generationRunning = generationStatus?.status === 'running'
  const generationCompleted = generationStatus?.status === 'completed'

  const loadGenerationStatus = useCallback(async () => {
    try {
      const payload = await technicalGenerateAPI.status(projectId)
      setGenerationStatus(payload)
      return payload
    } catch {
      return null
    }
  }, [projectId])

  useEffect(() => {
    if (!generationRunning) return undefined
    return subscribeTechnicalGenerationStatus({
      fetchStatus: () => technicalGenerateAPI.status(projectId),
      onStatus: setGenerationStatus,
    })
  }, [generationRunning, projectId])

  const closeGenerationModal = () => {
    setGenerationModalDismissed(true)
    setGenerationModalOpen(false)
  }

  const runTechnicalAssembly = async () => {
    if (busyAction) return
    if (!hasTechnicalGapPlan) {
      showToast?.('素材匹配完成后可生成技术标正文。', 'error')
      return
    }
    setBusyAction('technical-generate')
    setGenerationModalDismissed(false)
    setGenerationModalOpen(true)
    try {
      const payload = await technicalGenerateAPI.run(projectId)
      setGenerationStatus(payload)
      showToast?.(payload?.message || '已开始生成技术标正文。')
    } catch (e) {
      setGenerationModalOpen(false)
      showToast?.(e?.message || '生成技术标正文失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const advanceToTechnicalEditor = async () => {
    if (busyAction) return
    if (!generationCompleted) {
      showToast?.('请先完成技术标正文生成，再进入共创导出。', 'error')
      return
    }
    setBusyAction('advance-technical-editor')
    try {
      await technicalStagesAPI.update(projectId, 4, { status: 'completed', allowUnconfirmedTechnicalGap: true })
      showToast?.('已进入共创导出。')
      navigate(projectRoute(projectId, '/editor', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入共创导出失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  return {
    generationStatus,
    generationModalOpen,
    generationModalDismissed,
    generationRunning,
    generationCompleted,
    loadGenerationStatus,
    closeGenerationModal,
    runTechnicalAssembly,
    advanceToTechnicalEditor,
  }
}
