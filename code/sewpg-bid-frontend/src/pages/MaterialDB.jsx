import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { materialsAPI } from '../api'
import MaterialsViewSwitch from '../components/shared/MaterialsViewSwitch'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../components/shared/OnlyOfficeWorkspace'
import { PageError, PageLoading } from '../components/states/PageState'
import { bidTypeFromWorkspace, useWorkspaceSlug, workspaceRoute } from '../utils/workspace'

const MAX_FILE_SIZE = 1024 * 1024 * 1024
const FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff,.DS_Store'
const UPLOAD_KIND_STORAGE_KEY = 'materials.raw.upload.kind'
const MATERIAL_TIER_OPTIONS = [
  {
    value: 'standard',
    label: '通用素材',
    description: '大部分标书都会复用的基础资料。',
  },
  {
    value: 'customer',
    label: '客户素材',
    description: '只面向某个客户复用的专属资料。',
  },
  {
    value: 'project',
    label: '项目素材',
    description: '只在当前项目使用的补充资料。',
  },
]
const CLEAN_STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'cleaned', label: '已清洗' },
  { value: 'original_only', label: '仅保留原件' },
  { value: 'failed', label: '清洗失败' },
]
const BID_TYPE_TABS = [
  {
    value: '技术标',
    label: '技术标',
    icon: 'engineering',
    rootPath: '技术标/通用素材',
  },
  {
    value: '商务标',
    label: '商务标',
    icon: 'request_quote',
    rootPath: '商务标/通用素材',
  },
]
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'xlsm', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'ds_store',
])
const MATERIAL_ROOT_PATHS = ['技术标', '商务标']
const PROTECTED_MOVE_FOLDER_PATHS = new Set([
  '技术标',
  '商务标',
])
const PROTECTED_DELETE_FOLDER_PATHS = new Set([
  '技术标',
  '商务标',
])
const BUSINESS_STANDARD_PROTECTED_FOLDER_PATHS = new Set([
  '商务标/通用素材/01-资质合规库',
  '商务标/通用素材/02-企业能力库',
  '商务标/通用素材/03-业绩资产池',
  '商务标/通用素材/04-财务资料库',
  '商务标/通用素材/05-专题证书库',
  '商务标/通用素材/05-专题证书库/01-机型认证证书',
  '商务标/通用素材/05-专题证书库/02-大部件型式认证证书',
  '商务标/通用素材/06-通用模板底稿库',
])
const BUSINESS_CUSTOMIZED_PROTECTED_FOLDER_NAMES = new Set([
  '01-客户关系与专项证明',
  '02-商务响应文件',
  '03-模板底稿与过程文件',
])

const MATERIAL_ROOT_LABELS = {
  技术标: '技术标',
  商务标: '商务标',
  '技术标/通用素材': '通用素材',
  '技术标/客户素材': '客户素材',
  '技术标/项目素材': '项目素材',
  通用素材: '通用素材',
  客户素材: '客户素材',
  项目素材: '项目素材',
  标准模板: '通用素材',
  客户定制: '客户素材',
  项目定制: '项目素材',
}

const normalizeBidTypeTab = (value) => (value === '商务标' ? '商务标' : '技术标')

const bidTypeTabMeta = (value) =>
  BID_TYPE_TABS.find((item) => item.value === normalizeBidTypeTab(value)) || BID_TYPE_TABS[0]

const materialTierMeta = (value) =>
  MATERIAL_TIER_OPTIONS.find((item) => item.value === value) || MATERIAL_TIER_OPTIONS[0]

const cleanStatusMeta = (status) => {
  if (status === 'cleaned') return { label: '已清洗', className: 'bg-secondary-container text-on-secondary-container' }
  if (status === 'original_only') return { label: '仅保留原件', className: 'bg-tertiary-container text-on-tertiary-container' }
  if (status === 'failed') return { label: '清洗失败', className: 'bg-error-container text-on-error-container' }
  if (status === 'cleaning') return { label: '清洗中', className: 'bg-primary/10 text-primary' }
  return { label: '待清洗', className: 'bg-surface-container-high text-on-surface-variant' }
}

const canPreviewCleaned = (item) => item?.cleanStatus === 'cleaned' && Boolean(item?.hasCleanedWord)

const cleanedPreviewBlockedMessage = (item) => {
  if (!item) return '点击左侧已清洗文件，可在这里预览清洗稿。'
  if (item.cleanStatus === 'original_only') return '该文件为原件素材，系统保留原文件，不生成清洗稿。'
  if (item.cleanStatus === 'failed') return '该文件清洗失败，暂不开放清洗稿预览。'
  if (item.cleanStatus === 'cleaning') return '该文件仍在清洗中，完成后才可预览。'
  return '该文件尚未生成清洗后 Word，暂不开放预览。'
}

const displayFolderName = (name, path) => {
  const value = String(name || '')
  const normalizedPath = String(path || '').replace(/^\/+|\/+$/g, '')
  return MATERIAL_ROOT_LABELS[normalizedPath] || MATERIAL_ROOT_LABELS[value] || value
}

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
  if (String(name || '').toLowerCase() === '.ds_store') return 'ds_store'
  const parts = String(name || '').split('.')
  if (parts.length < 2) return ''
  return String(parts.pop() || '').toLowerCase()
}

const materialTierFromRootPath = (path) => {
  const normalized = String(path || '').replace(/^\/+|\/+$/g, '')
  const parts = normalized.split('/').filter(Boolean)
  const tierName = MATERIAL_ROOT_PATHS.includes(parts[0]) ? parts[1] : parts[0]
  if (tierName === '通用素材') return 'standard'
  if (tierName === '客户素材') return 'customer'
  if (tierName === '项目素材') return 'project'
  return ''
}

const normalizeTreeNodes = (nodes = []) =>
  (Array.isArray(nodes) ? nodes : []).map((node) => ({
    id: String(node?.id || node?.path || node?.name || `node-${Math.random().toString(36).slice(2, 8)}`),
    name: displayFolderName(node?.name || node?.title || node?.path || '未命名目录', node?.path || node?.name || ''),
    path: String(node?.path || node?.name || ''),
    directFileCount: Number(node?.directFileCount || 0),
    fileCount: Number(node?.fileCount || 0),
    children: normalizeTreeNodes(node?.children || []),
  }))

const ensureMaterialRootNodes = (nodes = []) => {
  const byPath = new Map()
  ;(Array.isArray(nodes) ? nodes : []).forEach((node) => {
    const path = String(node?.path || node?.name || '').replace(/^\/+|\/+$/g, '')
    if (path) byPath.set(path, node)
  })
  const technicalNode = byPath.get('技术标') || {
    id: '技术标',
    name: '技术标',
    path: '技术标',
    directFileCount: 0,
    fileCount: 0,
    children: [],
  }
  const techChildren = Array.isArray(technicalNode.children) ? technicalNode.children : []
  const normalizedTechnical = {
    ...technicalNode,
    name: '技术标',
    path: '技术标',
    children: techChildren,
    fileCount: Number(technicalNode.fileCount || 0) || techChildren.reduce((sum, child) => sum + Number(child.fileCount || 0), 0),
  }
  return [
    normalizedTechnical,
    byPath.get('商务标') || {
      id: '商务标',
      name: '商务标',
      path: '商务标',
      directFileCount: 0,
      fileCount: 0,
      children: [],
    },
  ]
}

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

