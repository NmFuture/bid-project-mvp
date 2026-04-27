import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { outlineAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
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

export default function OutlineReview({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
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
      await stagesAPI.update(id, 3, { status: 'completed' })
      showToast?.('目录审核已完成，已进入 S4 素材缺口识别')
      navigate(projectRoute(id, '/gaps', workspaceSlug))
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

        return (
          <div key={node.id}>
            <div
              onClick={() => setActiveNodeId(node.id)}
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
              <span className="w-9 shrink-0 text-xs font-semibold text-outline">{seq}</span>
              <input
                value={node.title || ''}
                onChange={(e) => handleTitleChange(node.id, e.target.value)}
                className="flex-1 !min-h-0 h-8 px-1.5 border-0 bg-transparent text-sm text-on-surface focus:ring-0 focus:outline-none"
                placeholder="输入章节标题"
              />
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

  if (loading) return <PageLoading title="正在加载 S3 目录审核..." />

  if (error) {
    return (
      <PageError
        title="S3 目录审核加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  const hasOnlyOfficeSession = Boolean(tenderPreview?.onlyoffice?.fileUrl && tenderPreview?.onlyoffice?.callbackUrl)
  const activeTenderFileName = tenderPreview?.activeFile?.name || '未选择文件'

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
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
              className="px-4 py-2.5 text-sm font-medium text-error bg-error-container/30 hover:bg-error-container/50 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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
              {confirming ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden min-h-[560px]">
        <div className="grid grid-cols-1 xl:grid-cols-2 min-h-[560px]">
          <section className="flex flex-col border-r border-surface-container-high">
            <div className="px-6 py-4 border-b border-surface-container-high bg-surface-container-low flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-base font-semibold text-on-surface">目录文档</h3>
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
                  新增一级章节
                </button>
              </div>
            </div>

            <div className="p-6 flex-1 overflow-y-auto">
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
          </section>

          <section className="flex flex-col bg-white">
            <div className="px-6 py-4 border-b border-surface-container-high bg-surface-container-low">
              <h3 className="text-base font-semibold text-on-surface">招标文件（OnlyOffice）</h3>
              <p className="text-xs text-outline mt-1 truncate" title={activeTenderFileName}>
                当前文件：{activeTenderFileName}
              </p>
            </div>
            <div className="p-4 flex-1 min-h-0">
              {onlyofficeError && (
                <div className="mb-3 rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">
                  {onlyofficeError}
                </div>
              )}
              {hasOnlyOfficeSession && !onlyofficeError ? (
                <OnlyOfficeEmbed
                  session={tenderPreview?.onlyoffice}
                  mode="view"
                  className="w-full h-full min-h-[460px] border border-surface-container-high bg-white"
                  onReady={() => setOnlyofficeError('')}
                  onError={(message) => setOnlyofficeError(message || 'OnlyOffice 文档加载失败')}
                />
              ) : (
                <div className="h-full min-h-[460px] border border-dashed border-surface-container-high flex items-center justify-center text-center px-6">
                  <p className="text-sm text-on-surface-variant">
                    {tenderPreview?.message || '暂无可预览的招标文件。'}
                  </p>
                </div>
              )}
            </div>
          </section>
        </div>
      </DataCard>
    </div>
  )
}
