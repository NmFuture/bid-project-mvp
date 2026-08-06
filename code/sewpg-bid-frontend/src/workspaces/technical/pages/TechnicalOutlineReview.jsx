import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalDirectoryAPI, technicalGapsAPI, technicalOutlineAPI, technicalProjectsAPI, technicalStagesAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import MaterialMatchProgressModal from '../../../components/shared/MaterialMatchProgressModal'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../../../components/shared/OnlyOfficeWorkspace'
import Button from '../../../components/ui/Button'
import { Dialog, DialogBody, DialogFooter, DialogHeader } from '../../../components/ui/Dialog'
import Toolbar from '../../../components/ui/Toolbar'
import { getOutlineDisplayNumber } from '../../../utils/outlineNumber'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import OutlineActionTag from '../components/OutlineActionTag'
import { getTechnicalStageRoute } from '../technicalStageFlow'
import {
  beginDirectoryProgressEpoch,
  buildDirectoryRegenerationPrompt,
  directoryElapsedSeconds,
  estimateDirectoryDisplayPercentage,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  loadConsistentOutlineReviewSnapshot,
  mergeMonotonicDirectoryProgress,
  summarizeDirectoryProgress,
} from '../technicalDirectoryProgress'
import {
  markOutlineNodeEdited,
  pickTenderBasis,
  shouldPreserveOutlineNumber,
  tenderBasisSearchText,
} from '../utils/outlineEvidence'

const cloneNodes = (nodes = []) => JSON.parse(JSON.stringify(nodes))
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

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

function DirectoryGenerationProgressModal({ open, state, progress, onClose }) {
  if (!open) return null
  const summary = summarizeDirectoryProgress(state || {})
  const running = isDirectoryProgressRunning(state)
  const completed = state?.status === 'completed'
  const failed = isDirectoryProgressFailed(state)

  return (
    <Dialog open={open} onClose={onClose} size="sm">
      <DialogHeader onClose={onClose}>
        <h3 className="text-lg font-headline font-bold text-on-surface">
          {running ? '正在重新生成目录' : completed ? '目录重新生成完成' : failed ? '目录重新生成失败' : '重新生成目录'}
        </h3>
        <p className="mt-1 text-sm text-on-surface-variant">{summary.summary}</p>
      </DialogHeader>
      <DialogBody className="space-y-4 p-5">
        <div className="flex items-center gap-3">
          <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-container-high">
            <div
              className={`h-full transition-all duration-700 ${failed ? 'bg-error' : completed ? 'bg-secondary' : 'bg-primary'}`}
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="w-12 text-right text-xs font-semibold text-outline">{Math.floor(progress)}%</span>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {summary.steps.map((step) => (
            <div
              key={step.id}
              className={`min-h-14 border px-3 py-2 text-xs ${
                step.status === 'failed'
                  ? 'border-error/30 bg-error/10 text-error'
                  : step.status === 'done'
                    ? 'border-secondary/25 bg-secondary-container/35 text-on-secondary-container'
                    : step.status === 'running'
                      ? 'border-primary/30 bg-primary/5 text-primary'
                      : 'border-surface-container-high bg-surface-container-low text-outline'
              }`}
            >
              <div className="font-semibold">{step.label}</div>
              <div className="mt-1">{step.status === 'done' ? '已完成' : step.status === 'running' ? '进行中' : step.status === 'failed' ? '失败' : '等待中'}</div>
            </div>
          ))}
        </div>
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
      </DialogBody>
      <DialogFooter>
        <Button type="button" onClick={onClose} variant={completed ? 'primary' : 'quiet'}>关闭</Button>
      </DialogFooter>
    </Dialog>
  )
}

