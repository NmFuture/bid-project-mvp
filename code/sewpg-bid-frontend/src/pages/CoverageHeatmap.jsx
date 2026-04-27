import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { coverageAPI, stagesAPI } from '../api'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const statusDotClass = {
  full: 'bg-secondary',
  partial: 'bg-tertiary',
  none: 'bg-error',
}

const collectParentNodeIds = (nodes = []) => {
  const ids = []
  const walk = (items) => {
    items.forEach((item) => {
      if (Array.isArray(item.children) && item.children.length > 0) {
        ids.push(item.id)
        walk(item.children)
      }
    })
  }
  walk(nodes)
  return ids
}

const renderTreeNode = (node, collapsedNodeIds, onToggleNodeCollapse, depth = 0) => {
  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  const isCollapsed = hasChildren && collapsedNodeIds.has(node.id)
  const leftPadding = 12 + depth * 20
  const coverageColor = node.coverage >= 90 ? 'text-secondary' : node.coverage >= 70 ? 'text-tertiary' : 'text-error'

  if (hasChildren) {
    return (
      <div key={node.id} className="flex flex-col gap-1">
        <div
          className="flex items-center justify-between rounded-lg bg-surface-container-low px-3 py-2"
          style={{ paddingLeft: `${leftPadding}px` }}
        >
          <button
            type="button"
            onClick={() => onToggleNodeCollapse(node.id)}
            className="flex items-center gap-1.5 min-w-0"
          >
            <span className="material-symbols-outlined text-sm text-outline">
              {isCollapsed ? 'chevron_right' : 'expand_more'}
            </span>
            <span className="text-sm font-semibold text-on-surface">{node.title}</span>
          </button>
          <span className={`text-sm font-bold ${coverageColor}`}>{node.coverage}%</span>
        </div>
        {!isCollapsed ? node.children.map((child) => renderTreeNode(child, collapsedNodeIds, onToggleNodeCollapse, depth + 1)) : null}
      </div>
    )
  }

  return (
    <div
      key={node.id}
      className="flex items-center justify-between rounded-lg px-3 py-2 hover:bg-surface-container-low"
      style={{ paddingLeft: `${leftPadding}px` }}
    >
      <span className="text-sm text-on-surface-variant">{node.title}</span>
      <span className={`w-2.5 h-2.5 rounded-full ${statusDotClass[node.status] || statusDotClass.none}`}></span>
    </div>
  )
}

export default function CoverageHeatmap({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [advancing, setAdvancing] = useState(false)
  const [collapsedNodeIds, setCollapsedNodeIds] = useState(() => new Set())

  const fetchCoverage = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await coverageAPI.get(id)
      setData(payload)
      setError('')
    } catch (e) {
      setError(e?.message || '覆盖热力数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchCoverage()
    }, 0)
    return () => clearTimeout(timer)
  }, [fetchCoverage])

  const partialItems = useMemo(() => data?.partialItems || [], [data?.partialItems])
  const noCoverItems = useMemo(() => data?.noCoverItems || [], [data?.noCoverItems])
  const incompleteItems = useMemo(() => [...partialItems, ...noCoverItems], [partialItems, noCoverItems])
  const treeNodes = useMemo(() => data?.tree || [], [data?.tree])
  const parentNodeIds = useMemo(() => collectParentNodeIds(treeNodes), [treeNodes])
  const allCollapsed = parentNodeIds.length > 0 && parentNodeIds.every((nodeId) => collapsedNodeIds.has(nodeId))

  const handleToggleNodeCollapse = (nodeId) => {
    setCollapsedNodeIds((prev) => {
      const next = new Set(prev)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }

  const handleToggleAllNodes = () => {
    setCollapsedNodeIds((prev) => {
      const next = new Set(prev)
      if (allCollapsed) {
        parentNodeIds.forEach((nodeId) => next.delete(nodeId))
      } else {
        parentNodeIds.forEach((nodeId) => next.add(nodeId))
      }
      return next
    })
  }

  const handleGoEditor = async () => {
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 8, { status: 'completed' })
      showToast('已进入 S9 人机共创编辑')
      navigate(projectRoute(id, '/editor', workspaceSlug))
    } catch (e) {
      showToast(e?.message || '进入 S9 失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <div className="animate-shimmer w-full h-96 rounded-xl"></div>

  if (error) {
    return (
      <div className="bg-error-container/20 border border-error/30 rounded-xl p-6 text-sm text-error">
        <p className="font-semibold mb-2">S8 覆盖热力图加载失败</p>
        <p>{error}</p>
        <button
          onClick={fetchCoverage}
          className="mt-4 px-4 py-2 bg-error text-on-error text-xs font-medium rounded-lg"
        >
          重新加载
        </button>
      </div>
    )
  }

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <div className="flex justify-end">
        <button
          onClick={handleGoEditor}
          disabled={advancing}
          className="stage-action-btn px-4 py-2 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {advancing ? '进入中...' : '进入下一阶段'}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[520px]">
        <div className="lg:col-span-5 bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-col">
          <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-on-surface">素材拼装覆盖树（按 S2 目录 JSON 校验）</h3>
            {parentNodeIds.length ? (
              <button
                type="button"
                onClick={handleToggleAllNodes}
                className="text-xs text-primary hover:text-primary/80 transition-colors"
              >
                {allCollapsed ? '展开全部' : '收起全部'}
              </button>
            ) : null}
          </div>
          <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
            {treeNodes.length ? treeNodes.map((node) => renderTreeNode(node, collapsedNodeIds, handleToggleNodeCollapse)) : (
              <div className="text-sm text-outline px-2 py-3">暂无目录评分数据</div>
            )}
          </div>
        </div>

        <div className="lg:col-span-7 bg-surface-container-lowest rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.06)] flex flex-col">
          <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
            <h3 className="text-sm font-semibold text-on-surface">问题清单</h3>
          </div>

          <div className="p-6">
            <section className="rounded-lg border border-error/25 bg-error-container/10">
              <div className="px-4 py-3 border-b border-error/25 flex items-center gap-2">
                <span className="material-symbols-outlined text-error text-sm">error</span>
                <h4 className="text-sm font-semibold text-on-surface">未拼装 / 未匹配项（{incompleteItems.length}）</h4>
              </div>
              <div className="p-3 flex flex-col gap-2 max-h-[380px] overflow-y-auto">
                {incompleteItems.length ? incompleteItems.map((item) => (
                  <div key={item.id} className="rounded-lg bg-surface-container-low px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium text-on-surface">{item.title}</div>
                      <span className="text-xs text-outline whitespace-nowrap">{item.id}</span>
                    </div>
                    <div className="text-xs text-on-surface-variant mt-1">{item.nodeTitle || '-'}</div>
                  </div>
                )) : (
                  <div className="text-sm text-outline p-2">暂无未完整覆盖项</div>
                )}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}
