import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { technicalDocumentAPI, technicalGenerateAPI, technicalProjectsAPI, technicalScoreIndexAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import MarkdownLite from '../../../components/shared/MarkdownLite'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import TechnicalGenerationProgressModal from '../components/TechnicalGenerationProgressModal'
import TechnicalScoreIndexProgressModal from '../components/TechnicalScoreIndexProgressModal'
import { markTechnicalTask, restoreTechnicalTask, updateTechnicalTask } from '../technicalBackgroundTasks.js'
import {
  generationDisplayPercentage,
  isGenerationProgressRunning,
  summarizeGenerationProgress,
} from '../technicalGenerationProgress.js'
import { subscribeTechnicalGenerationStatus } from '../technicalGenerationStatusPolling'
import { technicalTaskResponseMatchesProject } from '../technicalOutlineTaskLifecycle.js'
import { useTechnicalTaskPresence } from '../technicalTaskPresence.js'
import {
  isScoreIndexProgressRunning,
  scoreIndexDisplayPercentage,
  summarizeScoreIndexProgress,
} from '../technicalScoreIndexProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import Button from '../../../components/ui/Button'
import { Dialog, DialogBody, DialogFooter, DialogHeader } from '../../../components/ui/Dialog'
import IconButton from '../../../components/ui/IconButton'
import { DOCUMENT_FONT_OPTIONS } from '../../shared/fontOptions'
import {
  technicalFormatDocumentAfterApply,
  technicalFormatRequest,
  technicalFormatStateFromDocument,
} from './technicalGapRecognitionHelpers'

const technicalFormatPresets = [
  {
    key: 'standard',
    label: '标准版',
    description: '统一标题、正文、表格、目录、页眉和分页。',
  },
  {
    key: 'custom',
    label: '自定义格式',
    description: '按技术标要求设置字体、字号、页边距和目录。',
  },
]

const TECHNICAL_BID_LABEL = '技术标'
const TECHNICAL_DOCUMENT_PART_LABEL = '技术部分'
const INITIAL_TECHNICAL_CHAT_MESSAGES = [
  {
    role: 'assistant',
    content: '可在这里询问技术标内容、风险和表达建议。AI 回复仅供参考，不会自动修改 Word。',
  },
]

const DEFAULT_TECHNICAL_FORMAT_STYLE_OVERRIDES = {
  bodyZhFont: '等线',
  bodyEnFont: 'Times New Roman',
  bodySizePt: 12,
  bodyLineSpacing: 1.5,
  bodyFirstLineIndentChars: 2,
  heading1SizePt: 15,
  heading2SizePt: 14,
  heading3SizePt: 12,
  pageTopCm: 2.54,
  pageBottomCm: 2.54,
  pageLeftCm: 3.18,
  pageRightCm: 3.18,
  tableZhFont: '宋体',
  tableSizePt: 10.5,
  tableLineSpacing: 1,
  insertToc: true,
  tocPageBreakAfter: true,
  headerTextTemplate: `{projectName}投标文件-${TECHNICAL_DOCUMENT_PART_LABEL}`,
}

const triggerDownload = (url, fileName) => {
  if (!url) return false
  const link = document.createElement('a')
  link.href = url
  link.download = fileName || ''
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  return true
}

const generationTaskPatch = (status) => ({
  status: String(status?.status || 'queued').toLowerCase(),
  percentage: Math.round(generationDisplayPercentage(status || {})),
  summary: summarizeGenerationProgress(status || {}).detail,
})

const scoreIndexTaskPatch = (status) => ({
  status: String(status?.status || 'queued').toLowerCase(),
  percentage: Math.round(scoreIndexDisplayPercentage(status || {})),
  summary: summarizeScoreIndexProgress(status || {}).detail,
})

const TECHNICAL_TASK_TERMINAL_STATUSES = new Set(['completed', 'failed', 'error', 'cancelled'])

export default function TechnicalCoCreationEditor({ showToast }) {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const progressTask = searchParams.get('progressTask')
  const [projectName, setProjectName] = useState(id)
  const [data, setData] = useState(null)
  const [finalData, setFinalData] = useState(null)
  const [fallbackContent, setFallbackContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [savingFallback, setSavingFallback] = useState(false)
  const [technicalPreviewFullscreen, setTechnicalPreviewFullscreen] = useState(false)
  const [exportVersion, setExportVersion] = useState('marked')
  const [wordPreparing, setWordPreparing] = useState(false)
  const [pdfPreparing, setPdfPreparing] = useState(false)
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationOwnerId, setGenerationOwnerId] = useState('')
  const [generationModalOpen, setGenerationModalOpen] = useState(false)
  const [generationStopping, setGenerationStopping] = useState(false)
  // 生成在后台跑，弹窗允许关掉；关掉后不因为「还在运行」被重新弹出来。
  const [generationModalDismissed, setGenerationModalDismissed] = useState(false)
  const [regenerationConfirmOpen, setRegenerationConfirmOpen] = useState(false)
  const [regenerationStarting, setRegenerationStarting] = useState(false)
  const [scoreIndexStatus, setScoreIndexStatus] = useState(null)
  const [scoreIndexOwnerId, setScoreIndexOwnerId] = useState('')
  const [scoreIndexModalOpen, setScoreIndexModalOpen] = useState(false)
  const [scoreIndexStopping, setScoreIndexStopping] = useState(false)
  const [scoreIndexModalDismissed, setScoreIndexModalDismissed] = useState(false)
  const [scoreIndexStarting, setScoreIndexStarting] = useState(false)
  const scoreIndexRequestedRef = useRef(false)
  const generationStopRequestedRef = useRef(false)
  const scoreIndexStopRequestedRef = useRef(false)
  const [technicalRightTab, setTechnicalRightTab] = useState('chat')
  const [chatMessages, setChatMessages] = useState(() => [...INITIAL_TECHNICAL_CHAT_MESSAGES])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatSessionId, setChatSessionId] = useState('')
  const chatHistoryRef = useRef(null)
  const chatRequestVersionRef = useRef(0)
  const regenerationRequestedRef = useRef(false)
  const currentProjectIdRef = useRef(String(id))
  currentProjectIdRef.current = String(id)
  const [formatPreset, setFormatPreset] = useState('standard')
  const [formatApplying, setFormatApplying] = useState('')
  const [customFormat, setCustomFormat] = useState(DEFAULT_TECHNICAL_FORMAT_STYLE_OVERRIDES)

  const applyGenerationPayload = useCallback((payload, ownerId = id) => {
    const incomingStatus = String(payload?.status || '').toLowerCase()
    const active = isGenerationProgressRunning(payload)
    const ownsCurrentProject = technicalTaskResponseMatchesProject(ownerId, currentProjectIdRef.current)
    if (ownsCurrentProject && incomingStatus === 'cancel_requested') {
      generationStopRequestedRef.current = true
    }
    const nextPayload = ownsCurrentProject
      && generationStopRequestedRef.current
      && active
      && incomingStatus !== 'cancel_requested'
      ? {
          ...payload,
          status: 'cancel_requested',
          summary: '已请求停止正文重新生成，正在等待安全停止点。',
          message: '已请求停止正文重新生成，正在等待安全停止点。',
        }
      : payload
    if (ownsCurrentProject && TECHNICAL_TASK_TERMINAL_STATUSES.has(incomingStatus)) {
      generationStopRequestedRef.current = false
    }
    return nextPayload
  }, [id])

  const applyScoreIndexPayload = useCallback((payload, ownerId = id) => {
    const incomingStatus = String(payload?.status || '').toLowerCase()
    const active = isScoreIndexProgressRunning(payload)
    const ownsCurrentProject = technicalTaskResponseMatchesProject(ownerId, currentProjectIdRef.current)
    if (ownsCurrentProject && incomingStatus === 'cancel_requested') {
      scoreIndexStopRequestedRef.current = true
    }
    const nextPayload = ownsCurrentProject
      && scoreIndexStopRequestedRef.current
      && active
      && incomingStatus !== 'cancel_requested'
      ? {
          ...payload,
          status: 'cancel_requested',
          summary: '已请求停止章节索引重新生成，正在等待安全停止点。',
          message: '已请求停止章节索引重新生成，正在等待安全停止点。',
        }
      : payload
    if (ownsCurrentProject && TECHNICAL_TASK_TERMINAL_STATUSES.has(incomingStatus)) {
      scoreIndexStopRequestedRef.current = false
    }
    return nextPayload
  }, [id])

  useEffect(() => {
    // 项目切换先清空任务 UI；render 阶段的 owner gate 负责隔离切换首帧。
    setGenerationStatus(null)
    setGenerationOwnerId('')
    setGenerationModalOpen(false)
    setGenerationModalDismissed(false)
    setGenerationStopping(false)
    setRegenerationStarting(false)
    setRegenerationConfirmOpen(false)
    setScoreIndexStatus(null)
    setScoreIndexOwnerId('')
    setScoreIndexModalOpen(false)
    setScoreIndexModalDismissed(false)
    setScoreIndexStopping(false)
    setScoreIndexStarting(false)
    setProjectName(id)
    regenerationRequestedRef.current = false
    scoreIndexRequestedRef.current = false
    generationStopRequestedRef.current = false
    scoreIndexStopRequestedRef.current = false
  }, [id])

  const loadDocument = useCallback(async ({ silent = false } = {}) => {
    const requestProjectId = id
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const [payload, finalPayload, projectPayload] = await Promise.all([
        technicalDocumentAPI.get(requestProjectId),
        technicalDocumentAPI.final(requestProjectId).catch(() => null),
        technicalProjectsAPI.get(requestProjectId).catch(() => null),
      ])
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setProjectName(projectPayload?.name || requestProjectId)
      setData(payload)
      setFinalData(finalPayload)
      setFallbackContent(payload?.fallback?.content || '')
      const restoredFormat = technicalFormatStateFromDocument(payload, DEFAULT_TECHNICAL_FORMAT_STYLE_OVERRIDES)
      setFormatPreset(restoredFormat.preset)
      setCustomFormat(restoredFormat.styleOverrides)
      setOnlyofficeError('')
    } catch (e) {
      if (technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
        setError(e?.message || '技术标共创文档加载失败')
      }
    } finally {
      if (
        !silent
        && technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)
      ) setLoading(false)
    }
  }, [id])

  const loadGenerationStatus = useCallback(async () => {
    const requestProjectId = id
    try {
      const [payload, projectPayload] = await Promise.all([
        technicalGenerateAPI.status(requestProjectId),
        technicalProjectsAPI.get(requestProjectId).catch(() => null),
      ])
      const nextPayload = applyGenerationPayload(payload, requestProjectId)
      const resolvedProjectName = projectPayload?.name || requestProjectId
      const active = isGenerationProgressRunning(nextPayload)
      if (active) {
        // 正文任务全局只有一条登记：已有登记只更新进度，不把首次生成改名成重新生成。
        restoreTechnicalTask({
          taskType: 'body-generate',
          taskName: '重新生成正文',
          page: 'editor',
          projectId: requestProjectId,
          projectName: resolvedProjectName,
          ...generationTaskPatch(nextPayload),
        })
      } else {
        updateTechnicalTask('body-generate', requestProjectId, generationTaskPatch(nextPayload))
      }
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return null
      if (active) regenerationRequestedRef.current = true
      setProjectName(resolvedProjectName)
      setGenerationOwnerId(requestProjectId)
      setGenerationStatus(nextPayload)
      setGenerationStopping(String(nextPayload?.status || '').toLowerCase() === 'cancel_requested')
      if (active || progressTask === 'body-generate') {
        setGenerationModalDismissed(false)
        setGenerationModalOpen(true)
      }
      return nextPayload
    } catch {
      return null
    }
  }, [applyGenerationPayload, id, progressTask])

  const loadScoreIndexStatus = useCallback(async () => {
    const requestProjectId = id
    try {
      const [payload, projectPayload] = await Promise.all([
        technicalScoreIndexAPI.status(requestProjectId),
        technicalProjectsAPI.get(requestProjectId).catch(() => null),
      ])
      const nextPayload = applyScoreIndexPayload(payload, requestProjectId)
      const resolvedProjectName = projectPayload?.name || requestProjectId
      const active = isScoreIndexProgressRunning(nextPayload)
      if (active) {
        markTechnicalTask({
          taskType: 'index-regenerate',
          taskName: '重新生成索引',
          projectId: requestProjectId,
          projectName: resolvedProjectName,
          ...scoreIndexTaskPatch(nextPayload),
        })
      } else {
        updateTechnicalTask('index-regenerate', requestProjectId, scoreIndexTaskPatch(nextPayload))
      }
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return null
      if (active) scoreIndexRequestedRef.current = true
      setProjectName(resolvedProjectName)
      setScoreIndexOwnerId(requestProjectId)
      setScoreIndexStatus(nextPayload)
      setScoreIndexStopping(String(nextPayload?.status || '').toLowerCase() === 'cancel_requested')
      if (active || progressTask === 'index-regenerate') {
        setScoreIndexModalDismissed(false)
        setScoreIndexModalOpen(true)
      }
      return nextPayload
    } catch {
      return null
    }
  }, [applyScoreIndexPayload, id, progressTask])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadDocument()
      loadGenerationStatus()
      loadScoreIndexStatus()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadDocument, loadGenerationStatus, loadScoreIndexStatus])

  useEffect(() => {
    chatRequestVersionRef.current += 1
    setChatMessages([...INITIAL_TECHNICAL_CHAT_MESSAGES])
    setChatInput('')
    setChatLoading(false)
    setChatSessionId('')
    return () => {
      chatRequestVersionRef.current += 1
    }
  }, [id])

  useEffect(() => {
    if (!chatHistoryRef.current) return
    chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight
  }, [chatMessages, chatLoading])

  const hasOnlyOfficeSession = Boolean(data?.onlyoffice?.fileUrl && data?.onlyoffice?.callbackUrl)
  const useFallbackEditor = !hasOnlyOfficeSession || Boolean(onlyofficeError)
  const fileName = finalData?.fileName || data?.fileName || '技术标投标文件.docx'
  const bidLabel = TECHNICAL_BID_LABEL
  const defaultWordFileName = `${TECHNICAL_BID_LABEL}投标文件.docx`
  const defaultPdfFileName = `${TECHNICAL_BID_LABEL}投标文件.pdf`
  const generationBelongsToProject = generationOwnerId === id
  const scoreIndexBelongsToProject = scoreIndexOwnerId === id
  const generationRunning = generationBelongsToProject && isGenerationProgressRunning(generationStatus)
  const scoreIndexRunning = scoreIndexBelongsToProject && isScoreIndexProgressRunning(scoreIndexStatus)
  const generationModalVisible = generationBelongsToProject
    && (generationModalOpen || generationRunning)
    && !generationModalDismissed
  const scoreIndexModalVisible = scoreIndexBelongsToProject
    && (scoreIndexModalOpen || scoreIndexRunning)
    && !scoreIndexModalDismissed

  // 弹窗开着就别在右下角再挂一张同样的卡片；关掉弹窗或离开本页后才交给任务栈。
  useTechnicalTaskPresence('body-generate', id, generationModalVisible)
  useTechnicalTaskPresence('index-regenerate', id, scoreIndexModalVisible)

  useEffect(() => {
    if (!generationBelongsToProject || !generationStatus?.status) return
    updateTechnicalTask('body-generate', id, generationTaskPatch(generationStatus))
  }, [generationBelongsToProject, generationStatus, id])

  useEffect(() => {
    if (!scoreIndexBelongsToProject || !scoreIndexStatus?.status) return
    updateTechnicalTask('index-regenerate', id, scoreIndexTaskPatch(scoreIndexStatus))
  }, [id, scoreIndexBelongsToProject, scoreIndexStatus])

  useEffect(() => {
    if (!generationRunning) return undefined
    return subscribeTechnicalGenerationStatus({
      fetchStatus: () => technicalGenerateAPI.status(id),
      onStatus: (payload) => {
        const nextPayload = applyGenerationPayload(payload, id)
        if (isGenerationProgressRunning(nextPayload)) regenerationRequestedRef.current = true
        setGenerationOwnerId(id)
        setGenerationStatus(nextPayload)
        setGenerationStopping(String(nextPayload?.status || '').toLowerCase() === 'cancel_requested')
      },
    })
  }, [applyGenerationPayload, generationRunning, id])

  useEffect(() => {
    if (!generationBelongsToProject) return
    if (generationStatus?.status === 'cancelled') {
      regenerationRequestedRef.current = false
      return
    }
    if (generationStatus?.status === 'failed') {
      regenerationRequestedRef.current = false
      return
    }
    if (generationStatus?.status !== 'completed' || !regenerationRequestedRef.current) return
    regenerationRequestedRef.current = false
    loadDocument({ silent: true })
    showToast?.('技术标正文已重新生成，当前文档已刷新。')
  }, [generationBelongsToProject, generationStatus?.status, loadDocument, showToast])

  useEffect(() => {
    if (!scoreIndexRunning) return undefined
    return subscribeTechnicalGenerationStatus({
      fetchStatus: () => technicalScoreIndexAPI.status(id),
      onStatus: (payload) => {
        const nextPayload = applyScoreIndexPayload(payload, id)
        if (isScoreIndexProgressRunning(nextPayload)) scoreIndexRequestedRef.current = true
        setScoreIndexOwnerId(id)
        setScoreIndexStatus(nextPayload)
        setScoreIndexStopping(String(nextPayload?.status || '').toLowerCase() === 'cancel_requested')
      },
    })
  }, [applyScoreIndexPayload, scoreIndexRunning, id])

  useEffect(() => {
    if (!scoreIndexBelongsToProject) return
    if (scoreIndexStatus?.status === 'cancelled') {
      scoreIndexRequestedRef.current = false
      return
    }
    if (scoreIndexStatus?.status === 'failed') {
      // 只对本次会话发起的任务提示；页面加载时读到的历史失败态不该再弹一次。
      if (scoreIndexRequestedRef.current) {
        showToast?.('章节索引重新生成失败，当前成稿未被修改。', 'error')
      }
      scoreIndexRequestedRef.current = false
      return
    }
    if (scoreIndexStatus?.status !== 'completed' || !scoreIndexRequestedRef.current) return
    scoreIndexRequestedRef.current = false
    // 索引跳过时后端没换文件，重载只会白刷一次预览，因此只在真的改了成稿时刷新。
    if (!scoreIndexStatus?.output?.applied) return
    loadDocument({ silent: true })
    showToast?.('章节索引已重新生成，当前文档已刷新。')
  }, [scoreIndexBelongsToProject, scoreIndexStatus?.status, scoreIndexStatus?.output?.applied, loadDocument, showToast])

  useEffect(() => {
    if (!technicalPreviewFullscreen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setTechnicalPreviewFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [technicalPreviewFullscreen])

  const handleSaveFallback = async () => {
    const content = fallbackContent.trim()
    if (!content) {
      showToast?.('文档内容不能为空', 'error')
      return
    }

    setSavingFallback(true)
    try {
      const response = await technicalDocumentAPI.save(id, { content })
      setData(response?.payload || data)
      showToast?.('技术标文档已保存并回写')
    } catch (e) {
      showToast?.(e?.message || '保存失败，请稍后重试', 'error')
    } finally {
      setSavingFallback(false)
    }
  }

  const handleTechnicalChat = async () => {
    const message = chatInput.trim()
    if (!message || chatLoading) return
    const requestVersion = ++chatRequestVersionRef.current

    setChatMessages((current) => [...current, { role: 'user', content: message }])
    setChatInput('')
    setChatLoading(true)
    try {
      const response = await technicalDocumentAPI.technicalChat(id, {
        message,
        sessionId: chatSessionId,
      })
      if (requestVersion !== chatRequestVersionRef.current) return
      const modelLabel = response?.providerId && response?.modelId
        ? `${response.providerId}/${response.modelId}`
        : ''
      if (response?.sessionId) setChatSessionId(response.sessionId)
      setChatMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: response?.reply || '未返回有效建议。',
          fallbackModelUsed: Boolean(response?.fallbackModelUsed),
          modelLabel,
        },
      ])
      if (response?.fallbackModelUsed) {
        showToast?.(`系统设置模型不可用，已使用 ${modelLabel || 'opencode 默认模型'} 完成回复。`, 'warning')
      }
    } catch (e) {
      if (requestVersion !== chatRequestVersionRef.current) return
      setChatMessages((current) => [
        ...current,
        { role: 'assistant', content: e?.message || 'AI 对话失败，请稍后重试。', error: true },
      ])
      showToast?.(e?.message || 'AI 对话失败', 'error')
    } finally {
      if (requestVersion === chatRequestVersionRef.current) setChatLoading(false)
    }
  }

  const handleNewTechnicalChat = () => {
    if (chatLoading) return
    chatRequestVersionRef.current += 1
    setChatSessionId('')
    setChatInput('')
    setChatLoading(false)
    setChatMessages([])
  }

  const handleDownloadWord = async () => {
    if (wordPreparing) return
    setWordPreparing(true)
    try {
      const response = await technicalDocumentAPI.final(id, exportVersion)
      const downloaded = triggerDownload(response?.fileUrl, response?.fileName || defaultWordFileName)
      showToast?.(downloaded ? `${exportVersion === 'clean' ? '清洁版' : '标记版'} Word 已开始下载` : 'Word 已准备完成')
    } catch (e) {
      showToast?.(e?.message || 'Word 下载失败', 'error')
    } finally {
      setWordPreparing(false)
    }
  }

  const handlePreparePdf = async () => {
    if (pdfPreparing) return
    setPdfPreparing(true)
    try {
      const response = await technicalDocumentAPI.finalPdf(id, exportVersion)
      const downloaded = triggerDownload(response?.fileUrl, response?.fileName || defaultPdfFileName)
      showToast?.(downloaded ? 'PDF 已生成并开始下载' : (response?.message || 'PDF 已生成'))
    } catch (e) {
      showToast?.(e?.message || 'PDF 生成失败', 'error')
    } finally {
      setPdfPreparing(false)
    }
  }

  const handleRegenerateScoreIndex = async () => {
    if (scoreIndexStarting || scoreIndexRunning || generationRunning) return
    const requestProjectId = id
    const queuedStatus = {
      status: 'queued',
      percentage: 0,
      summary: '正在准备重新生成章节索引。',
      startedAt: new Date().toISOString(),
    }
    markTechnicalTask({
      taskType: 'index-regenerate',
      taskName: '重新生成索引',
      projectId: requestProjectId,
      projectName: projectName || requestProjectId,
      ...scoreIndexTaskPatch(queuedStatus),
      status: 'queued',
    })
    setTechnicalPreviewFullscreen(false)
    setScoreIndexStarting(true)
    setScoreIndexOwnerId(requestProjectId)
    setScoreIndexStatus(queuedStatus)
    setScoreIndexStopping(false)
    // 新任务重置上一轮停止请求标记，否则上一轮的「停止中」会盖住这一轮的运行态。
    scoreIndexStopRequestedRef.current = false
    setScoreIndexModalDismissed(false)
    setScoreIndexModalOpen(true)
    scoreIndexRequestedRef.current = true
    try {
      let payload = await technicalScoreIndexAPI.run(requestProjectId)
      if (payload?.error) throw new Error(payload.error)
      payload = applyScoreIndexPayload(payload, requestProjectId)
      updateTechnicalTask('index-regenerate', requestProjectId, scoreIndexTaskPatch(payload))
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setScoreIndexOwnerId(requestProjectId)
      setScoreIndexStatus(payload)
      setScoreIndexStopping(String(payload?.status || '').toLowerCase() === 'cancel_requested')
      showToast?.(payload?.message || '已开始重新生成章节索引。')
    } catch (e) {
      updateTechnicalTask('index-regenerate', requestProjectId, {
        status: 'failed',
        summary: e?.message || '重新生成章节索引失败',
      })
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      scoreIndexRequestedRef.current = false
      setScoreIndexStatus({ ...queuedStatus, status: 'failed', error: e?.message || '重新生成章节索引失败' })
      setScoreIndexModalOpen(false)
      showToast?.(e?.message || '重新生成章节索引失败', 'error')
    } finally {
      if (technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
        setScoreIndexStarting(false)
      }
    }
  }

  const handleRequestRegenerate = () => {
    // 两条链路都以成稿为最终产物，不能并行；后端也会 409 拦一次。
    if (regenerationStarting || generationRunning || scoreIndexRunning) return
    setTechnicalPreviewFullscreen(false)
    setRegenerationConfirmOpen(true)
  }

  const handleConfirmRegenerate = async () => {
    if (regenerationStarting || generationRunning || scoreIndexRunning) return
    const requestProjectId = id
    const queuedStatus = {
      status: 'queued',
      percentage: 0,
      summary: '正在准备重新生成技术标正文。',
      startedAt: new Date().toISOString(),
    }
    markTechnicalTask({
      taskType: 'body-generate',
      taskName: '重新生成正文',
      page: 'editor',
      projectId: requestProjectId,
      projectName: projectName || requestProjectId,
      ...generationTaskPatch(queuedStatus),
      status: 'queued',
    })
    setRegenerationConfirmOpen(false)
    setRegenerationStarting(true)
    setGenerationOwnerId(requestProjectId)
    setGenerationStatus(queuedStatus)
    setGenerationStopping(false)
    // 新任务重置上一轮停止请求标记，否则上一轮的「停止中」会盖住这一轮的运行态。
    generationStopRequestedRef.current = false
    setGenerationModalDismissed(false)
    setGenerationModalOpen(true)
    regenerationRequestedRef.current = true
    try {
      let payload = await technicalGenerateAPI.run(requestProjectId)
      if (payload?.error) throw new Error(payload.error)
      payload = applyGenerationPayload(payload, requestProjectId)
      updateTechnicalTask('body-generate', requestProjectId, generationTaskPatch(payload))
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setGenerationOwnerId(requestProjectId)
      setGenerationStatus(payload)
      setGenerationStopping(String(payload?.status || '').toLowerCase() === 'cancel_requested')
      showToast?.(payload?.message || '已开始重新生成技术标正文。')
    } catch (e) {
      updateTechnicalTask('body-generate', requestProjectId, {
        status: 'failed',
        summary: e?.message || '重新生成技术标正文失败',
      })
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      regenerationRequestedRef.current = false
      setGenerationStatus({ ...queuedStatus, status: 'failed', error: e?.message || '重新生成技术标正文失败' })
      setGenerationModalOpen(false)
      showToast?.(e?.message || '重新生成技术标正文失败', 'error')
    } finally {
      if (technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
        setRegenerationStarting(false)
      }
    }
  }

  const handleStopGeneration = async () => {
    if (!generationRunning || generationStopping) return
    const requestProjectId = id
    generationStopRequestedRef.current = true
    setGenerationStopping(true)
    try {
      let payload = await technicalGenerateAPI.cancel(requestProjectId)
      if (payload?.error) throw new Error(payload.error)
      payload = applyGenerationPayload(payload, requestProjectId)
      updateTechnicalTask('body-generate', requestProjectId, generationTaskPatch(payload))
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setGenerationOwnerId(requestProjectId)
      setGenerationStatus(payload)
      setGenerationStopping(String(payload?.status || '').toLowerCase() === 'cancel_requested')
      showToast?.(payload?.message || '已请求停止正文重新生成。')
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      generationStopRequestedRef.current = false
      setGenerationStopping(false)
      showToast?.(e?.message || '停止正文重新生成失败，请稍后重试', 'error')
    }
  }

  const handleStopScoreIndex = async () => {
    if (!scoreIndexRunning || scoreIndexStopping) return
    const requestProjectId = id
    scoreIndexStopRequestedRef.current = true
    setScoreIndexStopping(true)
    try {
      let payload = await technicalScoreIndexAPI.cancel(requestProjectId)
      if (payload?.error) throw new Error(payload.error)
      payload = applyScoreIndexPayload(payload, requestProjectId)
      updateTechnicalTask('index-regenerate', requestProjectId, scoreIndexTaskPatch(payload))
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setScoreIndexOwnerId(requestProjectId)
      setScoreIndexStatus(payload)
      setScoreIndexStopping(String(payload?.status || '').toLowerCase() === 'cancel_requested')
      showToast?.(payload?.message || '已请求停止章节索引重新生成。')
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      scoreIndexStopRequestedRef.current = false
      setScoreIndexStopping(false)
      showToast?.(e?.message || '停止章节索引重新生成失败，请稍后重试', 'error')
    }
  }

  const handleApplyTechnicalFormat = async (preset = formatPreset) => {
    if (formatApplying) return
    setFormatApplying(preset)
    try {
      const payload = technicalFormatRequest(preset, customFormat)
      const response = await technicalDocumentAPI.technicalFormat(id, payload)
      const nextDocument = technicalFormatDocumentAfterApply(
        data,
        preset,
        customFormat,
        response?.payload?.document || response?.document,
      )
      setData(nextDocument)
      const restoredFormat = technicalFormatStateFromDocument(nextDocument, customFormat)
      setFormatPreset(restoredFormat.preset)
      setCustomFormat(restoredFormat.styleOverrides)
      setFinalData(await technicalDocumentAPI.final(id).catch(() => finalData))
      setOnlyofficeError('')
      showToast?.(response?.message || '技术标格式已切换')
    } catch (e) {
      showToast?.(e?.message || '技术标格式切换失败', 'error')
    } finally {
      setFormatApplying('')
    }
  }

  const updateCustomFormat = (field, value) => {
    setCustomFormat((current) => ({ ...current, [field]: value }))
  }

  const updateCustomNumber = (field, value) => {
    const parsed = Number(value)
    setCustomFormat((current) => ({ ...current, [field]: Number.isFinite(parsed) ? parsed : '' }))
  }

  const renderFormatNumberInput = (field, label, props = {}) => (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-on-surface-variant">{label}</span>
      <input
        type="number"
        value={customFormat[field]}
        min={props.min}
        max={props.max}
        step={props.step || 0.1}
        onChange={(event) => updateCustomNumber(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
    </label>
  )

  const renderFormatFontSelect = (field, label, options) => (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-on-surface-variant">{label}</span>
      <select
        value={customFormat[field] || options[0]?.value || ''}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  )

  const renderFormatTextInput = (field, label, props = {}) => (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold text-on-surface-variant">{label}</span>
      <input
        type="text"
        value={customFormat[field] || ''}
        onChange={(event) => updateCustomFormat(field, event.target.value)}
        className="h-9 w-full rounded-md border border-surface-container-high bg-white px-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
        {...props}
      />
    </label>
  )

  const renderDocumentEditor = (minHeight = '740px') => {
    const minHeightClass = minHeight === '740px'
      ? 'min-h-[30rem] xl:min-h-0'
      : minHeight === '690px'
        ? 'min-h-[28rem] xl:min-h-0'
        : 'min-h-[26rem] xl:min-h-0'
    return (
      <>
        <div className={useFallbackEditor ? 'hidden' : 'min-h-0 flex-1'}>
          <OnlyOfficeEmbed
            session={data?.onlyoffice}
            className={`h-full ${minHeightClass} w-full rounded-md border border-outline-variant bg-white`}
            onReady={() => setOnlyofficeError('')}
            onError={(message) => setOnlyofficeError(message || 'OnlyOffice 文档加载失败，已切换到文本兜底。')}
          />
        </div>

        <div className={useFallbackEditor ? 'flex min-h-0 flex-1 flex-col gap-3' : 'hidden'}>
          <textarea
            value={fallbackContent}
            onChange={(event) => setFallbackContent(event.target.value)}
            className={`${minHeightClass} flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-3 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30`}
          />
          <div className="flex justify-end">
            <Button variant="primary" onClick={handleSaveFallback} disabled={savingFallback}>
              {savingFallback ? '保存中...' : '保存回写'}
            </Button>
          </div>
        </div>
      </>
    )
  }

  const renderTechnicalChatPanel = () => (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-4">
        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-surface-container-high bg-white">
          <div className="flex shrink-0 items-center justify-between gap-3 border-b border-surface-container-high px-3 py-2">
            <div className="text-sm font-semibold text-on-surface">通用 AI 对话</div>
            <button
              type="button"
              onClick={handleNewTechnicalChat}
              disabled={chatLoading}
              className="rounded px-2 py-1 text-xs font-semibold text-primary hover:bg-primary/10 disabled:opacity-50"
            >新对话</button>
          </div>
          <div ref={chatHistoryRef} role="log" aria-live="polite" className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 pr-2">
            {chatMessages.length === 0 && (
              <div className="px-3 py-8 text-center text-xs leading-5 text-on-surface-variant">
                已开始新对话。输入问题后将创建新的 AI 会话。
              </div>
            )}
            {chatMessages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={`rounded-lg px-3 py-2 text-sm leading-6 ${message.role === 'user' ? 'ml-8 bg-primary text-on-primary' : message.error ? 'mr-8 bg-error/10 text-error' : 'mr-8 bg-surface-container-low text-on-surface'}`}
              >
                <div className="mb-1 text-xs font-semibold opacity-70">
                  {message.role === 'user' ? '我' : message.fallbackModelUsed ? `AI助手（${message.modelLabel || '默认模型'}）` : 'AI助手'}
                </div>
                {message.role === 'assistant' && !message.error ? (
                  <MarkdownLite content={message.content} compact />
                ) : (
                  <div className="whitespace-pre-wrap break-words">{message.content}</div>
                )}
              </div>
            ))}
            {chatLoading && (
              <div className="mr-8 rounded-lg bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">
                AI 正在生成建议...
              </div>
            )}
          </div>
        </section>

      </div>

      <div className="border-t border-surface-container-high bg-surface-container-low p-3">
        <textarea
          aria-label="技术标 AI 对话输入"
          value={chatInput}
          onChange={(event) => setChatInput(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
              event.preventDefault()
              handleTechnicalChat()
            }
          }}
          placeholder="输入技术标问题或修改建议。Ctrl/⌘ + Enter 发送。"
          className="min-h-[96px] w-full resize-none rounded-md border border-surface-container-high bg-white px-3 py-2 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        <div className="mt-2 flex items-center justify-end">
          <button
            type="button"
            onClick={handleTechnicalChat}
            disabled={chatLoading || !chatInput.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
          >发送给AI</button>
        </div>
      </div>
    </>
  )

  const renderTechnicalFormatPanel = () => (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-1 gap-2">
          {technicalFormatPresets.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => setFormatPreset(preset.key)}
              className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${formatPreset === preset.key ? 'border-primary bg-primary/10 text-primary' : 'border-surface-container-high bg-white text-on-surface hover:bg-surface-container-low'}`}
            >
              <span className="block text-sm font-semibold">{preset.label}</span>
              <span className="mt-0.5 block text-xs text-on-surface-variant">{preset.description}</span>
            </button>
          ))}
        </div>

        {formatPreset === 'custom' && (
          <div className="mt-4 space-y-4 rounded-md border border-surface-container-high bg-white p-3">
            <div>
              <div className="text-sm font-semibold text-on-surface">正文格式</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatFontSelect('bodyZhFont', '中文字体', DOCUMENT_FONT_OPTIONS.zh)}
                {renderFormatFontSelect('bodyEnFont', '英文字体', DOCUMENT_FONT_OPTIONS.en)}
                {renderFormatNumberInput('bodySizePt', '正文字号 pt', { min: 8, max: 22, step: 0.5 })}
                {renderFormatNumberInput('bodyLineSpacing', '正文行距', { min: 1, max: 3, step: 0.05 })}
                {renderFormatNumberInput('bodyFirstLineIndentChars', '首行缩进字符', { min: 0, max: 4, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">标题字号</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatNumberInput('heading1SizePt', '一级标题 pt', { min: 8, max: 26, step: 0.5 })}
                {renderFormatNumberInput('heading2SizePt', '二级标题 pt', { min: 8, max: 24, step: 0.5 })}
                {renderFormatNumberInput('heading3SizePt', '三级标题 pt', { min: 8, max: 22, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">页面与表格</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {renderFormatNumberInput('pageTopCm', '上边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageBottomCm', '下边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageLeftCm', '左边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatNumberInput('pageRightCm', '右边距 cm', { min: 0.5, max: 6, step: 0.1 })}
                {renderFormatFontSelect('tableZhFont', '表格字体', DOCUMENT_FONT_OPTIONS.zh)}
                {renderFormatNumberInput('tableSizePt', '表格字号 pt', { min: 8, max: 16, step: 0.5 })}
              </div>
            </div>

            <div>
              <div className="text-sm font-semibold text-on-surface">目录与页眉</div>
              <div className="mt-2 space-y-2">
                <label className="flex items-center gap-2 text-sm text-on-surface">
                  <input
                    type="checkbox"
                    checked={Boolean(customFormat.insertToc)}
                    onChange={(event) => updateCustomFormat('insertToc', event.target.checked)}
                  />
                  缺少目录时自动插入目录
                </label>
                <label className="flex items-center gap-2 text-sm text-on-surface">
                  <input
                    type="checkbox"
                    checked={Boolean(customFormat.tocPageBreakAfter)}
                    onChange={(event) => updateCustomFormat('tocPageBreakAfter', event.target.checked)}
                  />
                  目录后分页
                </label>
                {renderFormatTextInput('headerTextTemplate', '页眉模板', { placeholder: `{projectName}投标文件-${TECHNICAL_DOCUMENT_PART_LABEL}` })}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-surface-container-high bg-surface-container-low p-3">
        <Button
          type="button"
          onClick={() => handleApplyTechnicalFormat(formatPreset)}
          disabled={!!formatApplying}
          className="w-full"
          variant="success"
        >
          {formatApplying ? '应用中...' : formatPreset === 'custom' ? '应用自定义格式' : '应用标准格式'}
        </Button>
      </div>
    </>
  )

  const renderProjectWorkspace = () => (
    <div className="business-ui-shell grid min-h-0 grid-cols-1 items-stretch gap-4 xl:h-[clamp(42rem,calc(100dvh-4.5rem),64rem)] xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
      <section className={`business-panel flex min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-white shadow-[0_1px_2px_rgba(13,33,55,0.05)] ${
        technicalPreviewFullscreen ? 'fixed inset-0 z-[160] rounded-none border-0' : ''
      }`}>
        <div className="business-section-head flex flex-col gap-3 px-3 py-3 sm:px-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-on-surface">{bidLabel}正文预览</h3>
            <p className="mt-1 truncate text-xs text-outline" title={fileName}>{fileName || '未生成文档'}</p>
          </div>
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <label className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md bg-surface-container-high px-2.5 text-xs font-semibold text-on-surface-variant">
                <span>版本：</span>
                <select
                  aria-label="下载版本"
                  value={exportVersion}
                  onChange={(event) => setExportVersion(event.target.value)}
                  disabled={wordPreparing || pdfPreparing}
                  className="h-6 cursor-pointer border-0 bg-transparent pr-1 text-xs font-semibold text-on-surface focus:outline-none disabled:cursor-not-allowed"
                >
                  <option value="marked">标记版</option>
                  <option value="clean">清洁版</option>
                </select>
              </label>
              <Button
                type="button"
                onClick={handleDownloadWord}
                disabled={wordPreparing}
                size="sm"
                variant="primary"
              >
                {wordPreparing ? '生成中...' : 'Word'}
              </Button>
              <Button
                type="button"
                onClick={handlePreparePdf}
                disabled={pdfPreparing}
                size="sm"
                variant="primary"
              >
                {pdfPreparing ? '生成中...' : 'PDF'}
              </Button>
              <Button
                type="button"
                onClick={handleRegenerateScoreIndex}
                disabled={scoreIndexStarting || scoreIndexRunning || generationRunning}
                size="sm"
                variant="secondary"
              >
                {scoreIndexStarting || scoreIndexRunning ? '重新生成中...' : '重新生成索引'}
              </Button>
              <Button
                type="button"
                onClick={handleRequestRegenerate}
                disabled={regenerationStarting || generationRunning || scoreIndexRunning}
                size="sm"
                variant="secondary"
              >
                {regenerationStarting || generationRunning ? '重新生成中...' : '重新生成正文'}
              </Button>
            </div>
            <IconButton
              type="button"
              aria-label={technicalPreviewFullscreen ? '退出全屏' : '全屏查看'}
              title={technicalPreviewFullscreen ? '退出全屏' : '全屏查看'}
              icon={technicalPreviewFullscreen ? 'close_fullscreen' : 'open_in_full'}
              onClick={() => setTechnicalPreviewFullscreen((value) => !value)}
              size="sm"
              variant="quiet"
              className="shrink-0"
            />
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
          {onlyofficeError && (
            <div role="alert" className="mb-3 rounded-md border border-error/30 bg-error/10 px-3 py-2 text-xs text-error">
              {onlyofficeError}
            </div>
          )}
          {renderDocumentEditor('740px')}
        </div>
      </section>

      <aside className="flex min-h-[36rem] flex-col overflow-hidden xl:h-full xl:min-h-0">
        <section className="business-panel flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-outline-variant/60 bg-surface-container-lowest shadow-[0_1px_2px_rgba(13,33,55,0.05)]">
          <div className="business-section-head business-editor-tool-head flex flex-col gap-3 border-b border-surface-container-high px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-base font-semibold text-on-surface">{bidLabel}共创工具</h3>
            </div>
            <div role="tablist" aria-label="共创工具" className="grid w-full shrink-0 grid-cols-2 gap-1 rounded-md bg-surface-container-high p-1 sm:w-[176px]">
              {[
                { key: 'chat', label: 'AI 对话' },
                { key: 'format', label: '格式设置' },
              ].map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={technicalRightTab === tab.key}
                  onClick={() => setTechnicalRightTab(tab.key)}
                  className={`rounded px-2 py-1.5 text-xs font-semibold transition-colors ${technicalRightTab === tab.key ? 'bg-surface-container-lowest text-primary shadow-sm' : 'text-on-surface-variant hover:bg-surface-dim'}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          {technicalRightTab === 'chat' ? renderTechnicalChatPanel() : renderTechnicalFormatPanel()}
        </section>
      </aside>
    </div>
  )

  if (loading) {
    return (
      <PageLoading
        title="正在打开技术标共创文档..."
        description="正在加载技术标正文、OnlyOffice 会话和最终稿状态。"
      />
    )
  }

  if (error) {
    return (
      <PageError
        title="技术标共创文档加载失败"
        description={error}
        onRetry={loadDocument}
      />
    )
  }

  return (
    <div className="stage-page flex w-full max-w-none flex-col gap-4 animate-fade-in sm:gap-6">
      <StageBreadcrumb />
      {renderProjectWorkspace()}
      <Dialog
        open={regenerationConfirmOpen}
        onClose={() => setRegenerationConfirmOpen(false)}
        size="sm"
      >
        <DialogHeader onClose={() => setRegenerationConfirmOpen(false)}>
          <h3 className="text-lg font-headline font-semibold text-on-surface">确认重新生成正文？</h3>
          <p className="mt-1 text-sm text-on-surface-variant">系统将重新执行技术标正文装配流程。</p>
        </DialogHeader>
        <DialogBody className="space-y-3 px-5 py-4">
          <p className="text-sm leading-6 text-on-surface">
            新正文将根据素材匹配页的当前结果生成，并覆盖共创导出页正在使用的正文。
          </p>
          <div className="rounded-md border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm leading-6 text-on-tertiary-fixed-variant">
            尚未保存的共创修改可能丢失。请先完成保存，或下载当前 Word 留档后再继续。
          </div>
        </DialogBody>
        <DialogFooter>
          <Button type="button" onClick={() => setRegenerationConfirmOpen(false)} variant="quiet">
            取消
          </Button>
          <Button type="button" onClick={handleConfirmRegenerate} variant="danger">
            继续重新生成
          </Button>
        </DialogFooter>
      </Dialog>
      <TechnicalGenerationProgressModal
        open={generationModalVisible}
        status={generationStatus}
        taskTitle="重新生成正文"
        completedMessage="技术标正文已重新生成，共创文档已刷新为最新版本。"
        onStop={handleStopGeneration}
        stopping={generationStopping}
        onClose={() => {
          setGenerationModalDismissed(true)
          setGenerationModalOpen(false)
        }}
      />
      <TechnicalScoreIndexProgressModal
        open={scoreIndexModalVisible}
        status={scoreIndexStatus}
        onStop={handleStopScoreIndex}
        stopping={scoreIndexStopping}
        onClose={() => {
          setScoreIndexModalDismissed(true)
          setScoreIndexModalOpen(false)
        }}
      />
    </div>
  )
}
