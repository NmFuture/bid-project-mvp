import { useCallback, useMemo, useState, useEffect } from 'react'
import { businessMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/BusinessMaterialsViewSwitch'
import MarkdownLite from '../../../components/shared/MarkdownLite'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import { workspaceRoute } from '../../../utils/workspace'

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const BUSINESS_BID_TYPE = '商务标'
const BUSINESS_WORKSPACE = 'business'

const normalizeNode = (node) => {
  if (!node) return null
  return {
    ...node,
    title: String(node.title || ''),
    markdownContent: String(node.markdownContent || ''),
    path: String(node.path || ''),
    pathText: String(node.pathText || node.path || ''),
    updatedAt: String(node.updatedAt || ''),
  }
}

export default function BusinessMaterialWiki({ showToast = () => {} }) {
  const activeBidType = BUSINESS_BID_TYPE
  const materialsBasePath = workspaceRoute(BUSINESS_WORKSPACE, '/materials')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [refreshingWiki, setRefreshingWiki] = useState(false)
  const [rebuildingWiki, setRebuildingWiki] = useState(false)
  const [collapsedMap, setCollapsedMap] = useState({})

  const applyPayload = useCallback((payload) => {
    setData(payload)
    setError('')
  }, [])

  const loadData = useCallback(async (params = {}, options = {}) => {
    if (options.silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }

    try {
      const response = await businessMaterialsAPI.wiki.list({
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

  const handleRefreshWiki = async () => {
    const ok = window.confirm(`确认刷新${activeBidType} Wiki？系统会重新读取当前素材库，并替换自动生成的 Wiki 节点。`)
    if (!ok) return
    setRefreshingWiki(true)
    try {
      const payload = await businessMaterialsAPI.wiki.bootstrap({
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
      const payload = await businessMaterialsAPI.wiki.bootstrap({
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

  const renderTree = (nodes, level = 0) =>
    (nodes || []).map((node) => {
      const folder = Array.isArray(node.children)
      const expanded = folder ? isExpanded(node) : false
      const selected = node.id === selectedNodeId
      return (
        <div key={node.id}>
          <div
            style={{ paddingLeft: `${12 + level * 18}px` }}
            className={`group flex items-center gap-2 pr-2 py-2 rounded-lg text-sm cursor-pointer transition-all border ${
              selected
                ? 'bg-primary/10 border-primary/20 text-primary'
                : 'border-transparent hover:bg-surface-container-low text-on-surface-variant'
            }`}
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
        description="当前还没有可展示的 Wiki 内容。"
      />
    )
  }

  return (
    <div className="flex flex-col gap-3 animate-fade-in">
      <MaterialsViewSwitch
        active="wiki"
        title={`${activeBidType} Wiki`}
        actions={(
          <div className="flex flex-nowrap gap-2">
            <button
              onClick={handleRefreshWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="h-9 whitespace-nowrap rounded-lg bg-secondary-container px-3 text-sm font-medium text-on-secondary-container transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {refreshingWiki ? '刷新中...' : '刷新Wiki'}
            </button>
            <button
              onClick={handleRebuildWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="h-9 whitespace-nowrap rounded-lg bg-surface-container-high px-3 text-sm font-medium text-on-surface-variant transition-colors hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
            >
              {rebuildingWiki ? '重建中...' : '重建Wiki'}
            </button>
          </div>
        )}
        basePath={materialsBasePath}
      />
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <div className="xl:col-span-3 bg-surface-container-lowest rounded-xl border border-surface-container-high flex flex-col min-h-[720px] max-h-[720px] overflow-hidden">
          <div className="px-4 py-4 border-b border-surface-container-high">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-on-surface">目录树</h3>
              </div>
            </div>
            {refreshing && (
              <p className="text-xs text-outline rounded-lg bg-surface-container-high px-3 py-2">
                正在同步最新树结构...
              </p>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-1">{renderTree(tree)}</div>
        </div>

        <div className="xl:col-span-9 flex flex-col min-w-0">
          <div className="bg-surface-container-lowest rounded-xl border border-surface-container-high overflow-hidden">
            <div className="min-h-[520px]">
              <div className="p-6 overflow-y-auto bg-white min-w-0">
                <MarkdownLite content={selectedNode?.markdownContent || ''} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
