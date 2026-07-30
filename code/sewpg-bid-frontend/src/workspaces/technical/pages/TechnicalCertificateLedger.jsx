import { useCallback, useEffect, useMemo, useState } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/TechnicalMaterialsViewSwitch'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import { PageError, PageLoading } from '../../../components/states/PageState'
import { workspaceRoute } from '../../../utils/workspace'

const safeMessage = (error, fallback) =>
  error?.payload?.detail || error?.message || fallback

const TECHNICAL_WORKSPACE = 'tech'
const extOf = (name = '') => String(name || '').split('.').pop()?.toLowerCase() || ''
const CERTIFICATE_VALIDITY_FILTERS = [
  { value: 'all', label: '全部记录' },
  { value: 'valid', label: '有效期内' },
  { value: 'expired', label: '已过期' },
  { value: 'follow', label: '跟随整机证' },
  { value: 'missing-expiry', label: '未识别到' },
  { value: 'same-name', label: '同名重复' },
  { value: 'merged-duplicate', label: '合并重复' },
]
const CERTIFICATE_VALIDITY_LABELS = {
  valid: '有效期内',
  expired: '已过期',
  follow: '跟随整机证',
  missing: '未识别到',
}
const certificateValidityOf = (item, today) => {
  if (item?.expiryDate && item.expiryDate < today) return 'expired'
  if ((item?.expiryDate && item.expiryDate >= today) || item?.longTerm) return 'valid'
  if (item?.validityBasis === 'follow_turbine') return 'follow'
  return 'missing'
}
const CERTIFICATE_STATUS_LABELS = {
  pending: '待识别',
  extracted: '已识别',
  not_found: '未找到日期',
  failed: '识别失败',
  unsupported: '不支持',
  manual: '人工维护',
}
const STAT_CARD_TONES = {
  neutral: {
    icon: 'bg-surface-container-high text-on-surface-variant',
    active: 'border-primary/50 bg-primary/5',
  },
  success: {
    icon: 'bg-secondary-container text-on-secondary-container',
    active: 'border-secondary/60 bg-secondary-container/25',
  },
  danger: {
    icon: 'bg-error-container text-error',
    active: 'border-error/60 bg-error-container/20',
  },
  warning: {
    icon: 'bg-tertiary-container text-on-tertiary-container',
    active: 'border-tertiary/60 bg-tertiary-container/25',
  },
}

const buildFailureReceipt = (item) => {
  const message = String(item?.errorMessage || '').trim()
  let conclusion = message || '未返回具体失败原因。'
  let suggestion = '可重新识别；如仍失败，请查看文件内容或改为人工维护日期。'

  if (message.includes('HTTP 403')) {
    conclusion = 'OCR 服务拒绝访问。'
    suggestion = '请检查系统设置中的 OCR 服务地址、API Key、模型权限或额度是否可用。'
  } else if (message.includes('No address associated with hostname')) {
    conclusion = 'OCR 服务地址无法解析。'
    suggestion = '请检查 OCR 服务域名、容器网络或本地 DNS 配置。'
  } else if (message.includes('OCR_CONFIG_REQUIRED') || message.includes('配置 OCR')) {
    conclusion = 'OCR 模型尚未完成配置。'
    suggestion = '请先在系统设置中启用并配置 OCR 模型。'
  }

  return {
    receiptNo: `${item?.fileId || 'RAW'}-${String(item?.updatedAt || '').replace(/[-:TZ]/g, '').slice(0, 14) || 'pending'}`,
    statusLabel: CERTIFICATE_STATUS_LABELS[item?.status] || item?.status || '-',
    rawMessage: message || '-',
    conclusion,
    suggestion,
  }
}

const normalizeSearchText = (value) => String(value || '').trim().toLocaleLowerCase()
const certificateNameKey = (item) => String(item?.name || '').trim().toLocaleLowerCase()
const normalizeScopePath = (value) => String(value || '').replace(/^\/+|\/+$/g, '')
const normalizeScopeTreeNodes = (nodes = []) =>
  (Array.isArray(nodes) ? nodes : [])
    .map((node) => {
      const path = normalizeScopePath(node?.path || node?.name || '')
      return {
        path,
        name: String(node?.name || node?.title || path.split('/').pop() || '未命名目录'),
        fileCount: Number(node?.fileCount || 0),
        children: normalizeScopeTreeNodes(node?.children || []),
      }
    })
    .filter((node) => node.path)
const collectDefaultExpandedTreePaths = (nodes = [], depth = 0, result = new Set()) => {
  nodes.forEach((node) => {
    if (node.children.length) {
      if (depth < 2) result.add(node.path)
      collectDefaultExpandedTreePaths(node.children, depth + 1, result)
    }
  })
  return result
}

