import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { outlineAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'

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

const formatDateTime = (value) => {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未知'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const countNodes = (items = []) =>
  (items || []).reduce(
    (sum, item) => sum + 1 + countNodes(Array.isArray(item.children) ? item.children : []),
    0,
  )

export default function OutlineReview({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [nodes, setNodes] = useState([])
  const [activeNodeId, setActiveNodeId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await outlineAPI.get(id)
      const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
      setData(payload)
      setNodes(nextNodes)
      setDirty(false)
      setActiveNodeId(nextNodes[0]?.id || '')
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
      setData(payload)
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
      setData(payload)
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
        setData(saved)
        setNodes(Array.isArray(saved?.nodes) ? saved.nodes : [])
        setDirty(false)
      }

      await outlineAPI.confirm(id)
      await stagesAPI.update(id, 3, { status: 'completed' })
      showToast?.('目录审核已完成，已进入 S4 素材缺口识别')
      navigate(`/projects/${id}/gaps`)
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

  const renderRows = (items, depth = 0, prefix = '') => (
    <div className="space-y-2">
      {(items || []).map((node, index) => {
        const seq = prefix ? `${prefix}.${index + 1}` : `${index + 1}`
        const isActive = activeNodeId === node.id
        const siblings = items || []
        const canMoveUp = index > 0
        const canMoveDown = index < siblings.length - 1

        return (
          <div key={node.id} className="space-y-2">
            <div
              onClick={() => setActiveNodeId(node.id)}
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition-colors ${
                isActive
                  ? 'border-primary bg-primary/10'
                  : 'border-surface-container-high bg-surface-container-lowest'
              }`}
              style={{ marginLeft: `${depth * 20}px` }}
            >
              <span className="w-12 shrink-0 text-xs font-semibold text-outline">{seq}</span>
              <input
                value={node.title || ''}
                onChange={(e) => handleTitleChange(node.id, e.target.value)}
                className="flex-1 h-9 px-3 rounded-md bg-surface-container-highest text-sm text-on-surface focus:ring-2 focus:ring-primary/30"
                placeholder="输入章节标题"
              />
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleAddChild(node.id)
                }}
                className="h-8 px-2 text-xs font-medium rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors"
                title="新增子节点"
              >
                +子项
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleAddSibling(node.id)
                }}
                className="h-8 px-2 text-xs font-medium rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors"
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
                className="h-8 w-8 rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center"
                title="上移"
              >
                <span className="material-symbols-outlined text-sm">arrow_upward</span>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleMove(node.id, 'down')
                }}
                disabled={!canMoveDown}
                className="h-8 w-8 rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center"
                title="下移"
              >
                <span className="material-symbols-outlined text-sm">arrow_downward</span>
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleDelete(node.id)
                }}
                className="h-8 w-8 rounded-md bg-error-container/20 text-error hover:bg-error-container/40 transition-colors flex items-center justify-center"
                title="删除节点"
              >
                <span className="material-symbols-outlined text-sm">delete</span>
              </button>
            </div>

            {Array.isArray(node.children) && node.children.length > 0
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

  return (
    <div className="flex flex-col gap-6 animate-fade-in max-w-6xl mx-auto w-full">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        title="S3 目录审核"
        description="直接在目录文档中编辑：支持新增、删除、调整顺序。"
        leftExtra={(
          <button
            onClick={() => window.history.back()}
            className="text-primary hover:bg-surface-container-low rounded-full w-10 h-10 flex items-center justify-center transition-colors"
          >
            <span className="material-symbols-outlined">arrow_back</span>
          </button>
        )}
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-sm">refresh</span>
              刷新
            </button>
            <button
              onClick={handleReject}
              disabled={rejecting}
              className="px-4 py-2.5 text-sm font-medium text-error bg-error-container/30 hover:bg-error-container/50 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">refresh</span>
              {rejecting ? '处理中...' : '驳回重生成'}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2.5 text-sm font-medium text-on-primary bg-primary hover:bg-primary-container rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">save</span>
              {saving ? '保存中...' : dirty ? '保存目录*' : '保存目录'}
            </button>
            <button
              onClick={handleConfirm}
              disabled={confirming}
              className="px-4 py-2.5 text-sm font-medium text-on-secondary bg-secondary hover:bg-secondary/90 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">check</span>
              {confirming ? '确认中...' : '确认并进入 S4'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden min-h-[520px]">
        <div className="px-6 py-4 border-b border-surface-container-high bg-surface-container-low flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">目录文档（可直接编辑）</h3>
            <p className="text-xs text-on-surface-variant mt-1">
              来源文件：{data?.source?.directoryFileName || '未命名目录.docx'} · 生成时间：{formatDateTime(data?.source?.generatedAt)}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-outline">
              节点数：{countNodes(nodes)}
            </span>
            <button
              onClick={handleAddRoot}
              className="px-3 py-1.5 rounded-lg bg-primary text-on-primary text-xs font-semibold hover:bg-primary-container transition-colors flex items-center gap-1"
            >
              <span className="material-symbols-outlined text-sm">add</span>
              新增一级章节
            </button>
          </div>
        </div>

        <div className="p-6">
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
      </DataCard>
    </div>
  )
}