const pathMatchesBidType = (path, bidType) => {
  const normalized = String(path || '').replace(/^\/+|\/+$/g, '')
  if (!normalized) return false
  const parts = normalized.split('/')
  return parts[0] === bidType
}

const collectCollapsiblePaths = (nodes = []) => {
  const result = []
  const walk = (list) => {
    list.forEach((node) => {
      if ((Array.isArray(node.children) && node.children.length) || Number(node.directFileCount || 0) > 0) {
        result.push(node.path)
      }
      if (Array.isArray(node.children) && node.children.length) {
        walk(node.children)
      }
    })
  }
  walk(nodes)
  return result
}

const buildDefaultCollapsedMap = (nodes = [], level = 0, map = {}) => {
  nodes.forEach((node) => {
    if ((Array.isArray(node.children) && node.children.length) || Number(node.directFileCount || 0) > 0) {
      map[node.path] = level > 0
    }
    if (Array.isArray(node.children) && node.children.length) {
      buildDefaultCollapsedMap(node.children, level + 1, map)
    }
  })
  return map
}

const expandPathInMap = (map, path) => {
  const parts = String(path || '').replace(/^\/+|\/+$/g, '').split('/').filter(Boolean)
  parts.forEach((_, index) => {
    map[parts.slice(0, index + 1).join('/')] = false
  })
  return map
}

const normalizePath = (path) => String(path || '').replace(/^\/+|\/+$/g, '')

const isProtectedDeleteFolderPath = (path) => {
  const normalized = normalizePath(path)
  if (PROTECTED_DELETE_FOLDER_PATHS.has(normalized) || BUSINESS_STANDARD_PROTECTED_FOLDER_PATHS.has(normalized)) {
    return true
  }
  const parts = normalized.split('/').filter(Boolean)
  return (
    parts.length === 4
    && parts[0] === '商务标'
    && (parts[1] === '客户素材' || parts[1] === '项目素材')
    && BUSINESS_CUSTOMIZED_PROTECTED_FOLDER_NAMES.has(parts[3])
  )
}

const parentPath = (path) => {
  const normalized = String(path || '').replace(/^\/+|\/+$/g, '')
  if (!normalized) return ''
  const parts = normalized.split('/')
  if (parts.length <= 1) return ''
  return parts.slice(0, -1).join('/')
}

const pickDefaultFolder = (nodes = [], bidType = '技术标') => {
  const paths = flattenTreePaths(nodes)
  if (!paths.length) return ''
  const preferred = bidTypeTabMeta(bidType).rootPath
  const exact = paths.find((path) => path === preferred)
  if (exact) return exact
  const scoped = paths.find((path) => pathMatchesBidType(path, bidType))
  if (scoped) return scoped
  return paths[0] || ''
}

const groupFilesByFolderPath = (items = []) => {
  const byPath = new Map()
  ;(Array.isArray(items) ? items : []).forEach((item) => {
    const path = normalizePath(item?.folderPath)
    if (!path) return
    const existing = byPath.get(path) || []
    existing.push(item)
    byPath.set(path, existing)
  })
  byPath.forEach((folderItems) => {
    folderItems.sort((left, right) => String(left?.name || '').localeCompare(String(right?.name || ''), 'zh-CN'))
  })
  return byPath
}

const getVisibleFileCount = (nodes = []) =>
  (Array.isArray(nodes) ? nodes : []).reduce((sum, node) => sum + Number(node?.fileCount || 0), 0)

const statusColor = (status) => {
  if (status === 'running') return 'bg-primary/10 text-primary'
  if (status === 'success') return 'bg-secondary-container text-on-secondary-container'
  if (status === 'failed') return 'bg-error-container text-on-error-container'
  return 'bg-surface-container-high text-on-surface-variant'
}

const listItems = (payload) => {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.items)) return payload.items
  return []
}

const IDENTITY_IGNORED_CHARS = new Set([
  ',', '，', '、', '.', '。', ':', '：', ';', '；', '(', ')', '（', '）',
  '[', ']', '【', '】', '{', '}', '<', '>', '《', '》', '"', "'", '`',
  '·', '_', '-', '—', '/', '\\', '|',
])

const identityKey = (value) =>
  String(value || '')
    .trim()
    .toLowerCase()
    .split('')
    .filter((char) => char !== '\u3000' && !/\s/.test(char) && !IDENTITY_IGNORED_CHARS.has(char))
    .join('')

const normalizeCustomerOptions = (customersPayload, projectsPayload) => {
  const byKey = new Map()
  const add = (candidate = {}) => {
    const customerId = String(candidate.customerId || '').trim()
    const name = String(candidate.name || candidate.customerCanonicalName || candidate.customerName || '').trim()
    if (!customerId && !name) return
    const key = customerId || identityKey(name)
    if (!key) return
    const existing = byKey.get(key) || {}
    byKey.set(key, {
      customerId: customerId || existing.customerId || '',
      name: name || existing.name || customerId,
      customerCanonicalName: String(candidate.customerCanonicalName || existing.customerCanonicalName || name || '').trim(),
      aliases: Array.from(new Set([
        ...(existing.aliases || []),
        ...(Array.isArray(candidate.aliases) ? candidate.aliases : []),
        ...(Array.isArray(candidate.customerAliases) ? candidate.customerAliases : []),
      ].filter(Boolean))),
    })
  }

  listItems(customersPayload).forEach((item) => add({
    customerId: item.customerId || item.id,
    name: item.name || item.customerCanonicalName,
    customerCanonicalName: item.customerCanonicalName || item.name,
    aliases: item.aliases || item.customerAliases || [],
  }))

  listItems(projectsPayload).forEach((project) => {
    const identity = project.identity || {}
    add({
      customerId: project.customerId || identity.customerId,
      name: project.customerCanonicalName || identity.customerCanonicalName || project.customerName || project.owner,
      customerCanonicalName: project.customerCanonicalName || identity.customerCanonicalName || project.customerName || project.owner,
      aliases: project.customerAliases || identity.customerAliases || [],
    })
  })

  return Array.from(byKey.values()).sort((left, right) => left.name.localeCompare(right.name, 'zh-CN'))
}

const normalizeProjectOptions = (payload) =>
  listItems(payload).map((project) => {
    const identity = project.identity || {}
    const id = String(project.projectId || project.id || identity.projectId || '').trim()
    if (!id) return null
    return {
      id,
      projectCode: String(project.projectCode || identity.projectCode || id).trim(),
      name: String(project.projectName || project.name || identity.projectName || id).trim(),
      bidType: String(project.bidType || identity.bidType || '').trim(),
      customerId: String(project.customerId || identity.customerId || '').trim(),
      customerName: String(project.customerName || identity.customerName || project.owner || '').trim(),
      customerCanonicalName: String(project.customerCanonicalName || identity.customerCanonicalName || project.customerName || project.owner || '').trim(),
    }
  }).filter(Boolean)