export default function TechnicalCertificateLedger({ showToast = () => {} }) {
  const materialsBasePath = workspaceRoute(TECHNICAL_WORKSPACE, '/materials')
  const [data, setData] = useState({ items: [], total: 0, summary: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [saving, setSaving] = useState(false)
  const [scopes, setScopes] = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [suggestionLoading, setSuggestionLoading] = useState(false)
  const [scopeSaving, setScopeSaving] = useState(false)
  const [incrementalRunning, setIncrementalRunning] = useState(false)
  const [incrementalProgress, setIncrementalProgress] = useState(null)
  const [recognizingIds, setRecognizingIds] = useState(new Set())
  const [runResult, setRunResult] = useState(null)
  const [previewItem, setPreviewItem] = useState(null)
  const [previewSession, setPreviewSession] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [filters, setFilters] = useState({ keyword: '', status: 'all', validity: 'all' })
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [scopeDialogOpen, setScopeDialogOpen] = useState(false)
  const [selectedSuggestionPaths, setSelectedSuggestionPaths] = useState(new Set())
  const [selectedConfirmedScopePaths, setSelectedConfirmedScopePaths] = useState(new Set())
  const [receiptItem, setReceiptItem] = useState(null)
  const [scopeSourceTab, setScopeSourceTab] = useState('suggestions')
  const [scopeTree, setScopeTree] = useState([])
  const [scopeTreeLoading, setScopeTreeLoading] = useState(false)
  const [scopeTreeLoaded, setScopeTreeLoaded] = useState(false)
  const [expandedTreePaths, setExpandedTreePaths] = useState(() => new Set())
  const [scopeDropActive, setScopeDropActive] = useState(false)

  const loadData = useCallback(async (options = {}) => {
    // quiet 模式供后台轮询使用，避免整页 loading 闪烁
    const quiet = Boolean(options?.quiet)
    if (!quiet) setLoading(true)
    setError('')
    try {
      const payload = await technicalMaterialsAPI.certificates.ledger()
      setData(payload || { items: [], total: 0, summary: {} })
      setScopes(payload?.config?.scopes || [])
      setSelectedConfirmedScopePaths(new Set())
    } catch (e) {
      const message = safeMessage(e, '证书台账加载失败，请稍后重试。')
      setError(message)
      showToast(message, 'error')
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  // 挂载时探测后台识别任务：任务在跑则直接进入轮询态（离开页面再回来可接上）
  useEffect(() => {
    let cancelled = false
    technicalMaterialsAPI.certificates.incrementalStatus()
      .then((status) => {
        if (cancelled || status?.status !== 'running') return
        setIncrementalProgress(status?.progress || null)
        setIncrementalRunning(true)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  // 后台识别任务轮询：刷新台账计数，直到任务到达终态
  useEffect(() => {
    if (!incrementalRunning) return undefined
    let stopped = false
    const finish = () => {
      setIncrementalRunning(false)
      setIncrementalProgress(null)
    }
    const tick = async () => {
      try {
        const status = await technicalMaterialsAPI.certificates.incrementalStatus()
        if (stopped) return
        if (status?.status === 'running') {
          setIncrementalProgress(status?.progress || null)
          loadData({ quiet: true })
          return
        }
        finish()
        if (status?.status === 'succeeded') {
          const result = status?.result || {}
          setRunResult(result)
          showToast(result?.message || '增量识别完成', (result?.failed || []).length ? 'warning' : 'success')
        } else if (status?.status === 'failed') {
          showToast(status?.error || '增量识别失败', 'error')
        } else {
          // idle：后端重启丢了任务状态，已识别成果已逐文件落库，提示重触续跑
          showToast('识别任务已随服务重启中断，已识别的成果已保留，可重新触发继续。', 'warning')
        }
        loadData({ quiet: true })
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
  }, [incrementalRunning, loadData, showToast])

  const rows = useMemo(() => (Array.isArray(data?.items) ? data.items : []), [data])
  const confirmedScopePaths = useMemo(() => scopes.map((scope) => normalizeScopePath(scope.path)).filter(Boolean), [scopes])
  const selectedScopePaths = useMemo(() => new Set(confirmedScopePaths), [confirmedScopePaths])
  const today = useMemo(() => new Date().toISOString().slice(0, 10), [])
  const nameCounts = useMemo(() => {
    const counts = new Map()
    rows.forEach((item) => {
      const key = certificateNameKey(item)
      if (!key) return
      counts.set(key, (counts.get(key) || 0) + 1)
    })
    return counts
  }, [rows])
  const statusOptions = useMemo(() => {
    const values = new Set(rows.map((item) => String(item.status || '').trim()).filter(Boolean))
    if (filters.status !== 'all') values.add(filters.status)
    return Array.from(values).sort((left, right) => left.localeCompare(right, 'zh-CN'))
  }, [filters.status, rows])
  const filteredRows = useMemo(() => {
    const keyword = normalizeSearchText(filters.keyword)
    return rows.filter((item) => {
      if (keyword) {
        const haystack = [
          item.name,
          item.folderPath,
          item.status,
          item.issueDate,
          item.expiryDate,
        ].map((value) => String(value || '').toLocaleLowerCase()).join(' ')
        if (!haystack.includes(keyword)) return false
      }
      if (filters.status !== 'all' && String(item.status || '') !== filters.status) return false
      const validity = certificateValidityOf(item, today)
      if (filters.validity === 'expired' && validity !== 'expired') return false
      if (filters.validity === 'valid' && validity !== 'valid') return false
      if (filters.validity === 'follow' && validity !== 'follow') return false
      if (filters.validity === 'missing-expiry' && validity !== 'missing') return false
      if (filters.validity === 'same-name' && (nameCounts.get(certificateNameKey(item)) || 0) <= 1) return false
      if (filters.validity === 'merged-duplicate' && Number(item.duplicateCount || 0) <= 1) return false
      return true
    })
  }, [filters, nameCounts, rows, today])
  const visibleFileIds = useMemo(
    () => filteredRows.map((item) => item.fileId).filter(Boolean),
    [filteredRows],
  )
  const selectedVisibleCount = useMemo(
    () => visibleFileIds.filter((fileId) => selectedIds.has(fileId)).length,
    [selectedIds, visibleFileIds],
  )
  const allVisibleSelected = visibleFileIds.length > 0 && selectedVisibleCount === visibleFileIds.length
  const expiredCount = useMemo(() => {
    return rows.filter((item) => certificateValidityOf(item, today) === 'expired').length
  }, [rows, today])
  const validCount = useMemo(() => {
    return rows.filter((item) => certificateValidityOf(item, today) === 'valid').length
  }, [rows, today])
  const failedCount = useMemo(() => {
    return rows.filter((item) => String(item.status || '') === 'failed').length
  }, [rows])
  const statCards = [
    {
      key: 'all',
      label: '台账记录',
      value: data?.total || 0,
      icon: 'database',
      tone: 'neutral',
      hint: '显示全部证书记录',
      active: filters.status === 'all' && filters.validity === 'all',
    },
    {
      key: 'valid',
      label: '有效期内',
      value: validCount,
      icon: 'verified_user',
      tone: 'success',
      hint: '点击查看仍在有效期内的证书，再次点击取消筛选',
      active: filters.validity === 'valid' && filters.status === 'all',
    },
    {
      key: 'expired',
      label: '已过期',
      value: expiredCount,
      icon: 'event_busy',
      tone: 'danger',
      hint: '点击查看已超过有效期的证书，再次点击取消筛选',
      active: filters.validity === 'expired' && filters.status === 'all',
    },
    {
      key: 'failed',
      label: '识别失败',
      value: failedCount,
      icon: 'error',
      tone: 'warning',
      hint: '点击查看日期识别失败的证书，再次点击取消筛选',
      active: filters.status === 'failed' && filters.validity === 'all',
    },
  ]
  const visibleSuggestions = useMemo(() => suggestions.slice(0, 40), [suggestions])
  const selectableSuggestionPaths = useMemo(() => {
    const paths = []
    visibleSuggestions.forEach((item) => {
      const path = normalizeScopePath(item.path)
      if (path && !selectedScopePaths.has(path)) paths.push(path)
    })
    return paths
  }, [selectedScopePaths, visibleSuggestions])
  const selectedSuggestionCount = useMemo(
    () => selectableSuggestionPaths.filter((path) => selectedSuggestionPaths.has(path)).length,
    [selectableSuggestionPaths, selectedSuggestionPaths],
  )
  const allSuggestionsSelected = selectableSuggestionPaths.length > 0
    && selectedSuggestionCount === selectableSuggestionPaths.length
  const selectedConfirmedScopeCount = useMemo(
    () => confirmedScopePaths.filter((path) => selectedConfirmedScopePaths.has(path)).length,
    [confirmedScopePaths, selectedConfirmedScopePaths],
  )
  const allConfirmedScopesSelected = confirmedScopePaths.length > 0
    && selectedConfirmedScopeCount === confirmedScopePaths.length

  const updateFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setSelectedIds(new Set())
  }

  const clearFilters = () => {
    setFilters({ keyword: '', status: 'all', validity: 'all' })
    setSelectedIds(new Set())
  }

  const applyStatCardFilter = (key) => {
    setFilters((prev) => {
      const reset = { ...prev, status: 'all', validity: 'all' }
      if (key === 'valid') {
        return prev.validity === 'valid' && prev.status === 'all'
          ? reset
          : { ...prev, status: 'all', validity: 'valid' }
      }
      if (key === 'expired') {
        return prev.validity === 'expired' && prev.status === 'all'
          ? reset
          : { ...prev, status: 'all', validity: 'expired' }
      }
      if (key === 'failed') {
        return prev.status === 'failed' && prev.validity === 'all'
          ? reset
          : { ...prev, status: 'failed', validity: 'all' }
      }
      return reset
    })
    setSelectedIds(new Set())
  }

  const toggleRowSelection = (fileId) => {
    if (!fileId) return
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(fileId)) {
        next.delete(fileId)
      } else {
        next.add(fileId)
      }
      return next
    })
  }

  const toggleVisibleSelection = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allVisibleSelected) {
        visibleFileIds.forEach((fileId) => next.delete(fileId))
      } else {
        visibleFileIds.forEach((fileId) => next.add(fileId))
      }
      return next
    })
  }

  const deleteSelectedRecords = async () => {
    const fileIds = visibleFileIds.filter((fileId) => selectedIds.has(fileId))
    if (!fileIds.length || bulkDeleting) return
    const ok = window.confirm(`确认从证书台账批量删除 ${fileIds.length} 条记录？原始素材文件不会删除。`)
    if (!ok) return
    setBulkDeleting(true)
    try {
      const payload = await technicalMaterialsAPI.certificates.bulkDelete(fileIds)
      setSelectedIds(new Set())
      showToast(payload?.message || '证书台账记录已批量删除', (payload?.failed || []).length ? 'warning' : 'success')
      await loadData()
    } catch (e) {
      showToast(safeMessage(e, '证书台账记录批量删除失败'), 'error')
    } finally {
      setBulkDeleting(false)
    }
  }

  const loadSuggestions = async () => {
    setSuggestionLoading(true)
    try {
      const payload = await technicalMaterialsAPI.certificates.suggestions()
      setSuggestions(payload?.items || [])
      setSelectedSuggestionPaths(new Set())
      if (payload?.config?.scopes) {
        setScopes(payload.config.scopes)
        setSelectedConfirmedScopePaths(new Set())
      }
    } catch (e) {
      showToast(safeMessage(e, '建议目录生成失败'), 'error')
    } finally {
      setSuggestionLoading(false)
    }
  }

  const loadScopeTree = async () => {
    setScopeTreeLoading(true)
    try {
      const payload = await technicalMaterialsAPI.raw.tree()
      const nodes = normalizeScopeTreeNodes(payload?.tree || payload?.items || payload?.nodes || [])
      setScopeTree(nodes)
      setExpandedTreePaths(collectDefaultExpandedTreePaths(nodes))
      setScopeTreeLoaded(true)
    } catch (e) {
      showToast(safeMessage(e, '素材目录树加载失败'), 'error')
    } finally {
      setScopeTreeLoading(false)
    }
  }

  const openScopeDialog = () => {
    setScopeDialogOpen(true)
    if (!scopeTreeLoaded && !scopeTreeLoading) loadScopeTree()
    if (!suggestions.length && !suggestionLoading) loadSuggestions()
  }

  const toggleTreeExpand = (path) => {
    setExpandedTreePaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  const handleScopeDragStart = (event, path) => {
    event.dataTransfer.setData('text/plain', path)
    event.dataTransfer.effectAllowed = 'copy'
  }

  const handleScopeDrop = (event) => {
    event.preventDefault()
    setScopeDropActive(false)
    const path = normalizeScopePath(event.dataTransfer.getData('text/plain'))
    if (!path) return
    if (selectedScopePaths.has(path)) {
      showToast('该目录已在已确认列表中', 'warning')
      return
    }
    addScope({ path, source: 'manual' })
  }

  const addScope = (scope) => {
    const path = normalizeScopePath(scope?.path)
    if (!path || selectedScopePaths.has(path)) return
    setScopes((prev) => [
      ...prev,
      {
        path,
        name: scope?.name || path.split('/').pop(),
        enabled: true,
        source: scope?.source || 'manual',
      },
    ])
  }

  const toggleSuggestionSelection = (path) => {
    const normalizedPath = normalizeScopePath(path)
    if (!normalizedPath || selectedScopePaths.has(normalizedPath)) return
    setSelectedSuggestionPaths((prev) => {
      const next = new Set(prev)
      if (next.has(normalizedPath)) {
        next.delete(normalizedPath)
      } else {
        next.add(normalizedPath)
      }
      return next
    })
  }

  const selectAllSuggestions = () => {
    setSelectedSuggestionPaths(new Set(selectableSuggestionPaths))
  }

  const clearSuggestionSelection = () => {
    setSelectedSuggestionPaths(new Set())
  }

  const addSuggestionScopes = (items) => {
    const normalizedItems = items
      .map((item) => ({ ...item, path: normalizeScopePath(item.path) }))
      .filter((item) => item.path && !selectedScopePaths.has(item.path))
    if (!normalizedItems.length) return
    const addedPaths = new Set(normalizedItems.map((item) => item.path))
    setScopes((prev) => {
      const seen = new Set(prev.map((scope) => normalizeScopePath(scope.path)))
      const next = [...prev]
      normalizedItems.forEach((item) => {
        if (seen.has(item.path)) return
        seen.add(item.path)
        next.push({
          path: item.path,
          name: item.name || item.path.split('/').pop(),
          enabled: true,
          source: 'suggestion',
        })
      })
      return next
    })
    setSelectedSuggestionPaths((prev) => new Set(Array.from(prev).filter((path) => !addedPaths.has(path))))
  }

  const addSelectedSuggestions = () => {
    addSuggestionScopes(visibleSuggestions.filter((item) => selectedSuggestionPaths.has(normalizeScopePath(item.path))))
  }

  const addAllSuggestions = () => {
    addSuggestionScopes(visibleSuggestions)
  }

  const toggleConfirmedScopeSelection = (path) => {
    const normalizedPath = normalizeScopePath(path)
    if (!normalizedPath || !selectedScopePaths.has(normalizedPath)) return
    setSelectedConfirmedScopePaths((prev) => {
      const next = new Set(prev)
      if (next.has(normalizedPath)) {
        next.delete(normalizedPath)
      } else {
        next.add(normalizedPath)
      }
      return next
    })
  }

  const selectAllConfirmedScopes = () => {
    setSelectedConfirmedScopePaths(new Set(confirmedScopePaths))
  }

  const clearConfirmedScopeSelection = () => {
    setSelectedConfirmedScopePaths(new Set())
  }

  const removeSelectedScopes = () => {
    if (!selectedConfirmedScopeCount) return
    setScopes((prev) => prev.filter((scope) => !selectedConfirmedScopePaths.has(normalizeScopePath(scope.path))))
    setSelectedConfirmedScopePaths(new Set())
  }

  const removeScope = (path) => {
    const normalizedPath = normalizeScopePath(path)
    setScopes((prev) => prev.filter((scope) => normalizeScopePath(scope.path) !== normalizedPath))
    setSelectedConfirmedScopePaths((prev) => {
      const next = new Set(prev)
      next.delete(normalizedPath)
      return next
    })
  }

  const renderScopeTreeNode = (node, depth = 0) => {
    const added = selectedScopePaths.has(node.path)
    const hasChildren = node.children.length > 0
    const expanded = expandedTreePaths.has(node.path)
    return (
      <div key={node.path}>
        <div
          draggable={!added}
          onDragStart={(event) => handleScopeDragStart(event, node.path)}
          className={`flex items-center gap-1.5 rounded-lg py-1 pr-1.5 text-xs hover:bg-surface-container-high/60 ${added ? '' : 'cursor-grab'}`}
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={() => toggleTreeExpand(node.path)}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline hover:bg-surface-container-high"
              aria-label={expanded ? `收起 ${node.name}` : `展开 ${node.name}`}
            >
              <span className="material-symbols-outlined text-[16px]">{expanded ? 'expand_more' : 'chevron_right'}</span>
            </button>
          ) : (
            <span className="h-5 w-5 shrink-0" aria-hidden="true" />
          )}
          <input
            type="checkbox"
            checked={added}
            onChange={() => (added ? removeScope(node.path) : addScope({ path: node.path, name: node.name, source: 'tree' }))}
            className="h-4 w-4 shrink-0 accent-primary"
            aria-label={`将目录 ${node.path} 加入识别范围`}
          />
          <span className="min-w-0 flex-1 truncate text-on-surface" title={node.path}>{node.name}</span>
          {node.fileCount > 0 && (
            <span className="shrink-0 rounded bg-surface-container-high px-1.5 py-0.5 text-[10px] tabular-nums text-on-surface-variant">{node.fileCount}</span>
          )}
        </div>
        {hasChildren && expanded ? node.children.map((child) => renderScopeTreeNode(child, depth + 1)) : null}
      </div>
    )
  }

  const saveScopes = async () => {
    setScopeSaving(true)
    try {
      const payload = await technicalMaterialsAPI.certificates.saveScopes({ scopes })
      setScopes(payload?.config?.scopes || [])
      setSelectedConfirmedScopePaths(new Set())
      showToast(payload?.message || '证书识别范围已更新')
      await loadData()
    } catch (e) {
      showToast(safeMessage(e, '证书识别范围保存失败'), 'error')
    } finally {
      setScopeSaving(false)
    }
  }

  const runIncremental = async () => {
    if (!scopes.length) {
      showToast('请先添加并保存需要识别的目录。', 'error')
      return
    }
    try {
      const saved = await technicalMaterialsAPI.certificates.saveScopes({ scopes })
      setScopes(saved?.config?.scopes || scopes)
      // 后台任务：立即返回，全量处理所有待识别文件，离开页面不中断
      const status = await technicalMaterialsAPI.certificates.incremental({ includeFailed: true })
      setIncrementalProgress(status?.progress || null)
      setIncrementalRunning(true)
      showToast('增量识别已在后台开始，将处理全部待识别文件；可离开本页，完成后自动更新。')
    } catch (e) {
      showToast(safeMessage(e, '增量识别启动失败'), 'error')
    }
  }

  const startEdit = (item) => {
    setEditing({
      fileId: item.fileId,
      name: item.name,
      issueDate: item.issueDate || '',
      expiryDate: item.expiryDate || '',
    })
  }

  const closeEdit = () => {
    if (saving) return
    setEditing(null)
  }

  const saveEdit = async () => {
    if (!editing?.fileId) return
    setSaving(true)
    try {
      const payload = await technicalMaterialsAPI.certificates.update(editing.fileId, {
        issueDate: editing.issueDate,
        expiryDate: editing.expiryDate,
      })
      const updated = payload?.item
      if (updated?.fileId) {
        setData((prev) => ({
          ...(prev || {}),
          items: (prev?.items || []).map((item) => item.fileId === updated.fileId ? updated : item),
        }))
      }
      showToast(payload?.message || '证书时间已更新')
      setEditing(null)
    } catch (e) {
      showToast(safeMessage(e, '证书时间保存失败'), 'error')
    } finally {
      setSaving(false)
    }
  }

  const openPreview = async (item) => {
    if (!item?.fileId) return
    setPreviewItem(item)
    setPreviewSession(null)
    setPreviewError('')
    const ext = extOf(item.name)
    if (ext === 'pdf' || ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'].includes(ext)) {
      return
    }
    setPreviewLoading(true)
    try {
      const payload = await technicalMaterialsAPI.raw.previewCleanedFile(item.fileId)
      setPreviewSession(payload)
    } catch (e) {
      setPreviewError(safeMessage(e, '当前文件暂不支持在线预览'))
    } finally {
      setPreviewLoading(false)
    }
  }

  const recognizeOne = async (item) => {
    if (!item?.fileId || recognizingIds.has(item.fileId)) return
    setRecognizingIds((prev) => new Set(prev).add(item.fileId))
    try {
      const payload = await technicalMaterialsAPI.certificates.recognize(item.fileId)
      const updated = payload?.items?.[0]
      if (updated?.fileId) {
        setData((prev) => ({
          ...(prev || {}),
          items: (prev?.items || []).map((row) => row.fileId === updated.fileId ? updated : row),
        }))
      }
      showToast(payload?.message || '单文件识别完成', (payload?.failed || []).length ? 'warning' : 'success')
      await loadData()
    } catch (e) {
      showToast(safeMessage(e, '单文件识别失败'), 'error')
    } finally {
      setRecognizingIds((prev) => {
        const next = new Set(prev)
        next.delete(item.fileId)
        return next
      })
    }
  }

  const deleteRecord = async (item) => {
    if (!item?.fileId) return
    const ok = window.confirm(`确认从证书台账删除「${item.name || item.fileId}」的证书时间记录？原始素材文件不会删除。`)
    if (!ok) return
    try {
      const payload = await technicalMaterialsAPI.certificates.delete(item.fileId)
      showToast(payload?.message || '证书台账记录已删除')
      await loadData()
    } catch (e) {
      showToast(safeMessage(e, '证书台账记录删除失败'), 'error')
    }
  }

  const closePreview = () => {
    setPreviewItem(null)
    setPreviewSession(null)
    setPreviewError('')
    setPreviewLoading(false)
  }

  if (loading && !rows.length) {
    return <PageLoading title="正在加载证书台账..." description="正在读取证书发证日期和有效期。" />
  }

  if (error && !rows.length) {
    return (
      <PageError
        title="证书台账加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  return (
    <>
      <div className="flex flex-col gap-3 animate-fade-in">
        <MaterialsViewSwitch
          active="certificates"
          title="证书台账"
          actions={(
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={openScopeDialog}
                className="h-9 rounded-lg bg-surface-container-high px-3 text-xs font-semibold text-on-surface hover:bg-surface-dim"
              >
                识别范围
              </button>
              <button
                type="button"
                onClick={runIncremental}
                disabled={incrementalRunning || scopeSaving}
                className="h-9 rounded-lg bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:cursor-not-allowed disabled:opacity-45"
              >
                {incrementalRunning
                  ? `识别中${incrementalProgress?.total ? ` ${incrementalProgress?.processed || 0}/${incrementalProgress.total}` : ''}...`
                  : '增量识别'}
              </button>
              <button
                type="button"
                onClick={loadData}
                disabled={loading}
                className="h-9 rounded-lg bg-surface-container-high px-3 text-xs font-semibold text-on-surface hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-45"
              >
                {loading ? '刷新中...' : '刷新'}
              </button>
            </div>
          )}
          basePath={materialsBasePath}
        />

        {runResult && (
          <div className="rounded-lg border border-tertiary/25 bg-tertiary-container/30 px-4 py-2 text-xs text-on-tertiary-container">
            {runResult.message || '增量识别完成'}，处理 {runResult.processed || 0} 个，跳过 {runResult.skipped || 0} 个。
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" role="group" aria-label="证书状态概览">
          {statCards.map((card) => {
            const tone = STAT_CARD_TONES[card.tone] || STAT_CARD_TONES.neutral
            return (
              <button
                key={card.key}
                type="button"
                onClick={() => applyStatCardFilter(card.key)}
                aria-pressed={card.active}
                title={card.hint}
                className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors ${
                  card.active
                    ? `${tone.active} shadow-sm`
                    : 'border-outline-variant/45 bg-surface-container-lowest hover:border-primary/40 hover:bg-surface-container-low'
                }`}
              >
                <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tone.icon}`}>
                  <span aria-hidden="true" className="material-symbols-outlined text-[18px]">{card.icon}</span>
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-outline">{card.label}</span>
                  <span className="mt-0.5 block text-xl font-semibold leading-6 tabular-nums text-on-surface">{card.value}</span>
                </span>
                {card.active ? (
                  <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[16px] text-primary">filter_alt</span>
                ) : null}
              </button>
            )
          })}
        </div>

        <section className="min-h-[520px] overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest">
          {error && rows.length > 0 ? (
            <div className="border-b border-error/20 bg-error-container/20 px-4 py-2 text-sm text-error">{error}</div>
          ) : null}
          <div className="flex flex-col gap-2 border-b border-surface-container-high bg-surface-container-lowest px-4 py-3 xl:flex-row xl:items-center">
            <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 md:grid-cols-[minmax(12rem,1fr)_10rem_10rem_auto]">
              <input
                value={filters.keyword}
                onChange={(event) => updateFilter('keyword', event.target.value)}
                placeholder="搜索文件、目录、状态、日期"
                className="h-9 min-w-0 rounded-lg border border-surface-container-high bg-white px-3 text-xs text-on-surface"
              />
              <select
                value={filters.status}
                onChange={(event) => updateFilter('status', event.target.value)}
                className="h-9 rounded-lg border border-surface-container-high bg-white px-3 text-xs text-on-surface"
              >
                <option value="all">全部状态</option>
                {statusOptions.map((status) => (
                  <option key={status} value={status}>{CERTIFICATE_STATUS_LABELS[status] || status}</option>
                ))}
              </select>
              <select
                value={filters.validity}
                onChange={(event) => updateFilter('validity', event.target.value)}
                className="h-9 rounded-lg border border-surface-container-high bg-white px-3 text-xs text-on-surface"
              >
                {CERTIFICATE_VALIDITY_FILTERS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={clearFilters}
                className="h-9 rounded-lg bg-surface-container-high px-3 text-xs font-semibold text-on-surface hover:bg-surface-dim"
              >
                清空
              </button>
            </div>
            <div className="flex shrink-0 items-center justify-between gap-2 xl:justify-end">
              <span className="whitespace-nowrap text-xs text-outline">
                已选 {selectedVisibleCount} 项 / 显示 {filteredRows.length} 项
              </span>
              <button
                type="button"
                onClick={deleteSelectedRecords}
                disabled={!selectedVisibleCount || bulkDeleting}
                className="h-9 rounded-lg bg-error-container px-3 text-xs font-semibold text-error hover:bg-error-container/80 disabled:cursor-not-allowed disabled:opacity-45"
              >
                {bulkDeleting ? '删除中...' : '批量删除'}
              </button>
            </div>
          </div>
          {rows.length ? (
            <div className="overflow-x-auto">
              <div className="min-w-[1060px]">
                <div className="grid grid-cols-[2rem_minmax(14rem,1.5fr)_7.5rem_7.5rem_5.5rem_6rem_minmax(12rem,1fr)_7rem] items-center gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-2 text-xs font-semibold text-on-surface-variant">
                  <label className="flex items-center" title="选择当前筛选结果">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleVisibleSelection}
                      disabled={!visibleFileIds.length}
                      className="h-4 w-4 accent-primary disabled:opacity-45"
                      aria-label="选择当前筛选结果"
                    />
                  </label>
                  <span>文件</span>
                  <span>发证日期</span>
                  <span>有效期至</span>
                  <span>有效期</span>
                  <span>状态</span>
                  <span>素材目录</span>
                  <span>操作</span>
                </div>
                <div className="max-h-[64vh] overflow-y-auto divide-y divide-surface-container-high">
                  {filteredRows.length ? filteredRows.map((item) => (
                    <div
                      key={item.fileId}
                      className={`grid grid-cols-[2rem_minmax(14rem,1.5fr)_7.5rem_7.5rem_5.5rem_6rem_minmax(12rem,1fr)_7rem] items-center gap-3 px-4 py-2 text-xs text-on-surface-variant transition-colors ${
                        selectedIds.has(item.fileId) ? 'bg-primary/5' : 'hover:bg-surface-container-low/70'
                      }`}
                    >
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(item.fileId)}
                          onChange={() => toggleRowSelection(item.fileId)}
                          className="h-4 w-4 accent-primary"
                          aria-label={`选择 ${item.name}`}
                        />
                      </label>
                      <span className="flex min-w-0 items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => openPreview(item)}
                          className="min-w-0 truncate text-left font-medium text-on-surface hover:text-primary hover:underline"
                          title={`预览 ${item.name}`}
                        >
                          {item.name}
                        </button>
                        {Number(item.duplicateCount || 0) > 1 && (
                          <span
                            className="shrink-0 rounded bg-tertiary-container px-1.5 py-0.5 text-[10px] font-semibold text-on-tertiary-container"
                            title={`已合并 ${item.duplicateCount} 条同路径同名记录`}
                          >
                            重复 {item.duplicateCount}
                          </span>
                        )}
                      </span>
                      <span className="truncate tabular-nums">{item.issueDate || '-'}</span>
                      <span className="flex min-w-0 items-center gap-1">
                        <span
                          className={`truncate font-semibold tabular-nums ${
                            item.expiryDate && item.expiryDate < today ? 'text-error' : 'text-on-surface'
                          }`}
                          title={item.validityNote || ''}
                        >
                          {item.expiryDate
                            ? `${item.expiryDate}${item.validityBasis === 'rule_derived' ? '（推算）' : item.validityBasis === 'follow_turbine' ? '（跟随整机证）' : ''}`
                            : item.longTerm
                              ? item.validityNote || '长期有效'
                              : item.validityBasis === 'follow_turbine'
                                ? '跟随整机证'
                                : '-'}
                        </span>
                        {(item.warnings || []).length > 0 && (
                          <span
                            className="material-symbols-outlined shrink-0 text-[14px] text-error"
                            title={(item.warnings || []).join('；')}
                          >
                            warning
                          </span>
                        )}
                      </span>
                      <span className="min-w-0 truncate">
                        <span className={`inline-flex max-w-full items-center rounded px-1.5 py-0.5 text-[11px] font-medium ${
                          certificateValidityOf(item, today) === 'valid'
                            ? 'bg-secondary-container text-on-secondary-container'
                            : certificateValidityOf(item, today) === 'expired'
                              ? 'bg-error-container/70 text-error'
                              : 'bg-surface-container-high text-on-surface-variant'
                        }`}>
                          <span className="truncate">{CERTIFICATE_VALIDITY_LABELS[certificateValidityOf(item, today)]}</span>
                        </span>
                      </span>
                      <span className="min-w-0 truncate" title={item.errorMessage || CERTIFICATE_STATUS_LABELS[item.status] || item.status}>
                        <span className={`inline-flex max-w-full items-center rounded px-1.5 py-0.5 text-[11px] font-medium ${
                          item.status === 'extracted' || item.status === 'manual'
                            ? 'bg-secondary-container text-on-secondary-container'
                            : item.status === 'failed' || item.status === 'unsupported'
                              ? 'bg-error-container/70 text-error'
                              : 'bg-surface-container-high text-on-surface-variant'
                        }`}>
                          <span className="truncate">{CERTIFICATE_STATUS_LABELS[item.status] || item.status || '-'}</span>
                        </span>
                        {item.errorMessage ? (
                          <button
                            type="button"
                            onClick={() => setReceiptItem(item)}
                            className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded text-error hover:bg-error-container/50"
                            aria-label={`查看 ${item.name} 的识别失败回执`}
                            title="查看识别失败回执"
                          >
                            <span className="material-symbols-outlined text-[14px]">receipt_long</span>
                          </button>
                        ) : null}
                      </span>
                      <span className="truncate" title={item.folderPath}>{item.folderPath || '-'}</span>
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => recognizeOne(item)}
                          disabled={recognizingIds.has(item.fileId)}
                          className="flex h-7 w-7 items-center justify-center rounded text-outline hover:bg-secondary-container/50 hover:text-secondary disabled:cursor-not-allowed disabled:opacity-45"
                          aria-label={`重新识别 ${item.name} 的证书时间`}
                          title="重新识别"
                        >
                          <span className={`material-symbols-outlined text-[16px] ${recognizingIds.has(item.fileId) ? 'animate-spin' : ''}`}>
                            {recognizingIds.has(item.fileId) ? 'progress_activity' : 'sync'}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => startEdit(item)}
                          className="flex h-7 w-7 items-center justify-center rounded text-outline hover:bg-primary/10 hover:text-primary"
                          aria-label={`编辑 ${item.name} 的证书时间`}
                          title="编辑"
                        >
                          <span className="material-symbols-outlined text-[16px]">edit</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteRecord(item)}
                          className="flex h-7 w-7 items-center justify-center rounded text-outline hover:bg-error-container/30 hover:text-error"
                          aria-label={`删除 ${item.name} 的证书时间记录`}
                          title="删除记录"
                        >
                          <span className="material-symbols-outlined text-[16px]">delete</span>
                        </button>
                      </span>
                    </div>
                  )) : (
                    <div className="px-4 py-12 text-center text-sm text-on-surface-variant">
                      当前筛选条件下暂无证书记录
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-[520px] items-center justify-center text-center">
              <div>
                <span className="material-symbols-outlined text-4xl text-outline/60">event_busy</span>
                <p className="mt-2 text-sm text-on-surface-variant">暂无证书台账记录</p>
                <p className="mt-1 text-xs text-outline">请先添加识别范围并执行增量识别。</p>
              </div>
            </div>
          )}
        </section>
      </div>

      {scopeDialogOpen && (
        <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="wizard-modal-surface flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest animate-float-in">
            <div className="flex items-center justify-between gap-3 border-b border-surface-container-high px-5 py-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-on-surface">识别范围</h3>
                <p className="mt-1 text-xs text-outline">{scopes.length} 个已确认目录，{suggestions.length} 个建议目录</p>
              </div>
              <button
                type="button"
                onClick={() => setScopeDialogOpen(false)}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-primary"
                aria-label="关闭识别范围"
                title="关闭"
              >
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-auto p-5">
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <section className="flex h-[60vh] flex-col rounded-lg border border-outline-variant/45 bg-surface-container-low p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-0.5 rounded-lg bg-surface-container-high p-0.5">
                      <button
                        type="button"
                        onClick={() => setScopeSourceTab('suggestions')}
                        className={`h-7 rounded-md px-3 text-xs font-semibold transition-colors ${
                          scopeSourceTab === 'suggestions'
                            ? 'bg-surface-container-lowest text-on-surface shadow-sm'
                            : 'text-on-surface-variant hover:text-on-surface'
                        }`}
                      >
                        建议目录
                      </button>
                      <button
                        type="button"
                        onClick={() => setScopeSourceTab('tree')}
                        className={`h-7 rounded-md px-3 text-xs font-semibold transition-colors ${
                          scopeSourceTab === 'tree'
                            ? 'bg-surface-container-lowest text-on-surface shadow-sm'
                            : 'text-on-surface-variant hover:text-on-surface'
                        }`}
                      >
                        目录树
                      </button>
                    </div>
                    {scopeSourceTab === 'suggestions' ? (
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={loadSuggestions}
                          disabled={suggestionLoading}
                          className="h-8 rounded-lg bg-surface-container-high px-3 text-xs font-semibold text-on-surface hover:bg-surface-dim disabled:opacity-45"
                        >
                          {suggestionLoading ? '生成中...' : '生成建议'}
                        </button>
                        <button
                          type="button"
                          onClick={addAllSuggestions}
                          disabled={!selectableSuggestionPaths.length}
                          className="h-8 rounded-lg bg-primary/10 px-3 text-xs font-semibold text-primary hover:bg-primary/15 disabled:opacity-45"
                        >
                          全部加入
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={loadScopeTree}
                        disabled={scopeTreeLoading}
                        className="h-8 rounded-lg bg-surface-container-high px-3 text-xs font-semibold text-on-surface hover:bg-surface-dim disabled:opacity-45"
                      >
                        {scopeTreeLoading ? '加载中...' : '刷新目录树'}
                      </button>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-outline">
                    {scopeSourceTab === 'suggestions'
                      ? `已选 ${selectedSuggestionCount} 项 / 可加入 ${selectableSuggestionPaths.length} 项，可勾选批量加入或拖动到右侧`
                      : '勾选目录即加入右侧已确认列表，也可直接拖动目录到右侧'}
                  </p>
                  {scopeSourceTab === 'suggestions' ? (
                    <>
                      {suggestions.length ? (
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-container-high bg-surface-container-lowest px-2 py-2">
                          <div className="flex items-center gap-2">
                            <label className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant">
                              <input
                                type="checkbox"
                                checked={allSuggestionsSelected}
                                onChange={allSuggestionsSelected ? clearSuggestionSelection : selectAllSuggestions}
                                disabled={!selectableSuggestionPaths.length}
                                className="h-4 w-4 accent-primary disabled:opacity-45"
                              />
                              全选
                            </label>
                            <button
                              type="button"
                              onClick={clearSuggestionSelection}
                              disabled={!selectedSuggestionCount}
                              className="h-7 rounded px-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-high disabled:opacity-45"
                            >
                              清空
                            </button>
                          </div>
                          <button
                            type="button"
                            onClick={addSelectedSuggestions}
                            disabled={!selectedSuggestionCount}
                            className="h-7 rounded bg-primary px-2.5 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-45"
                          >
                            加入所选
                          </button>
                        </div>
                      ) : null}
                      <div className="mt-3 min-h-0 flex-1 space-y-0.5 overflow-y-auto rounded-lg border border-surface-container-high bg-surface-container-lowest p-1.5">
                        {suggestionLoading && !visibleSuggestions.length ? (
                          <div className="flex h-full items-center justify-center px-3 text-center text-xs text-outline">
                            正在根据台账与素材目录生成建议...
                          </div>
                        ) : visibleSuggestions.length ? visibleSuggestions.map((item) => {
                          const path = normalizeScopePath(item.path)
                          const added = selectedScopePaths.has(path)
                          const checked = selectedSuggestionPaths.has(path)
                          return (
                            <div
                              key={item.path}
                              draggable={!added}
                              onDragStart={(event) => handleScopeDragStart(event, path)}
                              className={`rounded-lg px-1.5 py-1.5 hover:bg-surface-container-high/60 ${added ? '' : 'cursor-grab'}`}
                            >
                              <div className="flex items-center gap-2">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleSuggestionSelection(path)}
                                  disabled={added}
                                  className="h-4 w-4 shrink-0 accent-primary disabled:opacity-45"
                                  aria-label={`选择建议目录 ${item.path}`}
                                />
                                <span className="min-w-0 flex-1 truncate text-xs font-medium text-on-surface" title={item.path}>{item.path}</span>
                                <span className="shrink-0 rounded bg-surface-container-high px-1.5 py-0.5 text-[10px] text-on-surface-variant">{item.candidateCount || 0}</span>
                                <button
                                  type="button"
                                  onClick={() => addSuggestionScopes([item])}
                                  disabled={added}
                                  className="h-6 rounded px-2 text-[11px] font-semibold text-primary hover:bg-primary/10 disabled:text-outline"
                                >
                                  {added ? '已加入' : '加入'}
                                </button>
                              </div>
                              {!!item.examples?.length && (
                                <div className="mt-1 truncate pl-6 text-[11px] text-outline" title={item.examples.join('，')}>
                                  {item.examples.join('，')}
                                </div>
                              )}
                            </div>
                          )
                        }) : (
                          <div className="flex h-full items-center justify-center px-3 text-center text-xs text-outline">
                            暂无建议目录，可点击「生成建议」或切换到「目录树」手动挑选
                          </div>
                        )}
                      </div>
                    </>
                  ) : (
                    <div className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-lg border border-surface-container-high bg-surface-container-lowest p-1.5">
                      {scopeTreeLoading && !scopeTree.length ? (
                        <div className="flex h-full items-center justify-center px-3 text-center text-xs text-outline">
                          正在加载素材目录树...
                        </div>
                      ) : scopeTree.length ? (
                        scopeTree.map((node) => renderScopeTreeNode(node, 0))
                      ) : (
                        <div className="flex h-full items-center justify-center px-3 text-center text-xs text-outline">
                          素材目录树为空，请先在原始材料库中建立目录
                        </div>
                      )}
                    </div>
                  )}
                </section>

                <section
                  onDragOver={(event) => {
                    event.preventDefault()
                    event.dataTransfer.dropEffect = 'copy'
                    setScopeDropActive(true)
                  }}
                  onDragLeave={() => setScopeDropActive(false)}
                  onDrop={handleScopeDrop}
                  className={`flex h-[60vh] flex-col rounded-lg border p-4 transition-colors ${
                    scopeDropActive
                      ? 'border-primary/60 bg-primary/5'
                      : 'border-outline-variant/45 bg-surface-container-low'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h4 className="text-sm font-semibold text-on-surface">已确认目录</h4>
                      <p className="mt-0.5 text-xs text-outline">
                        已选 {selectedConfirmedScopeCount} 项 / 共 {confirmedScopePaths.length} 项，可拖动左侧目录到本区域
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={saveScopes}
                      disabled={scopeSaving}
                      className="h-8 rounded-lg bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-45"
                    >
                      {scopeSaving ? '保存中...' : '保存范围'}
                    </button>
                  </div>
                  {scopes.length ? (
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-container-high bg-surface-container-lowest px-2 py-2">
                      <div className="flex items-center gap-2">
                        <label className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant">
                          <input
                            type="checkbox"
                            checked={allConfirmedScopesSelected}
                            onChange={allConfirmedScopesSelected ? clearConfirmedScopeSelection : selectAllConfirmedScopes}
                            className="h-4 w-4 accent-primary"
                          />
                          全选
                        </label>
                        <button
                          type="button"
                          onClick={clearConfirmedScopeSelection}
                          disabled={!selectedConfirmedScopeCount}
                          className="h-7 rounded px-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-high disabled:opacity-45"
                        >
                          清空
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={removeSelectedScopes}
                        disabled={!selectedConfirmedScopeCount}
                        className="h-7 rounded bg-error-container px-2.5 text-xs font-semibold text-error hover:bg-error-container/80 disabled:opacity-45"
                      >
                        删除所选
                      </button>
                    </div>
                  ) : null}
                  <div className="mt-3 min-h-0 flex-1 space-y-0.5 overflow-y-auto rounded-lg border border-surface-container-high bg-surface-container-lowest p-1.5">
                    {scopes.length ? scopes.map((scope) => {
                      const path = normalizeScopePath(scope.path)
                      return (
                        <div key={scope.path} className="flex items-center gap-2 rounded-lg px-1.5 py-1.5 text-xs hover:bg-surface-container-high/60">
                          <input
                            type="checkbox"
                            checked={selectedConfirmedScopePaths.has(path)}
                            onChange={() => toggleConfirmedScopeSelection(path)}
                            className="h-4 w-4 shrink-0 accent-primary"
                            aria-label={`选择识别范围 ${scope.path}`}
                          />
                          <span className="min-w-0 flex-1 truncate text-on-surface" title={scope.path}>{scope.path}</span>
                          <button
                            type="button"
                            onClick={() => removeScope(scope.path)}
                            className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-error-container/30 hover:text-error"
                            aria-label={`移除识别范围 ${scope.path}`}
                            title="移除范围"
                          >
                            <span className="material-symbols-outlined text-[15px]">delete</span>
                          </button>
                        </div>
                      )
                    }) : (
                      <div className="flex h-full items-center justify-center px-3 text-center text-xs text-outline">
                        尚未确认识别目录，可从左侧勾选、点击加入或拖动目录到此处
                      </div>
                    )}
                  </div>
                </section>
              </div>
            </div>
          </div>
        </div>
      )}

      {previewItem && (
        <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="flex h-[86vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest animate-float-in">
            <div className="flex items-center justify-between gap-3 border-b border-surface-container-high px-5 py-3">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold text-on-surface" title={previewItem.name}>{previewItem.name}</h3>
                <p className="mt-1 truncate text-xs text-outline" title={previewItem.folderPath}>{previewItem.folderPath || previewItem.fileId}</p>
              </div>
              <button
                type="button"
                onClick={closePreview}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-primary"
                aria-label="关闭预览"
                title="关闭"
              >
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>
            <div className="min-h-0 flex-1 bg-white p-3">
              {(() => {
                const ext = extOf(previewItem.name)
                const previewUrl = technicalMaterialsAPI.raw.previewContentUrl(previewItem.fileId)
                if (previewLoading) {
                  return (
                    <div className="flex h-full items-center justify-center text-sm text-on-surface-variant">
                      正在加载在线预览...
                    </div>
                  )
                }
                if (ext === 'pdf') {
                  return (
                    <iframe
                      src={previewUrl}
                      title={`预览 ${previewItem.name}`}
                      className="h-full w-full rounded-lg border border-surface-container-high bg-white"
                    />
                  )
                }
                if (['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff'].includes(ext)) {
                  return (
                    <div className="flex h-full items-center justify-center overflow-auto rounded-lg border border-surface-container-high bg-surface-container-lowest">
                      <img src={previewUrl} alt={previewItem.name} className="max-h-full max-w-full object-contain" />
                    </div>
                  )
                }
                if (previewSession?.onlyoffice) {
                  return (
                    <OnlyOfficeEmbed
                      session={previewSession.onlyoffice}
                      mode="view"
                      className="h-full w-full rounded-lg border border-surface-container-high bg-white"
                      onError={(message) => setPreviewError(message || 'OnlyOffice 在线预览加载失败')}
                    />
                  )
                }
                return (
                  <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-surface-container-high px-6 text-center">
                    <p className="max-w-md text-sm text-on-surface-variant">
                      {previewError || '当前文件暂不支持在线预览。'}
                    </p>
                  </div>
                )
              })()}
            </div>
          </div>
        </div>
      )}

      {receiptItem && (() => {
        const receipt = buildFailureReceipt(receiptItem)
        return (
          <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="wizard-modal-surface w-full max-w-lg overflow-hidden rounded-xl border border-surface-container-high bg-surface-container-lowest animate-float-in">
              <div className="flex items-center justify-between gap-3 border-b border-surface-container-high px-6 py-4">
                <div className="min-w-0">
                  <h3 className="text-base font-semibold text-on-surface">识别失败回执</h3>
                  <p className="mt-1 truncate text-xs text-outline" title={receiptItem.name}>{receiptItem.name}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setReceiptItem(null)}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-primary"
                  aria-label="关闭回执"
                  title="关闭"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>
              <div className="space-y-3 p-6 text-sm">
                <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-2">
                  <span className="text-on-surface-variant">回执编号</span>
                  <span className="min-w-0 break-all font-medium text-on-surface">{receipt.receiptNo}</span>
                  <span className="text-on-surface-variant">文件编号</span>
                  <span className="min-w-0 break-all text-on-surface">{receiptItem.fileId || '-'}</span>
                  <span className="text-on-surface-variant">识别状态</span>
                  <span className="text-error">{receipt.statusLabel}</span>
                  <span className="text-on-surface-variant">处理时间</span>
                  <span className="min-w-0 break-all text-on-surface">{receiptItem.updatedAt || '-'}</span>
                  <span className="text-on-surface-variant">素材目录</span>
                  <span className="min-w-0 break-all text-on-surface">{receiptItem.folderPath || '-'}</span>
                </div>
                <div className="rounded-lg border border-error-container bg-error-container/25 p-3">
                  <p className="text-xs font-semibold text-error">失败原因</p>
                  <p className="mt-1 break-words text-sm text-on-surface">{receipt.rawMessage}</p>
                </div>
                <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-3">
                  <p className="text-xs font-semibold text-on-surface-variant">处理结论</p>
                  <p className="mt-1 text-sm text-on-surface">{receipt.conclusion}</p>
                  <p className="mt-2 text-xs leading-5 text-on-surface-variant">{receipt.suggestion}</p>
                </div>
              </div>
              <div className="flex justify-end gap-2 border-t border-surface-container-high bg-surface-container-low px-6 py-4">
                <button
                  type="button"
                  onClick={() => setReceiptItem(null)}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary hover:bg-primary-container hover:text-on-primary-container"
                >
                  知道了
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      {editing && (
        <div className="dialog-overlay fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="wizard-modal-surface w-full max-w-md rounded-xl border border-surface-container-high bg-surface-container-lowest animate-float-in">
            <div className="flex items-center justify-between border-b border-surface-container-high px-6 py-4">
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-on-surface">编辑证书时间</h3>
                <p className="mt-1 truncate text-xs text-outline">{editing.name}</p>
              </div>
              <button
                type="button"
                onClick={closeEdit}
                disabled={saving}
                className="close-plain text-on-surface-variant transition-colors hover:text-primary disabled:opacity-50"
                aria-label="关闭"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="space-y-3 p-6">
              <label className="block text-sm text-on-surface-variant">
                <span className="mb-1 block">发证日期</span>
                <input
                  type="date"
                  value={editing.issueDate}
                  onChange={(event) => setEditing((prev) => ({ ...(prev || {}), issueDate: event.target.value }))}
                  disabled={saving}
                  className="h-10 w-full rounded-lg border border-surface-container-high bg-white px-3 text-sm text-on-surface"
                />
              </label>
              <label className="block text-sm text-on-surface-variant">
                <span className="mb-1 block">有效期至</span>
                <input
                  type="date"
                  value={editing.expiryDate}
                  onChange={(event) => setEditing((prev) => ({ ...(prev || {}), expiryDate: event.target.value }))}
                  disabled={saving}
                  className="h-10 w-full rounded-lg border border-surface-container-high bg-white px-3 text-sm text-on-surface"
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 rounded-b-xl border-t border-surface-container-high bg-surface-container-low px-6 py-4">
              <button
                type="button"
                onClick={closeEdit}
                disabled={saving}
                className="rounded-lg px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-high disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={saveEdit}
                disabled={saving}
                className="rounded-lg bg-primary px-4 py-2 text-sm text-on-primary hover:bg-primary-container disabled:opacity-50"
              >
                {saving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
