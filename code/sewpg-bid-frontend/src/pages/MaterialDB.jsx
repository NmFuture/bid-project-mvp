import { useCallback, useEffect, useRef, useState } from 'react'
import { materialsAPI } from '../api'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'

const MAX_FILE_SIZE = 1024 * 1024 * 1024
const FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const UPLOAD_KIND_STORAGE_KEY = 'materials.raw.upload.kind'
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

const readStoredUploadKind = () => {
  if (typeof window === 'undefined') return 'files'
  try {
    const value = window.localStorage.getItem(UPLOAD_KIND_STORAGE_KEY)
    return value === 'folder' ? 'folder' : 'files'
  } catch {
    return 'files'
  }
}

const persistUploadKind = (value) => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(UPLOAD_KIND_STORAGE_KEY, value === 'folder' ? 'folder' : 'files')
  } catch {
    // ignore storage failures
  }
}

const safeMessage = (error, fallback) => error?.payload?.detail || error?.message || fallback

const toSizeLabel = (bytes) => {
  const value = Number(bytes || 0)
  if (!Number.isFinite(value) || value <= 0) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(2)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

const extOf = (name) => {
  const parts = String(name || '').split('.')
  if (parts.length < 2) return ''
  return String(parts.pop() || '').toLowerCase()
}

const normalizeTreeNodes = (nodes = []) =>
  (Array.isArray(nodes) ? nodes : []).map((node) => ({
    id: String(node?.id || node?.path || node?.name || `node-${Math.random().toString(36).slice(2, 8)}`),
    name: String(node?.name || node?.title || node?.path || '未命名目录'),
    path: String(node?.path || node?.name || ''),
    fileCount: Number(node?.fileCount || 0),
    children: normalizeTreeNodes(node?.children || []),
  }))

const flattenTreePaths = (nodes = []) => {
  const result = []
  const walk = (list) => {
    list.forEach((node) => {
      if (node.path) result.push(node.path)
      if (Array.isArray(node.children) && node.children.length) walk(node.children)
    })
  }
  walk(nodes)
  return result
}

const collectCollapsiblePaths = (nodes = []) => {
  const result = []
  const walk = (list) => {
    list.forEach((node) => {
      if (Array.isArray(node.children) && node.children.length) {
        result.push(node.path)
        walk(node.children)
      }
    })
  }
  walk(nodes)
  return result
}

const buildDefaultCollapsedMap = (nodes = [], level = 0, map = {}) => {
  nodes.forEach((node) => {
    if (Array.isArray(node.children) && node.children.length) {
      map[node.path] = level > 0
      buildDefaultCollapsedMap(node.children, level + 1, map)
    }
  })
  return map
}

const parentPath = (path) => {
  const normalized = String(path || '').replace(/^\/+|\/+$/g, '')
  if (!normalized) return ''
  const parts = normalized.split('/')
  if (parts.length <= 1) return ''
  return parts.slice(0, -1).join('/')
}

const pickDefaultFolder = (nodes = []) => {
  const paths = flattenTreePaths(nodes)
  if (!paths.length) return ''
  return paths[0] || ''
}

const statusColor = (status) => {
  if (status === 'running') return 'bg-primary/10 text-primary'
  if (status === 'success') return 'bg-secondary-container text-on-secondary-container'
  if (status === 'failed') return 'bg-error-container text-on-error-container'
  return 'bg-surface-container-high text-on-surface-variant'
}

function TreeNode({
  node,
  selectedPath,
  onSelect,
  level = 0,
  collapsedMap,
  onToggle,
  scale = 100,
}) {
  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  const collapsed = hasChildren ? Boolean(collapsedMap[node.path]) : false
  const selected = selectedPath === node.path
  const indent = (12 + level * 16) * (scale / 100)
  return (
    <div>
      <button
        onClick={() => onSelect(node.path)}
        style={{ paddingLeft: `${indent}px`, fontSize: `${Math.max(11, Math.min(14, 13 * (scale / 100)))}px` }}
        className={`w-full text-left rounded-lg py-2 pr-2 transition-colors flex items-center justify-between gap-2 ${
          selected
            ? 'bg-primary/10 text-primary font-semibold'
            : 'text-on-surface-variant hover:bg-surface-container-low'
        }`}
      >
        <span className="min-w-0 flex items-center gap-1.5">
          {hasChildren ? (
            <span
              onClick={(event) => {
                event.stopPropagation()
                onToggle(node.path)
              }}
              className="material-symbols-outlined text-sm text-outline hover:text-primary"
            >
              {collapsed ? 'chevron_right' : 'expand_more'}
            </span>
          ) : (
            <span className="w-4" />
          )}
          <span className="material-symbols-outlined text-sm text-primary">
            folder
          </span>
          <span className="truncate">{node.name}</span>
        </span>
        <span className="text-xs text-outline shrink-0">{node.fileCount}</span>
      </button>
      {hasChildren && !collapsed && (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
              level={level + 1}
              collapsedMap={collapsedMap}
              onToggle={onToggle}
              scale={scale}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function MaterialDB({ showToast = () => {} }) {
  const uploadPickerRef = useRef(null)
  const [tree, setTree] = useState([])
  const [collapsedMap, setCollapsedMap] = useState({})
  const [treeScale, setTreeScale] = useState(100)
  const [filesPayload, setFilesPayload] = useState({ items: [], total: 0, page: 1, pageSize: 20 })
  const [parseStatus, setParseStatus] = useState(null)
  const [selectedFolderPath, setSelectedFolderPath] = useState('')
  const [filters, setFilters] = useState({
    keyword: '',
    bidType: 'all',
    customerName: '',
    projectId: '',
    page: 1,
    pageSize: 20,
  })
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [showUploadModal, setShowUploadModal] = useState(false)
  const [uploadKind, setUploadKind] = useState(() => readStoredUploadKind())
  const [uploadMode, setUploadMode] = useState('path')
  const [uploadPath, setUploadPath] = useState('')
  const [uploadProjectId, setUploadProjectId] = useState('')
  const [uploadBidType, setUploadBidType] = useState('技术标')
  const [uploadFiles, setUploadFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')

  const [conflictContext, setConflictContext] = useState(null)

  const canManageCurrentFolder = Boolean(selectedFolderPath)
  const canCreateFolder = Boolean(selectedFolderPath) && canManageCurrentFolder
  const canDeleteFolder = Boolean(selectedFolderPath && selectedFolderPath.includes('/')) && canManageCurrentFolder

  const fileItems = filesPayload?.items || []
  const totalCount = Number(filesPayload?.total || 0)

  const loadLibrary = useCallback(async (options = {}) => {
    const silent = Boolean(options.silent)
    if (silent) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const treeResponse = await materialsAPI.raw.tree()
      const normalizedTree = normalizeTreeNodes(treeResponse?.tree || treeResponse?.items || treeResponse?.nodes || [])
      setTree(normalizedTree)
      setCollapsedMap((prev) => {
        const validPathSet = new Set(flattenTreePaths(normalizedTree))
        const next = Object.fromEntries(
          Object.entries(prev).filter(([path]) => validPathSet.has(path)),
        )
        if (Object.keys(next).length > 0) return next
        return buildDefaultCollapsedMap(normalizedTree)
      })

      const validPaths = new Set(flattenTreePaths(normalizedTree))
      const effectiveFolder = validPaths.has(selectedFolderPath)
        ? selectedFolderPath
        : pickDefaultFolder(normalizedTree)
      if (selectedFolderPath !== effectiveFolder) {
        setSelectedFolderPath(effectiveFolder)
      }

      const payload = await materialsAPI.raw.files({
        folderPath: effectiveFolder,
        keyword: filters.keyword.trim(),
        bidType: filters.bidType === 'all' ? '' : filters.bidType,
        customerName: filters.customerName.trim(),
        projectId: filters.projectId.trim(),
        page: filters.page,
        pageSize: filters.pageSize,
      })
      setFilesPayload(payload || { items: [], total: 0, page: 1, pageSize: filters.pageSize })

      if (filters.projectId.trim()) {
        try {
          const status = await materialsAPI.raw.parseStatus(filters.projectId.trim())
          setParseStatus(status)
        } catch {
          setParseStatus(null)
        }
      } else {
        setParseStatus(null)
      }
    } catch (e) {
      setError(safeMessage(e, '原始材料库加载失败，请稍后重试。'))
    } finally {
      if (silent) setRefreshing(false)
      else setLoading(false)
    }
  }, [filters, selectedFolderPath])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadLibrary()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadLibrary])

  useEffect(() => {
    persistUploadKind(uploadKind)
  }, [uploadKind])

  const setCollapseForAll = (collapsed) => {
    const paths = collectCollapsiblePaths(tree)
    const map = {}
    paths.forEach((path) => {
      map[path] = collapsed
    })
    setCollapsedMap(map)
  }

  const toggleNode = (path) => {
    setCollapsedMap((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  const changeTreeScale = (delta) => {
    setTreeScale((prev) => Math.max(80, Math.min(140, prev + delta)))
  }

  const openUploadModal = (options = {}) => {
    const mode = options.mode || 'path'
    setShowUploadModal(true)
    setUploadKind(options.kind || 'files')
    setUploadMode(mode)
    setUploadPath(options.targetPath || selectedFolderPath)
    setUploadProjectId(options.projectId || filters.projectId.trim())
    setUploadBidType(filters.bidType === 'all' ? '技术标' : filters.bidType)
    setUploadFiles([])
    setUploadError('')
  }

  const closeUploadModal = () => {
    setShowUploadModal(false)
    setUploadFiles([])
    setUploadError('')
    if (uploadPickerRef.current) {
      uploadPickerRef.current.value = ''
    }
  }

  const onUploadFilesChanged = (event) => {
    const files = Array.from(event.target.files || [])
    if (!files.length) return
    for (const file of files) {
      if (Number(file.size || 0) > MAX_FILE_SIZE) {
        setUploadError(`文件 ${file.name} 超过 1024MB 上限。`)
        return
      }
      if (!ALLOWED_EXTENSIONS.has(extOf(file.name))) {
        setUploadError(`文件 ${file.name} 类型不在白名单内。`)
        return
      }
    }
    setUploadError('')
    setUploadFiles((prev) => {
      const next = [...prev]
      const signatures = new Set(
        prev.map((file) => `${file.webkitRelativePath || file.name}::${file.size}::${file.lastModified}`)
      )
      files.forEach((file) => {
        const signature = `${file.webkitRelativePath || file.name}::${file.size}::${file.lastModified}`
        if (!signatures.has(signature)) {
          signatures.add(signature)
          next.push(file)
        }
      })
      return next
    })
    event.target.value = ''
  }

  const openUploadPicker = () => {
    uploadPickerRef.current?.click()
  }

  const performUpload = async (onConflict) => {
    if (!uploadFiles.length) {
      setUploadError('请先选择上传文件。')
      return
    }

    setUploading(true)
    setUploadError('')

    const payload = new FormData()
    try {
      const targetPath = uploadMode === 'path' ? uploadPath.trim() : ''
      const projectId = uploadMode === 'project' ? uploadProjectId.trim() : ''

      if (!targetPath && !projectId) {
        setUploadError('请填写目标目录或项目 ID。')
        setUploading(false)
        return
      }

      payload.append('targetPath', targetPath)
      payload.append('projectId', projectId)
      payload.append('bidType', uploadBidType)
      if (onConflict) {
        payload.append('onConflict', onConflict)
      }
      uploadFiles.forEach((file) => {
        payload.append('files', file, file.name)
        payload.append('relativePaths', file.webkitRelativePath || '')
      })

      const result = await materialsAPI.raw.upload(payload)
      showToast(result?.message || `上传成功：${uploadFiles.length} 个文件`)
      setConflictContext(null)
      closeUploadModal()
      await loadLibrary({ silent: true })
    } catch (e) {
      if (e?.status === 409 && e?.code === 'MATERIAL_CONFLICT') {
        setConflictContext({ type: 'upload', payload: null, detail: e?.payload?.conflict || null })
      } else {
        setUploadError(safeMessage(e, '上传失败，请稍后重试。'))
      }
    } finally {
      setUploading(false)
    }
  }

  const handleCreateFolder = async () => {
    if (!canCreateFolder) {
      showToast('请先选择一个目标目录。', 'error')
      return
    }
    const folderName = window.prompt('请输入新建文件夹名称')
    if (!folderName || !folderName.trim()) return
    try {
      const result = await materialsAPI.raw.createFolder({
        parentPath: selectedFolderPath,
        folderName: folderName.trim(),
      })
      const createdPath = result?.folderPath || `${selectedFolderPath}/${folderName.trim()}`
      showToast(result?.message || '文件夹创建成功')
      setSelectedFolderPath(createdPath)
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '新建文件夹失败'), 'error')
    }
  }

  const handleDeleteFolder = async () => {
    if (!canDeleteFolder) {
      showToast('当前目录暂不支持删除。', 'error')
      return
    }
    const ok = window.confirm(`确认删除文件夹：${selectedFolderPath} ？`)
    if (!ok) return
    try {
      const result = await materialsAPI.raw.deleteFolder({ path: selectedFolderPath })
      showToast(result?.message || '文件夹删除成功')
      setSelectedFolderPath(parentPath(selectedFolderPath))
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '删除文件夹失败'), 'error')
    }
  }

  const handleRename = async (item) => {
    if (!canManageCurrentFolder) {
      showToast('请先选择一个目标目录。', 'error')
      return
    }
    const nextName = window.prompt('请输入新文件名', item.name || '')
    if (!nextName || nextName.trim() === item.name) return
    try {
      await materialsAPI.raw.updateFile(item.id, { name: nextName.trim() })
      showToast('重命名成功')
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '重命名失败'), 'error')
    }
  }

  const doMove = async (payload) => {
    try {
      await materialsAPI.raw.moveFile(payload)
      showToast('文件移动成功')
      await loadLibrary({ silent: true })
      setConflictContext(null)
    } catch (e) {
      if (e?.status === 409 && e?.code === 'MATERIAL_CONFLICT') {
        setConflictContext({ type: 'move', payload, detail: e?.payload?.conflict || null })
      } else {
        showToast(safeMessage(e, '文件移动失败'), 'error')
      }
    }
  }

  const handleMove = async (item) => {
    if (!canManageCurrentFolder) {
      showToast('请先选择一个目标目录。', 'error')
      return
    }
    const targetPath = window.prompt('请输入目标目录路径', item.folderPath || selectedFolderPath)
    if (!targetPath || targetPath.trim() === item.folderPath) return
    await doMove({ fileId: item.id, targetPath: targetPath.trim() })
  }

  const handleDelete = async (item) => {
    if (!canManageCurrentFolder) {
      showToast('请先选择一个目标目录。', 'error')
      return
    }
    if (!window.confirm(`确认删除文件：${item.name}？`)) return
    try {
      await materialsAPI.raw.deleteFile(item.id)
      showToast('文件已删除')
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '删除失败'), 'error')
    }
  }

  const handleDownload = async (item) => {
    try {
      const payload = await materialsAPI.raw.downloadFile(item.id)
      const url = payload?.downloadUrl || payload?.fileUrl
      if (url) {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
      showToast(payload?.message || '已触发下载')
    } catch (e) {
      showToast(safeMessage(e, '下载失败'), 'error')
    }
  }

  const resolveConflict = async (action) => {
    if (!conflictContext?.payload) return
    if (conflictContext.type === 'upload') {
      await performUpload(action)
      return
    }
    if (conflictContext.type === 'move') {
      await doMove({ ...conflictContext.payload, onConflict: action })
    }
  }

  const updateFilter = (key, value) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value,
      page: key === 'page' ? value : 1,
    }))
  }

  const noData = !fileItems.length

  if (loading) {
    return (
      <PageLoading
        title="正在加载原始材料库..."
        description="正在同步目录树、权限和文件列表。"
      />
    )
  }

  if (error) {
    return (
      <PageError
        title="原始材料库加载失败"
        description={error}
        onRetry={() => loadLibrary()}
      />
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">原始材料库</h1>
          {(refreshing || error) && (
            <p className={`text-xs mt-1 ${error ? 'text-error' : 'text-outline'}`}>
              {error || '正在刷新...'}
            </p>
          )}
        </div>

        <div className="flex gap-3">
          <button
            onClick={() => loadLibrary({ silent: true })}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors"
          >
            刷新
          </button>
          <button
            onClick={() => openUploadModal({ mode: 'path' })}
            disabled={!canManageCurrentFolder}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-on-primary hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title={canManageCurrentFolder ? '' : '请先在左侧选择一个目录'}
          >
            上传文件
          </button>
        </div>
      </div>

      {parseStatus && (
        <div className="rounded-xl border border-surface-container-high p-4 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary">sync</span>
            <span className="text-sm text-on-surface">后台解析联动状态</span>
            <span className={`text-xs px-2 py-1 rounded-full font-medium ${statusColor(parseStatus.status)}`}>
              {parseStatus.status || 'pending'}
            </span>
          </div>
          <span className="text-xs text-outline">
            {parseStatus.lastMessage || '状态只读展示，前端不可操作。'}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <div className="xl:col-span-3 bg-surface-container-lowest rounded-xl border border-surface-container-high p-4 max-h-[720px] overflow-auto">
          <div className="flex items-center justify-between mb-3 gap-2">
            <div className="text-sm font-semibold text-on-surface">目录树</div>
            <div className="flex items-center gap-1">
              <button onClick={() => setCollapseForAll(false)} className="px-2 py-1 text-xs rounded bg-surface-container-high hover:bg-surface-dim">展开</button>
              <button onClick={() => setCollapseForAll(true)} className="px-2 py-1 text-xs rounded bg-surface-container-high hover:bg-surface-dim">收起</button>
            </div>
          </div>

          <div className="flex items-center justify-between mb-3 text-xs text-on-surface-variant">
            <span>目录缩放</span>
            <div className="flex items-center gap-1">
              <button onClick={() => changeTreeScale(-10)} className="w-6 h-6 rounded bg-surface-container-high hover:bg-surface-dim">-</button>
              <span className="w-10 text-center">{treeScale}%</span>
              <button onClick={() => changeTreeScale(10)} className="w-6 h-6 rounded bg-surface-container-high hover:bg-surface-dim">+</button>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            {tree.map((node) => (
              <TreeNode
                key={node.id}
                node={node}
                selectedPath={selectedFolderPath}
                onSelect={(path) => setSelectedFolderPath(path)}
                collapsedMap={collapsedMap}
                onToggle={toggleNode}
                scale={treeScale}
              />
            ))}
          </div>

          <div className="mt-4 pt-3 border-t border-surface-container-high grid grid-cols-3 gap-2">
            <button
              onClick={handleCreateFolder}
              disabled={!canCreateFolder}
              className="px-2 py-2 text-xs rounded bg-surface-container-high hover:bg-surface-dim disabled:opacity-50 disabled:cursor-not-allowed"
            >
              新建文件夹
            </button>
            <button
              onClick={handleDeleteFolder}
              disabled={!canDeleteFolder}
              className="px-2 py-2 text-xs rounded bg-surface-container-high hover:bg-surface-dim disabled:opacity-50 disabled:cursor-not-allowed"
            >
              删除文件夹
            </button>
            <button
              onClick={() => openUploadModal({ mode: 'path', targetPath: selectedFolderPath })}
              disabled={!canManageCurrentFolder || !selectedFolderPath}
              className="px-2 py-2 text-xs rounded bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50 disabled:cursor-not-allowed"
            >
              上传到此目录
            </button>
          </div>
        </div>

        <div className="xl:col-span-9 flex flex-col gap-4">
          <div className="bg-surface-container-lowest rounded-xl border border-surface-container-high p-4">
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
              <input
                value={filters.keyword}
                onChange={(e) => updateFilter('keyword', e.target.value)}
                placeholder="搜索文件名"
                className="h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
              />
              <select
                value={filters.bidType}
                onChange={(e) => updateFilter('bidType', e.target.value)}
                className="h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
              >
                <option value="all">全部标书类型</option>
                <option value="技术标">技术标</option>
                <option value="商务标">商务标</option>
                <option value="通用">通用</option>
              </select>
              <input
                value={filters.customerName}
                onChange={(e) => updateFilter('customerName', e.target.value)}
                placeholder="按客户筛选"
                className="h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
              />
              <input
                value={filters.projectId}
                onChange={(e) => updateFilter('projectId', e.target.value)}
                placeholder="按项目ID筛选"
                className="h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
              />
              <select
                value={filters.pageSize}
                onChange={(e) => updateFilter('pageSize', Number(e.target.value))}
                className="h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
              >
                {[10, 20, 50].map((size) => (
                  <option key={size} value={size}>每页 {size} 条</option>
                ))}
              </select>
            </div>
            <div className="mt-3 text-xs text-outline flex flex-wrap justify-between gap-2">
              <span>当前目录：{selectedFolderPath || '-'}</span>
              <span>权限：所有登录用户可编辑</span>
            </div>
          </div>

          <div className="bg-surface-container-lowest rounded-xl border border-surface-container-high overflow-hidden">
            {noData ? (
              <div className="p-8">
                <PageEmpty
                  title="当前目录暂无文件"
                  description="可上传文件、调整筛选，或在目录树中新建文件夹。"
                  actionText="立即上传"
                  onAction={() => openUploadModal({ mode: 'path' })}
                  showActionIcon={false}
                />
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-container-high bg-surface-container-low">
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">文件名</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">类型</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">大小</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">标书类型</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">版本</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">更新人/时间</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-on-surface-variant uppercase">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fileItems.map((item) => (
                        <tr key={item.id} className="border-b border-surface-container-high/60 hover:bg-surface-container-low">
                          <td className="px-4 py-3 min-w-[280px]">
                            <div className="font-medium text-on-surface truncate">{item.name || '-'}</div>
                            <div className="text-xs text-outline truncate mt-1">{item.folderPath || '-'}</div>
                          </td>
                          <td className="px-4 py-3">{item.ext || item.type || '-'}</td>
                          <td className="px-4 py-3">{item.sizeLabel || toSizeLabel(item.size)}</td>
                          <td className="px-4 py-3">{item.bidType || '-'}</td>
                          <td className="px-4 py-3">{item.version ? `v${item.version}` : '-'}</td>
                          <td className="px-4 py-3 text-xs text-on-surface-variant">
                            <div>{item.lastOperator || '-'}</div>
                            <div>{item.updatedAt || '-'}</div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap gap-2">
                              <button onClick={() => handleDownload(item)} className="text-primary hover:underline text-xs">下载</button>
                              <button onClick={() => handleRename(item)} disabled={!canManageCurrentFolder} className="text-on-surface-variant hover:underline text-xs disabled:opacity-50">重命名</button>
                              <button onClick={() => handleMove(item)} disabled={!canManageCurrentFolder} className="text-on-surface-variant hover:underline text-xs disabled:opacity-50">移动</button>
                              <button onClick={() => handleDelete(item)} disabled={!canManageCurrentFolder} className="text-error hover:underline text-xs disabled:opacity-50">删除</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-4 py-3 border-t border-surface-container-high text-xs text-outline flex items-center justify-between">
                  <span>总计 {totalCount} 条</span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => updateFilter('page', Math.max(1, filters.page - 1))}
                      disabled={filters.page <= 1}
                      className="px-2 py-1 rounded border border-surface-container-high disabled:opacity-40"
                    >
                      上一页
                    </button>
                    <span>第 {filters.page} 页</span>
                    <button
                      onClick={() => updateFilter('page', filters.page + 1)}
                      disabled={filters.page * filters.pageSize >= totalCount}
                      className="px-2 py-1 rounded border border-surface-container-high disabled:opacity-40"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {showUploadModal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-surface-container-lowest rounded-xl border border-surface-container-high shadow-2xl">
            <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
              <h2 className="text-lg font-headline font-bold text-on-surface">上传原始素材</h2>
              <button onClick={closeUploadModal} className="close-plain text-on-surface-variant hover:text-primary transition-colors" aria-label="关闭">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label className="text-sm text-on-surface-variant">
                  <span className="block mb-1">落位模式</span>
                  <select
                    value={uploadMode}
                    onChange={(e) => setUploadMode(e.target.value)}
                    className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                  >
                    <option value="path">指定目录路径</option>
                    <option value="project">按项目自动落位</option>
                  </select>
                </label>
                <label className="text-sm text-on-surface-variant">
                  <span className="block mb-1">标书类型</span>
                  <select
                    value={uploadBidType}
                    onChange={(e) => setUploadBidType(e.target.value)}
                    className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                  >
                    <option value="技术标">技术标</option>
                    <option value="商务标">商务标</option>
                    <option value="通用">通用</option>
                  </select>
                </label>
              </div>

              {uploadMode === 'path' ? (
                <label className="text-sm text-on-surface-variant block">
                  <span className="block mb-1">目标目录</span>
                  <input
                    value={uploadPath}
                    onChange={(e) => setUploadPath(e.target.value)}
                    className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                    placeholder="例如：项目定制/PRJ-2026-0001/技术标"
                  />
                </label>
              ) : (
                <label className="text-sm text-on-surface-variant block">
                  <span className="block mb-1">项目 ID</span>
                  <input
                    value={uploadProjectId}
                    onChange={(e) => setUploadProjectId(e.target.value)}
                    className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                    placeholder="例如：PRJ-2026-0001"
                  />
                </label>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label className="text-sm text-on-surface-variant">
                  <span className="block mb-1">上传内容</span>
                  <select
                    value={uploadKind}
                    onChange={(e) => {
                      setUploadKind(e.target.value)
                      setUploadFiles([])
                      setUploadError('')
                    }}
                    className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                  >
                    <option value="files">文件</option>
                    <option value="folder">文件夹</option>
                  </select>
                </label>
              </div>

              <input
                ref={uploadPickerRef}
                type="file"
                multiple
                accept={FILE_ACCEPT}
                onChange={onUploadFilesChanged}
                {...(uploadKind === 'folder' ? { webkitdirectory: '', directory: '' } : {})}
                className="hidden"
              />

              <div className="space-y-2">
                <div className="text-sm text-on-surface-variant">
                  {uploadKind === 'folder' ? '选择文件夹' : '选择文件'}
                </div>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={openUploadPicker}
                    className="px-4 py-2 text-sm rounded-lg bg-surface-container-high text-on-surface hover:bg-surface-dim"
                  >
                    {uploadFiles.length
                      ? uploadKind === 'folder' ? '继续添加文件夹' : '继续添加文件'
                      : uploadKind === 'folder' ? '选择文件夹' : '选择文件'}
                  </button>
                  {!!uploadFiles.length && (
                    <button
                      type="button"
                      onClick={() => {
                        setUploadFiles([])
                        setUploadError('')
                        if (uploadPickerRef.current) {
                          uploadPickerRef.current.value = ''
                        }
                      }}
                      className="px-4 py-2 text-sm rounded-lg bg-surface-container-high text-on-surface-variant hover:bg-surface-dim"
                    >
                      清空已选
                    </button>
                  )}
                </div>
              </div>

              <div className="text-xs text-outline">
                {uploadKind === 'folder'
                  ? '浏览器原生一次通常只能选择一个文件夹，但你可以连续点击“继续添加文件夹”，同一次上传会合并这些目录。'
                  : '支持一次选择多个文件。'}
              </div>

              <div className="text-sm text-on-surface-variant block">
                <span className="block mb-1">当前选择</span>
                <input
                  type="text"
                  readOnly
                  value={uploadFiles.length ? `已选择 ${uploadFiles.length} 个项目` : '未选择任何文件'}
                  className="w-full h-10 px-3 py-2 rounded-lg bg-surface-container-highest border-none text-sm"
                />
              </div>

              {!!uploadFiles.length && (
                <div className="rounded-lg bg-surface-container-low p-3 text-xs text-on-surface-variant">
                  {uploadFiles.map((item) => (
                    <div key={`${item.name}-${item.size}`} className="flex items-center justify-between py-1">
                      <span className="truncate mr-2">{item.webkitRelativePath || item.name}</span>
                      <span>{toSizeLabel(item.size)}</span>
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs text-outline">
                白名单：doc/docx/xls/xlsx/pdf/zip/png/jpg/jpeg/webp/bmp/tif/tiff；单文件 1024MB；支持一次选择多个文件，或选择整个文件夹并保留目录结构。
              </p>

              {uploadError && (
                <div className="text-sm text-error bg-error-container/30 border border-error/30 rounded-lg px-3 py-2">
                  {uploadError}
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-surface-container-high flex justify-end gap-3 bg-surface-container-low rounded-b-xl">
              <button onClick={closeUploadModal} className="px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-high rounded-lg">
                取消
              </button>
              <button
                onClick={() => performUpload()}
                disabled={uploading}
                className="px-4 py-2 text-sm bg-primary text-on-primary rounded-lg hover:bg-primary-container disabled:opacity-50"
              >
                {uploading ? '上传中...' : '确认上传'}
              </button>
            </div>
          </div>
        </div>
      )}

      {conflictContext && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-surface-container-lowest rounded-xl border border-surface-container-high shadow-2xl">
            <div className="px-6 py-4 border-b border-surface-container-high">
              <h3 className="text-base font-semibold text-on-surface">发现命名冲突</h3>
            </div>
            <div className="p-6 text-sm text-on-surface-variant space-y-2">
              <p>目标路径存在同名文件，请选择处理方式：</p>
              {conflictContext.detail?.path && (
                <p className="text-xs text-outline break-all">路径：{conflictContext.detail.path}</p>
              )}
            </div>
            <div className="px-6 py-4 border-t border-surface-container-high bg-surface-container-low flex justify-end gap-2 rounded-b-xl">
              <button
                onClick={() => setConflictContext(null)}
                className="px-3 py-2 text-sm rounded-lg text-on-surface-variant hover:bg-surface-container-high"
              >
                取消
              </button>
              <button
                onClick={() => resolveConflict('overwrite')}
                className="px-3 py-2 text-sm rounded-lg border border-surface-container-high text-on-surface-variant hover:bg-surface-container-high"
              >
                覆盖原文件
              </button>
              <button
                onClick={() => resolveConflict('version')}
                className="px-3 py-2 text-sm rounded-lg bg-primary text-on-primary hover:bg-primary-container"
              >
                生成 v2
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