const customerOptionMatches = (option, value) => {
  const key = identityKey(value)
  if (!key) return false
  return [
    option.name,
    option.customerCanonicalName,
    ...(option.aliases || []),
  ].some((candidate) => {
    const candidateKey = identityKey(candidate)
    return candidateKey && (candidateKey === key || candidateKey.includes(key) || key.includes(candidateKey))
  })
}

const customerLabel = (option) => {
  const id = option.customerId ? ` / ${option.customerId}` : ''
  return `${option.name}${id}`
}

const projectLabel = (option) => {
  const parts = [
    option.id,
    option.projectCode && option.projectCode !== option.id ? option.projectCode : '',
    option.customerCanonicalName || option.customerName,
  ].filter(Boolean)
  return `${option.name}（${parts.join(' / ')}）`
}

function IconButton({
  icon,
  label,
  title = label,
  onClick,
  disabled = false,
  variant = 'neutral',
  children,
}) {
  const tone = variant === 'primary'
    ? 'bg-primary text-on-primary hover:bg-primary-container'
    : variant === 'danger'
      ? 'bg-error-container/45 text-error hover:bg-error-container'
      : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim'

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={label}
      className={`inline-flex h-7 min-w-7 items-center justify-center gap-1 rounded px-2 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${tone}`}
    >
      {icon ? <span aria-hidden="true" className="material-symbols-outlined text-[17px]">{icon}</span> : null}
      {children ? <span className="leading-none">{children}</span> : null}
    </button>
  )
}

