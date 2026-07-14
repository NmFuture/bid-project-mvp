import { useCallback, useMemo, useState, useEffect } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/TechnicalMaterialsViewSwitch'
import MarkdownLite from '../../../components/shared/MarkdownLite'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import { workspaceRoute } from '../../../utils/workspace'

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const TECHNICAL_BID_TYPE = '技术标'
const TECHNICAL_WORKSPACE = 'tech'

// 后端对所有节点都返回 children 数组（叶子为 []），不能用 Array.isArray 判断文件夹，
// 否则每个叶子节点也会被当成文件夹渲染（带展开箭头 + folder 图标）。
const isFolderNode = (node) => Array.isArray(node?.children) && node.children.length > 0

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

export default function TechnicalMaterialWiki({ showToast = () => {} }) {
  const activeBidType = TECHNICAL_BID_TYPE
  const materialsBasePath = workspaceRoute(TECHNICAL_WORKSPACE, '/materials')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [refreshingWiki, setRefreshingWiki] = useState(false)
  const [rebuildingWiki, setRebuildingWiki] = useState(false)
  const [collapsedMap, setCollapsedMap] = useState({})

  const applyPayload = useCallback((payload, options = {}) => {
    // 选中节点（preserveTree）时只更新 selectedNode，保留现有 tree 引用，
    // 避免整棵树被新响应替换导致全部 key 重挂载 → 目录树闪烁。
    if (options.preserveTree) {
      setData((prev) => {
        if (!prev) return payload
        return { ...prev, selectedNode: payload?.selectedNode ?? prev.selectedNode }
      })
    } else {
      setData(payload)
    }
    setError('')
  }, [])

  const loadData = useCallback(async (params = {}, options = {}) => {
    // preserveTree：仅切换选中节点内容，不动树结构，也不展示任何加载提示，
    // 避免左栏「正在同步目录树」提示条闪现导致目录树闪烁 / 高度跳动。
    // 非 preserveTree（首屏 / 刷新 / 重建）才展示全屏 loading。
    if (!options.preserveTree) {
      setLoading(true)
    }

    try {
      const response = await technicalMaterialsAPI.wiki.list({
        ...params,
        bidType: activeBidType,
      })
      applyPayload(response, { preserveTree: options.preserveTree })
    } catch (e) {
      console.error(e)
      const message = safeMessage(e, 'Wiki 数据加载失败，请稍后重试。')
      // preserveTree 下首屏树已在，静默失败时用 toast 提示，不打断当前视图。
      if (options.preserveTree) {
        showToast(message, 'error')
      } else {
        setError(message)
      }
    } finally {
      if (!options.preserveTree) {
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

  // 展开/收起以 collapsedMap 为唯一本地真相：未记录的节点回退到服务端 node.expanded，
  // 已被用户操作过的节点保留本地值。重新拉取树时不会覆盖（避免闪烁 / 收起后回弹）。
  const isExpanded = useCallback(
    (node) => {
      if (!isFolderNode(node)) return false
      if (Object.prototype.hasOwnProperty.call(collapsedMap, node.id)) {
        return !collapsedMap[node.id]
      }
      return node.expanded !== false
    },
    [collapsedMap],
  )

  const toggleExpand = (node) => {
    setCollapsedMap((prev) => {
      const currentlyExpanded = Object.prototype.hasOwnProperty.call(prev, node.id)
        ? !prev[node.id]
        : node.expanded !== false
      return { ...prev, [node.id]: currentlyExpanded }
    })
  }

  const handleSelectNode = async (nodeId) => {
    if (!nodeId || nodeId === selectedNodeId) return
    await loadData({ nodeId }, { preserveTree: true })
  }

  // 点击整行：叶子节点仅选中；文件夹节点选中的同时切换展开/收起，
  // 与原始素材库的目录树交互对齐（不必精准点中三角即可展开）。
  const handleRowClick = (node) => {
    handleSelectNode(node.id)
    if (isFolderNode(node)) {
      toggleExpand(node)
    }
  }

  const handleRefreshWiki = async () => {
    const ok = window.confirm(`确认刷新${activeBidType} Wiki？系统会读取当前 JSON 索引，并同步新增、更新、删除自动生成的 Wiki 节点。`)
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

  const renderTree = (nodes, level = 0) =>
    (nodes || []).map((node) => {
      const folder = isFolderNode(node)
      const expanded = folder ? isExpanded(node) : false
      const selected = node.id === selectedNodeId
      return (
        <div key={node.id}>
          <div
            style={{ paddingLeft: `${12 + level * 18}px` }}
            className={`group flex items-center gap-1.5 pr-2 py-2 rounded-lg text-[13px] leading-[1.6] cursor-pointer transition-colors border ${
              selected
                ? 'bg-primary/10 border-primary/20 text-primary'
                : 'border-transparent hover:bg-surface-container-low text-on-surface-variant'
            }`}
            onClick={() => handleRowClick(node)}
          >
            {folder ? (
              <button
                title={expanded ? '收起' : '展开'}
                aria-label={expanded ? '收起' : '展开'}
                aria-expanded={expanded}
                onClick={(event) => {
                  event.stopPropagation()
                  toggleExpand(node)
                }}
                className="w-5 h-5 shrink-0 rounded flex items-center justify-center text-outline hover:bg-primary/10 hover:text-primary"
              >
                <span
                  aria-hidden="true"
                  className={`material-symbols-outlined text-[18px] transition-transform duration-200 ease-out ${expanded ? 'rotate-90' : 'rotate-0'}`}
                >
                  chevron_right
                </span>
              </button>
            ) : (
              <span className="w-5 h-5 shrink-0" />
            )}
            <span
              aria-hidden="true"
              className={`material-symbols-outlined shrink-0 text-[17px] ${folder ? 'text-primary' : 'text-outline'}`}
            >
              {folder ? (expanded ? 'folder_open' : 'folder') : 'article'}
            </span>
            <span
              className={`truncate ${
                selected
                  ? 'font-semibold text-primary'
                  : folder
                    ? 'font-medium text-on-surface'
                    : ''
              }`}
            >
              {node.title}
            </span>
            {folder && (
              <span className="ml-auto shrink-0 text-xs text-outline">{node.children.length}</span>
            )}
          </div>
          {folder && expanded && (
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
    <>
    <div className="flex flex-col gap-3 animate-fade-in">
      <MaterialsViewSwitch
        active="wiki"
        title={`${activeBidType} Wiki`}
        actions={(
          <div className="flex flex-nowrap gap-2">
            <button
              onClick={handleRefreshWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="h-9 whitespace-nowrap rounded-lg bg-primary px-3 text-[13px] leading-[1.6] font-medium text-on-primary transition-colors hover:bg-primary-container hover:text-on-primary-container disabled:cursor-not-allowed disabled:opacity-50"
            >
              {refreshingWiki ? '刷新中...' : '刷新Wiki'}
            </button>
            <button
              onClick={handleRebuildWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="h-9 whitespace-nowrap rounded-lg bg-surface-container-high px-3 text-[13px] leading-[1.6] font-medium text-on-surface-variant transition-colors hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
            >
              {rebuildingWiki ? '重建中...' : '重建Wiki'}
            </button>
          </div>
        )}
        basePath={materialsBasePath}
      />
      <div className="grid grid-cols-1 gap-6 xl:h-[calc(100dvh-12rem)] xl:grid-cols-12 xl:items-stretch">
        <div className="xl:col-span-3 bg-surface-container-lowest rounded-lg border border-outline-variant/45 flex min-h-[320px] max-h-[60vh] flex-col overflow-hidden xl:min-h-0 xl:max-h-none">
          <div className="shrink-0 px-4 py-4 border-b border-surface-container-high">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h3 className="text-[14px] leading-[1.6] font-semibold text-on-surface">目录树</h3>
              </div>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 space-y-1">
            {renderTree(tree)}
          </div>
        </div>

        <div className="xl:col-span-9 flex min-w-0 flex-col">
          <div className="flex min-h-[520px] max-h-[75vh] flex-1 flex-col overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest xl:max-h-none">
            <div className="min-h-0 flex-1 overflow-y-auto bg-white p-6">
              {selectedNode?.markdownContent ? (
                <MarkdownLite content={selectedNode.markdownContent} compact />
              ) : (
                <div className="flex min-h-[440px] items-center justify-center text-center">
                  <div>
                    <span className="material-symbols-outlined text-4xl text-outline/60">description</span>
                    <p className="mt-2 text-sm text-on-surface-variant">暂无内容</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
    </>
  )
}
