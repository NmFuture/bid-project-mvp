import { useCallback, useMemo, useState, useEffect, useRef } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/TechnicalMaterialsViewSwitch'
import MarkdownLite from '../../../components/shared/MarkdownLite'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import { workspaceRoute } from '../../../utils/workspace'

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const TECHNICAL_BID_TYPE = '技术标'
const TECHNICAL_WORKSPACE = 'tech'
// key 是后端打在 wiki_docs.tags 上的原始状态 tag（run_from_manifest.py），
// 只在此映射成用户可读的展示文案；其余内部 tag（__auto_generated__、文件卡片、扩展名等）不展示。
const PREVIEW_STATUS_META = {
  AI预览成功: {
    label: '解析成功',
    shortLabel: '成功',
    icon: 'check_circle',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  },
  AI预览待重试: {
    label: '待重试',
    shortLabel: '待重试',
    icon: 'refresh',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
  },
  本地TLDR: {
    label: '本地摘要',
    shortLabel: '本地',
    icon: 'info',
    className: 'border-outline-variant bg-surface-container-low text-on-surface-variant',
  },
  AI预览失败: {
    label: '解析失败',
    shortLabel: '失败',
    icon: 'error',
    className: 'border-rose-200 bg-rose-50 text-rose-700',
  },
}

const normalizeTags = (tags) => (
  Array.isArray(tags) ? tags.map((tag) => String(tag || '').trim()).filter(Boolean) : []
)

const previewStatusForTags = (tags) => {
  const normalized = normalizeTags(tags)
  const tag = normalized.find((item) => PREVIEW_STATUS_META[item])
  return tag ? { tag, ...PREVIEW_STATUS_META[tag] } : null
}

const countPreviewStatuses = (nodes, counts = {}) => {
  for (const node of nodes || []) {
    const status = previewStatusForTags(node?.tags)
    if (status) counts[status.tag] = (counts[status.tag] || 0) + 1
    countPreviewStatuses(node?.children, counts)
  }
  return counts
}

// 后端对所有节点都返回 children 数组（叶子为 []），不能用 Array.isArray 判断文件夹，
// 否则每个叶子节点也会被当成文件夹渲染（带展开箭头 + folder 图标）。
const isFolderNode = (node) => Array.isArray(node?.children) && node.children.length > 0

// 左侧目录树可拖拽宽度（仅 xl 断点生效；移动端上下堆叠不限制宽度）。
const TREE_WIDTH_DEFAULT = 320
const TREE_WIDTH_MIN = 240
const TREE_WIDTH_MAX = 560
// 拖拽时给右侧内容区保留的最小宽度，避免把右栏挤没。
const CONTENT_WIDTH_MIN = 480

const normalizeNode = (node) => {
  if (!node) return null
  return {
    ...node,
    title: String(node.title || ''),
    markdownContent: String(node.markdownContent || ''),
    path: String(node.path || ''),
    pathText: String(node.pathText || node.path || ''),
    updatedAt: String(node.updatedAt || ''),
    tags: normalizeTags(node.tags),
  }
}

// 后台 Wiki 生成任务的阶段标签（后端 on_progress 回报 preview → build → import）
const WIKI_JOB_PHASE_LABELS = {
  preview: '生成内容预览',
  build: '构建目录树',
  import: '导入 Wiki',
}

