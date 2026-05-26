import { useCallback, useMemo, useRef, useState, useEffect } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/TechnicalMaterialsViewSwitch'
import MarkdownLite from '../../../components/shared/MarkdownLite'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import { useWorkspaceSlug, workspaceRoute } from '../../../utils/workspace'

const normalizeArray = (value) =>
  Array.isArray(value) ? [...new Set(value)].filter(Boolean).sort() : []

const sameArray = (left, right) => {
  const a = normalizeArray(left)
  const b = normalizeArray(right)
  if (a.length !== b.length) return false
  return a.every((item, index) => item === b[index])
}

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const normalizeNode = (node) => {
  if (!node) return null
  return {
    ...node,
    title: String(node.title || ''),
    markdownContent: String(node.markdownContent || ''),
    aiSummary: String(node.aiSummary || ''),
    tags: Array.isArray(node.tags) ? node.tags : [],
    applicableTypes: Array.isArray(node.applicableTypes) ? node.applicableTypes : [],
    attachments: Array.isArray(node.attachments) ? node.attachments : [],
    path: String(node.path || ''),
    pathText: String(node.pathText || node.path || ''),
    updatedAt: String(node.updatedAt || ''),
  }
}

const normalizeDraft = (node) => ({
  title: String(node?.title || ''),
  markdownContent: String(node?.markdownContent || ''),
  tags: Array.isArray(node?.tags) ? node.tags : [],
  applicableTypes: Array.isArray(node?.applicableTypes) ? node.applicableTypes : [],
})

