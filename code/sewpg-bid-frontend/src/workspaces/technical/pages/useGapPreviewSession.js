import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { technicalMaterialsAPI, technicalParseAPI } from '../../../api'
import { isEditableArtifactChoice, previewChoicesForItem } from './technicalGapRecognitionHelpers'
import { isSameArtifactPreviewSession, resolveGapPreviewChoice } from './technicalGapPreviewChoice'

// 预览族状态 hook（从 TechnicalGapRecognition.jsx 抽出）：
// 预览选项/key、OnlyOffice 会话（结果 + 参考稿）、手工构造的预览项、弹窗开关，
// 以及两个伴随 effect——会话加载（带 documentKey 防重载）与可编辑产物打开时的静默数据轮询。
export const useGapPreviewSession = ({ projectId, items, selected, onSilentReload }) => {
  const [previewChoiceKey, setPreviewChoiceKey] = useState('')
  const [previewSession, setPreviewSession] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  // 预览 session 的实时引用：静默轮询刷新数据后判断产物 documentKey 是否真的变了，
  // 没变就不重载编辑器，避免打断正在进行的在线编辑。
  const previewSessionRef = useRef(null)
  const [referencePreviewSession, setReferencePreviewSession] = useState(null)
  const [referencePreviewLoading, setReferencePreviewLoading] = useState(false)
  const [referencePreviewError, setReferencePreviewError] = useState('')
  const [manualPreviewChoice, setManualPreviewChoice] = useState(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  const selectedPreviewChoices = useMemo(
    () => previewChoicesForItem(selected, items),
    [items, selected],
  )
  const {
    selected: selectedPreviewChoice,
    visible: visiblePreviewChoices,
    comparison: previewComparison,
  } = useMemo(
    () => resolveGapPreviewChoice({
      choices: selectedPreviewChoices,
      manualPreviewChoice,
      selectedId: selected?.id,
      previewChoiceKey,
    }),
    [selectedPreviewChoices, manualPreviewChoice, selected?.id, previewChoiceKey],
  )

  useEffect(() => {
    let cancelled = false
    const sessionForChoice = async (choice) => {
      if (choice.kind === 'artifact') {
        return {
          onlyoffice: choice.artifact?.onlyoffice,
          fileName: choice.title,
          source: 'artifact',
          artifactId: String(choice.artifact?.id || ''),
        }
      }
      return choice.kind === 'appendix'
        ? technicalParseAPI.appendixPreview(projectId, choice.blankSource.id)
        : technicalMaterialsAPI.raw.previewCleanedFile(choice.material.id)
    }

    const loadSelectedPreview = async () => {
      setPreviewLoading(true)
      try {
        const payload = await sessionForChoice(selectedPreviewChoice)
        if (!cancelled) setPreviewSession(payload)
      } catch (e) {
        if (!cancelled) setPreviewError(e?.message || '预览加载失败')
      } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    }

    const loadReferencePreview = async () => {
      if (!previewComparison?.reference) return
      setReferencePreviewLoading(true)
      try {
        const payload = await sessionForChoice(previewComparison.reference)
        if (!cancelled) setReferencePreviewSession(payload)
      } catch (e) {
        if (!cancelled) setReferencePreviewError(e?.message || '参考稿预览加载失败')
      } finally {
        if (!cancelled) setReferencePreviewLoading(false)
      }
    }

    const loadPreviews = async () => {
      if (isSameArtifactPreviewSession(selectedPreviewChoice, previewSessionRef.current)) {
        // 同一产物同一版本（静默轮询带来的对象刷新）：不重载编辑器，避免打断在线编辑
        return
      }
      setPreviewSession(null)
      setPreviewLoading(false)
      setPreviewError('')
      setReferencePreviewSession(null)
      setReferencePreviewLoading(false)
      setReferencePreviewError('')
      if (!previewOpen || !selectedPreviewChoice) return
      await Promise.all([loadSelectedPreview(), loadReferencePreview()])
    }

    loadPreviews()
    return () => {
      cancelled = true
    }
  }, [projectId, previewComparison, previewOpen, selectedPreviewChoice])

  useEffect(() => {
    previewSessionRef.current = previewSession
  }, [previewSession])

  // 只有 AI 填写产物可在线编辑；同一会话的阶段性保存不会改变 documentKey。
  const artifactPreviewOpen = previewOpen && isEditableArtifactChoice(selectedPreviewChoice)
  useEffect(() => {
    if (!artifactPreviewOpen) return undefined
    const timer = setInterval(() => {
      onSilentReload({ silent: true })
    }, 15000)
    return () => clearInterval(timer)
  }, [artifactPreviewOpen, onSilentReload])

  // 切换目录项、AI 填写完成等场景统一复位预览选择（原主组件里多处内联的同一组 setter）。
  const resetPreviewChoice = useCallback(() => {
    setPreviewChoiceKey('')
    setPreviewSession(null)
    setPreviewError('')
    setManualPreviewChoice(null)
  }, [])

  return {
    previewChoiceKey,
    setPreviewChoiceKey,
    previewSession,
    setPreviewSession,
    previewLoading,
    previewError,
    setPreviewError,
    referencePreviewSession,
    referencePreviewLoading,
    referencePreviewError,
    manualPreviewChoice,
    setManualPreviewChoice,
    previewOpen,
    setPreviewOpen,
    selectedPreviewChoices,
    selectedPreviewChoice,
    visiblePreviewChoices,
    previewComparison,
    resetPreviewChoice,
  }
}