export default function TechnicalMaterialWiki({ showToast = () => {} }) {
  const activeBidType = TECHNICAL_BID_TYPE
  const materialsBasePath = workspaceRoute(TECHNICAL_WORKSPACE, '/materials')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [refreshingWiki, setRefreshingWiki] = useState(false)
  const [rebuildingWiki, setRebuildingWiki] = useState(false)
  const [wikiJobActive, setWikiJobActive] = useState(false)
  const [wikiJobPhase, setWikiJobPhase] = useState('')
  const [collapsedMap, setCollapsedMap] = useState({})

  const splitContainerRef = useRef(null)
  const [treeWidth, setTreeWidth] = useState(TREE_WIDTH_DEFAULT)
  const [resizing, setResizing] = useState(false)

  const startTreeResize = useCallback((event) => {
    if (event.button !== 0) return
    const container = splitContainerRef.current
    if (!container) return
    event.preventDefault()
    const containerLeft = container.getBoundingClientRect().left
    setResizing(true)
    const handleMove = (moveEvent) => {
      const maxByContainer = Math.max(
        TREE_WIDTH_MIN,
        container.getBoundingClientRect().width - CONTENT_WIDTH_MIN,
      )
      const next = Math.round(moveEvent.clientX - containerLeft)
      setTreeWidth(Math.min(Math.max(next, TREE_WIDTH_MIN), Math.min(TREE_WIDTH_MAX, maxByContainer)))
    }
    const handleUp = () => {
      setResizing(false)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
    // 拖拽期间禁止文本选中、锁定光标，避免拖动时页面文本被刷蓝。
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
  }, [])

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

  // 挂载时探测后台 Wiki 生成任务：任务在跑则恢复轮询态（离开页面再回来可接上）。
  // 恢复时无法区分触发方式，两个按钮同时置忙、禁用，避免重复触发。
  useEffect(() => {
    let cancelled = false
    technicalMaterialsAPI.wiki.bootstrapStatus()
      .then((status) => {
        if (cancelled || status?.status !== 'running') return
        setWikiJobPhase(String(status?.progress?.phase || ''))
        setRefreshingWiki(true)
        setRebuildingWiki(true)
        setWikiJobActive(true)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  // 后台 Wiki 生成任务轮询：到达终态后应用结果或提示失败
  useEffect(() => {
    if (!wikiJobActive) return undefined
    let stopped = false
    const finish = () => {
      setWikiJobActive(false)
      setWikiJobPhase('')
      setRefreshingWiki(false)
      setRebuildingWiki(false)
    }
    const tick = async () => {
      try {
        const status = await technicalMaterialsAPI.wiki.bootstrapStatus()
        if (stopped) return
        if (status?.status === 'running') {
          setWikiJobPhase(String(status?.progress?.phase || ''))
          return
        }
        finish()
        if (status?.status === 'succeeded') {
          const payload = status?.result || {}
          applyPayload(payload)
          showToast(payload?.generation?.summary || payload?.message || `${activeBidType} Wiki 已更新`)
        } else if (status?.status === 'failed') {
          showToast(status?.error || 'Wiki 生成失败，请稍后重试。', 'error')
        } else {
          // idle：后端重启丢了任务状态，AI 预览缓存已保留，提示重触续跑
          showToast('Wiki 生成任务已随服务重启中断，已生成的预览缓存已保留，可重新触发继续。', 'warning')
          loadData()
        }
      } catch {
        // 单次轮询失败不影响任务本身，下一轮重试
      }
    }
    const timer = setInterval(tick, 8000)
    tick()
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [wikiJobActive, activeBidType, applyPayload, loadData, showToast])

  const selectedNode = useMemo(() => normalizeNode(data?.selectedNode), [data])
  const selectedNodeId = selectedNode?.id || ''
  // 右侧只派生一个用户可读的状态小 tag，后端原始 tags 不再透出到界面。
  const selectedStatus = useMemo(() => previewStatusForTags(selectedNode?.tags), [selectedNode])
  const tree = data?.tree || []
  const previewStatusCounts = useMemo(() => countPreviewStatuses(tree), [tree])
  const previewStatusItems = useMemo(
    () => Object.entries(PREVIEW_STATUS_META)
      .map(([tag, meta]) => ({ tag, ...meta, count: previewStatusCounts[tag] || 0 }))
      .filter((item) => item.count > 0),
    [previewStatusCounts],
  )

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

  const startWikiJob = async (mode) => {
    // 后台任务：立即返回，离开页面不中断，终态由轮询 effect 接管
    const status = await technicalMaterialsAPI.wiki.bootstrap({
      mode,
      bidType: activeBidType,
    })
    setWikiJobPhase(String(status?.progress?.phase || ''))
    setWikiJobActive(true)
    showToast('任务已在后台开始，可离开本页，完成后自动更新。')
  }

  const handleRefreshWiki = async () => {
    const ok = window.confirm(`确认刷新${activeBidType} Wiki？系统会同步目录，并重新尝试“待重试”项；已成功解析的继续使用缓存。`)
    if (!ok) return
    setRefreshingWiki(true)
    try {
      await startWikiJob('refresh')
    } catch (e) {
      console.error(e)
      setRefreshingWiki(false)
      showToast(safeMessage(e, '刷新 Wiki 启动失败，请稍后重试。'), 'error')
    }
  }

  const handleRebuildWiki = async () => {
    const ok = window.confirm(`确认重建${activeBidType} Wiki？现有自动生成根树会被重新生成。`)
    if (!ok) return
    setRebuildingWiki(true)
    try {
      await startWikiJob('replace')
    } catch (e) {
      console.error(e)
      setRebuildingWiki(false)
      showToast(safeMessage(e, '重建 Wiki 启动失败，请稍后重试。'), 'error')
    }
  }

  const renderTree = (nodes, level = 0) =>
    (nodes || []).map((node) => {
      const folder = isFolderNode(node)
      const expanded = folder ? isExpanded(node) : false
      const selected = node.id === selectedNodeId
      const previewStatus = previewStatusForTags(node.tags)
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
              className={`min-w-0 flex-1 truncate ${
                selected
                  ? 'font-semibold text-primary'
                  : folder
                    ? 'font-medium text-on-surface'
                    : ''
              }`}
            >
              {node.title}
            </span>
            {!folder && previewStatus && (
              <span
                title={previewStatus.label}
                className={`inline-flex h-6 shrink-0 items-center gap-1 rounded border px-1.5 text-[11px] leading-none ${previewStatus.className}`}
              >
                <span aria-hidden="true" className="material-symbols-outlined text-[14px]">
                  {previewStatus.icon}
                </span>
                {previewStatus.shortLabel}
              </span>
            )}
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
              {refreshingWiki
                ? `刷新并重试中${WIKI_JOB_PHASE_LABELS[wikiJobPhase] ? `（${WIKI_JOB_PHASE_LABELS[wikiJobPhase]}）` : ''}...`
                : '刷新并重试'}
            </button>
            <button
              onClick={handleRebuildWiki}
              disabled={refreshingWiki || rebuildingWiki}
              className="h-9 whitespace-nowrap rounded-lg bg-surface-container-high px-3 text-[13px] leading-[1.6] font-medium text-on-surface-variant transition-colors hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
            >
              {rebuildingWiki
                ? `重建中${WIKI_JOB_PHASE_LABELS[wikiJobPhase] ? `（${WIKI_JOB_PHASE_LABELS[wikiJobPhase]}）` : ''}...`
                : '重建Wiki'}
            </button>
          </div>
        )}
        basePath={materialsBasePath}
      />
      {previewStatusItems.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-outline-variant/45 px-1 py-2 text-xs">
          <span className="font-medium text-on-surface">解析状态</span>
          {previewStatusItems.map((item) => (
            <span key={item.tag} className={`inline-flex h-7 items-center gap-1.5 rounded border px-2 ${item.className}`}>
              <span aria-hidden="true" className="material-symbols-outlined text-[15px]">{item.icon}</span>
              <span>{item.label}</span>
              <span className="font-semibold tabular-nums">{item.count}</span>
            </span>
          ))}
        </div>
      )}
      {!selectedNode && !tree.length ? (
        <PageEmpty
          title="Wiki 暂无节点"
          description="当前还没有可展示的 Wiki 内容。"
        />
      ) : (
      <div
        ref={splitContainerRef}
        className="flex flex-col gap-6 xl:h-[calc(100dvh-12rem)] xl:flex-row xl:items-stretch xl:gap-0"
      >
        <div
          style={{ '--tree-w': `${treeWidth}px` }}
          className="w-full xl:w-[var(--tree-w)] xl:shrink-0 bg-surface-container-lowest rounded-lg border border-outline-variant/45 flex min-h-[320px] max-h-[60vh] flex-col overflow-hidden xl:min-h-0 xl:max-h-none"
        >
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

        <div
          role="separator"
          aria-orientation="vertical"
          title="拖动调整目录树宽度"
          onMouseDown={startTreeResize}
          className={`hidden xl:block w-1 shrink-0 mx-2.5 my-1 cursor-col-resize rounded-full transition-colors ${
            resizing ? 'bg-primary/50' : 'bg-outline-variant/30 hover:bg-primary/40'
          }`}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-[520px] max-h-[75vh] flex-1 flex-col overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest xl:max-h-none">
            {selectedStatus && (
              <div className="flex shrink-0 items-center border-b border-surface-container-high px-5 py-3">
                <span
                  className={`inline-flex h-7 items-center gap-1 rounded border px-2 text-xs ${selectedStatus.className}`}
                >
                  <span aria-hidden="true" className="material-symbols-outlined text-[14px]">
                    {selectedStatus.icon}
                  </span>
                  {selectedStatus.label}
                </span>
              </div>
            )}
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
      )}
    </div>
    </>
  )
}
