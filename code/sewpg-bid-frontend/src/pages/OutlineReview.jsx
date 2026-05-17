import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { outlineAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../components/shared/OnlyOfficeWorkspace'
import { getOutlineDisplayNumber } from '../utils/outlineNumber'
import { getStageRoute } from '../utils/stageFlow'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const cloneNodes = (nodes = []) => JSON.parse(JSON.stringify(nodes))

const createNode = (title = '新章节') => ({
  id: `OL-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title,
  children: [],
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

const SEARCH_STORAGE_KEY = 'onlyoffice-search-bridge-message'
const SEARCH_CHANNEL_NAME = 'onlyoffice-search-bridge'
const SEARCH_RESULT_SOURCE = 'onlyoffice-search-bridge'

const collectSourceRefs = (node) => {
  if (Array.isArray(node?.sourceRefs)) return node.sourceRefs
  if (Array.isArray(node?.source_refs)) return node.source_refs
  return []
}

const isBusinessOutlineNode = (node) =>
  node?.source === 'business_outline' ||
  collectSourceRefs(node).some((ref) => ref?.kind === 'business_outline_section')

const pickTenderBasisRef = (node) => {
  const refs = collectSourceRefs(node).filter((ref) => ref?.type === 'tender')
  return refs.find((ref) => ref?.role === 'basis') || refs[0] || null
}

const sourceRefSearchText = (ref) =>
  String(ref?.searchText || ref?.basisText || ref?.rawText || ref?.raw_text || ref?.title || '')
    .replace(/\s+/g, ' ')
    .trim()

const nodeSearchText = (node) => {
  const refText = collectSourceRefs(node).map(sourceRefSearchText).find(Boolean) || ''
  return String(node?.sourceText || node?.source_text || refText || node?.title || '')
    .replace(/\s+/g, ' ')
    .trim()
}

const requiredStatusLabel = (node) => {
  const explicit = String(node?.requiredStatus || node?.required_status || '').trim()
  if (explicit) return explicit
  if (!isBusinessOutlineNode(node)) return ''
  const annotation = String(node?.annotation || '').trim()
  if (annotation === '保留') return '必要'
  return annotation
}

const requiredStatusClassName = (status) => {
  if (status === '必要') {
    return 'border-primary/20 bg-primary/10 text-primary'
  }
  if (status === '可选') {
    return 'border-surface-container-high bg-surface-container-high text-on-surface-variant'
  }
  if (status === '待确认') {
    return 'border-amber-200 bg-amber-50 text-amber-950'
  }
  return 'border-secondary/20 bg-secondary-container text-on-secondary-container'
}

const relationLabel = (relation = '') => {
  const labels = {
    direct_requirement: '直接要求',
    chapter_requirement: '章节要求',
    appendix_requirement: '附表要求',
    appendix_required: '附表要求',
    supporting_requirement: '支撑要求',
    semantic_match: '语义匹配',
  }
  return labels[relation] || relation || ''
}

const confidenceLabel = (value) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return ''
  return `置信 ${Math.round(value * 100)}%`
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

export default function OutlineReview({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const isBusinessWorkspace = workspaceSlug === 'business'
  const [nodes, setNodes] = useState([])
  const [activeNodeId, setActiveNodeId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [tenderPreview, setTenderPreview] = useState(null)
  const [onlyofficeError, setOnlyofficeError] = useState('')
  const [collapsedNodeIds, setCollapsedNodeIds] = useState(new Set())
  const [pendingSearchText, setPendingSearchText] = useState('')
  const [activeBasisRef, setActiveBasisRef] = useState(null)
  const onlyofficeEmbedRef = useRef(null)
  const pendingSearchNonceRef = useRef('')

  const markPendingSearch = useCallback((nonce) => {
    pendingSearchNonceRef.current = nonce || ''
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await outlineAPI.get(id)
      const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
      setNodes(nextNodes)
      setDirty(false)
      setActiveNodeId(nextNodes[0]?.id || '')
      setCollapsedNodeIds(
        countNodes(nextNodes) > 180
          ? new Set(collectExpandableNodeIds(nextNodes))
          : new Set(),
      )
      setTenderPreview(payload?.tenderPreview || null)
      setOnlyofficeError('')
    } catch (e) {
      setError(e?.message || '目录数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

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

  const focusSourceRef = useCallback(async (basisRef) => {
    if (!basisRef) return
    const searchText = sourceRefSearchText(basisRef)
    if (!searchText) return

    setActiveBasisRef(basisRef)
    const refFileId = String(basisRef.fileId || '').trim()
    const activeFileId = String(tenderPreview?.activeFile?.id || '').trim()
    if (basisRef?.type === 'tender' && refFileId && refFileId !== activeFileId) {
      try {
        const payload = await outlineAPI.get(id, { fileId: refFileId })
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

  const focusTenderBasis = useCallback(async (node) => {
    const basisRef = pickTenderBasisRef(node)
    if (basisRef) {
      await focusSourceRef(basisRef)
      return
    }
    const searchText = nodeSearchText(node)
    if (searchText) {
      setActiveBasisRef(null)
      sendOnlyOfficeSearch(searchText, onlyofficeEmbedRef, markPendingSearch)
    }
  }, [focusSourceRef, markPendingSearch])

  const handleSave = async () => {
    if (saving) return
    if (!dirty) {
      showToast?.('目录暂无变更，无需保存。')
      return
    }

    setSaving(true)
    try {
      const payload = await outlineAPI.save(id, { nodes })
      const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
      setNodes(nextNodes)
      setDirty(false)
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

  const handleReject = async () => {
    const shouldRegenerate = window.confirm('将按 S2 的目录结果重生成 S3，当前未保存修改会丢失。确认继续吗？')
    if (!shouldRegenerate) return

    setRejecting(true)
    try {
      const payload = await outlineAPI.regenerate(id)
      const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
      setNodes(nextNodes)
      setDirty(false)
      setActiveNodeId(nextNodes[0]?.id || '')
      showToast?.(payload?.message || '已重生成目录审核稿')
    } catch (e) {
      showToast?.(e?.message || '重生成失败，请稍后重试', 'error')
    } finally {
      setRejecting(false)
    }
  }

  const handleConfirm = async () => {
    if (!nodes.length) {
      showToast?.('目录为空，请先新增章节后再确认。', 'error')
      return
    }

    setConfirming(true)
    try {
      if (dirty) {
        const saved = await outlineAPI.save(id, { nodes })
        setNodes(Array.isArray(saved?.nodes) ? saved.nodes : [])
        setDirty(false)
      }

      await outlineAPI.confirm(id)
      const stageResult = await stagesAPI.update(id, 2, { status: 'completed' })
      const nextStageId = Number(stageResult?.currentStage) || 3
      const nextRoute = getStageRoute(id, nextStageId, workspaceSlug) || projectRoute(id, '/gaps', workspaceSlug)
      showToast?.('目录确认已完成，已进入素材匹配')
      navigate(nextRoute)
    } catch (e) {
      showToast?.(e?.message || '目录确认失败，请稍后重试', 'error')
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

  const handleMove = (targetId, direction) => {
    setDirty(true)
    setNodes((prev) => {
      const next = cloneNodes(prev)
      const context = findNodeContext(next, targetId)
      if (!context) return prev
      const toIndex = direction === 'up' ? context.index - 1 : context.index + 1
      if (toIndex < 0 || toIndex >= context.siblings.length) return prev
      const [current] = context.siblings.splice(context.index, 1)
      context.siblings.splice(toIndex, 0, current)
      return next
    })
  }

  const handleTitleChange = (targetId, value) => {
    setDirty(true)
    setNodes((prev) => {
      const next = cloneNodes(prev)
      const context = findNodeContext(next, targetId)
      if (!context) return prev
      context.node.title = value
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
        const siblings = items || []
        const canMoveUp = index > 0
        const canMoveDown = index < siblings.length - 1
        const hasChildren = Array.isArray(node.children) && node.children.length > 0
        const isCollapsed = collapsedNodeIds.has(node.id)
        const status = requiredStatusLabel(node)
        const canFocusBasis = Boolean(pickTenderBasisRef(node) || nodeSearchText(node))
        const displayNumber = getOutlineDisplayNumber(node)

        return (
          <div key={node.id}>
            <div
              onClick={() => {
                setActiveNodeId(node.id)
                focusTenderBasis(node)
              }}
              className={`flex items-center gap-1 px-2 py-1.5 transition-colors border-b border-surface-container-high ${
                isActive ? 'bg-primary/5' : 'bg-white'
              }`}
              style={{ marginLeft: `${depth * 20}px` }}
            >
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
              <span className={`${isBusinessWorkspace ? 'w-20' : 'w-9'} shrink-0 text-xs font-semibold text-outline`}>{displayNumber}</span>
              <input
                value={node.title || ''}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => handleTitleChange(node.id, e.target.value)}
                className="flex-1 !min-h-0 h-8 px-1.5 border-0 bg-transparent text-sm text-on-surface focus:ring-0 focus:outline-none"
                placeholder="输入章节标题"
              />
              {status ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    setActiveNodeId(node.id)
                    focusTenderBasis(node)
                  }}
                  disabled={!canFocusBasis}
                  className={`shrink-0 rounded border px-2 py-1 text-[11px] font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-secondary/30 disabled:cursor-default ${requiredStatusClassName(status)} ${canFocusBasis ? 'hover:brightness-95' : ''}`}
                  title={canFocusBasis ? '点击定位招标依据' : ''}
                >
                  {status}
                </button>
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
                  handleMove(node.id, 'up')
                }}
                disabled={!canMoveUp}
                className="h-7 w-7 text-outline hover:text-primary transition-colors disabled:opacity-35 disabled:cursor-not-allowed flex items-center justify-center"
                title="上移"
              >
                <svg viewBox="0 0 20 20" className="w-4 h-4" aria-hidden="true" fill="none">
                  <path d="M10 16V5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <path d="M6.5 8.5L10 5L13.5 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleMove(node.id, 'down')
                }}
                disabled={!canMoveDown}
                className="h-7 w-7 text-outline hover:text-primary transition-colors disabled:opacity-35 disabled:cursor-not-allowed flex items-center justify-center"
                title="下移"
              >
                <svg viewBox="0 0 20 20" className="w-4 h-4" aria-hidden="true" fill="none">
                  <path d="M10 4V15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  <path d="M6.5 11.5L10 15L13.5 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
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
  const activeNode = findNodeContext(nodes, activeNodeId)?.node || null
  const activeRefs = collectSourceRefs(activeNode)

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        leftExtra={(
          <div>
            <p className="text-xs font-semibold text-primary">审核目录</p>
            <h1 className="mt-1 text-lg font-headline font-bold text-on-surface">确认投标文件目录</h1>
          </div>
        )}
        className="rounded-md border border-outline-variant/50 bg-white px-5 py-4 shadow-[0_1px_3px_rgba(13,33,55,0.06)]"
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={handleReject}
              disabled={rejecting}
              className="px-4 py-2.5 text-sm font-medium text-on-surface-variant bg-surface-container-high hover:bg-surface-dim rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {rejecting ? '处理中...' : '驳回重生成'}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2.5 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? '保存中...' : dirty ? '保存目录*' : '保存目录'}
            </button>
            <button
              onClick={handleConfirm}
              disabled={confirming}
              className="px-4 py-2.5 text-sm font-medium text-on-secondary bg-secondary hover:bg-secondary/90 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {confirming ? '进入中...' : '确认目录并进入素材匹配'}
            </button>
          </>
        )}
      />

      <OnlyOfficeWorkspace
        heightClass="h-[calc(100vh-16rem)] min-h-[620px] max-h-[860px]"
        gridClassName="grid-rows-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-none lg:grid-cols-[minmax(24rem,38rem)_minmax(0,1fr)]"
        documentTitle="招标文件预览"
        documentSubtitle={activeTenderFileName}
        documentMeta={(
          <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${hasOnlyOfficeSession && !onlyofficeError ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {hasOnlyOfficeSession && !onlyofficeError ? '可预览' : '无预览'}
          </span>
        )}
        documentAreaClassName="flex flex-col"
        sidebar={(
          <section className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
              <h3 className="text-base font-semibold text-on-surface">投标文件目录</h3>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleToggleAllCollapse}
                  disabled={!collectExpandableNodeIds(nodes).length}
                  className="stage-action-btn px-3 py-1.5 rounded-lg bg-surface-container-high text-on-surface-variant text-xs font-semibold hover:bg-surface-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {collapsedNodeIds.size ? '展开全部' : '收起全部'}
                </button>
                <button
                  onClick={handleAddRoot}
                  className="stage-action-btn px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-semibold hover:bg-primary-container transition-colors"
                >
                  新增一级
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {nodes.length ? (
                renderRows(nodes)
              ) : (
                <div className="h-[320px] rounded-lg border border-dashed border-surface-container-high flex flex-col items-center justify-center text-center">
                  <span className="material-symbols-outlined text-4xl text-outline mb-3">account_tree</span>
                  <p className="text-sm text-on-surface-variant">当前目录为空，请新增章节后继续审核。</p>
                  <button
                    onClick={handleAddRoot}
                    className="mt-4 px-4 py-2 text-sm font-medium bg-primary text-on-primary rounded-lg hover:bg-primary-container transition-colors"
                  >
                    新增一级章节
                  </button>
                </div>
              )}
            </div>
            {activeRefs.length ? (
              <div className="max-h-[34%] min-h-[140px] overflow-y-auto border-t border-surface-container-high bg-white px-5 py-4">
                <h4 className="text-xs font-semibold text-on-surface">当前目录依据</h4>
                <div className="mt-2 flex flex-col gap-2">
                  {activeRefs.slice(0, 4).map((ref, index) => {
                    const searchText = sourceRefSearchText(ref)
                    const isTender = ref?.type === 'tender'
                    const isSemantic = ref?.kind === 'codex_semantic'
                    const relation = relationLabel(ref?.relation)
                    const confidence = confidenceLabel(ref?.confidence)
                    const selected = activeBasisRef === ref
                    return (
                      <button
                        key={`${ref?.type || 'ref'}-${ref?.paragraphIndex || index}-${index}`}
                        type="button"
                        onClick={() => {
                          if (!isTender || !searchText) return
                          setActiveBasisRef(ref)
                          focusSourceRef(ref)
                        }}
                        disabled={!isTender || !searchText}
                        className={`rounded-md border px-3 py-2 text-left text-xs transition-colors disabled:cursor-default disabled:opacity-70 ${
                          selected
                            ? 'border-primary bg-primary/5 text-on-surface'
                            : 'border-surface-container-high bg-surface-container-low text-on-surface-variant enabled:hover:border-primary enabled:hover:bg-primary/5'
                        }`}
                        title={searchText}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-1.5">
                            <span className="font-semibold text-on-surface">
                              {isTender ? (isSemantic ? '语义依据' : '招标依据') : '模板骨架'}
                            </span>
                            {relation ? (
                              <span className="rounded bg-secondary-container px-1.5 py-0.5 text-[10px] font-semibold text-on-secondary-container">
                                {relation}
                              </span>
                            ) : null}
                            {confidence ? (
                              <span className="rounded bg-surface-container-high px-1.5 py-0.5 text-[10px] font-semibold text-on-surface-variant">
                                {confidence}
                              </span>
                            ) : null}
                          </div>
                          <span className="shrink-0">{ref?.fileName || ref?.type || '-'}</span>
                        </div>
                        {ref?.reason ? (
                          <div className="mt-1 line-clamp-2 text-on-surface">{ref.reason}</div>
                        ) : null}
                        <div className="mt-1 line-clamp-2">{searchText || ref?.rawText || ref?.raw_text || '-'}</div>
                      </button>
                    )
                  })}
                </div>
              </div>
            ) : null}
          </section>
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
    </div>
  )
}
