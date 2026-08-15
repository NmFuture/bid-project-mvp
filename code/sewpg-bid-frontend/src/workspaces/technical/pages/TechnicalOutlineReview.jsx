import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { technicalDirectoryAPI, technicalGapsAPI, technicalOutlineAPI, technicalProjectsAPI, technicalStagesAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import TechnicalDirectoryProgressPanel from '../components/TechnicalDirectoryProgressPanel'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import TechnicalMaterialMatchProgressModal from '../components/TechnicalMaterialMatchProgressModal'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../../../components/shared/OnlyOfficeWorkspace'
import Button from '../../../components/ui/Button'
import TechnicalTaskProgressDialog from '../components/TechnicalTaskProgressDialog'
import Toolbar from '../../../components/ui/Toolbar'
import { getOutlineDisplayNumber } from '../../../utils/outlineNumber'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import OutlineActionTag from '../components/OutlineActionTag'
import { getTechnicalStageRoute } from '../technicalStageFlow'
import {
  beginDirectoryProgressEpoch,
  buildDirectoryRegenerationPrompt,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  loadConsistentOutlineReviewSnapshot,
  mergeMonotonicDirectoryProgress,
} from '../technicalDirectoryProgress'
import {
  markOutlineNodeEdited,
  pickTenderBasis,
  shouldPreserveOutlineNumber,
  tenderBasisSearchText,
} from '../utils/outlineEvidence'
import { markTechnicalTask, updateTechnicalTask } from '../technicalBackgroundTasks.js'
import {
  scopeTechnicalTaskPayload,
  technicalTaskBelongsToProject,
  technicalTaskResponseMatchesProject,
} from '../technicalOutlineTaskLifecycle.js'

const cloneNodes = (nodes = []) => JSON.parse(JSON.stringify(nodes))
const MATERIAL_MATCH_ACTIVE_STATUSES = new Set(['queued', 'running', 'processing', 'cancel_requested'])
const MATERIAL_MATCH_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

const materialMatchStatusName = (payload) => String(payload?.status || '').toLowerCase()
const materialMatchTaskPatch = (payload) => ({
  status: materialMatchStatusName(payload),
  percentage: Number(payload?.percentage) || 0,
  summary: payload?.message || '',
})

const createNode = (title = '新章节') => ({
  id: `OL-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title,
  children: [],
  suggestionAction: '待确认',
  suggestionReason: '人工新增目录项，请确认其必要性和归属位置。',
})

const findNodeContext = (nodes, targetId, parent = null) => {
  for (let i = 0; i < (nodes || []).length; i += 1) {
    const current = nodes[i]
    if (current.id === targetId) {
      return {
        node: current,
        siblings: nodes,
        index: i,
        parent,
      }
    }

    const children = Array.isArray(current.children) ? current.children : []
    const inChild = findNodeContext(children, targetId, current)
    if (inChild) return inChild
  }

  return null
}

const moveNodeWithinSameParent = (nodes, movingId, targetId, placement = 'before') => {
  if (!movingId || !targetId || movingId === targetId) return null
  const next = cloneNodes(nodes)
  const movingContext = findNodeContext(next, movingId)
  const targetContext = findNodeContext(next, targetId)
  if (!movingContext || !targetContext || movingContext.siblings !== targetContext.siblings) {
    return null
  }

  const siblings = movingContext.siblings
  const [movingNode] = siblings.splice(movingContext.index, 1)
  const targetIndex = siblings.findIndex((item) => item.id === targetId)
  if (!movingNode || targetIndex < 0) return null
  siblings.splice(placement === 'after' ? targetIndex + 1 : targetIndex, 0, movingNode)
  return next
}

const collectExpandableNodeIds = (items = []) =>
  (items || []).reduce((result, item) => {
    const children = Array.isArray(item.children) ? item.children : []
    if (children.length > 0) {
      result.push(item.id)
      result.push(...collectExpandableNodeIds(children))
    }
    return result
  }, [])

const countNodes = (items = []) =>
  (items || []).reduce((total, item) => total + 1 + countNodes(item.children || []), 0)

const chineseNumber = (value) => {
  const digits = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九']
  const num = Number(value)
  if (!Number.isFinite(num) || num <= 0) return String(value)
  if (num <= 10) return num === 10 ? '十' : digits[num]
  if (num < 20) return `十${digits[num - 10]}`
  if (num < 100) {
    const tens = Math.floor(num / 10)
    const ones = num % 10
    return `${digits[tens]}十${digits[ones]}`
  }
  return String(value)
}

const numberStyle = (value, level = 0) => {
  const text = String(value || '').trim()
  if (/^第[一二三四五六七八九十百]+节/.test(text)) return 'section'
  if (/^第[一二三四五六七八九十百]+章/.test(text)) return 'chapter'
  if (/^[（(][一二三四五六七八九十百]+[）)]/.test(text)) return 'chinese-paren'
  if (/^[一二三四五六七八九十百]+[、．.]/.test(text)) return 'chinese-comma'
  if (/^[（(]\d+[）)]/.test(text)) return 'arabic-paren'
  if (/^\d+[、．.]/.test(text)) return 'arabic-comma'
  if (/^\d+(?:\.\d+)+$/.test(text)) return 'decimal'
  if (/^\d+$/.test(text)) return level === 0 ? 'arabic' : 'decimal'
  return ''
}

const collectNumberStyles = (items = [], level = 0, styles = {}) => {
  ;(items || []).forEach((item) => {
    const style = numberStyle(getOutlineDisplayNumber(item), level)
    if (style && !styles[level]) styles[level] = style
    if (Array.isArray(item?.children) && item.children.length) {
      collectNumberStyles(item.children, level + 1, styles)
    }
  })
  return styles
}

const formatOutlineNumber = (index, level, decimalPrefix, style) => {
  const normalizedStyle = style || (level === 0 ? 'arabic' : 'decimal')
  if (normalizedStyle === 'chapter') return `第${chineseNumber(index)}章`
  if (normalizedStyle === 'section') return `第${chineseNumber(index)}节`
  if (normalizedStyle === 'chinese-paren') return `（${chineseNumber(index)}）`
  if (normalizedStyle === 'chinese-comma') return `${chineseNumber(index)}、`
  if (normalizedStyle === 'arabic-paren') return `（${index}）`
  if (normalizedStyle === 'arabic-comma') return `${index}、`
  if (normalizedStyle === 'decimal') return decimalPrefix ? `${decimalPrefix}.${index}` : String(index)
  return String(index)
}

const renumberOutlineNodes = (items = []) => {
  const styles = collectNumberStyles(items)
  const walk = (nodes = [], level = 0, decimalPrefix = '') => (
    (nodes || []).map((node, index) => {
      const position = index + 1
      const nextDecimalPrefix = decimalPrefix ? `${decimalPrefix}.${position}` : String(position)
      const nextNumber = shouldPreserveOutlineNumber(node)
        ? getOutlineDisplayNumber(node)
        : formatOutlineNumber(position, level, decimalPrefix, styles[level])
      const nextNode = {
        ...node,
        number: nextNumber,
        tocNumber: nextNumber,
        toc_number: nextNumber,
      }
      nextNode.children = Array.isArray(node.children)
        ? walk(node.children, level + 1, nextDecimalPrefix)
        : []
      return nextNode
    })
  )
  return walk(cloneNodes(items))
}

const SEARCH_STORAGE_KEY = 'onlyoffice-search-bridge-message'
const SEARCH_CHANNEL_NAME = 'onlyoffice-search-bridge'
const SEARCH_RESULT_SOURCE = 'onlyoffice-search-bridge'

const suggestionActionLabel = (node) => {
  const explicit = String(node?.suggestionAction || node?.suggestion_action || '').trim()
  return explicit
}

const sendOnlyOfficeSearch = (text, onlyofficeEmbedRef = null, beforeSend = null) => {
  const cleanText = String(text || '').replace(/\s+/g, ' ').trim()
  if (!cleanText) return null
  const payload = {
    source: SEARCH_RESULT_SOURCE,
    type: 'search-basis-text',
    text: cleanText,
    nonce: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  }
  const storedPayload = {
    type: payload.type,
    text: payload.text,
    nonce: payload.nonce,
  }
  beforeSend?.(payload.nonce)
  try {
    window.localStorage.setItem(SEARCH_STORAGE_KEY, JSON.stringify(storedPayload))
  } catch {
    // BroadcastChannel is still enough in normal browser contexts.
  }
  if ('BroadcastChannel' in window) {
    const channel = new BroadcastChannel(SEARCH_CHANNEL_NAME)
    channel.postMessage(storedPayload)
    channel.close()
  }
  onlyofficeEmbedRef?.current?.postMessage?.(payload)
  return payload.nonce
}

function DirectoryGenerationProgressModal({ open, state, nowMs, onClose, onStop, stopping = false }) {
  if (!open) return null
  const running = isDirectoryProgressRunning(state)
  const completed = state?.status === 'completed'
  const failed = isDirectoryProgressFailed(state)
  const cancelled = state?.status === 'cancelled'

  return (
    <TechnicalTaskProgressDialog
      open={open}
      title={running ? '正在重新生成目录' : completed ? '目录重新生成完成' : failed ? '目录重新生成失败' : cancelled ? '目录重新生成已停止' : '重新生成目录'}
      active={running}
      stopping={stopping}
      onClose={onClose}
      onStop={onStop}
    >
        <TechnicalDirectoryProgressPanel state={state} nowMs={nowMs} />
        {running ? (
          <p className="text-xs text-outline">任务在后台运行，可以关闭弹窗或离开页面。</p>
        ) : null}
        {completed ? (
          <div className="border border-secondary/25 bg-secondary-container/35 px-3 py-2 text-sm text-on-secondary-container">
            新目录已载入，请重新审核并进入素材匹配。
          </div>
        ) : null}
        {failed ? (
          <div className="border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
            当前目录及原有下游结果未被修改，可关闭后重试。
          </div>
        ) : null}
        {cancelled ? (
          <div className="border border-outline-variant bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">
            目录重新生成已停止，当前目录未被修改。
          </div>
        ) : null}
    </TechnicalTaskProgressDialog>
  )
}

export default function TechnicalOutlineReview({ showToast, workspaceKind = 'tech' }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const progressTask = searchParams.get('progressTask')
  const routeWorkspaceSlug = useWorkspaceSlug()
  const workspaceSlug = workspaceKind || routeWorkspaceSlug
  const [nodes, setNodes] = useState([])
  const [activeNodeId, setActiveNodeId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerationModalOpen, setRegenerationModalOpen] = useState(false)
  const [regenerationPendingState, setRegenerationPendingState] = useState(null)
  const [directoryState, setDirectoryState] = useState(null)
  const [directoryStopping, setDirectoryStopping] = useState(false)
  const [directoryProgressClock, setDirectoryProgressClock] = useState(() => Date.now())
  const [reviewStatus, setReviewStatus] = useState('draft')
  const [currentStage, setCurrentStage] = useState(2)
  const [projectName, setProjectName] = useState(id)
  const [materialMatchStatus, setMaterialMatchStatus] = useState(null)
  const [materialMatchModalOpen, setMaterialMatchModalOpen] = useState(false)
  const [materialMatchStopping, setMaterialMatchStopping] = useState(false)
  const [materialMatchSubmitting, setMaterialMatchSubmitting] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [tenderPreview, setTenderPreview] = useState(null)
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [collapsedNodeIds, setCollapsedNodeIds] = useState(new Set())
  const [pendingSearchText, setPendingSearchText] = useState('')
  const [dragNodeId, setDragNodeId] = useState('')
  const [dragOverNodeId, setDragOverNodeId] = useState('')
  const [dragPlacement, setDragPlacement] = useState('before')
  const onlyofficeEmbedRef = useRef(null)
  const pendingSearchNonceRef = useRef('')
  const directoryStopRequestedRef = useRef(false)
  const materialMatchStopRequestedRef = useRef(false)
  const materialMatchEpochRef = useRef(0)
  const materialMatchTerminalHandledRef = useRef(0)
  const materialMatchShouldFinalizeRef = useRef(false)
  const currentProjectIdRef = useRef(String(id))
  // 路由参数在 render 阶段即生效，避免上一项目的异步响应抢在 effect 前回写。
  // eslint-disable-next-line react-hooks/refs
  currentProjectIdRef.current = String(id)

  const markPendingSearch = useCallback((nonce) => {
    pendingSearchNonceRef.current = nonce || ''
  }, [])

  const applyOutlinePayload = useCallback((payload) => {
    const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
    setNodes(nextNodes)
    setDirty(false)
    setActiveNodeId((current) => nextNodes.some((node) => node.id === current) ? current : nextNodes[0]?.id || '')
    setCollapsedNodeIds(
      countNodes(nextNodes) > 180
        ? new Set(collectExpandableNodeIds(nextNodes))
        : new Set(),
    )
    setTenderPreview(payload?.tenderPreview || null)
    setReviewStatus(String(payload?.reviewStatus || 'draft'))
    setOnlyofficeError('')
  }, [])

  const applyMaterialMatchPayload = useCallback((payload, ownerId = id) => {
    if (!payload?.status) return
    const incomingStatus = materialMatchStatusName(payload)
    const active = MATERIAL_MATCH_ACTIVE_STATUSES.has(incomingStatus)
    if (incomingStatus === 'cancel_requested') {
      materialMatchStopRequestedRef.current = true
      setMaterialMatchStopping(true)
    }
    const nextPayload = materialMatchStopRequestedRef.current && active && incomingStatus !== 'cancel_requested'
      ? { ...payload, status: 'cancel_requested', message: '已请求停止素材匹配，正在等待安全停止点。' }
      : payload
    const scopedPayload = scopeTechnicalTaskPayload(ownerId, nextPayload)

    if (MATERIAL_MATCH_TERMINAL_STATUSES.has(materialMatchStatusName(scopedPayload))) {
      materialMatchStopRequestedRef.current = false
      setMaterialMatchStopping(false)
    }
    setMaterialMatchStatus((previous) => {
      const previousStatus = materialMatchStatusName(previous)
      if (
        technicalTaskBelongsToProject(previous, ownerId)
        && MATERIAL_MATCH_TERMINAL_STATUSES.has(previousStatus)
        && MATERIAL_MATCH_ACTIVE_STATUSES.has(materialMatchStatusName(scopedPayload))
      ) {
        return previous
      }
      return scopedPayload
    })
  }, [id])

  useEffect(() => {
    // 项目切换必须在新项目加载前同步清空上一项目的任务 UI。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDirectoryState(null)
    setMaterialMatchStatus(null)
    setRegenerationModalOpen(false)
    setMaterialMatchModalOpen(false)
    setDirectoryStopping(false)
    setMaterialMatchStopping(false)
    setMaterialMatchSubmitting(false)
    setConfirming(false)
    setRegenerating(false)
    setRegenerationPendingState(null)
    directoryStopRequestedRef.current = false
    materialMatchStopRequestedRef.current = false
    materialMatchEpochRef.current = 0
    materialMatchTerminalHandledRef.current = 0
    materialMatchShouldFinalizeRef.current = false
  }, [id])

  const loadData = useCallback(async () => {
    const requestProjectId = id
    setLoading(true)
    setError('')
    try {
      const [{ outlinePayload, generationPayload, projectPayload }, detectionPayload] = await Promise.all([
        loadConsistentOutlineReviewSnapshot({
          loadDirectoryState: () => technicalDirectoryAPI.status(requestProjectId).catch(() => null),
          loadOutline: () => technicalOutlineAPI.get(requestProjectId),
          loadProject: () => technicalProjectsAPI.get(requestProjectId).catch(() => null),
        }),
        technicalGapsAPI.detectionStatus(requestProjectId).catch(() => null),
      ])
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      const resolvedProjectName = projectPayload?.name || requestProjectId
      applyOutlinePayload(outlinePayload)
      setDirectoryState((previous) => scopeTechnicalTaskPayload(
        requestProjectId,
        mergeMonotonicDirectoryProgress(
          technicalTaskBelongsToProject(previous, requestProjectId) ? previous : null,
          generationPayload,
        ),
      ))
      if (generationPayload?.status === 'cancel_requested') {
        directoryStopRequestedRef.current = true
        setDirectoryStopping(true)
      }
      if (isDirectoryProgressRunning(generationPayload) || progressTask === 'outline-regenerate') {
        setRegenerationModalOpen(true)
      }
      setCurrentStage(Number(projectPayload?.currentStage) || 2)
      setProjectName(resolvedProjectName)

      if (detectionPayload?.status) {
        const detectionStatus = materialMatchStatusName(detectionPayload)
        const detectionActive = MATERIAL_MATCH_ACTIVE_STATUSES.has(detectionStatus)
        applyMaterialMatchPayload(detectionPayload, requestProjectId)
        if (detectionActive) {
          materialMatchEpochRef.current += 1
          materialMatchShouldFinalizeRef.current = true
          markTechnicalTask({
            taskType: 'material-match',
            taskName: '素材匹配',
            projectId: requestProjectId,
            projectName: resolvedProjectName,
            ...materialMatchTaskPatch(detectionPayload),
          })
          setMaterialMatchModalOpen(true)
        } else if (
          progressTask === 'material-match'
          && MATERIAL_MATCH_TERMINAL_STATUSES.has(detectionStatus)
        ) {
          setMaterialMatchModalOpen(true)
        }
      }
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setError(e?.message || '目录数据加载失败')
    } finally {
      if (technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
        setLoading(false)
      }
    }
  }, [applyMaterialMatchPayload, applyOutlinePayload, id, progressTask])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const directoryRunning = technicalTaskBelongsToProject(directoryState, id)
    && isDirectoryProgressRunning(directoryState)
  const directoryLocked = regenerating || directoryRunning
  const materialMatchRunning = technicalTaskBelongsToProject(materialMatchStatus, id)
    && MATERIAL_MATCH_ACTIVE_STATUSES.has(materialMatchStatusName(materialMatchStatus))

  useEffect(() => {
    if (!technicalTaskBelongsToProject(directoryState, id) || !directoryState?.status) return
    updateTechnicalTask('outline-regenerate', id, {
      status: String(directoryState.status).toLowerCase(),
      percentage: Number(directoryState.percentage) || 0,
      summary: directoryState.summary || directoryState.message || '',
    })
  }, [directoryState, id])

  useEffect(() => {
    if (!directoryRunning && !regenerating) return undefined
    const timer = window.setInterval(() => setDirectoryProgressClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [directoryRunning, regenerating])

  useEffect(() => {
    if (!directoryRunning) return undefined
    const requestProjectId = id
    let cancelled = false
    let timer = null

    const pollDirectoryStatus = async () => {
      try {
        const response = await technicalDirectoryAPI.status(requestProjectId)
        if (cancelled || !technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
        const responseStatus = String(response?.status || '').toLowerCase()
        const payload = directoryStopRequestedRef.current
          && isDirectoryProgressRunning(response)
          && responseStatus !== 'cancel_requested'
          ? { ...response, status: 'cancel_requested', summary: '已请求停止目录重新生成，正在等待安全停止点。' }
          : response
        if (payload?.status === 'completed') {
          const [outlinePayload, projectPayload] = await Promise.all([
            technicalOutlineAPI.get(requestProjectId),
            technicalProjectsAPI.get(requestProjectId).catch(() => null),
          ])
          if (cancelled || !technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
          setDirectoryState((previous) => scopeTechnicalTaskPayload(
            requestProjectId,
            mergeMonotonicDirectoryProgress(previous, payload),
          ))
          applyOutlinePayload(outlinePayload)
          setCurrentStage(Number(projectPayload?.currentStage) || 2)
          directoryStopRequestedRef.current = false
          setRegenerating(false)
          setDirectoryStopping(false)
          showToast?.('目录重新生成完成，请重新审核。')
          return
        }
        setDirectoryState((previous) => scopeTechnicalTaskPayload(
          requestProjectId,
          mergeMonotonicDirectoryProgress(previous, payload),
        ))
        if (payload?.status === 'cancel_requested') {
          directoryStopRequestedRef.current = true
          setDirectoryStopping(true)
        }
        if (payload?.status === 'cancelled') {
          directoryStopRequestedRef.current = false
          setRegenerating(false)
          setDirectoryStopping(false)
          showToast?.('目录重新生成已停止。')
          return
        }
        if (isDirectoryProgressFailed(payload)) {
          directoryStopRequestedRef.current = false
          setRegenerating(false)
          setDirectoryStopping(false)
          showToast?.('目录重新生成失败，当前目录未被修改。', 'error')
          return
        }
      } catch {
        // 后台任务不中断，保留当前进度并继续轮询。
      }
      if (!cancelled) timer = window.setTimeout(pollDirectoryStatus, 1000)
    }

    timer = window.setTimeout(pollDirectoryStatus, 1000)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [applyOutlinePayload, directoryRunning, id, showToast])

  useEffect(() => {
    if (!technicalTaskBelongsToProject(materialMatchStatus, id) || !materialMatchStatus?.status) return
    updateTechnicalTask('material-match', id, materialMatchTaskPatch(materialMatchStatus))
  }, [id, materialMatchStatus])

  useEffect(() => {
    if (!materialMatchRunning || materialMatchSubmitting) return undefined
    const requestProjectId = id
    let disposed = false
    let timer = null

    const pollMaterialMatchStatus = async () => {
      try {
        const payload = await technicalGapsAPI.detectionStatus(requestProjectId)
        if (disposed || !technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
        applyMaterialMatchPayload(payload, requestProjectId)
      } catch {
        // 后台任务不中断，保留当前进度并继续轮询。
      }
      if (!disposed) timer = window.setTimeout(pollMaterialMatchStatus, 1000)
    }

    timer = window.setTimeout(pollMaterialMatchStatus, 1000)
    return () => {
      disposed = true
      window.clearTimeout(timer)
    }
  }, [applyMaterialMatchPayload, id, materialMatchRunning, materialMatchSubmitting])

  useEffect(() => {
    if (!technicalTaskBelongsToProject(materialMatchStatus, id)) return undefined
    const status = materialMatchStatusName(materialMatchStatus)
    if (!MATERIAL_MATCH_TERMINAL_STATUSES.has(status)) return undefined

    if (!materialMatchShouldFinalizeRef.current) return undefined
    const epoch = materialMatchEpochRef.current
    if (materialMatchTerminalHandledRef.current === epoch) return undefined
    materialMatchTerminalHandledRef.current = epoch
    materialMatchShouldFinalizeRef.current = false

    if (status === 'cancelled') {
      showToast?.('素材匹配已停止。')
      return undefined
    }
    if (status === 'failed') {
      showToast?.(materialMatchStatus?.error || materialMatchStatus?.message || '素材匹配失败，请稍后重试。', 'error')
      return undefined
    }

    const requestProjectId = id
    let disposed = false
    const finishStage = async () => {
      try {
        const stageResult = await technicalStagesAPI.update(requestProjectId, 2, { status: 'completed' })
        if (
          disposed
          || materialMatchEpochRef.current !== epoch
          || !technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)
        ) return
        const nextStageId = Number(stageResult?.currentStage) || 3
        const nextRoute = getTechnicalStageRoute(requestProjectId, nextStageId, workspaceSlug)
          || projectRoute(requestProjectId, '/gaps', workspaceSlug)
        showToast?.('素材匹配已完成，已进入素材匹配')
        navigate(nextRoute)
      } catch (error) {
        if (!disposed && technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
          showToast?.(error?.message || '素材匹配完成，但阶段状态更新失败。', 'error')
        }
      }
    }
    finishStage()
    return () => {
      disposed = true
    }
  }, [id, materialMatchStatus, navigate, showToast, workspaceSlug])

  useEffect(() => {
    if (!pendingSearchText) return undefined
    const timer = setTimeout(() => {
      sendOnlyOfficeSearch(pendingSearchText, onlyofficeEmbedRef, markPendingSearch)
      setPendingSearchText('')
    }, 800)
    return () => clearTimeout(timer)
  }, [markPendingSearch, pendingSearchText, showToast, tenderPreview?.activeFile?.id])

  useEffect(() => {
    const handleSearchResult = (event) => {
      if (event.origin !== window.location.origin) return
      const payload = event.data
      if (!payload || payload.source !== SEARCH_RESULT_SOURCE) return
      if (payload.type === 'search-debug') {
        console.debug('[onlyoffice-search]', payload.stage, payload.detail || '')
        return
      }
      if (payload.type !== 'search-result') return
      const expectedNonce = pendingSearchNonceRef.current
      if (expectedNonce && payload.nonce && payload.nonce !== expectedNonce) return
      markPendingSearch('')
      if (payload.found) {
        showToast?.('已定位到招标依据')
      } else {
        showToast?.('未在当前招标文件中找到这段依据', 'error')
      }
    }

    window.addEventListener('message', handleSearchResult)
    return () => window.removeEventListener('message', handleSearchResult)
  }, [markPendingSearch, showToast])

  const focusTenderBasis = useCallback(async (basis) => {
    if (!basis) return
    const searchText = tenderBasisSearchText(basis)
    if (!searchText) return

    const refFileId = String(basis.fileId || basis.file_id || '').trim()
    const activeFileId = String(tenderPreview?.activeFile?.id || '').trim()
    if (refFileId && refFileId !== activeFileId) {
      try {
        const payload = await technicalOutlineAPI.get(id, { fileId: refFileId })
        setTenderPreview(payload?.tenderPreview || null)
        setOnlyofficeError('')
        setPendingSearchText(searchText)
      } catch (e) {
        setPendingSearchText('')
        showToast?.(e?.message || '招标文件预览切换失败', 'error')
      }
      return
    }

    sendOnlyOfficeSearch(searchText, onlyofficeEmbedRef, markPendingSearch)
  }, [id, markPendingSearch, showToast, tenderPreview?.activeFile?.id])

  const handleRegenerateDirectory = async () => {
    if (directoryLocked) return
    const requestProjectId = id
    const confirmed = window.confirm(buildDirectoryRegenerationPrompt({
      dirty,
      hasDownstreamResults: currentStage > 2 || reviewStatus === 'confirmed',
    }))
    if (!confirmed) return

    const queuedAt = new Date().toISOString()
    const queuedState = scopeTechnicalTaskPayload(requestProjectId, beginDirectoryProgressEpoch({
      incoming: {
        status: 'queued',
        percentage: 0,
        summary: '正在提交目录生成任务，请稍候。',
        startedAt: queuedAt,
        updatedAt: queuedAt,
      },
    }))
    setRegenerationPendingState(queuedState)
    directoryStopRequestedRef.current = false
    setDirectoryStopping(false)
    setRegenerating(true)
    setRegenerationModalOpen(true)
    markTechnicalTask({
      taskType: 'outline-regenerate',
      taskName: '重新生成目录',
      projectId: requestProjectId,
      projectName,
      status: 'queued',
      percentage: 0,
      summary: queuedState.summary,
      startedAt: queuedAt,
    })
    try {
      const payload = await technicalOutlineAPI.regenerate(id)
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setDirectoryState((previous) => scopeTechnicalTaskPayload(
        requestProjectId,
        beginDirectoryProgressEpoch({ previous, incoming: payload }),
      ))
      showToast?.(payload?.message || '已开始重新生成目录。')
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      const failedState = scopeTechnicalTaskPayload(requestProjectId, {
        status: 'failed',
        percentage: 0,
        summary: e?.message || '启动目录重新生成失败',
        completedAt: new Date().toISOString(),
      })
      setDirectoryState(failedState)
      setRegenerationModalOpen(false)
      updateTechnicalTask('outline-regenerate', requestProjectId, {
        status: 'failed',
        percentage: 0,
        summary: e?.message || '启动目录重新生成失败',
      })
      showToast?.(e?.message || '启动目录重新生成失败', 'error')
    } finally {
      if (technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
        setRegenerationPendingState(null)
        setRegenerating(false)
      }
    }
  }

  const handleStopDirectory = async () => {
    if (!directoryRunning || directoryStopping) return
    const requestProjectId = id
    directoryStopRequestedRef.current = true
    setDirectoryStopping(true)
    try {
      const payload = await technicalDirectoryAPI.cancel(requestProjectId)
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      if (payload?.error) throw new Error(payload.error)
      setDirectoryState((previous) => scopeTechnicalTaskPayload(
        requestProjectId,
        mergeMonotonicDirectoryProgress(previous, payload),
      ))
      updateTechnicalTask('outline-regenerate', requestProjectId, {
        status: String(payload?.status || 'cancel_requested').toLowerCase(),
        percentage: Number(payload?.percentage) || Number(directoryState?.percentage) || 0,
        summary: payload?.summary || payload?.message || '已请求停止目录重新生成。',
      })
      if (!isDirectoryProgressRunning(payload)) {
        directoryStopRequestedRef.current = false
        setDirectoryStopping(false)
      }
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      directoryStopRequestedRef.current = false
      setDirectoryStopping(false)
      showToast?.(e?.message || '停止目录重新生成失败，请稍后重试。', 'error')
    }
  }

  const handleSave = async () => {
    if (saving || directoryLocked) return
    if (!dirty) {
      showToast?.('目录暂无变更，无需保存。')
      return
    }

    setSaving(true)
    try {
      const nodesToSave = renumberOutlineNodes(nodes)
      const payload = await technicalOutlineAPI.save(id, { nodes: nodesToSave })
      const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
      setNodes(nextNodes)
      setDirty(false)
      setReviewStatus(String(payload?.reviewStatus || 'draft'))
      if (!nextNodes.find((node) => node.id === activeNodeId)) {
        setActiveNodeId(nextNodes[0]?.id || '')
      }
      showToast?.(payload?.message || '目录已保存')
    } catch (e) {
      showToast?.(e?.message || '目录保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleConfirm = async () => {
    if (directoryLocked) return
    if (!nodes.length) {
      showToast?.('目录为空，请先新增章节后再确认。', 'error')
      return
    }

    const requestProjectId = id
    setConfirming(true)
    let submittedEpoch = 0
    try {
      if (dirty) {
        const nodesToSave = renumberOutlineNodes(nodes)
        const saved = await technicalOutlineAPI.save(requestProjectId, { nodes: nodesToSave })
        if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
        setNodes(Array.isArray(saved?.nodes) ? saved.nodes : [])
        setDirty(false)
      }

      await technicalOutlineAPI.confirm(requestProjectId)
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setReviewStatus('confirmed')
      showToast?.('目录确认已完成，正在执行素材匹配...')

      const epoch = materialMatchEpochRef.current + 1
      submittedEpoch = epoch
      const queuedAt = new Date().toISOString()
      const queuedState = {
        status: 'queued',
        percentage: 0,
        message: '正在提交素材匹配任务，请稍候。',
        startedAt: queuedAt,
      }
      materialMatchEpochRef.current = epoch
      materialMatchTerminalHandledRef.current = 0
      materialMatchShouldFinalizeRef.current = true
      materialMatchStopRequestedRef.current = false
      setMaterialMatchStopping(false)
      setMaterialMatchSubmitting(true)
      setMaterialMatchStatus(scopeTechnicalTaskPayload(requestProjectId, queuedState))
      markTechnicalTask({
        taskType: 'material-match',
        taskName: '素材匹配',
        projectId: requestProjectId,
        projectName,
        ...materialMatchTaskPatch(queuedState),
        startedAt: queuedAt,
      })

      const payload = await technicalGapsAPI.runDetection(requestProjectId)
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      setMaterialMatchSubmitting(false)
      if (materialMatchEpochRef.current !== epoch) return
      applyMaterialMatchPayload(payload, requestProjectId)
      updateTechnicalTask('material-match', requestProjectId, materialMatchTaskPatch(payload))
      setMaterialMatchModalOpen(true)
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      const message = e?.message || '目录确认或素材匹配失败，请稍后重试'
      if (submittedEpoch > 0 && materialMatchEpochRef.current === submittedEpoch) {
        const failedState = {
          status: 'failed',
          percentage: 0,
          message,
          completedAt: new Date().toISOString(),
        }
        materialMatchShouldFinalizeRef.current = false
        setMaterialMatchStatus(scopeTechnicalTaskPayload(requestProjectId, failedState))
        updateTechnicalTask('material-match', requestProjectId, materialMatchTaskPatch(failedState))
        setMaterialMatchModalOpen(true)
      }
      setMaterialMatchSubmitting(false)
      showToast?.(message, 'error')
    } finally {
      if (technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) {
        setConfirming(false)
      }
    }
  }

  const handleStopMaterialMatch = async () => {
    if (!materialMatchRunning || materialMatchStopping) return
    const requestProjectId = id
    materialMatchStopRequestedRef.current = true
    setMaterialMatchStopping(true)
    try {
      const payload = await technicalGapsAPI.cancelDetection(requestProjectId)
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      if (payload?.error) throw new Error(payload.error)
      applyMaterialMatchPayload(payload, requestProjectId)
      updateTechnicalTask('material-match', requestProjectId, materialMatchTaskPatch(payload))
      if (!MATERIAL_MATCH_ACTIVE_STATUSES.has(materialMatchStatusName(payload))) {
        materialMatchStopRequestedRef.current = false
        setMaterialMatchStopping(false)
      }
    } catch (e) {
      if (!technicalTaskResponseMatchesProject(requestProjectId, currentProjectIdRef.current)) return
      materialMatchStopRequestedRef.current = false
      setMaterialMatchStopping(false)
      showToast?.(e?.message || '停止素材匹配失败，请稍后重试。', 'error')
    }
  }

  const handleAddRoot = () => {
    const newNode = createNode('新章节')
    setDirty(true)
    setNodes((prev) => [...cloneNodes(prev), newNode])
    setActiveNodeId(newNode.id)
  }

  const handleAddSibling = (targetId) => {
    const newNode = createNode('新章节')
    setDirty(true)
    setNodes((prev) => {
      const next = cloneNodes(prev)
      const context = findNodeContext(next, targetId)
      if (!context) return prev
      context.siblings.splice(context.index + 1, 0, newNode)
      return next
    })
    setActiveNodeId(newNode.id)
  }

  const handleAddChild = (targetId) => {
    const newNode = createNode('新小节')
    setDirty(true)
    setNodes((prev) => {
      const next = cloneNodes(prev)
      const context = findNodeContext(next, targetId)
      if (!context) return prev
      if (!Array.isArray(context.node.children)) {
        context.node.children = []
      }
      context.node.children.push(newNode)
      return next
    })
    setActiveNodeId(newNode.id)
  }

  const handleDelete = (targetId) => {
    const shouldDelete = window.confirm('确认删除这个目录节点吗？')
    if (!shouldDelete) return

    setDirty(true)
    setNodes((prev) => {
      const next = cloneNodes(prev)
      const context = findNodeContext(next, targetId)
      if (!context) return prev
      context.siblings.splice(context.index, 1)
      return next
    })

    if (activeNodeId === targetId) {
      setActiveNodeId('')
    }
  }

  const handleDragStart = (event, targetId) => {
    setDragNodeId(targetId)
    setDragOverNodeId('')
    setDragPlacement('before')
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', targetId)
  }

  const handleDragOver = (event, targetId) => {
    const movingId = dragNodeId || event.dataTransfer.getData('text/plain')
    if (!movingId || movingId === targetId) return
    const movingContext = findNodeContext(nodes, movingId)
    const targetContext = findNodeContext(nodes, targetId)
    if (!movingContext || !targetContext || movingContext.siblings !== targetContext.siblings) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    const rect = event.currentTarget.getBoundingClientRect()
    const placement = event.clientY > rect.top + rect.height / 2 ? 'after' : 'before'
    setDragOverNodeId(targetId)
    setDragPlacement(placement)
  }

  const handleDrop = (event, targetId) => {
    event.preventDefault()
    const movingId = dragNodeId || event.dataTransfer.getData('text/plain')
    setDragNodeId('')
    setDragOverNodeId('')
    if (!movingId || movingId === targetId) return
    setNodes((prev) => {
      const moved = moveNodeWithinSameParent(prev, movingId, targetId, dragPlacement)
      const next = moved ? renumberOutlineNodes(moved) : moved
      if (!next) {
        showToast?.('暂只支持同级目录拖拽排序。', 'error')
        return prev
      }
      setDirty(true)
      return next
    })
  }

  const handleDragEnd = () => {
    setDragNodeId('')
    setDragOverNodeId('')
    setDragPlacement('before')
  }

  const handleTitleChange = (targetId, value) => {
    setDirty(true)
    setNodes((prev) => {
      const next = cloneNodes(prev)
      const context = findNodeContext(next, targetId)
      if (!context) return prev
      Object.assign(context.node, markOutlineNodeEdited(context.node, value))
      return next
    })
  }

  const handleToggleNodeCollapse = (targetId) => {
    setCollapsedNodeIds((prev) => {
      const next = new Set(prev)
      if (next.has(targetId)) {
        next.delete(targetId)
      } else {
        next.add(targetId)
      }
      return next
    })
  }

  const handleToggleAllCollapse = () => {
    const expandableIds = collectExpandableNodeIds(nodes)
    if (!expandableIds.length) return
    setCollapsedNodeIds((prev) => (
      prev.size ? new Set() : new Set(expandableIds)
    ))
  }

  const renderRows = (items, depth = 0, prefix = '') => (
    <div>
      {(items || []).map((node, index) => {
        const seq = prefix ? `${prefix}.${index + 1}` : `${index + 1}`
        const isActive = activeNodeId === node.id
        const isDragging = dragNodeId === node.id
        const isDragTarget = dragOverNodeId === node.id
        const hasChildren = Array.isArray(node.children) && node.children.length > 0
        const isCollapsed = collapsedNodeIds.has(node.id)
        const action = suggestionActionLabel(node)
        const tenderBasis = pickTenderBasis(node)
        const canFocusBasis = Boolean(tenderBasis)
        const displayNumber = getOutlineDisplayNumber(node, seq)

        return (
          <div key={node.id}>
            <div
              onClick={() => setActiveNodeId(node.id)}
              draggable={!directoryLocked}
              onDragStart={(event) => handleDragStart(event, node.id)}
              onDragOver={(event) => handleDragOver(event, node.id)}
              onDrop={(event) => handleDrop(event, node.id)}
              onDragEnd={handleDragEnd}
              onDragLeave={() => {
                if (dragOverNodeId === node.id) setDragOverNodeId('')
              }}
              className={`flex cursor-grab items-center gap-1 px-2 py-1.5 transition-colors border-b border-surface-container-high active:cursor-grabbing ${
                isActive ? 'bg-primary/5' : 'bg-white'
              } ${isDragging ? 'opacity-45' : ''} ${isDragTarget ? `${dragPlacement === 'after' ? 'border-b-2 border-b-primary' : 'border-t-2 border-t-primary'} bg-primary/10` : ''}`}
              style={{ marginLeft: `${depth * 20}px` }}
            >
              <span className="flex h-6 w-5 shrink-0 items-center justify-center text-outline" title="拖拽排序">
                <span className="material-symbols-outlined text-[18px]">drag_indicator</span>
              </span>
              {hasChildren ? (
                <button
                  type="button"
                  aria-label={isCollapsed ? '展开子章节' : '收起子章节'}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleToggleNodeCollapse(node.id)
                  }}
                  className="h-6 w-6 shrink-0 flex items-center justify-center text-outline hover:text-primary transition-colors"
                  title={isCollapsed ? '展开' : '收起'}
                >
                  <span aria-hidden="true" className="material-symbols-outlined text-[16px]">
                    {isCollapsed ? 'chevron_right' : 'expand_more'}
                  </span>
                </button>
              ) : (
                <span className="w-6 shrink-0" />
              )}
              <span className="w-20 shrink-0 text-xs font-semibold text-outline">{displayNumber}</span>
              <input
                value={node.title || ''}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => handleTitleChange(node.id, e.target.value)}
                className="h-8 !min-h-0 flex-1 border-0 bg-transparent px-1.5 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/25"
                placeholder="输入章节标题"
              />
              {action ? (
                <OutlineActionTag
                  action={action}
                  basis={canFocusBasis ? tenderBasis : null}
                  reason={node.suggestionReason || node.suggestion_reason || ''}
                  onFocusBasis={(basis) => {
                    setActiveNodeId(node.id)
                    focusTenderBasis(basis)
                  }}
                />
              ) : null}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleAddChild(node.id)
                }}
                className="h-7 px-2 text-xs font-medium text-on-surface-variant hover:text-primary transition-colors"
                title="新增子节点"
              >
                +子项
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleAddSibling(node.id)
                }}
                className="h-7 px-2 text-xs font-medium text-on-surface-variant hover:text-primary transition-colors"
                title="新增同级节点"
              >
                +同级
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleDelete(node.id)
                }}
                className="h-7 w-7 text-error hover:text-error transition-colors flex items-center justify-center"
                title="删除节点"
              >
                <svg viewBox="0 0 20 20" className="w-4 h-4" aria-hidden="true" fill="none">
                  <path d="M5.5 6.5H14.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  <path d="M7 6.5V15.5H13V6.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M8 4.8H12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  <path d="M8.8 8.8V13.2M11.2 8.8V13.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                </svg>
              </button>
            </div>

            {hasChildren && !isCollapsed
              ? renderRows(node.children, depth + 1, seq)
              : null}
          </div>
        )
      })}
    </div>
  )

  if (loading) return <PageLoading title="正在加载目录确认..." />

  if (error) {
    return (
      <PageError
        title="目录确认加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  const hasOnlyOfficeSession = Boolean(tenderPreview?.onlyoffice?.fileUrl && tenderPreview?.onlyoffice?.callbackUrl)
  const activeTenderFileName = tenderPreview?.activeFile?.name || '未选择文件'

  return (
    <div className="stage-page business-ui-shell flex w-full max-w-none flex-col gap-4 animate-fade-in sm:gap-6">
      <StageBreadcrumb />

      <PageHeader
        className="mb-2"
        actionsClassName="stage-header-actions w-full sm:w-auto"
        actions={(
          <Toolbar className="w-full sm:w-auto">
            <Button
              onClick={handleRegenerateDirectory}
              disabled={directoryLocked || saving || confirming}
              size="lg"
              variant="primary"
              className="!h-10 flex-1 sm:flex-none"
            >
              {directoryLocked ? '生成中...' : '重新生成目录'}
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={confirming || directoryLocked}
              size="lg"
              variant="success"
              className="!h-10 flex-1 sm:flex-none"
            >
              {confirming ? '进入中...' : '进入素材匹配'}
            </Button>
          </Toolbar>
        )}
      />

      <OnlyOfficeWorkspace
        heightClass="min-h-0 lg:h-[clamp(36rem,calc(100dvh-13.5rem),57.5rem)]"
        gridClassName="grid-rows-[minmax(22rem,44dvh)_minmax(30rem,56dvh)] lg:grid-rows-none lg:grid-cols-[minmax(24rem,38rem)_minmax(0,1fr)]"
        headerClassName="min-h-[64px] sm:min-h-[72px]"
        documentTitle="招标文件预览"
        documentSubtitle={activeTenderFileName}
        documentMeta={(
          <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${hasOnlyOfficeSession && !onlyofficeError ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {hasOnlyOfficeSession && !onlyofficeError ? '可预览' : '无预览'}
          </span>
        )}
        documentAreaClassName="flex flex-col"
        sidebar={(
          <fieldset
            disabled={directoryLocked}
            className={`flex h-full min-h-0 flex-col overflow-hidden border-0 p-0 ${directoryLocked ? 'opacity-70' : ''}`}
          >
            <div className="flex min-h-[64px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3 sm:min-h-[72px]">
              <h3 className="text-base font-semibold text-on-surface">投标文件目录</h3>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <Button
                  onClick={handleToggleAllCollapse}
                  disabled={!collectExpandableNodeIds(nodes).length}
                  size="sm"
                  variant="quiet"
                >
                  {collapsedNodeIds.size ? '展开全部' : '收起全部'}
                </Button>
                <Button
                  onClick={handleSave}
                  disabled={saving}
                  size="sm"
                  variant="primary"
                >
                  {saving ? '保存中...' : dirty ? '保存目录*' : '保存目录'}
                </Button>
              </div>
            </div>

            <div data-outline-scroll className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5">
              {nodes.length ? (
                renderRows(nodes)
              ) : (
                <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-surface-container-high p-4 text-center sm:min-h-[320px]">
                  <span aria-hidden="true" className="material-symbols-outlined text-4xl text-outline mb-3">account_tree</span>
                  <p className="text-sm text-on-surface-variant">当前目录为空，请新增章节后继续审核。</p>
                  <Button
                    onClick={handleAddRoot}
                    className="mt-4"
                    size="md"
                    variant="primary"
                  >
                    新增一级章节
                  </Button>
                </div>
              )}
            </div>
          </fieldset>
        )}
      >
        {onlyofficeError && (
          <div className="mb-3 rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">
            {onlyofficeError}
          </div>
        )}
        {hasOnlyOfficeSession && !onlyofficeError ? (
          <OnlyOfficeEmbed
            ref={onlyofficeEmbedRef}
            session={tenderPreview?.onlyoffice}
            mode="view"
            enableSearchPlugin
            className="h-full min-h-0 w-full rounded-md border border-surface-container-high bg-white"
            onReady={() => {
              setOnlyofficeError('')
              if (pendingSearchText) {
                setTimeout(() => {
                  sendOnlyOfficeSearch(pendingSearchText, onlyofficeEmbedRef, markPendingSearch)
                }, 300)
              }
            }}
            onError={(message) => setOnlyofficeError(message || 'OnlyOffice 文档加载失败')}
          />
        ) : (
          <div className="flex min-h-[28rem] flex-1 items-center justify-center rounded-md border border-dashed border-surface-container-high px-4 text-center sm:px-6 lg:min-h-[32rem]">
            <p className="text-sm text-on-surface-variant">
              {tenderPreview?.message || '暂无可预览的招标文件。'}
            </p>
          </div>
        )}
      </OnlyOfficeWorkspace>
      <TechnicalMaterialMatchProgressModal
        open={materialMatchModalOpen}
        status={materialMatchStatus}
        itemCount={countNodes(nodes)}
        onClose={() => setMaterialMatchModalOpen(false)}
        onStop={handleStopMaterialMatch}
        stopping={materialMatchStopping}
      />
      <DirectoryGenerationProgressModal
        open={regenerationModalOpen}
        state={regenerating && regenerationPendingState ? regenerationPendingState : directoryState}
        nowMs={directoryProgressClock}
        onClose={() => setRegenerationModalOpen(false)}
        onStop={handleStopDirectory}
        stopping={directoryStopping}
      />
    </div>
  )
}