function TreeNode({
  node,
  selectedPath,
  selectedFileId,
  onSelect,
  onFileSelect,
  onRenameFile,
  onDeleteFile,
  onDeleteFolder,
  onMoveDrop,
  dragTargetPath,
  setDragTargetPath,
  level = 0,
  collapsedMap,
  onToggle,
  scale = 100,
  filesByFolderPath,
}) {
  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  const directFileCount = Number(node.directFileCount || 0)
  const canExpand = hasChildren || directFileCount > 0
  const collapsed = canExpand ? Boolean(collapsedMap[node.path]) : false
  const selected = selectedPath === node.path
  const indent = (12 + level * 16) * (scale / 100)
  const fileIndent = (34 + (level + 1) * 16) * (scale / 100)
  const directFiles = filesByFolderPath?.get(normalizePath(node.path)) || []
  const displayFileCount = directFiles.length || directFileCount
  const normalizedNodePath = normalizePath(node.path)
  const canDragFolder = !PROTECTED_MOVE_FOLDER_PATHS.has(normalizedNodePath)
  const canDeleteThisFolder = Boolean(normalizedNodePath) && !isProtectedDeleteFolderPath(normalizedNodePath)
  const isDropTarget = dragTargetPath === normalizedNodePath
  return (
    <div>
      <button
        type="button"
        draggable={canDragFolder}
        onDragStart={(event) => {
          if (!canDragFolder) {
            event.preventDefault()
            return
          }
          event.dataTransfer.effectAllowed = 'move'
          event.dataTransfer.setData('application/x-raw-folder', JSON.stringify({ path: normalizedNodePath }))
          event.dataTransfer.setData('text/plain', normalizedNodePath)
        }}
        onDragOver={(event) => {
          event.preventDefault()
          event.dataTransfer.dropEffect = 'move'
          setDragTargetPath(normalizedNodePath)
          if (canExpand) onToggle(node.path, false)
        }}
        onDragLeave={() => setDragTargetPath((current) => (current === normalizedNodePath ? '' : current))}
        onDrop={(event) => {
          event.preventDefault()
          setDragTargetPath('')
          onMoveDrop(event, normalizedNodePath)
        }}
        onClick={() => {
          onSelect(node.path)
          if (canExpand) onToggle(node.path, false)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight' && canExpand) {
            event.preventDefault()
            onSelect(node.path)
            onToggle(node.path, false)
          }
          if (event.key === 'ArrowLeft' && canExpand) {
            event.preventDefault()
            onSelect(node.path)
            onToggle(node.path, true)
          }
        }}
        style={{ paddingLeft: `${indent}px`, fontSize: `${Math.max(11, Math.min(14, 13 * (scale / 100)))}px` }}
        className={`group w-full text-left rounded-lg py-2 pr-2 transition-colors flex items-center justify-between gap-2 ${
          isDropTarget
            ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
            :
          selected
            ? 'bg-primary/10 text-primary font-semibold'
            : 'text-on-surface-variant hover:bg-surface-container-low'
        }`}
      >
        <span className="min-w-0 flex items-center gap-1.5">
          {canExpand ? (
            <span
              role="presentation"
              onClick={(event) => {
                event.stopPropagation()
                onSelect(node.path)
                onToggle(node.path)
              }}
              aria-hidden="true"
              className="material-symbols-outlined text-sm text-outline group-hover:text-primary"
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
        <span className="flex shrink-0 items-center gap-1">
          <span className="text-xs text-outline">
            {displayFileCount ? `${displayFileCount}/${node.fileCount}` : node.fileCount}
          </span>
          {canDeleteThisFolder && (
            <button
              type="button"
              title="删除此文件夹"
              aria-label={`删除文件夹 ${node.name}`}
              onClick={(event) => {
                event.stopPropagation()
                onDeleteFolder(normalizedNodePath)
              }}
              className="hidden h-6 w-6 items-center justify-center rounded text-outline hover:bg-error-container/40 hover:text-error group-hover:inline-flex"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[16px]">delete</span>
            </button>
          )}
        </span>
      </button>
      {!collapsed && directFiles.length > 0 && (
        <div className="mt-0.5 space-y-0.5">
          {directFiles.map((item) => {
            const fileSelected = selectedFileId === item.id
            const previewable = canPreviewCleaned(item)
            const meta = cleanStatusMeta(item.cleanStatus)
            return (
              <div
                key={item.id}
                role="button"
                tabIndex={0}
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = 'move'
                  event.dataTransfer.setData('application/x-raw-file', JSON.stringify({ id: item.id, folderPath: item.folderPath || '' }))
                  event.dataTransfer.setData('text/plain', item.id)
                }}
                onClick={() => onFileSelect(item)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onFileSelect(item)
                  }
                }}
                title={previewable ? item.name || '' : cleanedPreviewBlockedMessage(item)}
                style={{
                  paddingLeft: `${fileIndent}px`,
                  fontSize: `${Math.max(11, Math.min(14, 12.5 * (scale / 100)))}px`,
                }}
                className={`group flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left transition-colors ${
                  fileSelected
                    ? 'bg-secondary-container text-on-secondary-container'
                    : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
                }`}
              >
                <span className={`material-symbols-outlined shrink-0 text-[17px] ${previewable ? 'text-secondary' : 'text-outline'}`}>
                  {previewable ? 'description' : 'draft'}
                </span>
                <span className="min-w-0 flex-1 truncate">{item.name || '-'}</span>
                <span className={`hidden shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium sm:inline-flex ${meta.className}`}>
                  {meta.label}
                </span>
                <span className="hidden shrink-0 items-center gap-1 group-hover:inline-flex">
                  <button
                    type="button"
                    title="重命名文件"
                    aria-label={`重命名文件 ${item.name || item.id}`}
                    onClick={(event) => {
                      event.stopPropagation()
                      onRenameFile?.(item)
                    }}
                    className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-surface-container-high hover:text-primary"
                  >
                    <span aria-hidden="true" className="material-symbols-outlined text-[15px]">drive_file_rename_outline</span>
                  </button>
                  <button
                    type="button"
                    title="删除文件"
                    aria-label={`删除文件 ${item.name || item.id}`}
                    onClick={(event) => {
                      event.stopPropagation()
                      onDeleteFile?.(item)
                    }}
                    className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-error-container/40 hover:text-error"
                  >
                    <span aria-hidden="true" className="material-symbols-outlined text-[15px]">delete</span>
                  </button>
                </span>
              </div>
            )
          })}
        </div>
      )}
      {hasChildren && !collapsed && (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              selectedPath={selectedPath}
              selectedFileId={selectedFileId}
              onSelect={onSelect}
              onFileSelect={onFileSelect}
              onRenameFile={onRenameFile}
              onDeleteFile={onDeleteFile}
              onDeleteFolder={onDeleteFolder}
              onMoveDrop={onMoveDrop}
              dragTargetPath={dragTargetPath}
              setDragTargetPath={setDragTargetPath}
              level={level + 1}
              collapsedMap={collapsedMap}
              onToggle={onToggle}
              scale={scale}
              filesByFolderPath={filesByFolderPath}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function MaterialDB({ showToast = () => {} }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const workspaceSlug = useWorkspaceSlug()
  const lockedBidType = bidTypeFromWorkspace(workspaceSlug)
  const materialsBasePath = workspaceSlug ? workspaceRoute(workspaceSlug, '/materials') : '/materials'
  const queryBidType = normalizeBidTypeTab(searchParams.get('bidType') || '')
  const uploadPickerRef = useRef(null)
  const libraryLoadedRef = useRef(false)
  const [tree, setTree] = useState([])
  const [collapsedMap, setCollapsedMap] = useState({})
  const [treeScale, setTreeScale] = useState(100)
  const [dragTargetPath, setDragTargetPath] = useState('')
  const [filesPayload, setFilesPayload] = useState({ items: [], total: 0, page: 1, pageSize: 20 })
  const [parseStatus, setParseStatus] = useState(null)
  const [selectedFolderPath, setSelectedFolderPath] = useState('')
  const [activeBidType, setActiveBidType] = useState(() => normalizeBidTypeTab(lockedBidType || queryBidType || '技术标'))
  const [filters, setFilters] = useState({
    keyword: '',
    customerName: '',
    projectId: '',
    materialTier: '',
    cleanStatus: '',
  })
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [showUploadModal, setShowUploadModal] = useState(false)
  const [uploadKind, setUploadKind] = useState(() => readStoredUploadKind())
  const [uploadMode, setUploadMode] = useState('tier')
  const [uploadPath, setUploadPath] = useState('')
  const [uploadMaterialTier, setUploadMaterialTier] = useState('standard')
  const [customerOptions, setCustomerOptions] = useState([])
  const [projectOptions, setProjectOptions] = useState([])
  const [loadingIdentityOptions, setLoadingIdentityOptions] = useState(false)
  const [uploadCustomerId, setUploadCustomerId] = useState('')
  const [uploadCustomerName, setUploadCustomerName] = useState('')
  const [uploadProjectId, setUploadProjectId] = useState('')
  const [uploadProjectCode, setUploadProjectCode] = useState('')
  const [uploadProjectName, setUploadProjectName] = useState('')
  const [uploadBidType, setUploadBidType] = useState('技术标')
  const [uploadFiles, setUploadFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [previewItem, setPreviewItem] = useState(null)
  const [previewSession, setPreviewSession] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [onlyofficePreviewError, setOnlyofficePreviewError] = useState('')

  const [conflictContext, setConflictContext] = useState(null)

  const canManageCurrentFolder = Boolean(selectedFolderPath)
  const canCreateFolder = Boolean(selectedFolderPath) && canManageCurrentFolder
  const canDeleteFolder = Boolean(selectedFolderPath) && !isProtectedDeleteFolderPath(selectedFolderPath)

  const fileItems = useMemo(() => filesPayload?.items || [], [filesPayload?.items])
  const totalCount = Number(filesPayload?.total || 0)
  const filesByFolderPath = useMemo(() => groupFilesByFolderPath(fileItems), [fileItems])
  const visibleTreeFileCount = useMemo(() => getVisibleFileCount(tree), [tree])
  const previewTitle = previewSession?.fileName || previewItem?.cleanedFileName || previewItem?.name || '未选择清洗稿'
  const hasPreviewSession = Boolean(previewSession?.onlyoffice?.fileUrl) && !onlyofficePreviewError
  const previewModeLabel = previewLoading
    ? '加载中'
    : onlyofficePreviewError
      ? '异常'
      : hasPreviewSession
        ? '可预览'
        : previewItem
          ? '未开放'
          : '未选择'
  const selectedUploadCustomer = customerOptions.find((option) => option.customerId === uploadCustomerId)
  const selectedUploadProject = projectOptions.find((option) => option.id === uploadProjectId)
  const activeFilterCount = [
    filters.keyword,
    filters.customerName,
    filters.projectId,
    filters.materialTier,
    filters.cleanStatus,
  ].filter((value) => String(value || '').trim()).length

  const loadLibrary = useCallback(async (options = {}) => {
    const silent = Boolean(options.silent || libraryLoadedRef.current)
    if (silent) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const treeResponse = await materialsAPI.raw.tree()
      const normalizedTree = ensureMaterialRootNodes(
        normalizeTreeNodes(treeResponse?.tree || treeResponse?.items || treeResponse?.nodes || [])
      )
      const visibleTree = normalizedTree.filter((node) => normalizePath(node.path) === activeBidType)
      setTree(visibleTree)
      const validPaths = new Set(flattenTreePaths(visibleTree))
      const effectiveFolder = validPaths.has(selectedFolderPath)
        ? selectedFolderPath
        : pickDefaultFolder(visibleTree, activeBidType)
      setCollapsedMap((prev) => {
        const validPathSet = new Set(flattenTreePaths(visibleTree))
        let next = Object.fromEntries(
          Object.entries(prev).filter(([path]) => validPathSet.has(path)),
        )
        if (Object.keys(next).length === 0) {
          next = buildDefaultCollapsedMap(visibleTree)
        }
        return expandPathInMap(next, effectiveFolder)
      })
      if (selectedFolderPath !== effectiveFolder) {
        setSelectedFolderPath(effectiveFolder)
      }

      const filePageSize = Math.max(1000, getVisibleFileCount(visibleTree) + 50)
      const payload = await materialsAPI.raw.files({
        folderPath: '',
        recursive: true,
        keyword: filters.keyword.trim(),
        bidType: activeBidType,
        customerName: filters.customerName.trim(),
        projectId: filters.projectId.trim(),
        materialTier: filters.materialTier,
        cleanStatus: filters.cleanStatus,
        page: 1,
        pageSize: filePageSize,
      })
      setFilesPayload(payload || { items: [], total: 0, page: 1, pageSize: filePageSize })

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
      libraryLoadedRef.current = true
      if (silent) setRefreshing(false)
      else setLoading(false)
    }
  }, [activeBidType, filters, selectedFolderPath])

  const loadUploadIdentityOptions = useCallback(async () => {
    setLoadingIdentityOptions(true)
    try {
      const identityPayload = await materialsAPI.identityOptions({ bidType: activeBidType }) || {}
      const normalizedProjects = normalizeProjectOptions(identityPayload.projects || [])
      setProjectOptions(normalizedProjects)
      setCustomerOptions(normalizeCustomerOptions(identityPayload.customers || [], identityPayload.projects || []))
    } catch (e) {
      setCustomerOptions([])
      setProjectOptions([])
      setUploadError(safeMessage(e, '客户/项目列表加载失败，请刷新后重试。'))
    } finally {
      setLoadingIdentityOptions(false)
    }
  }, [activeBidType])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadLibrary()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadLibrary])

  useEffect(() => {
    if (!lockedBidType) return
    const timer = setTimeout(() => {
      const next = normalizeBidTypeTab(lockedBidType)
      setActiveBidType(next)
      setUploadBidType(next)
      setSelectedFolderPath('')
      setParseStatus(null)
    }, 0)
    return () => clearTimeout(timer)
  }, [lockedBidType])

  useEffect(() => {
    persistUploadKind(uploadKind)
  }, [uploadKind])

  useEffect(() => {
    if (!showUploadModal) return
    const timer = setTimeout(() => {
      loadUploadIdentityOptions()
    }, 0)
    return () => clearTimeout(timer)
  }, [showUploadModal, loadUploadIdentityOptions])

  useEffect(() => {
    if (!showUploadModal || uploadCustomerId || !uploadCustomerName.trim()) return
    const matchedCustomer = customerOptions.find((option) => customerOptionMatches(option, uploadCustomerName))
    if (!matchedCustomer) return
    const timer = setTimeout(() => {
      setUploadCustomerId(matchedCustomer.customerId)
      setUploadCustomerName(matchedCustomer.name)
    }, 0)
    return () => clearTimeout(timer)
  }, [customerOptions, showUploadModal, uploadCustomerId, uploadCustomerName])

  const setCollapseForAll = (collapsed) => {
    const paths = collectCollapsiblePaths(tree)
    const map = {}
    paths.forEach((path) => {
      map[path] = collapsed
    })
    setCollapsedMap(map)
  }

  const toggleNode = (path, nextValue) => {
    setCollapsedMap((prev) => ({
      ...prev,
      [path]: typeof nextValue === 'boolean' ? nextValue : !prev[path],
    }))
  }

  const changeTreeScale = (delta) => {
    setTreeScale((prev) => Math.max(80, Math.min(140, prev + delta)))
  }

  const openUploadModal = (options = {}) => {
    const targetPath = options.targetPath || selectedFolderPath
    const rootTier = materialTierFromRootPath(targetPath)
    const mode = options.mode || (rootTier ? 'tier' : 'tier')
    const nextTier = options.materialTier || rootTier || (filters.projectId.trim() ? 'project' : 'standard')
    setShowUploadModal(true)
    setUploadKind(options.kind || 'files')
    setUploadMode(mode)
    setUploadPath(targetPath)
    setUploadMaterialTier(nextTier)
    setUploadCustomerId(options.customerId || '')
    setUploadCustomerName(options.customerName || filters.customerName.trim())
    setUploadProjectId(options.projectId || filters.projectId.trim())
    setUploadProjectCode(options.projectCode || '')
    setUploadProjectName(options.projectName || '')
    setUploadBidType(activeBidType)
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

  useEffect(() => {
    if (!showUploadModal && !conflictContext) return undefined
    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return
      if (conflictContext) {
        setConflictContext(null)
        return
      }
      if (showUploadModal && !uploading) closeUploadModal()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [conflictContext, showUploadModal, uploading])

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
      const selectedCustomer = customerOptions.find((option) => option.customerId === uploadCustomerId)
      const selectedProject = projectOptions.find((option) => option.id === uploadProjectId)
      const projectId = uploadMode === 'tier' && uploadMaterialTier === 'project' ? uploadProjectId.trim() : ''
      const projectCode = uploadMode === 'tier' && uploadMaterialTier === 'project'
        ? String(selectedProject?.projectCode || uploadProjectCode || projectId).trim()
        : ''
      const projectName = uploadMode === 'tier' && uploadMaterialTier === 'project'
        ? String(selectedProject?.name || uploadProjectName || '').trim()
        : ''
      const customerId = uploadMode === 'tier' && uploadMaterialTier === 'customer'
        ? String(selectedCustomer?.customerId || uploadCustomerId || '').trim()
        : uploadMode === 'tier' && uploadMaterialTier === 'project'
          ? String(selectedProject?.customerId || uploadCustomerId || '').trim()
          : ''
      const customerName = uploadMode === 'tier' && uploadMaterialTier === 'customer'
        ? String(selectedCustomer?.name || uploadCustomerName || '').trim()
        : uploadMode === 'tier' && uploadMaterialTier === 'project'
          ? String(selectedProject?.customerCanonicalName || selectedProject?.customerName || uploadCustomerName || '').trim()
          : ''
      const materialTier = uploadMode === 'tier' ? uploadMaterialTier : ''

      if (uploadMode === 'path' && !targetPath) {
        setUploadError('请填写目标目录。')
        setUploading(false)
        return
      }
      if (uploadMode === 'tier' && uploadMaterialTier === 'customer' && !customerId) {
        setUploadError('请选择客户。')
        setUploading(false)
        return
      }
      if (uploadMode === 'tier' && uploadMaterialTier === 'project' && !projectId) {
        setUploadError('请选择项目。')
        setUploading(false)
        return
      }

      payload.append('targetPath', targetPath)
      payload.append('projectId', projectId)
      payload.append('projectCode', projectCode)
      payload.append('projectName', projectName)
      payload.append('bidType', uploadBidType)
      payload.append('materialTier', materialTier)
      payload.append('customerId', customerId)
      payload.append('customerName', customerName)
      if (onConflict) {
        payload.append('onConflict', onConflict)
      }
      uploadFiles.forEach((file) => {
        const relativePath = uploadKind === 'folder' ? (file.webkitRelativePath || file.name) : ''
        payload.append('files', file, file.name)
        payload.append('relativePaths', relativePath)
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

  const handleDeleteFolder = async (path = selectedFolderPath) => {
    const targetPath = normalizePath(path)
    const canDeleteTarget = Boolean(targetPath) && !isProtectedDeleteFolderPath(targetPath)
    if (!canDeleteTarget) {
      showToast('基础素材目录不允许删除。', 'error')
      return
    }
    const ok = window.confirm(`确认删除文件夹：${targetPath} ？\n\n该目录下的子文件夹和素材文件也会一起删除。`)
    if (!ok) return
    try {
      const result = await materialsAPI.raw.deleteFolder({ path: targetPath })
      showToast(result?.message || '文件夹删除成功')
      setSelectedFolderPath(parentPath(targetPath))
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '删除文件夹失败'), 'error')
    }
  }

  const handleRenameFile = async (item) => {
    if (!item?.id) return
    const currentName = String(item.name || '').trim()
    const nextName = window.prompt('请输入新的文件名', currentName)
    if (!nextName || !nextName.trim() || nextName.trim() === currentName) return
    try {
      const result = await materialsAPI.raw.updateFile(item.id, { name: nextName.trim() })
      showToast(result?.message || '文件重命名成功')
      if (previewItem?.id === item.id) {
        setPreviewItem((prev) => ({ ...prev, name: result?.item?.name || nextName.trim() }))
        setPreviewSession(null)
        setOnlyofficePreviewError('')
      }
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '文件重命名失败'), 'error')
    }
  }

  const handleDeleteFile = async (item) => {
    if (!item?.id) return
    const ok = window.confirm(`确认删除文件：${item.name || item.id} ？\n\n原始文件及其清洗稿也会一起删除。`)
    if (!ok) return
    try {
      const result = await materialsAPI.raw.deleteFile(item.id)
      showToast(result?.message || '文件删除成功')
      if (previewItem?.id === item.id) {
        setPreviewItem(null)
        setPreviewSession(null)
        setPreviewError('')
        setOnlyofficePreviewError('')
      }
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '文件删除失败'), 'error')
    }
  }

  const handlePreviewCleaned = async (item) => {
    setPreviewItem(item)
    setPreviewSession(null)
    setOnlyofficePreviewError('')

    if (!canPreviewCleaned(item)) {
      const message = cleanedPreviewBlockedMessage(item)
      setPreviewError(message)
      showToast(message, 'error')
      return
    }

    setPreviewLoading(true)
    setPreviewError('')
    try {
      const payload = await materialsAPI.raw.previewCleanedFile(item.id)
      setPreviewSession(payload)
    } catch (e) {
      setPreviewError(safeMessage(e, '清洗稿预览加载失败'))
    } finally {
      setPreviewLoading(false)
    }
  }

  const parseDragPayload = (event, mimeType) => {
    try {
      const raw = event.dataTransfer.getData(mimeType)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }

  const handleMoveDrop = async (event, targetPath) => {
    const normalizedTarget = normalizePath(targetPath)
    if (!normalizedTarget || normalizedTarget.startsWith('商务标')) {
      showToast('商务标素材库当前不可移动。', 'error')
      return
    }

    const filePayload = parseDragPayload(event, 'application/x-raw-file')
    if (filePayload?.id) {
      const sourceFolder = normalizePath(filePayload.folderPath)
      if (sourceFolder === normalizedTarget) return
      try {
        const result = await materialsAPI.raw.moveFile({
          fileId: filePayload.id,
          targetPath: normalizedTarget,
        })
        showToast(result?.message || '文件移动成功')
        await loadLibrary({ silent: true })
      } catch (e) {
        if (e?.status === 409 && e?.code === 'MATERIAL_CONFLICT') {
          setConflictContext({
            type: 'move-file',
            payload: { fileId: filePayload.id, targetPath: normalizedTarget },
            detail: e?.payload?.conflict || null,
          })
        } else {
          showToast(safeMessage(e, '文件移动失败'), 'error')
        }
      }
      return
    }

    const folderPayload = parseDragPayload(event, 'application/x-raw-folder')
    const sourcePath = normalizePath(folderPayload?.path)
    if (!sourcePath || sourcePath === normalizedTarget) return
    if (PROTECTED_MOVE_FOLDER_PATHS.has(sourcePath)) {
      showToast('基础目录不允许移动。', 'error')
      return
    }
    if (normalizedTarget.startsWith(`${sourcePath}/`)) {
      showToast('不能将目录移动到自身的子目录下。', 'error')
      return
    }

    try {
      const result = await materialsAPI.raw.moveFolder({
        sourcePath,
        targetParentPath: normalizedTarget,
      })
      showToast(result?.message || '文件夹移动成功')
      setSelectedFolderPath(result?.folderPath || normalizedTarget)
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '文件夹移动失败'), 'error')
    }
  }

  const handleBidTypeChange = (value) => {
    if (lockedBidType) return
    const next = normalizeBidTypeTab(value)
    if (next === activeBidType) return
    setActiveBidType(next)
    setSearchParams({ bidType: next })
    setSelectedFolderPath('')
    setParseStatus(null)
  }

  const resolveConflict = async (action) => {
    if (conflictContext.type === 'upload') {
      await performUpload(action)
    } else if (conflictContext.type === 'move-file') {
      try {
        const result = await materialsAPI.raw.moveFile({
          ...(conflictContext.payload || {}),
          onConflict: action,
        })
        showToast(result?.message || '文件移动成功')
        setConflictContext(null)
        await loadLibrary({ silent: true })
      } catch (e) {
        showToast(safeMessage(e, '文件移动失败'), 'error')
      }
    }
  }

  const updateFilter = (key, value) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value,
    }))
  }

  const clearFilters = () => {
    setFilters({
      keyword: '',
      customerName: '',
      projectId: '',
      materialTier: '',
      cleanStatus: '',
    })
  }

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
      <MaterialsViewSwitch
        active="structured"
        activeBidType={activeBidType}
        lockedBidType={lockedBidType}
        onBidTypeChange={handleBidTypeChange}
        title="原始材料库"
        subtitle={refreshing || error ? (error || '正在刷新...') : (
          activeBidType === '技术标'
            ? '管理技术标通用、客户、项目三档原始素材。'
            : '管理商务标通用、客户、项目三档原始素材。'
        )}
        actions={(
          <div className="flex flex-nowrap gap-2">
            <button
              onClick={() => loadLibrary({ silent: true })}
              className="whitespace-nowrap px-3 py-2 text-sm font-medium rounded-lg bg-surface-container-high text-on-surface-variant hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={() => openUploadModal({ mode: 'tier' })}
              className="whitespace-nowrap px-3 py-2 text-sm font-medium rounded-lg bg-primary text-on-primary hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              上传文件
            </button>
          </div>
        )}
        meta={(
          <div className="flex flex-nowrap gap-2 text-xs xl:justify-end">
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-primary/10 text-primary">
              {activeBidType}
            </span>
            <span className="max-w-[260px] truncate whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              当前目录 {selectedFolderPath || '-'}
            </span>
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              文件 {fileItems.length}/{visibleTreeFileCount || totalCount}
            </span>
            <span className="whitespace-nowrap px-2.5 py-1 rounded-full bg-surface-container-high text-on-surface-variant">
              权限 可编辑
            </span>
          </div>
        )}
        basePath={materialsBasePath}
      />

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

      <OnlyOfficeWorkspace
        heightClass="min-h-[760px]"
        gridClassName="xl:grid-cols-[minmax(28rem,38rem)_minmax(0,1fr)]"
        documentTitle="清洗稿预览"
        documentSubtitle={`当前文件：${previewTitle}`}
        documentMeta={(
          <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${hasPreviewSession ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {previewModeLabel}
          </span>
        )}
        documentAreaClassName="flex flex-col"
        sidebar={(
          <section className="flex h-full min-h-0 flex-col">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-on-surface">素材目录</h3>
                <p className="mt-1 truncate text-xs text-outline">{selectedFolderPath || '未选择目录'}</p>
              </div>
              <span className="rounded-full bg-surface-container-high px-2.5 py-1 text-xs font-semibold text-on-surface-variant">
                已加载 {fileItems.length}
              </span>
            </div>

            <div className="flex min-h-0 flex-1 flex-col">
              <div className="border-b border-surface-container-high bg-surface-container-lowest px-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-on-surface">目录与文件</div>
                    <div className="mt-0.5 truncate text-xs text-outline">
                      {selectedFolderPath || '请选择目录'}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-1" role="toolbar" aria-label="素材目录工具栏">
                    <IconButton icon="unfold_more" label="展开全部" onClick={() => setCollapseForAll(false)} />
                    <IconButton icon="unfold_less" label="收起全部" onClick={() => setCollapseForAll(true)} />
                    <span className="mx-1 h-4 w-px bg-surface-container-high" aria-hidden="true" />
                    <IconButton label="缩小目录" onClick={() => changeTreeScale(-10)}>-</IconButton>
                    <span className="w-9 text-center text-xs text-on-surface-variant" aria-label={`目录缩放 ${treeScale}%`}>{treeScale}%</span>
                    <IconButton label="放大目录" onClick={() => changeTreeScale(10)}>+</IconButton>
                    <span className="mx-1 h-4 w-px bg-surface-container-high" aria-hidden="true" />
                    <IconButton icon="create_new_folder" label="新建文件夹" onClick={handleCreateFolder} disabled={!canCreateFolder} />
                    <IconButton
                      icon="folder_delete"
                      label="删除文件夹"
                      title={selectedFolderPath && isProtectedDeleteFolderPath(selectedFolderPath) ? '基础素材目录不可删除' : '删除文件夹'}
                      onClick={handleDeleteFolder}
                      disabled={!canDeleteFolder}
                      variant="danger"
                    />
                    <IconButton
                      icon="upload_file"
                      label="上传到当前目录"
                      onClick={() => openUploadModal({ mode: 'path', targetPath: selectedFolderPath })}
                      disabled={!canManageCurrentFolder || !selectedFolderPath}
                      variant="primary"
                    />
                  </div>
                </div>

                <div className="mt-3 rounded-md border border-surface-container-high bg-surface-container-low px-3 py-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-on-surface">筛选</span>
                    <div className="flex items-center gap-2">
                      {activeFilterCount > 0 && (
                        <button
                          type="button"
                          onClick={clearFilters}
                          className="text-xs font-medium text-primary hover:text-on-primary-container"
                        >
                          清除 {activeFilterCount}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setShowAdvancedFilters((value) => !value)}
                        aria-expanded={showAdvancedFilters}
                        className="inline-flex items-center gap-0.5 rounded px-1.5 py-1 text-xs font-medium text-on-surface-variant hover:bg-surface-container-high"
                      >
                        高级
                        <span aria-hidden="true" className="material-symbols-outlined text-[15px]">
                          {showAdvancedFilters ? 'expand_less' : 'expand_more'}
                        </span>
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_9rem]">
                    <label className="relative">
                      <span className="sr-only">搜索文件名</span>
                      <span aria-hidden="true" className="material-symbols-outlined pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[17px] text-outline">search</span>
                      <input
                        value={filters.keyword}
                        onChange={(e) => updateFilter('keyword', e.target.value)}
                        placeholder="搜索文件名"
                        className="h-9 w-full rounded-md border-none bg-surface-container-highest px-8 text-xs"
                      />
                      {filters.keyword && (
                        <button
                          type="button"
                          aria-label="清空文件名搜索"
                          onClick={() => updateFilter('keyword', '')}
                          className="absolute right-1.5 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-outline hover:bg-surface-container-high hover:text-on-surface"
                        >
                          <span aria-hidden="true" className="material-symbols-outlined text-[15px]">close</span>
                        </button>
                      )}
                    </label>
                    <select
                      aria-label="清洗状态"
                      value={filters.cleanStatus}
                      onChange={(e) => updateFilter('cleanStatus', e.target.value)}
                      className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-xs"
                    >
                      {CLEAN_STATUS_OPTIONS.map((option) => (
                        <option key={option.value || 'all'} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                    {showAdvancedFilters && (
                      <>
                        <select
                          aria-label="素材层级"
                          value={filters.materialTier}
                          onChange={(e) => updateFilter('materialTier', e.target.value)}
                          className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-xs"
                        >
                          <option value="">全部层级</option>
                          {MATERIAL_TIER_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                        <input
                          aria-label="按客户筛选"
                          value={filters.customerName}
                          onChange={(e) => updateFilter('customerName', e.target.value)}
                          placeholder="客户"
                          className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-xs"
                        />
                        <input
                          aria-label="按项目筛选"
                          value={filters.projectId}
                          onChange={(e) => updateFilter('projectId', e.target.value)}
                          placeholder="项目ID/编号"
                          className="h-9 rounded-md border-none bg-surface-container-highest px-3 text-xs"
                        />
                      </>
                    )}
                  </div>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                <div className="min-h-full rounded-md border border-surface-container-high bg-surface-container-lowest p-2">
                  {tree.map((node) => (
                    <TreeNode
                      key={node.id}
                      node={node}
                      selectedPath={selectedFolderPath}
                      selectedFileId={previewItem?.id}
                      onSelect={(path) => setSelectedFolderPath(path)}
                      onFileSelect={(item) => {
                        setSelectedFolderPath(item.folderPath || selectedFolderPath)
                        handlePreviewCleaned(item)
                      }}
                      onRenameFile={handleRenameFile}
                      onDeleteFile={handleDeleteFile}
                      onDeleteFolder={handleDeleteFolder}
                      onMoveDrop={handleMoveDrop}
                      dragTargetPath={dragTargetPath}
                      setDragTargetPath={setDragTargetPath}
                      collapsedMap={collapsedMap}
                      onToggle={toggleNode}
                      scale={treeScale}
                      filesByFolderPath={filesByFolderPath}
                    />
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}
      >
        {onlyofficePreviewError && (
          <div className="mb-3 rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">
            {onlyofficePreviewError}
          </div>
        )}
        {previewLoading ? (
          <div className="flex min-h-[560px] flex-1 items-center justify-center rounded-md border border-surface-container-high bg-surface-container-lowest px-6 text-center">
            <div>
              <span className="material-symbols-outlined text-4xl text-primary">hourglass_empty</span>
              <p className="mt-3 text-sm text-on-surface-variant">正在加载清洗稿预览...</p>
            </div>
          </div>
        ) : hasPreviewSession ? (
          <OnlyOfficeEmbed
            session={previewSession?.onlyoffice}
            mode="view"
            className="h-full min-h-[560px] w-full rounded-md border border-surface-container-high bg-white"
            onReady={() => setOnlyofficePreviewError('')}
            onError={(message) => setOnlyofficePreviewError(message || 'OnlyOffice 清洗稿加载失败')}
          />
        ) : (
          <div className="flex min-h-[560px] flex-1 items-center justify-center rounded-md border border-dashed border-surface-container-high px-6 text-center">
            <p className="max-w-md text-sm text-on-surface-variant">
              {onlyofficePreviewError || previewError || cleanedPreviewBlockedMessage(previewItem)}
            </p>
          </div>
        )}
      </OnlyOfficeWorkspace>

      {showUploadModal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-hidden p-3 sm:p-4">
          <div className="w-full max-w-2xl h-[calc(100vh-1.5rem)] sm:h-[calc(100vh-2rem)] max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2rem)] bg-surface-container-lowest rounded-xl border border-surface-container-high shadow-2xl flex flex-col overflow-hidden">
            <div className="px-5 sm:px-6 py-4 border-b border-surface-container-high flex items-center justify-between shrink-0">
              <h2 className="text-lg font-headline font-bold text-on-surface">上传{activeBidType}原始素材</h2>
              <button onClick={closeUploadModal} className="close-plain text-on-surface-variant hover:text-primary transition-colors" aria-label="关闭">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-5 sm:p-6 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="text-sm text-on-surface-variant">
                  <span className="block mb-1">落位方式</span>
                  <div className="grid h-10 grid-cols-2 rounded-lg bg-surface-container-highest p-1" role="group" aria-label="落位方式">
                    {[
                      ['tier', '素材层级'],
                      ['path', '当前目录'],
                    ].map(([value, label]) => {
                      const active = uploadMode === value
                      return (
                        <button
                          key={value}
                          type="button"
                          onClick={() => setUploadMode(value)}
                          aria-pressed={active}
                          className={`rounded-md text-sm font-semibold transition-colors ${active ? 'bg-white text-primary shadow-[0_1px_2px_rgba(17,34,51,0.08)]' : 'text-on-surface-variant hover:bg-surface-container-high'}`}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                </div>
                <label className="text-sm text-on-surface-variant">
                  <span className="block mb-1">标书类型</span>
                  <select
                    value={uploadBidType}
                    onChange={(e) => setUploadBidType(normalizeBidTypeTab(e.target.value))}
                    className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                  >
                    <option value="技术标">技术标</option>
                    <option value="商务标">商务标</option>
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
                    placeholder={`例如：${activeBidType}/通用素材/01-示例目录`}
                  />
                </label>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <label className="text-sm text-on-surface-variant">
                    <span className="block mb-1">素材层级</span>
                    <select
                      value={uploadMaterialTier}
                      onChange={(e) => {
                        setUploadMaterialTier(e.target.value)
                        setUploadError('')
                      }}
                      className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                    >
                      {MATERIAL_TIER_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  {uploadMaterialTier === 'customer' ? (
                    <label className="text-sm text-on-surface-variant">
                      <span className="block mb-1">选择客户</span>
                      <select
                        value={uploadCustomerId}
                        onChange={(e) => {
                          const customerId = e.target.value
                          const customer = customerOptions.find((option) => option.customerId === customerId)
                          setUploadCustomerId(customerId)
                          setUploadCustomerName(customer?.name || '')
                          setUploadError('')
                        }}
                        disabled={loadingIdentityOptions}
                        className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                      >
                        <option value="">{loadingIdentityOptions ? '正在加载客户...' : '选择客户'}</option>
                        {customerOptions.map((option) => (
                          <option key={option.customerId || option.name} value={option.customerId}>
                            {customerLabel(option)}
                          </option>
                        ))}
                      </select>
                      <span className="block mt-1 text-xs text-outline">
                        {selectedUploadCustomer?.customerId ? `系统ID：${selectedUploadCustomer.customerId}` : '客户ID由系统写入'}
                      </span>
                    </label>
                  ) : uploadMaterialTier === 'project' ? (
                    <label className="text-sm text-on-surface-variant">
                      <span className="block mb-1">选择项目</span>
                      <select
                        value={uploadProjectId}
                        onChange={(e) => {
                          const projectId = e.target.value
                          const project = projectOptions.find((option) => option.id === projectId)
                          setUploadProjectId(projectId)
                          setUploadProjectCode(project?.projectCode || '')
                          setUploadProjectName(project?.name || '')
                          setUploadCustomerId(project?.customerId || '')
                          setUploadCustomerName(project?.customerCanonicalName || project?.customerName || '')
                          setUploadError('')
                        }}
                        disabled={loadingIdentityOptions}
                        className="w-full h-10 px-3 rounded-lg bg-surface-container-highest border-none text-sm"
                      >
                        <option value="">{loadingIdentityOptions ? '正在加载项目...' : '选择项目'}</option>
                        {projectOptions.map((option) => (
                          <option key={option.id} value={option.id}>
                            {projectLabel(option)}
                          </option>
                        ))}
                      </select>
                      <span className="block mt-1 text-xs text-outline">
                        {selectedUploadProject
                          ? `素材项目ID：${selectedUploadProject.id}${selectedUploadProject.projectCode ? `；项目编号：${selectedUploadProject.projectCode}` : ''}`
                          : '素材项目ID由系统写入'}
                      </span>
                    </label>
                  ) : (
                    <div className="rounded-lg bg-surface-container-highest px-3 py-2 text-xs text-on-surface-variant leading-5">
                      {materialTierMeta(uploadMaterialTier).description}
                    </div>
                  )}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="text-sm text-on-surface-variant">
                  <span className="block mb-1">上传内容</span>
                  <div className="grid h-10 grid-cols-2 rounded-lg bg-surface-container-highest p-1" role="group" aria-label="上传内容">
                    {[
                      ['files', '文件'],
                      ['folder', '文件夹'],
                    ].map(([value, label]) => {
                      const active = uploadKind === value
                      return (
                        <button
                          key={value}
                          type="button"
                          onClick={() => {
                            setUploadKind(value)
                            setUploadFiles([])
                            setUploadError('')
                          }}
                          aria-pressed={active}
                          className={`rounded-md text-sm font-semibold transition-colors ${active ? 'bg-white text-primary shadow-[0_1px_2px_rgba(17,34,51,0.08)]' : 'text-on-surface-variant hover:bg-surface-container-high'}`}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                </div>
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
                <div className="rounded-lg bg-surface-container-low p-3 text-xs text-on-surface-variant max-h-48 overflow-y-auto overscroll-contain">
                  {uploadFiles.map((item) => (
                    <div key={`${item.webkitRelativePath || item.name}-${item.size}-${item.lastModified}`} className="flex items-center justify-between py-1">
                      <span className="truncate mr-2">{item.webkitRelativePath || item.name}</span>
                      <span>{toSizeLabel(item.size)}</span>
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs text-outline">
                白名单：pdf/doc/docx/xls/xlsx/xlsm/png/jpg/jpeg/webp/bmp/tif/tiff/DS_Store；单文件 1024MB。图片类素材仅保留原件，不触发自动清洗。
              </p>

              {uploadError && (
                <div className="text-sm text-error bg-error-container/30 border border-error/30 rounded-lg px-3 py-2">
                  {uploadError}
                </div>
              )}
            </div>
            <div className="px-5 sm:px-6 py-4 border-t border-surface-container-high flex justify-end gap-3 bg-surface-container-low rounded-b-xl shrink-0 shadow-[0_-8px_20px_rgba(0,0,0,0.04)]">
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