export default function TechnicalOutlineReview({ showToast, workspaceKind = 'tech' }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const routeWorkspaceSlug = useWorkspaceSlug()
  const workspaceSlug = workspaceKind || routeWorkspaceSlug
  const [nodes, setNodes] = useState([])
  const [activeNodeId, setActiveNodeId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerationModalOpen, setRegenerationModalOpen] = useState(false)
  const [directoryState, setDirectoryState] = useState(null)
  const [directoryProgressClock, setDirectoryProgressClock] = useState(() => Date.now())
  const [reviewStatus, setReviewStatus] = useState('draft')
  const [currentStage, setCurrentStage] = useState(2)
  const [materialMatchProgress, setMaterialMatchProgress] = useState({
    open: false,
    running: false,
    error: '',
  })
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

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const { outlinePayload, generationPayload, projectPayload } = await loadConsistentOutlineReviewSnapshot({
        loadDirectoryState: () => technicalDirectoryAPI.status(id).catch(() => null),
        loadOutline: () => technicalOutlineAPI.get(id),
        loadProject: () => technicalProjectsAPI.get(id).catch(() => null),
      })
      applyOutlinePayload(outlinePayload)
      setDirectoryState((previous) => mergeMonotonicDirectoryProgress(previous, generationPayload))
      if (isDirectoryProgressRunning(generationPayload)) setRegenerationModalOpen(true)
      setCurrentStage(Number(projectPayload?.currentStage) || 2)
    } catch (e) {
      setError(e?.message || '目录数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [applyOutlinePayload, id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const directoryRunning = isDirectoryProgressRunning(directoryState)
  const directoryLocked = regenerating || directoryRunning
  const directoryElapsed = directoryElapsedSeconds(directoryState || {}, directoryProgressClock)
  const directoryProgress = estimateDirectoryDisplayPercentage({
    status: directoryState?.status || 'idle',
    elapsedSeconds: directoryElapsed,
    fallbackPercentage: directoryState?.percentage || 0,
  })

  useEffect(() => {
    if (!directoryRunning) return undefined
    const timer = window.setInterval(() => setDirectoryProgressClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [directoryRunning])

  useEffect(() => {
    if (!directoryRunning) return undefined
    let cancelled = false
    let timer = null

    const pollDirectoryStatus = async () => {
      try {
        const payload = await technicalDirectoryAPI.status(id)
        if (cancelled) return
        if (payload?.status === 'completed') {
          const [outlinePayload, projectPayload] = await Promise.all([
            technicalOutlineAPI.get(id),
            technicalProjectsAPI.get(id).catch(() => null),
          ])
          if (cancelled) return
          setDirectoryState((previous) => mergeMonotonicDirectoryProgress(previous, payload))
          applyOutlinePayload(outlinePayload)
          setCurrentStage(Number(projectPayload?.currentStage) || 2)
          setRegenerating(false)
          showToast?.('目录重新生成完成，请重新审核。')
          return
        }
        setDirectoryState((previous) => mergeMonotonicDirectoryProgress(previous, payload))
        if (isDirectoryProgressFailed(payload)) {
          setRegenerating(false)
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
    const confirmed = window.confirm(buildDirectoryRegenerationPrompt({
      dirty,
      hasDownstreamResults: currentStage > 2 || reviewStatus === 'confirmed',
    }))
    if (!confirmed) return

    setRegenerating(true)
    setRegenerationModalOpen(true)
    try {
      const payload = await technicalOutlineAPI.regenerate(id)
      setDirectoryState((previous) => beginDirectoryProgressEpoch({ previous, incoming: payload }))
      showToast?.(payload?.message || '已开始重新生成目录。')
    } catch (e) {
      setRegenerationModalOpen(false)
      showToast?.(e?.message || '启动目录重新生成失败', 'error')
    } finally {
      setRegenerating(false)
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

    setConfirming(true)
    setMaterialMatchProgress({ open: true, running: true, error: '' })
    try {
      if (dirty) {
        const nodesToSave = renumberOutlineNodes(nodes)
        const saved = await technicalOutlineAPI.save(id, { nodes: nodesToSave })
        setNodes(Array.isArray(saved?.nodes) ? saved.nodes : [])
        setDirty(false)
      }

      await technicalOutlineAPI.confirm(id)
      setReviewStatus('confirmed')
      showToast?.('目录确认已完成，正在执行素材匹配...')
      await technicalGapsAPI.runDetection(id)
      setMaterialMatchProgress({ open: true, running: false, error: '' })
      const stageResult = await technicalStagesAPI.update(id, 2, { status: 'completed' })
      const nextStageId = Number(stageResult?.currentStage) || 3
      const nextRoute = getTechnicalStageRoute(id, nextStageId, workspaceSlug) || projectRoute(id, '/gaps', workspaceSlug)
      showToast?.('素材匹配已完成，已进入素材匹配')
      await delay(350)
      navigate(nextRoute)
    } catch (e) {
      const message = e?.message || '目录确认或素材匹配失败，请稍后重试'
      setMaterialMatchProgress({ open: true, running: false, error: message })
      showToast?.(message, 'error')
    } finally {
      setConfirming(false)
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
                  onClick={(e) => {
                    e.stopPropagation()
                    handleToggleNodeCollapse(node.id)
                  }}
                  className="h-6 w-6 shrink-0 flex items-center justify-center text-outline hover:text-primary transition-colors"
                  title={isCollapsed ? '展开' : '收起'}
                >
                  <span className="material-symbols-outlined text-[16px]">
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
                className="flex-1 !min-h-0 h-8 px-1.5 border-0 bg-transparent text-sm text-on-surface focus:ring-0 focus:outline-none"
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
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none business-ui-shell">
      <StageBreadcrumb />
      <TechnicalProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        className="mb-2"
        actionsClassName="stage-header-actions"
        actions={(
          <Toolbar>
            <Button
              onClick={handleRegenerateDirectory}
              disabled={directoryLocked || saving || confirming}
              size="lg"
              variant="primary"
            >
              {directoryLocked ? '生成中...' : '重新生成目录'}
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={confirming || directoryLocked}
              size="lg"
              variant="success"
            >
              {confirming ? '进入中...' : '进入素材匹配'}
            </Button>
          </Toolbar>
        )}
      />

      <OnlyOfficeWorkspace
        heightClass="h-[calc(100vh-13.5rem)] min-h-[680px] max-h-[920px]"
        gridClassName="grid-rows-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-none lg:grid-cols-[minmax(24rem,38rem)_minmax(0,1fr)]"
        headerClassName="h-[72px] min-h-[72px]"
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
            <div className="flex h-[72px] min-h-[72px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
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

            <div data-outline-scroll className="min-h-0 flex-1 overflow-y-auto p-5">
              {nodes.length ? (
                renderRows(nodes)
              ) : (
                <div className="h-[320px] rounded-lg border border-dashed border-surface-container-high flex flex-col items-center justify-center text-center">
                  <span className="material-symbols-outlined text-4xl text-outline mb-3">account_tree</span>
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
          <div className="flex min-h-[560px] flex-1 items-center justify-center rounded-md border border-dashed border-surface-container-high px-6 text-center">
            <p className="text-sm text-on-surface-variant">
              {tenderPreview?.message || '暂无可预览的招标文件。'}
            </p>
          </div>
        )}
      </OnlyOfficeWorkspace>
      <MaterialMatchProgressModal
        open={materialMatchProgress.open}
        running={materialMatchProgress.running}
        error={materialMatchProgress.error}
        onClose={() => setMaterialMatchProgress({ open: false, running: false, error: '' })}
      />
      <DirectoryGenerationProgressModal
        open={regenerationModalOpen}
        state={directoryState}
        progress={directoryProgress}
        onClose={() => setRegenerationModalOpen(false)}
      />
    </div>
  )
}