export default function MaterialWiki({ showToast = () => {} }) {
  const workspaceSlug = useWorkspaceSlug()
  const materialsBasePath = workspaceRoute(workspaceSlug || 'tech', '/materials')
  const activeBidType = '技术标'
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [draft, setDraft] = useState(normalizeDraft(null))
  const [saving, setSaving] = useState(false)
  const [refreshingSummary, setRefreshingSummary] = useState(false)
  const [refreshingWiki, setRefreshingWiki] = useState(false)
  const [rebuildingWiki, setRebuildingWiki] = useState(false)
  const [creatingNode, setCreatingNode] = useState(false)
  const [movingNode, setMovingNode] = useState(false)
  const [deletingNode, setDeletingNode] = useState(false)
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [deletingAttachmentId, setDeletingAttachmentId] = useState('')

  const [dragNodeId, setDragNodeId] = useState('')
  const [collapsedMap, setCollapsedMap] = useState({})

  const editorRef = useRef(null)
  const uploadInputRef = useRef(null)

  const applyPayload = useCallback((payload) => {
    setData(payload)
    setDraft(normalizeDraft(payload?.selectedNode))
    setError('')
  }, [])

  const loadData = useCallback(async (params = {}, options = {}) => {
    if (options.silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }

    try {
      const response = await technicalMaterialsAPI.wiki.list({
        ...params,
        bidType: activeBidType,
      })
      applyPayload(response)
    } catch (e) {
      console.error(e)
      const message = safeMessage(e, 'Wiki 数据加载失败，请稍后重试。')
      setError(message)
      if (options.silent) {
        showToast(message, 'error')
      }
    } finally {
      if (options.silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [activeBidType, applyPayload, showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const selectedNode = useMemo(() => normalizeNode(data?.selectedNode), [data])
  const selectedNodeId = selectedNode?.id || ''
  const tree = data?.tree || []
  const tagOptions = data?.tagOptions || []
  const applicableTypeOptions = data?.applicableTypeOptions || []

  const attachments = useMemo(
    () =>
      (selectedNode?.attachments || []).map((item, index) => ({
        id: item?.id || `att-${index}`,
        name: String(item?.name || '未命名附件'),
        size: String(item?.size || '-'),
        time: String(item?.time || '-'),
        downloadUrl: item?.downloadUrl || '',
      })),
    [selectedNode],
  )

  const isDirty = useMemo(() => {
    if (!selectedNode) return false
    if (draft.title !== selectedNode.title) return true
    if (draft.markdownContent !== selectedNode.markdownContent) return true
    if (!sameArray(draft.tags, selectedNode.tags)) return true
    if (!sameArray(draft.applicableTypes, selectedNode.applicableTypes)) return true
    return false
  }, [draft, selectedNode])

  const isExpanded = useCallback(
    (node) => {
      if (!Array.isArray(node.children)) return false
      if (Object.prototype.hasOwnProperty.call(collapsedMap, node.id)) {
        return !collapsedMap[node.id]
      }
      return node.expanded !== false
    },
    [collapsedMap],
  )

  const toggleExpand = (node) => {
    const expanded = isExpanded(node)
    setCollapsedMap((prev) => ({ ...prev, [node.id]: expanded }))
  }

  const handleSelectNode = async (nodeId) => {
    if (!nodeId || nodeId === selectedNodeId) return
    await loadData({ nodeId }, { silent: true })
  }

  const handleCreateNode = async (isFolder = false) => {
    setCreatingNode(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.create({
        parentId: selectedNodeId,
        title: isFolder ? '新建目录' : '新建节点',
        isFolder,
        bidType: activeBidType,
      })
      applyPayload(payload)
      showToast(isFolder ? '目录创建成功' : '节点创建成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '创建节点失败，请稍后重试。'), 'error')
    } finally {
      setCreatingNode(false)
    }
  }

  const handleSave = async () => {
    if (!selectedNodeId) return
    const title = draft.title.trim()
    if (!title) {
      showToast('节点标题不能为空', 'error')
      return
    }

    setSaving(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.update(selectedNodeId, {
        title,
        markdownContent: draft.markdownContent,
        tags: draft.tags,
        applicableTypes: draft.applicableTypes,
        bidType: activeBidType,
      })
      applyPayload(payload)
      showToast('节点保存成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '节点保存失败，请稍后重试。'), 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteNode = async (nodeId = selectedNodeId, title = selectedNode?.title || '') => {
    if (!nodeId) return
    const ok = window.confirm(`确认删除 Wiki 节点：${title || nodeId} ？\n\n该节点下的子节点、正文和附件也会一起删除。`)
    if (!ok) return
    setDeletingNode(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.delete(nodeId, { bidType: activeBidType })
      applyPayload(payload)
      showToast(payload?.message || 'Wiki 节点删除成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '删除 Wiki 节点失败，请稍后重试。'), 'error')
    } finally {
      setDeletingNode(false)
    }
  }

  const handleRefreshSummary = async () => {
    if (!selectedNodeId) return
    setRefreshingSummary(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.refreshSummary(selectedNodeId, { bidType: activeBidType })
      applyPayload(payload)
      showToast('摘要已刷新')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '摘要刷新失败，请稍后重试。'), 'error')
    } finally {
      setRefreshingSummary(false)
    }
  }

  const handleRefreshWiki = async () => {
    const ok = window.confirm(`确认刷新${activeBidType} Wiki？系统会重新读取当前素材库，并替换自动生成的 Wiki 节点。`)
    if (!ok) return
    setRefreshingWiki(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.bootstrap({
        mode: 'refresh',
        bidType: activeBidType,
      })
      applyPayload(payload)
      showToast(payload?.generation?.summary || payload?.message || `${activeBidType} Wiki 已刷新`)
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '刷新 Wiki 失败，请稍后重试。'), 'error')
    } finally {
      setRefreshingWiki(false)
    }
  }

  const handleRebuildWiki = async () => {
    const ok = window.confirm(`确认重建${activeBidType} Wiki？现有自动生成根树会被重新生成。`)
    if (!ok) return
    setRebuildingWiki(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.bootstrap({
        mode: 'replace',
        bidType: activeBidType,
      })
      applyPayload(payload)
      showToast(payload?.generation?.summary || payload?.message || `${activeBidType} Wiki 已重建`)
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '重建 Wiki 失败，请稍后重试。'), 'error')
    } finally {
      setRebuildingWiki(false)
    }
  }

  const toggleDraftListValue = (field, value) => {
    setDraft((prev) => {
      const current = Array.isArray(prev[field]) ? prev[field] : []
      const exists = current.includes(value)
      const next = exists ? current.filter((item) => item !== value) : [...current, value]
      return { ...prev, [field]: next }
    })
  }

  const handleUploadAttachment = async (file) => {
    if (!file || !selectedNodeId) return

    setUploadingAttachment(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('fileName', file.name)
      formData.append('fileSize', String(file.size))
      formData.append('bidType', activeBidType)
      const payload = await technicalMaterialsAPI.wiki.uploadAttachment(selectedNodeId, formData)
      applyPayload(payload)
      showToast('附件上传成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '附件上传失败，请稍后重试。'), 'error')
    } finally {
      setUploadingAttachment(false)
    }
  }

  const handleDeleteAttachment = async (attachment) => {
    if (!attachment?.id) return
    const ok = window.confirm(`确认删除附件：${attachment.name} ？`)
    if (!ok) return
    setDeletingAttachmentId(attachment.id)
    try {
      const payload = await technicalMaterialsAPI.wiki.deleteAttachment(attachment.id, { bidType: activeBidType })
      applyPayload(payload)
      showToast(payload?.message || '附件删除成功')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '附件删除失败，请稍后重试。'), 'error')
    } finally {
      setDeletingAttachmentId('')
    }
  }

  const handleMoveNode = async (movingId, targetNode, mode) => {
    if (!movingId || !targetNode?.id || movingId === targetNode.id) return
    setMovingNode(true)
    try {
      const payload = await technicalMaterialsAPI.wiki.move(movingId, {
        targetId: targetNode.id,
        mode,
        bidType: activeBidType,
      })
      applyPayload(payload)
      showToast(mode === 'inside' ? '节点已移动为子节点' : '节点顺序已更新')
    } catch (e) {
      console.error(e)
      showToast(safeMessage(e, '节点移动失败，请稍后重试。'), 'error')
    } finally {
      setMovingNode(false)
    }
  }

  const insertAroundSelection = (prefix, suffix = '') => {
    const target = editorRef.current
    if (!target) return
    const start = target.selectionStart || 0
    const end = target.selectionEnd || 0
    const before = draft.markdownContent.slice(0, start)
    const selected = draft.markdownContent.slice(start, end)
    const after = draft.markdownContent.slice(end)
    const next = `${before}${prefix}${selected}${suffix}${after}`
    setDraft((prev) => ({ ...prev, markdownContent: next }))

    requestAnimationFrame(() => {
      target.focus()
      const cursor = start + prefix.length + selected.length + suffix.length
      target.setSelectionRange(cursor, cursor)
    })
  }

  const renderTree = (nodes, level = 0) =>
    (nodes || []).map((node) => {
      const folder = Array.isArray(node.children)
      const expanded = folder ? isExpanded(node) : false
      const selected = node.id === selectedNodeId
      const draggable = !movingNode

      return (
        <div key={node.id}>
          <div
            draggable={draggable}
            onDragStart={(event) => {
              setDragNodeId(node.id)
              event.dataTransfer.effectAllowed = 'move'
              event.dataTransfer.setData('text/plain', node.id)
            }}
            onDragEnd={() => setDragNodeId('')}
            onDragOver={(event) => {
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
            }}
            onDrop={(event) => {
              event.preventDefault()
              const movingId = dragNodeId || event.dataTransfer.getData('text/plain')
              setDragNodeId('')
              const mode = event.altKey ? 'before' : folder ? 'inside' : 'before'
              handleMoveNode(movingId, node, mode)
            }}
            style={{ paddingLeft: `${12 + level * 18}px` }}
            className={`group flex items-center gap-2 pr-2 py-2 rounded-lg text-sm cursor-pointer transition-all border ${
              selected
                ? 'bg-primary/10 border-primary/20 text-primary'
                : 'border-transparent hover:bg-surface-container-low text-on-surface-variant'
            } ${dragNodeId && dragNodeId !== node.id ? 'border-dashed border-outline-variant/60' : ''}`}
            onClick={() => handleSelectNode(node.id)}
          >
            {folder ? (
              <button
                onClick={(event) => {
                  event.stopPropagation()
                  toggleExpand(node)
                }}
                className="w-5 h-5 rounded hover:bg-surface-container-high flex items-center justify-center"
              >
                <span className="material-symbols-outlined text-sm text-outline">
                  {expanded ? 'expand_more' : 'chevron_right'}
                </span>
              </button>
            ) : (
              <span className="w-5 h-5" />
            )}
            <span className={`material-symbols-outlined text-sm ${folder ? 'text-primary' : 'text-outline'}`}>
              {folder ? 'folder' : 'article'}
            </span>
            <span className={`truncate ${selected ? 'font-semibold text-primary' : ''}`}>
              {node.title}
            </span>
            <button
              type="button"
              title="删除节点"
              disabled={deletingNode}
              onClick={(event) => {
                event.stopPropagation()
                handleDeleteNode(node.id, node.title)
              }}
              className="ml-auto hidden h-6 w-6 items-center justify-center rounded text-outline hover:bg-error-container/40 hover:text-error disabled:opacity-50 group-hover:inline-flex"
            >
              <span className="material-symbols-outlined text-[16px]">delete</span>
            </button>
            <span className="material-symbols-outlined text-sm text-outline opacity-50 group-hover:opacity-100">
              drag_indicator
            </span>
          </div>
          {folder && expanded && node.children?.length > 0 && (
            <div className="mt-1">{renderTree(node.children, level + 1)}</div>
          )}
        </div>
      )
    })

  if (loading && !data) {
    return <PageLoading title="正在加载 Wiki..." description="正在同步节点树和元数据。" />
  }

  if (error && !data) {
    return (
      <PageError
        title="Wiki 加载失败"
        description={error}
        onRetry={() => loadData()}
      />
    )
  }

  if (!selectedNode && !tree.length) {
    return (
      <PageEmpty
        title="Wiki 暂无节点"
        description="可以先创建一个目录或节点开始维护素材。"
        actionText="新建节点"
        onAction={() => handleCreateNode(false)}
      />
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <MaterialsViewSwitch
        active="wiki"
        activeBidType={activeBidType}
        title={`${activeBidType} Wiki`}
        subtitle={selectedNode?.pathText || selectedNode?.title || `${activeBidType} Wiki 内容维护`}
        actions={(
          <div className="flex flex-nowrap gap-2">
            <button
              type="button"
              onClick={handleRefreshWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="whitespace-nowrap px-3 py-2 text-sm font-medium rounded-lg bg-secondary-container text-on-secondary-container hover:opacity-90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {refreshingWiki ? '刷新中...' : '刷新Wiki'}
            </button>
            <button
              type="button"
              onClick={handleRebuildWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="whitespace-nowrap px-3 py-2 text-sm font-medium rounded-lg bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {rebuildingWiki ? '重建中...' : '重建Wiki'}
            </button>
          </div>
        )}
        meta={(
          <div className="flex flex-nowrap gap-2 text-xs xl:justify-end">
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              标类 {activeBidType}
            </span>
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              标签 {draft.tags.length}
            </span>
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              适用类型 {draft.applicableTypes.length}
            </span>
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              附件 {attachments.length}
            </span>
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              更新 {selectedNode?.updatedAt ? selectedNode.updatedAt.replace('T', ' ').slice(0, 19) : '-'}
            </span>
          </div>
        )}
        basePath={materialsBasePath}
      />
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <div className="xl:col-span-3 bg-surface-container-lowest rounded-xl border border-surface-container-high flex flex-col min-h-[720px] max-h-[720px] overflow-hidden">
          <div className="px-4 py-4 border-b border-surface-container-high space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-on-surface">目录树</h3>
                <p className="mt-1 text-xs text-outline leading-5 break-words">
                  拖拽节点可调整树结构。拖到目录默认入子级，按 `Alt` 可改为同级前置。
                </p>
              </div>
              <div className="flex flex-wrap gap-2 shrink-0">
                <button
                  onClick={() => handleCreateNode(false)}
                  disabled={creatingNode}
                  className="inline-flex items-center justify-center rounded-lg border border-surface-container-high bg-white px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
                >
                  新建节点
                </button>
                <button
                  onClick={() => handleCreateNode(true)}
                  disabled={creatingNode}
                  className="inline-flex items-center justify-center rounded-lg border border-surface-container-high bg-white px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:opacity-50"
                >
                  新建目录
                </button>
              </div>
            </div>
            {(refreshing || movingNode) && (
              <p className="text-xs text-outline rounded-lg bg-surface-container-high px-3 py-2">
                正在同步最新树结构...
              </p>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-1">{renderTree(tree)}</div>
        </div>

        <div className="xl:col-span-9 flex flex-col gap-4 min-w-0">
          <div className="bg-surface-container-lowest rounded-xl border border-surface-container-high p-4 space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-on-surface">节点内容</h3>
                <p className="mt-1 truncate text-xs text-outline">
                  {selectedNode?.pathText || selectedNode?.title || '当前节点'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => handleDeleteNode()}
                  disabled={!selectedNodeId || deletingNode}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-error/20 bg-error-container px-3 py-2 text-xs font-medium text-on-error-container hover:bg-error-container/80 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]">delete</span>
                  {deletingNode ? '删除中...' : '删除节点'}
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={!isDirty || saving || deletingNode}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-on-primary hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]">save</span>
                  {saving ? '保存中...' : '保存'}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <label className="text-xs text-on-surface-variant">
                节点标题
                <input
                  value={draft.title}
                  onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))}
                  className="mt-1 w-full px-3 py-2 rounded-lg border border-surface-container-high text-sm text-on-surface bg-white"
                />
              </label>
              <div className="text-xs text-on-surface-variant">
                节点路径
                <div className="mt-1 px-3 py-2 rounded-lg border border-surface-container-high text-sm text-on-surface bg-surface-container-low break-all">
                  {selectedNode?.pathText || '根目录'}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <div className="text-xs text-on-surface-variant">
                标签
                <div className="mt-1 flex flex-wrap gap-2">
                  {tagOptions.map((tag) => (
                    <label key={tag} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-surface-container-high bg-surface-container-low text-xs">
                      <input
                        type="checkbox"
                        checked={draft.tags.includes(tag)}
                        onChange={() => toggleDraftListValue('tags', tag)}
                      />
                      {tag}
                    </label>
                  ))}
                </div>
              </div>
              <div className="text-xs text-on-surface-variant">
                适用类型
                <div className="mt-1 flex flex-wrap gap-2">
                  {applicableTypeOptions.map((type) => (
                    <label key={type} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-surface-container-high bg-surface-container-low text-xs">
                      <input
                        type="checkbox"
                        checked={draft.applicableTypes.includes(type)}
                        onChange={() => toggleDraftListValue('applicableTypes', type)}
                      />
                      {type}
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1">
              <button onClick={() => insertAroundSelection('**', '**')} className="p-2 hover:bg-surface-container-high rounded font-bold text-on-surface">B</button>
              <button onClick={() => insertAroundSelection('*', '*')} className="p-2 hover:bg-surface-container-high rounded italic text-on-surface">I</button>
              <button onClick={() => insertAroundSelection('\n## ', '')} className="p-2 hover:bg-surface-container-high rounded text-on-surface">H2</button>
              <button onClick={() => insertAroundSelection('\n- ', '')} className="p-2 hover:bg-surface-container-high rounded">
                <span className="material-symbols-outlined text-lg text-outline">format_list_bulleted</span>
              </button>
            </div>
          </div>

          <div className="bg-surface-container-lowest rounded-xl border border-surface-container-high overflow-hidden">
            <div className="grid grid-cols-1 2xl:grid-cols-[minmax(0,1fr),20rem] min-h-[520px]">
              <div className="grid grid-cols-1 xl:grid-cols-2 min-h-[520px]">
                <div className="p-4 overflow-y-auto border-r-0 xl:border-r border-b xl:border-b-0 border-surface-container-high bg-surface-container-low min-h-[320px]">
                  <textarea
                    ref={editorRef}
                    value={draft.markdownContent}
                    onChange={(event) => setDraft((prev) => ({ ...prev, markdownContent: event.target.value }))}
                    className="w-full min-h-full h-full resize-none rounded-lg border border-surface-container-high bg-white p-4 text-sm text-on-surface font-mono leading-relaxed"
                  />
                </div>
                <div className="p-6 overflow-y-auto bg-white min-w-0">
                  <h1 className="text-xl font-headline font-bold text-on-surface mb-4 break-words">
                    {draft.title || '未命名节点'}
                  </h1>
                  <MarkdownLite content={draft.markdownContent} />
                </div>
              </div>

              <div className="bg-surface-container-lowest border-t 2xl:border-t-0 2xl:border-l border-surface-container-high flex flex-col overflow-y-auto">
                <div className="p-4 border-b border-surface-container-high">
                  <div className="p-4 bg-ai-accent-light rounded-xl">
                    <div className="flex items-center justify-between mb-2 gap-3">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="material-symbols-outlined text-ai-accent text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>auto_awesome</span>
                        <h4 className="text-sm font-semibold text-ai-accent truncate">AI 自动摘要</h4>
                      </div>
                      <button
                        onClick={handleRefreshSummary}
                        disabled={refreshingSummary}
                        className="text-primary flex items-center gap-1 hover:underline disabled:opacity-50 text-xs shrink-0"
                      >
                        <span className="material-symbols-outlined text-sm">refresh</span>
                        {refreshingSummary ? '生成中' : '重新生成'}
                      </button>
                    </div>
                    <p className="text-xs text-on-surface-variant leading-relaxed whitespace-pre-wrap break-words">
                      {selectedNode?.aiSummary || '暂无摘要'}
                    </p>
                  </div>
                </div>

                <div className="p-4 min-h-0">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-semibold text-on-surface flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">attach_file</span>
                      附件列表
                      <span className="text-xs bg-surface-container-high rounded-full px-2 py-0.5">{attachments.length}</span>
                    </h4>
                    <button
                      type="button"
                      onClick={() => uploadInputRef.current?.click()}
                      disabled={!selectedNodeId || uploadingAttachment}
                      className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-surface-container-high bg-white px-2.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <span className="material-symbols-outlined text-[16px]">upload_file</span>
                      {uploadingAttachment ? '上传中' : '上传附件'}
                    </button>
                  </div>
                  <div className="flex flex-col gap-2">
                    {attachments.map((att) => (
                      <div
                        key={att.id}
                        className="flex items-center gap-3 p-3 bg-surface-container-low rounded-lg hover:bg-surface-container transition-colors"
                      >
                        <span className="material-symbols-outlined text-error text-lg">
                          {att.name.toLowerCase().endsWith('.pdf') ? 'picture_as_pdf' : 'description'}
                        </span>
                        <a
                          href={att.downloadUrl || '#'}
                          onClick={(event) => {
                            if (!att.downloadUrl) event.preventDefault()
                          }}
                          className="flex-1 min-w-0"
                        >
                          <div className="text-sm font-medium text-on-surface truncate">{att.name}</div>
                          <div className="text-xs text-outline">{att.size} · {att.time}</div>
                        </a>
                        <button
                          type="button"
                          title="删除附件"
                          disabled={deletingAttachmentId === att.id}
                          onClick={() => handleDeleteAttachment(att)}
                          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-outline hover:bg-error-container/40 hover:text-error disabled:opacity-50"
                        >
                          <span className="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                      </div>
                    ))}
                    {!attachments.length && (
                      <div className="text-xs text-outline p-3 bg-surface-container-low rounded-lg">当前节点暂无附件</div>
                    )}
                  </div>
                  <input
                    ref={uploadInputRef}
                    type="file"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) handleUploadAttachment(file)
                      event.target.value = ''
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
