import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { businessMaterialsAPI } from '../../../api'
import MaterialsViewSwitch from '../components/BusinessMaterialsViewSwitch'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import { PageError, PageLoading } from '../../../components/states/PageState'
import { workspaceRoute } from '../../../utils/workspace'

const MAX_FILE_SIZE = 30 * 1024 * 1024 * 1024
const FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
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
const BUSINESS_MATERIAL_KIND_OPTIONS = [
  {
    value: 'fixed',
    label: '固定素材',
  },
  {
    value: 'ai_fill',
    label: 'AI填写',
  },
  {
    value: 'other',
    label: '其他',
  },
]
const BUSINESS_BID_TYPE = '商务标'
const BUSINESS_WORKSPACE = 'business'
const BUSINESS_ROOT_PATH = '商务标/通用素材'
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'xlsm', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])
const MATERIAL_ROOT_PATHS = ['商务标']
const PROTECTED_DELETE_FOLDER_PATHS = new Set([
  '商务标',
  '商务标/通用素材',
  '商务标/客户素材',
  '商务标/项目素材',
])
const BUSINESS_STANDARD_PROTECTED_FOLDER_PATHS = new Set([
  '商务标/通用素材/资格审查与基础证明',
  '商务标/通用素材/财务信用与合规声明',
  '商务标/通用素材/制造商与供应链材料',
  '商务标/通用素材/机型认证与测试报告',
  '商务标/通用素材/企业能力与供货业绩',
  '商务标/通用素材/表单模板与过程稿',
])
const BUSINESS_CUSTOMER_PROTECTED_FOLDER_NAMES = new Set([
  '客户准入与专项证明',
  '客户专用响应口径',
  '客户模板与历史文件',
])
const BUSINESS_PROJECT_PROTECTED_FOLDER_NAMES = new Set([
  '招标要求与专项证明',
  '资格审查与商务响应成册',
  '项目过程稿与澄清文件',
])

const MATERIAL_ROOT_LABELS = {
  商务标: '商务标',
  通用素材: '通用素材',
  客户素材: '客户素材',
  项目素材: '项目素材',
  标准模板: '通用素材',
  客户定制: '客户素材',
  项目定制: '项目素材',
}

const bidTypeTabMeta = (value) =>
  value === BUSINESS_BID_TYPE
    ? { value: BUSINESS_BID_TYPE, label: BUSINESS_BID_TYPE, icon: 'request_quote', rootPath: BUSINESS_ROOT_PATH }
    : { value: BUSINESS_BID_TYPE, label: BUSINESS_BID_TYPE, icon: 'request_quote', rootPath: BUSINESS_ROOT_PATH }

const materialTierMeta = (value) =>
  MATERIAL_TIER_OPTIONS.find((item) => item.value === value) || MATERIAL_TIER_OPTIONS[0]

const businessMaterialKindMeta = (value) =>
  BUSINESS_MATERIAL_KIND_OPTIONS.find((item) => item.value === value) || BUSINESS_MATERIAL_KIND_OPTIONS[2]

const normalizeTagList = (value) => {
  const source = Array.isArray(value)
    ? value
    : String(value || '').split(/[,，;；\n\r\t]+/)
  const seen = new Set()
  const tags = []
  source.forEach((item) => {
    const tag = String(item || '').replace(/\s+/g, ' ').trim().slice(0, 40)
    if (!tag) return
    const key = tag.toLocaleLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    tags.push(tag)
  })
  return tags.slice(0, 20)
}

const normalizeTagOptions = (value) => {
  const source = Array.isArray(value)
    ? value
    : String(value || '').split(/[,，;；\n\r\t]+/)
  const seen = new Set()
  const tags = []
  source.forEach((item) => {
    const tag = String(item || '').replace(/\s+/g, ' ').trim().slice(0, 40)
    if (!tag) return
    const key = tag.toLocaleLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    tags.push(tag)
  })
  return tags.slice(0, 100)
}

const tagInputPreview = (committedTags, draftValue) => normalizeTagList([
  ...normalizeTagList(committedTags),
  ...normalizeTagList(draftValue),
])

const canPreviewCleaned = (item) => item?.cleanStatus === 'cleaned' && Boolean(item?.hasCleanedWord)

const cleanedPreviewBlockedMessage = (item) => {
  if (!item) return '选择已清洗文件后预览。'
  if (item.cleanStatus === 'original_only') return '该素材仅保留原件。'
  if (item.cleanStatus === 'failed') return '清洗失败，暂无预览。'
  if (item.cleanStatus === 'cleaning') return '清洗中，完成后可预览。'
  if (item.cleanStatus === 'pending') return '等待清洗，完成后可预览。'
  if (item.cleanStatus === 'cleaned' && !item.hasCleanedWord) return '清洗文件丢失，请联系管理员重新处理。'
  return '暂无清洗稿。'
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
  return [
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
  if (parts.length === 3 && parts[0] === '商务标' && (parts[1] === '客户素材' || parts[1] === '项目素材')) {
    return true
  }
  if (parts.length !== 4 || parts[0] !== '商务标') return false
  if (parts[1] === '客户素材') return BUSINESS_CUSTOMER_PROTECTED_FOLDER_NAMES.has(parts[3])
  if (parts[1] === '项目素材') return BUSINESS_PROJECT_PROTECTED_FOLDER_NAMES.has(parts[3])
  return false
}

const parentPath = (path) => {
  const normalized = String(path || '').replace(/^\/+|\/+$/g, '')
  if (!normalized) return ''
  const parts = normalized.split('/')
  if (parts.length <= 1) return ''
  return parts.slice(0, -1).join('/')
}

const pickDefaultFolder = (nodes = [], bidType = BUSINESS_BID_TYPE) => {
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

const filterTreeByMatchedFiles = (nodes = [], filesByFolderPath = new Map()) =>
  (Array.isArray(nodes) ? nodes : [])
    .map((node) => {
      const path = normalizePath(node?.path)
      const directFileCount = filesByFolderPath.get(path)?.length || 0
      const children = filterTreeByMatchedFiles(node?.children || [], filesByFolderPath)
      const childFileCount = children.reduce((sum, child) => sum + Number(child?.fileCount || 0), 0)
      const fileCount = directFileCount + childFileCount
      if (fileCount <= 0) return null
      return {
        ...node,
        children,
        directFileCount,
        fileCount,
      }
    })
    .filter(Boolean)

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

function TagInput({
  value,
  inputValue,
  onChange,
  onInputChange,
  placeholder = '输入标签后按 Enter',
  disabled = false,
  autoFocus = false,
}) {
  const tags = normalizeTagList(value)

  const commitInput = (rawValue = inputValue) => {
    const nextTags = tagInputPreview(tags, rawValue)
    onChange(nextTags)
    onInputChange('')
  }

  const removeTag = (tag) => {
    onChange(tags.filter((item) => item !== tag))
  }

  return (
    <div className="rounded-lg border border-surface-container-high bg-surface-container-highest px-2 py-2 focus-within:border-primary">
      <div className="flex min-h-8 flex-wrap items-center gap-1.5">
        {tags.map((tag) => (
          <span key={tag} className="inline-flex max-w-full items-center gap-1 rounded-full bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
            <span className="truncate">{tag}</span>
            <button
              type="button"
              onClick={() => removeTag(tag)}
              disabled={disabled}
              aria-label={`移除标签 ${tag}`}
              className="inline-flex h-4 w-4 items-center justify-center rounded-full text-primary hover:bg-primary/10 disabled:opacity-50"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[14px]">close</span>
            </button>
          </span>
        ))}
        <input
          type="text"
          value={inputValue}
          disabled={disabled || tags.length >= 20}
          autoFocus={autoFocus}
          onChange={(event) => {
            const nextValue = event.target.value
            if (/[,，;；\n\r\t]/.test(nextValue)) {
              commitInput(nextValue)
            } else {
              onInputChange(nextValue)
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              commitInput()
              return
            }
            if (event.key === 'Backspace' && !inputValue && tags.length) {
              event.preventDefault()
              onChange(tags.slice(0, -1))
            }
          }}
          onBlur={() => {
            if (String(inputValue || '').trim()) commitInput()
          }}
          onPaste={(event) => {
            const text = event.clipboardData?.getData('text') || ''
            if (!/[,，;；\n\r\t]/.test(text)) return
            event.preventDefault()
            commitInput(text)
          }}
          placeholder={tags.length ? '' : placeholder}
          className="h-7 min-w-[12rem] flex-1 bg-transparent px-1 text-sm text-on-surface outline-none placeholder:text-outline disabled:cursor-not-allowed"
        />
      </div>
    </div>
  )
}

function TagFilterDropdown({
  options,
  selectedTags,
  searchValue,
  onSearchChange,
  onToggleTag,
  onClear,
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)
  const selected = normalizeTagList(selectedTags)
  const selectedSet = useMemo(() => new Set(selected.map((tag) => tag.toLocaleLowerCase())), [selected])
  const visibleOptions = useMemo(() => {
    const keyword = String(searchValue || '').trim().toLocaleLowerCase()
    if (!keyword) return options
    return options.filter((tag) => tag.toLocaleLowerCase().includes(keyword))
  }, [options, searchValue])
  const buttonLabel = selected.length
    ? `标签/tag ${selected.length}`
    : '标签/tag'
  const selectedTitle = selected.length ? selected.join('，') : '标签/tag'

  useEffect(() => {
    if (!open) return undefined
    const handlePointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [open])

  return (
    <div ref={containerRef} className="relative min-w-0">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={selectedTitle}
        onClick={() => setOpen((value) => !value)}
        className="flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-transparent bg-surface-container-highest px-3 text-left text-xs text-on-surface-variant hover:bg-surface-container-high"
      >
        <span className="min-w-0 truncate">
          {selected.length ? selected.join('，') : buttonLabel}
        </span>
        <span className="material-symbols-outlined shrink-0 text-[18px]">
          {open ? 'expand_less' : 'expand_more'}
        </span>
      </button>

      {open && (
        <div
          className="absolute left-0 top-[calc(100%+0.35rem)] z-40 w-full min-w-[18rem] rounded-lg border border-outline-variant bg-surface-container-low p-2"
          style={{ boxShadow: '0 12px 28px -16px rgba(0,62,111,0.32)' }}
        >
          <input
            value={searchValue}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="检索标签/tag"
            className="h-8 w-full rounded-lg border border-transparent bg-surface-container-highest px-3 text-xs text-on-surface"
          />
          <div className="mt-2 max-h-56 overflow-y-auto pr-1" role="listbox" aria-label="标签/tag 多选">
            {visibleOptions.length ? (
              visibleOptions.map((tag) => {
                const checked = selectedSet.has(tag.toLocaleLowerCase())
                return (
                  <label
                    key={tag}
                    className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-on-surface-variant hover:bg-surface-container-low"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleTag(tag)}
                      className="h-3.5 w-3.5 accent-primary"
                    />
                    <span className="min-w-0 flex-1 truncate" title={tag}>{tag}</span>
                  </label>
                )
              })
            ) : (
              <div className="px-2 py-5 text-center text-xs text-outline">无匹配标签</div>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between border-t border-surface-container-high pt-2">
            <span className="text-[11px] text-outline">已选 {selected.length}</span>
            <button
              type="button"
              onClick={onClear}
              disabled={!selected.length}
              className="rounded-lg px-2 py-1 text-xs font-semibold text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-45"
            >
              清空标签
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function TreeNode({
  node,
  selectedPath,
  selectedFileId,
  onSelect,
  onFileSelect,
  onFileDownload,
  onRenameFile,
  onDeleteFile,
  onUpdateBusinessMaterialKind,
  onEditTags,
  onSplitFile,
  onDeleteFolder,
  onRenameFolder,
  onMoveDrop,
  dragTargetPath,
  setDragTargetPath,
  level = 0,
  collapsedMap,
  onToggle,
  filesByFolderPath,
  forceExpanded = false,
}) {
  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  const directFileCount = Number(node.directFileCount || 0)
  const canExpand = hasChildren || directFileCount > 0
  const collapsed = canExpand && !forceExpanded ? Boolean(collapsedMap[node.path]) : false
  const expanded = canExpand && !collapsed
  const selected = selectedPath === node.path
  const indent = 12 + level * 16
  const fileIndent = 34 + (level + 1) * 16
  const directFiles = filesByFolderPath?.get(normalizePath(node.path)) || []
  const displayFileCount = directFiles.length || directFileCount
  const normalizedNodePath = normalizePath(node.path)
  const canDragFolder = !isProtectedDeleteFolderPath(normalizedNodePath)
  const canDeleteThisFolder = Boolean(normalizedNodePath) && !isProtectedDeleteFolderPath(normalizedNodePath)
  // 商务标后端对删除保护目录同样禁止重命名（根目录、默认档位与自动预置目录）
  const canRenameThisFolder = canDeleteThisFolder
  const isDropTarget = dragTargetPath === normalizedNodePath
  const hasBranchContent = directFiles.length > 0 || hasChildren
  const dragExpandTimerRef = useRef(null)
  const rowTitle = !canExpand
    ? '点击选择目录'
    : forceExpanded
      ? '筛选模式下目录保持展开，点击选择目录'
      : collapsed
        ? '点击展开并选择目录'
        : selected
          ? '点击收起目录'
          : '点击选择目录'
  const toggleLabel = forceExpanded
    ? `筛选模式下保持展开，选择目录 ${node.name}`
    : expanded
      ? `收起目录 ${node.name}`
      : `展开目录 ${node.name}`

  useEffect(() => () => {
    if (dragExpandTimerRef.current) {
      window.clearTimeout(dragExpandTimerRef.current)
    }
  }, [])

  const clearDragExpandTimer = () => {
    if (!dragExpandTimerRef.current) return
    window.clearTimeout(dragExpandTimerRef.current)
    dragExpandTimerRef.current = null
  }

  const toggleFolder = (nextValue) => {
    if (!canExpand || forceExpanded) return
    onToggle(node.path, nextValue)
  }

  const handleFolderActivate = () => {
    onSelect(node.path)
    if (!canExpand || forceExpanded) return
    if (collapsed) {
      onToggle(node.path, false)
      return
    }
    if (selected) {
      onToggle(node.path, true)
    }
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        data-folder-path={normalizedNodePath}
        aria-expanded={canExpand ? expanded : undefined}
        aria-selected={selected}
        title={rowTitle}
        draggable={canDragFolder}
        onDragStart={(event) => {
          clearDragExpandTimer()
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
          if (canExpand && collapsed && !forceExpanded && !dragExpandTimerRef.current) {
            dragExpandTimerRef.current = window.setTimeout(() => {
              onToggle(node.path, false)
              dragExpandTimerRef.current = null
            }, 420)
          }
        }}
        onDragLeave={() => {
          clearDragExpandTimer()
          setDragTargetPath((current) => (current === normalizedNodePath ? '' : current))
        }}
        onDrop={(event) => {
          event.preventDefault()
          clearDragExpandTimer()
          setDragTargetPath('')
          onMoveDrop(event, normalizedNodePath)
        }}
        onClick={handleFolderActivate}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            handleFolderActivate()
            return
          }
          if (event.key === 'ArrowRight' && canExpand) {
            event.preventDefault()
            onSelect(node.path)
            toggleFolder(false)
          }
          if (event.key === 'ArrowLeft' && canExpand) {
            event.preventDefault()
            onSelect(node.path)
            toggleFolder(true)
          }
        }}
        style={{ paddingLeft: `${indent}px` }}
        className={`group w-full cursor-pointer text-left rounded-lg py-2 pr-2 text-sm transition-[background-color,color,box-shadow] duration-150 ease-out flex items-center justify-between gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/35 ${
          isDropTarget
            ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
            :
          selected
            ? 'bg-primary/10 text-primary font-semibold shadow-[inset_3px_0_0_rgba(0,113,206,0.72)]'
            : 'text-on-surface-variant hover:bg-surface-container-low'
        }`}
      >
        <span className="grid min-w-0 flex-1 grid-cols-[1.25rem_1.25rem_minmax(0,1fr)] items-center gap-1.5">
          {canExpand ? (
            <button
              type="button"
              title={toggleLabel}
              aria-label={toggleLabel}
              aria-expanded={expanded}
              onClick={(event) => {
                event.stopPropagation()
                onSelect(node.path)
                toggleFolder()
              }}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline transition-[background-color,color] duration-150 hover:bg-primary/10 hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/40"
            >
              <span
                aria-hidden="true"
                className={`material-symbols-outlined text-[18px] transition-transform duration-200 ease-out ${expanded ? 'rotate-90' : 'rotate-0'}`}
              >
                chevron_right
              </span>
            </button>
          ) : (
            <span className="h-5 w-5" />
          )}
          <span className="flex h-5 w-5 items-center justify-center text-primary">
            <span aria-hidden="true" className="material-symbols-outlined text-[17px] leading-none">
              {expanded ? 'folder_open' : 'folder'}
            </span>
          </span>
          <span className="truncate">{node.name}</span>
        </span>
        <span className="relative flex w-[4.25rem] shrink-0 items-center justify-end">
          <span
            className={`text-xs text-outline transition-opacity duration-150 ${canDeleteThisFolder || canRenameThisFolder ? 'group-hover:opacity-0 group-focus-within:opacity-0' : ''}`}
            title={displayFileCount ? `当前显示 ${displayFileCount} 个，目录总计 ${node.fileCount || 0} 个` : '空目录'}
          >
            {displayFileCount ? `${displayFileCount}/${node.fileCount || displayFileCount}` : '-'}
          </span>
          {canRenameThisFolder && (
            <button
              type="button"
              title="重命名文件夹"
              aria-label={`重命名文件夹 ${node.name}`}
              onClick={(event) => {
                event.stopPropagation()
                onRenameFolder?.(normalizedNodePath)
              }}
              className={`absolute ${canDeleteThisFolder ? 'right-6' : 'right-0'} top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-outline opacity-0 transition-opacity hover:bg-surface-container-high hover:text-primary group-hover:opacity-100 focus:opacity-100`}
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[16px]">drive_file_rename_outline</span>
            </button>
          )}
          {canDeleteThisFolder && (
            <button
              type="button"
              title="删除此文件夹"
              aria-label={`删除文件夹 ${node.name}`}
              onClick={(event) => {
                event.stopPropagation()
                onDeleteFolder(normalizedNodePath)
              }}
              className="absolute right-0 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-outline opacity-0 transition-opacity hover:bg-error-container/40 hover:text-error group-hover:opacity-100 focus:opacity-100"
            >
              <span aria-hidden="true" className="material-symbols-outlined text-[16px]">delete</span>
            </button>
          )}
        </span>
      </div>
      {hasBranchContent && (
        <div
          data-tree-branch={normalizedNodePath}
          aria-hidden={!expanded}
          inert={!expanded ? true : undefined}
          style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
          className={`grid transition-[grid-template-rows,opacity,transform] duration-200 ease-out ${
            expanded ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1 opacity-0'
          }`}
        >
          <div className="min-h-0 overflow-hidden">
            {directFiles.length > 0 && (
              <div className="mt-0.5 space-y-0.5">
                {directFiles.map((item) => {
                  const fileSelected = selectedFileId === item.id
                  const previewable = canPreviewCleaned(item)
                  const canSplit = item.bidType === '商务标' && extOf(item.name) === 'docx'
                  const itemTags = normalizeTagList(item.tags)
                  return (
                    <div
                      key={item.id}
                      role="button"
                      tabIndex={0}
                      data-file-id={item.id}
                      data-file-folder-path={normalizePath(item.folderPath || '')}
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
                      title={previewable ? `${item.name || ''}，悬停可预览或下载` : cleanedPreviewBlockedMessage(item)}
                      style={{
                        paddingLeft: `${fileIndent}px`,
                      }}
                      className={`group flex w-full items-center gap-2 rounded-lg py-1.5 pr-2 text-left text-sm transition-[background-color,color] duration-150 ease-out ${
                        fileSelected
                          ? 'bg-secondary-container text-on-secondary-container'
                          : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'
                      }`}
                    >
                      <span className={`material-symbols-outlined shrink-0 text-[17px] ${previewable ? 'text-secondary' : 'text-outline'}`}>
                        {previewable ? 'description' : 'draft'}
                      </span>
                      <span className="min-w-0 flex-1 basis-32 truncate">{item.name || '-'}</span>
                      {!!itemTags.length && (
                        <span
                          className="hidden min-w-0 max-w-[10rem] shrink items-center gap-1 overflow-hidden sm:inline-flex"
                          title={itemTags.join('，')}
                        >
                          {itemTags.slice(0, 3).map((tag) => (
                            <span key={tag} className="max-w-[4.5rem] truncate rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                              {tag}
                            </span>
                          ))}
                          {itemTags.length > 3 && (
                            <span className="rounded-full bg-surface-container-high px-1.5 py-0.5 text-[10px] font-medium text-on-surface-variant">
                              +{itemTags.length - 3}
                            </span>
                          )}
                        </span>
                      )}
                      <span className="flex min-w-[8rem] shrink-0 items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                        {previewable && (
                          <button
                            type="button"
                            title="OnlyOffice 预览"
                            aria-label={`OnlyOffice 预览 ${item.name || item.id}`}
                            onClick={(event) => {
                              event.stopPropagation()
                              onFileSelect?.(item)
                            }}
                            className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-primary/10 hover:text-primary"
                          >
                            <span aria-hidden="true" className="material-symbols-outlined text-[15px]">visibility</span>
                          </button>
                        )}
                        <button
                          type="button"
                          title="下载原件"
                          aria-label={`下载原件 ${item.name || item.id}`}
                          onClick={(event) => {
                            event.stopPropagation()
                            onFileDownload?.(item)
                          }}
                          className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-primary/10 hover:text-primary"
                        >
                          <span aria-hidden="true" className="material-symbols-outlined text-[15px]">download</span>
                        </button>
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
                        {item.bidType === '商务标' && (
                          <button
                            type="button"
                            title="编辑标签"
                            aria-label={`编辑标签 ${item.name || item.id}`}
                            onClick={(event) => {
                              event.stopPropagation()
                              onEditTags?.(item)
                            }}
                            className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-primary/10 hover:text-primary"
                          >
                            <span aria-hidden="true" className="material-symbols-outlined text-[15px]">label</span>
                          </button>
                        )}
                        {canSplit && (
                          <button
                            type="button"
                            title="切分商务素材"
                            aria-label={`切分商务素材 ${item.name || item.id}`}
                            onClick={(event) => {
                              event.stopPropagation()
                              onSplitFile?.(item)
                            }}
                            className="flex h-6 w-6 items-center justify-center rounded text-outline hover:bg-primary/10 hover:text-primary"
                          >
                            <span className="material-symbols-outlined text-[15px]">call_split</span>
                          </button>
                        )}
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
            {hasChildren && (
              <div className="mt-0.5">
                {node.children.map((child) => (
                  <TreeNode
                    key={child.id}
                    node={child}
                    selectedPath={selectedPath}
                    selectedFileId={selectedFileId}
                    onSelect={onSelect}
                    onFileSelect={onFileSelect}
                    onFileDownload={onFileDownload}
                    onRenameFile={onRenameFile}
                    onDeleteFile={onDeleteFile}
                    onUpdateBusinessMaterialKind={onUpdateBusinessMaterialKind}
                    onEditTags={onEditTags}
                    onSplitFile={onSplitFile}
                    onDeleteFolder={onDeleteFolder}
                    onRenameFolder={onRenameFolder}
                    onMoveDrop={onMoveDrop}
                    dragTargetPath={dragTargetPath}
                    setDragTargetPath={setDragTargetPath}
                    level={level + 1}
                    collapsedMap={collapsedMap}
                    onToggle={onToggle}
                    filesByFolderPath={filesByFolderPath}
                    forceExpanded={forceExpanded}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function BusinessMaterialDB({ showToast = () => {} }) {
  const activeBidType = BUSINESS_BID_TYPE
  const uploadBidType = BUSINESS_BID_TYPE
  const materialsBasePath = workspaceRoute(BUSINESS_WORKSPACE, '/materials')
  const uploadPickerRef = useRef(null)
  const libraryLoadedRef = useRef(false)
  const [tree, setTree] = useState([])
  const [collapsedMap, setCollapsedMap] = useState({})
  const [dragTargetPath, setDragTargetPath] = useState('')
  const [filesPayload, setFilesPayload] = useState({ items: [], total: 0, page: 1, pageSize: 20 })
  const [parseStatus, setParseStatus] = useState(null)
  const [selectedFolderPath, setSelectedFolderPath] = useState('')
  const [filters, setFilters] = useState({
    title: '',
    tags: [],
  })
  const [tagFilterSearch, setTagFilterSearch] = useState('')
  const [loading, setLoading] = useState(true)
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
  const [uploadTags, setUploadTags] = useState([])
  const [uploadTagsInput, setUploadTagsInput] = useState('')
  const [uploadFiles, setUploadFiles] = useState([])
  const [uploadAfterSplit, setUploadAfterSplit] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [previewItem, setPreviewItem] = useState(null)
  const [previewSession, setPreviewSession] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [onlyofficePreviewError, setOnlyofficePreviewError] = useState('')
  const [previewFullscreen, setPreviewFullscreen] = useState(false)
  const [tagEditorItem, setTagEditorItem] = useState(null)
  const [tagEditorTags, setTagEditorTags] = useState([])
  const [tagEditorValue, setTagEditorValue] = useState('')
  const [tagEditorSaving, setTagEditorSaving] = useState(false)
  const [tagEditorError, setTagEditorError] = useState('')
  const [splitModalOpen, setSplitModalOpen] = useState(false)
  const [splitLoading, setSplitLoading] = useState(false)
  const [splitConfirming, setSplitConfirming] = useState(false)
  const [splitError, setSplitError] = useState('')
  const [splitPlan, setSplitPlan] = useState(null)
  const [splitSourceItem, setSplitSourceItem] = useState(null)

  const [conflictContext, setConflictContext] = useState(null)

  const canManageCurrentFolder = Boolean(selectedFolderPath)
  const canCreateFolder = Boolean(selectedFolderPath) && canManageCurrentFolder
  const canDeleteFolder = Boolean(selectedFolderPath) && !isProtectedDeleteFolderPath(selectedFolderPath)

  const fileItems = useMemo(() => filesPayload?.items || [], [filesPayload?.items])
  const filesByFolderPath = useMemo(() => groupFilesByFolderPath(fileItems), [fileItems])
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
  const selectedFilterTags = useMemo(() => normalizeTagList(filters.tags || []), [filters.tags])
  const activeFilterCount = [
    filters.title,
    ...selectedFilterTags,
  ].filter((value) => String(value || '').trim()).length
  const tagOptions = useMemo(() => normalizeTagOptions(filesPayload?.tagOptions || []), [filesPayload?.tagOptions])
  const hasActiveFilters = activeFilterCount > 0
  const displayTree = useMemo(
    () => (hasActiveFilters ? filterTreeByMatchedFiles(tree, filesByFolderPath) : tree),
    [filesByFolderPath, hasActiveFilters, tree],
  )
  const loadLibrary = useCallback(async (options = {}) => {
    const silent = Boolean(options.silent || libraryLoadedRef.current)
    if (!silent) setLoading(true)
    setError('')
    try {
      const treeResponse = await businessMaterialsAPI.raw.tree()
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
      const payload = await businessMaterialsAPI.raw.files({
        folderPath: '',
        recursive: true,
        title: filters.title.trim(),
        bidType: activeBidType,
        tag: selectedFilterTags,
        page: 1,
        pageSize: filePageSize,
      })
      setFilesPayload(payload || { items: [], total: 0, page: 1, pageSize: filePageSize })
      setParseStatus(null)
    } catch (e) {
      setError(safeMessage(e, '原始材料库加载失败，请稍后重试。'))
    } finally {
      libraryLoadedRef.current = true
      if (!silent) setLoading(false)
    }
  }, [activeBidType, filters.title, selectedFilterTags, selectedFolderPath])

  const loadUploadIdentityOptions = useCallback(async () => {
    setLoadingIdentityOptions(true)
    try {
      const identityPayload = await businessMaterialsAPI.identityOptions({ bidType: activeBidType }) || {}
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

  useEffect(() => {
    if (!previewFullscreen) return undefined

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setPreviewFullscreen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [previewFullscreen])

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

  const openUploadModal = (options = {}) => {
    const targetPath = options.targetPath || selectedFolderPath
    const rootTier = materialTierFromRootPath(targetPath)
    const mode = options.mode || (rootTier ? 'tier' : 'tier')
    const nextTier = options.materialTier || rootTier || 'standard'
    setShowUploadModal(true)
    setUploadKind(options.kind || 'files')
    setUploadMode(mode)
    setUploadPath(targetPath)
    setUploadMaterialTier(nextTier)
    setUploadCustomerId(options.customerId || '')
    setUploadCustomerName(options.customerName || '')
    setUploadProjectId(options.projectId || '')
    setUploadProjectCode(options.projectCode || '')
    setUploadProjectName(options.projectName || '')
    setUploadTags([])
    setUploadTagsInput('')
    setUploadFiles([])
    setUploadAfterSplit(false)
    setUploadError('')
  }

  const closeUploadModal = () => {
    setShowUploadModal(false)
    setUploadTags([])
    setUploadTagsInput('')
    setUploadFiles([])
    setUploadError('')
    if (uploadPickerRef.current) {
      uploadPickerRef.current.value = ''
    }
  }

  useEffect(() => {
    if (!showUploadModal && !conflictContext && !tagEditorItem) return undefined
    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return
      if (tagEditorItem && !tagEditorSaving) {
        setTagEditorItem(null)
        setTagEditorTags([])
        setTagEditorValue('')
        setTagEditorError('')
        return
      }
      if (conflictContext) {
        setConflictContext(null)
        return
      }
      if (showUploadModal && !uploading) closeUploadModal()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [conflictContext, showUploadModal, tagEditorItem, tagEditorSaving, uploading])

  const onUploadFilesChanged = (event) => {
    const files = Array.from(event.target.files || [])
    if (!files.length) return
    const oversized = []
    const accepted = []
    for (const file of files) {
      const name = file.name
      if (/^\._/.test(name) || name === '.DS_Store') continue
      if (!ALLOWED_EXTENSIONS.has(extOf(name))) continue
      if (Number(file.size || 0) > MAX_FILE_SIZE) {
        oversized.push(name)
        continue
      }
      accepted.push(file)
    }
    setUploadError(oversized.length ? `以下文件超过 30GB 上限：${oversized.join('、')}` : '')
    if (!accepted.length) {
      event.target.value = ''
      return
    }
    setUploadFiles((prev) => {
      const next = [...prev]
      const signatures = new Set(
        prev.map((file) => `${file.webkitRelativePath || file.name}::${file.size}::${file.lastModified}`)
      )
      accepted.forEach((file) => {
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
      payload.append('businessMaterialKind', uploadBidType === '商务标' ? 'other' : '')
      tagInputPreview(uploadTags, uploadTagsInput).forEach((tag) => payload.append('tags', tag))
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

      const result = await businessMaterialsAPI.raw.upload(payload)
      showToast(result?.message || `上传成功：${uploadFiles.length} 个文件`)
      setConflictContext(null)
      closeUploadModal()
      await loadLibrary({ silent: true })
      const uploadedDocx = (result?.items || []).find((item) => item?.bidType === '商务标' && extOf(item?.name) === 'docx')
      if (uploadAfterSplit && uploadedDocx) {
        showToast('上传完成，正在打开商务素材切分审核。')
        await openBusinessSplitModal(uploadedDocx)
      } else if (uploadAfterSplit) {
        showToast('上传完成，但未找到可切分的商务 docx 文件。', 'warning')
      }
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
      const result = await businessMaterialsAPI.raw.createFolder({
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
      const result = await businessMaterialsAPI.raw.deleteFolder({ path: targetPath })
      showToast(result?.message || '文件夹删除成功')
      setSelectedFolderPath(parentPath(targetPath))
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '删除文件夹失败'), 'error')
    }
  }

  const handleRenameFolder = async (path = selectedFolderPath) => {
    const targetPath = normalizePath(path)
    if (!targetPath || isProtectedDeleteFolderPath(targetPath)) {
      showToast('基础素材目录不允许重命名。', 'error')
      return
    }
    const currentName = targetPath.split('/').pop()
    const nextName = window.prompt('请输入新的文件夹名称', currentName)
    if (!nextName || !nextName.trim() || nextName.trim() === currentName) return
    try {
      const result = await businessMaterialsAPI.raw.renameFolder({ path: targetPath, newName: nextName.trim() })
      showToast(result?.message || '文件夹重命名成功')
      const renamedPath = normalizePath(result?.folderPath || '')
      if (renamedPath && (selectedFolderPath === targetPath || selectedFolderPath.startsWith(`${targetPath}/`))) {
        setSelectedFolderPath(`${renamedPath}${selectedFolderPath.slice(targetPath.length)}`)
      }
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '文件夹重命名失败'), 'error')
    }
  }

  const handleRenameFile = async (item) => {
    if (!item?.id) return
    const currentName = String(item.name || '').trim()
    const nextName = window.prompt('请输入新的文件名', currentName)
    if (!nextName || !nextName.trim() || nextName.trim() === currentName) return
    try {
      const result = await businessMaterialsAPI.raw.updateFile(item.id, {
        name: nextName.trim(),
        businessMaterialKind: item.businessMaterialKind || '',
      })
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

  const updateBusinessMaterialKind = async (item) => {
    if (!item?.id || item.bidType !== '商务标') return
    const current = BUSINESS_MATERIAL_KIND_OPTIONS.some((option) => option.value === item.businessMaterialKind)
      ? item.businessMaterialKind
      : 'other'
    const nextKind = current === 'other' ? 'fixed' : current === 'fixed' ? 'ai_fill' : 'other'
    try {
      const result = await businessMaterialsAPI.raw.updateFile(item.id, {
        businessMaterialKind: nextKind,
      })
      showToast(result?.message || `已标记为${businessMaterialKindMeta(nextKind).label}`)
      if (previewItem?.id === item.id) {
        setPreviewItem((prev) => ({
          ...(prev || {}),
          businessMaterialKind: nextKind,
          businessMaterialKindLabel: businessMaterialKindMeta(nextKind).label,
        }))
      }
      await loadLibrary({ silent: true })
    } catch (e) {
      showToast(safeMessage(e, '素材类型更新失败'), 'error')
    }
  }

  const openTagEditor = (item) => {
    if (!item?.id || item.bidType !== '商务标') return
    const currentTags = normalizeTagList(item.tags)
    setTagEditorItem(item)
    setTagEditorTags(currentTags)
    setTagEditorValue('')
    setTagEditorError('')
  }

  const closeTagEditor = () => {
    setTagEditorItem(null)
    setTagEditorTags([])
    setTagEditorValue('')
    setTagEditorError('')
  }

  const saveMaterialTags = async () => {
    if (!tagEditorItem?.id) return
    const nextTags = tagInputPreview(tagEditorTags, tagEditorValue)
    setTagEditorSaving(true)
    setTagEditorError('')
    try {
      const result = await businessMaterialsAPI.raw.updateFile(tagEditorItem.id, {
        businessMaterialKind: tagEditorItem.businessMaterialKind || '',
        tags: nextTags,
      })
      showToast(result?.message || '素材标签已更新')
      if (previewItem?.id === tagEditorItem.id) {
        setPreviewItem((prev) => ({ ...(prev || {}), tags: nextTags }))
      }
      closeTagEditor()
      await loadLibrary({ silent: true })
    } catch (e) {
      const message = safeMessage(e, '素材标签更新失败')
      setTagEditorError(message)
      showToast(message, 'error')
    } finally {
      setTagEditorSaving(false)
    }
  }

  const handleDeleteFile = async (item) => {
    if (!item?.id) return
    const ok = window.confirm(`确认删除文件：${item.name || item.id} ？\n\n原始文件及其清洗稿也会一起删除。`)
    if (!ok) return
    try {
      const result = await businessMaterialsAPI.raw.deleteFile(item.id)
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

  const loadBusinessSplitPlan = async (item, { aiMode = 'auto' } = {}) => {
    const payload = await businessMaterialsAPI.raw.previewBusinessSplit(item.id, { targetPath: item.folderPath || selectedFolderPath, aiMode })
    setSplitPlan({
      ...payload,
      fragments: (payload?.fragments || []).map((fragment) => ({
        ...fragment,
        selected: fragment.selected !== false,
        targetPath: fragment.suggestedPath || item.folderPath || selectedFolderPath,
        fileName: fragment.suggestedFileName || `${fragment.title || '商务素材片段'}.docx`,
      })),
    })
  }

  const openBusinessSplitModal = async (item) => {
    if (!item?.id) return
    if (activeBidType !== '商务标' || item.bidType !== '商务标') {
      showToast('素材切分入口当前仅支持商务标素材。', 'error')
      return
    }
    if (extOf(item.name) !== 'docx') {
      showToast('第一版素材切分仅支持 Word docx 文件。', 'error')
      return
    }
    setSplitSourceItem(item)
    setSplitModalOpen(true)
    setSplitLoading(true)
    setSplitError('')
    setSplitPlan(null)
    try {
      await loadBusinessSplitPlan(item, { aiMode: 'auto' })
    } catch (e) {
      setSplitError(safeMessage(e, '生成切分建议失败。'))
    } finally {
      setSplitLoading(false)
    }
  }

  const rerunBusinessSplitWithAi = async () => {
    if (!splitSourceItem?.id) return
    setSplitLoading(true)
    setSplitError('')
    try {
      await loadBusinessSplitPlan(splitSourceItem, { aiMode: 'force' })
      showToast('AI 增强识别完成，请审核切分片段。')
    } catch (e) {
      setSplitError(safeMessage(e, 'AI 增强识别失败。'))
    } finally {
      setSplitLoading(false)
    }
  }

  const closeBusinessSplitModal = () => {
    setSplitModalOpen(false)
    setSplitLoading(false)
    setSplitConfirming(false)
    setSplitError('')
    setSplitPlan(null)
    setSplitSourceItem(null)
  }

  const updateSplitFragment = (fragmentId, patch) => {
    setSplitPlan((current) => ({
      ...(current || {}),
      fragments: (current?.fragments || []).map((fragment) => (
        fragment.id === fragmentId ? { ...fragment, ...patch } : fragment
      )),
    }))
  }

  const confirmBusinessSplit = async () => {
    const fragments = (splitPlan?.fragments || []).filter((fragment) => fragment.selected)
    if (!splitSourceItem?.id || !fragments.length) {
      setSplitError('请至少勾选一个切分片段。')
      return
    }
    setSplitConfirming(true)
    setSplitError('')
    try {
      const result = await businessMaterialsAPI.raw.confirmBusinessSplit(splitSourceItem.id, {
        fragments: fragments.map((fragment) => ({
          id: fragment.id,
          selected: true,
          title: fragment.title,
          fileName: fragment.fileName,
          targetPath: fragment.targetPath,
          materialType: fragment.materialType,
          sourceLocation: fragment.sourceLocation,
          suggestedPath: fragment.suggestedPath,
          suggestedFileName: fragment.suggestedFileName,
          contentPreview: fragment.contentPreview,
          confidence: fragment.confidence,
          riskTips: fragment.riskTips,
        })),
      })
      showToast(result?.message || `已生成 ${fragments.length} 个子素材`)
      closeBusinessSplitModal()
      await loadLibrary({ silent: true })
    } catch (e) {
      setSplitError(safeMessage(e, '确认切分入库失败。'))
    } finally {
      setSplitConfirming(false)
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
      const payload = await businessMaterialsAPI.raw.previewCleanedFile(item.id)
      setPreviewSession(payload)
    } catch (e) {
      setPreviewError(safeMessage(e, '清洗稿预览加载失败'))
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleDownloadFile = (item) => {
    if (!item?.id) return
    window.open(businessMaterialsAPI.raw.contentUrl(item.id), '_blank', 'noopener')
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
    if (!normalizedTarget) {
      showToast('请选择目标目录。', 'error')
      return
    }
    if (normalizedTarget !== activeBidType && !normalizedTarget.startsWith(`${activeBidType}/`)) {
      showToast('只能在当前素材库内移动。', 'error')
      return
    }

    const filePayload = parseDragPayload(event, 'application/x-raw-file')
    if (filePayload?.id) {
      const sourceFolder = normalizePath(filePayload.folderPath)
      if (sourceFolder === normalizedTarget) return
      try {
        const result = await businessMaterialsAPI.raw.moveFile({
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
    if (isProtectedDeleteFolderPath(sourcePath)) {
      showToast('基础目录不允许移动。', 'error')
      return
    }
    if (normalizedTarget.startsWith(`${sourcePath}/`)) {
      showToast('不能将目录移动到自身的子目录下。', 'error')
      return
    }

    try {
      const result = await businessMaterialsAPI.raw.moveFolder({
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

  const resolveConflict = async (action) => {
    if (conflictContext.type === 'upload') {
      await performUpload(action)
    } else if (conflictContext.type === 'move-file') {
      try {
        const result = await businessMaterialsAPI.raw.moveFile({
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

  const toggleFilterTag = (tag) => {
    setFilters((prev) => {
      const currentTags = normalizeTagList(prev.tags || [])
      const key = tag.toLocaleLowerCase()
      const exists = currentTags.some((item) => item.toLocaleLowerCase() === key)
      return {
        ...prev,
        tags: exists ? currentTags.filter((item) => item.toLocaleLowerCase() !== key) : [...currentTags, tag],
      }
    })
  }

  const clearFilterTags = () => {
    setFilters((prev) => ({ ...prev, tags: [] }))
  }

  const materialToolbar = (
    <div className="rounded-lg border border-outline-variant/45 bg-surface-container-lowest px-3 py-3">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="grid min-w-0 w-full grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] md:w-1/2 md:max-w-[36rem] xl:flex-none">
          <label>
            <span className="sr-only">文件标题</span>
            <input
              value={filters.title}
              onChange={(e) => updateFilter('title', e.target.value)}
              placeholder="文件标题"
              className="h-9 w-full rounded-lg border border-transparent bg-surface-container-highest px-3 text-xs"
            />
          </label>
          <TagFilterDropdown
            options={tagOptions}
            selectedTags={selectedFilterTags}
            searchValue={tagFilterSearch}
            onSearchChange={setTagFilterSearch}
            onToggleTag={toggleFilterTag}
            onClear={clearFilterTags}
          />
        </div>

        <div className="flex flex-wrap items-center justify-start gap-1.5 xl:justify-end" role="toolbar" aria-label="素材目录工具栏">
          <button type="button" onClick={() => setCollapseForAll(false)} className="rounded-lg bg-surface-container-high px-3 py-2 text-xs font-semibold text-on-surface ring-1 ring-inset ring-outline-variant/60 hover:bg-surface-dim">
            展开
          </button>
          <button type="button" onClick={() => setCollapseForAll(true)} className="rounded-lg bg-surface-container-high px-3 py-2 text-xs font-semibold text-on-surface ring-1 ring-inset ring-outline-variant/60 hover:bg-surface-dim">
            收起
          </button>
          <button type="button" onClick={handleCreateFolder} disabled={!canCreateFolder} className="rounded-lg bg-surface-container-high px-3 py-2 text-xs font-semibold text-on-surface ring-1 ring-inset ring-outline-variant/60 hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-45">
            新建文件夹
          </button>
          <button
            type="button"
            title={selectedFolderPath && isProtectedDeleteFolderPath(selectedFolderPath) ? '基础素材目录不可删除' : '删除文件夹'}
            onClick={handleDeleteFolder}
            disabled={!canDeleteFolder}
            className="rounded-lg bg-error-container/45 px-3 py-2 text-xs font-semibold text-error hover:bg-error-container disabled:cursor-not-allowed disabled:opacity-45"
          >
            删除文件夹
          </button>
          <button
            type="button"
            onClick={() => openUploadModal({ mode: 'path', targetPath: selectedFolderPath })}
            disabled={!canManageCurrentFolder || !selectedFolderPath}
            className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-on-primary hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-45"
          >
            上传
          </button>
        </div>
      </div>
    </div>
  )

  const previewContent = (
    <>
      {onlyofficePreviewError && (
        <div className="mb-3 rounded-lg border border-error/25 bg-error-container/20 px-3 py-2 text-xs text-error">
          {onlyofficePreviewError}
        </div>
      )}
      {previewLoading ? (
        <div className="flex min-h-[520px] flex-1 items-center justify-center rounded-lg border border-surface-container-high bg-surface-container-lowest px-6 text-center">
          <div>
            <span className="material-symbols-outlined text-3xl text-primary">hourglass_empty</span>
            <p className="mt-2 text-sm text-on-surface-variant">正在加载...</p>
          </div>
        </div>
      ) : hasPreviewSession ? (
        <OnlyOfficeEmbed
          session={previewSession?.onlyoffice}
          mode="view"
          className="h-full min-h-[520px] w-full flex-1 rounded-lg border border-surface-container-high bg-white"
          onReady={() => setOnlyofficePreviewError('')}
          onError={(message) => setOnlyofficePreviewError(message || 'OnlyOffice 清洗稿加载失败')}
        />
      ) : (
        <div className="flex min-h-[520px] flex-1 items-center justify-center rounded-lg border border-dashed border-surface-container-high bg-surface-container-lowest/45 px-6 text-center">
          <p className="max-w-xs text-sm text-on-surface-variant">
            {onlyofficePreviewError || previewError || cleanedPreviewBlockedMessage(previewItem)}
          </p>
        </div>
      )}
    </>
  )

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
    <div className="flex flex-col gap-3">
      <MaterialsViewSwitch
        active="raw"
        title="商务标素材库"
        subtitle={error || ''}
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

      {materialToolbar}

      <div className="grid min-h-[680px] grid-cols-1 gap-3 xl:min-h-[calc(100vh-12rem)] xl:grid-cols-[minmax(30rem,40rem)_minmax(0,1fr)]">
        {loading ? (
          <div className="col-span-full flex min-h-[680px] items-center justify-center rounded-lg border border-outline-variant/45 bg-surface-container-lowest xl:min-h-[calc(100vh-12rem)]">
            <PageLoading
              title="正在加载原始材料库..."
              description="正在同步目录树、权限和文件列表。"
              containerClassName="min-h-0"
            />
          </div>
        ) : (
          <>
        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest">
          <div className="flex min-h-[52px] items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-on-surface">素材目录</h3>
              <span className="rounded-lg bg-surface-container-high px-2 py-1 text-xs font-semibold text-on-surface-variant">
                {hasActiveFilters ? '筛选' : '已加载'} {fileItems.length}
              </span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <div className="min-h-full rounded-lg bg-white p-2">
              {displayTree.length > 0 ? (
                displayTree.map((node) => (
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
                    onFileDownload={handleDownloadFile}
                    onRenameFile={handleRenameFile}
                    onDeleteFile={handleDeleteFile}
                    onUpdateBusinessMaterialKind={updateBusinessMaterialKind}
                    onEditTags={openTagEditor}
                    onSplitFile={openBusinessSplitModal}
                    onDeleteFolder={handleDeleteFolder}
                    onRenameFolder={handleRenameFolder}
                    onMoveDrop={handleMoveDrop}
                    dragTargetPath={dragTargetPath}
                    setDragTargetPath={setDragTargetPath}
                    collapsedMap={collapsedMap}
                    onToggle={toggleNode}
                    filesByFolderPath={filesByFolderPath}
                    forceExpanded={hasActiveFilters}
                  />
                ))
              ) : (
                <div className="flex min-h-[10rem] items-center justify-center rounded-lg text-sm text-outline">
                  {hasActiveFilters ? '未找到匹配素材' : '暂无素材目录'}
                </div>
              )}
            </div>
          </div>
        </section>

        <section className={[
          previewFullscreen
            ? 'fixed inset-0 z-[160] flex min-h-0 flex-col bg-white p-3'
            : 'flex min-h-0 flex-col overflow-hidden rounded-lg border border-outline-variant/45 bg-surface-container-lowest',
        ].join(' ')}>
          <div className="flex min-h-[52px] items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-sm font-semibold text-on-surface">清洗稿预览</h3>
              {previewItem && (
                <span
                  title={previewTitle}
                  className="hidden max-w-[18rem] truncate rounded-lg bg-surface-container-high px-2.5 py-1 text-xs font-medium text-on-surface-variant sm:inline-block"
                >
                  {previewTitle}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className={`whitespace-nowrap rounded-lg px-2.5 py-1 text-xs font-semibold ${onlyofficePreviewError ? 'bg-error-container text-on-error-container' : hasPreviewSession ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                {previewModeLabel}
              </span>
              <button
                type="button"
                aria-label={previewFullscreen ? '退出全屏' : '全屏查看'}
                aria-pressed={previewFullscreen}
                title={previewFullscreen ? '退出全屏' : '全屏查看'}
                onClick={() => setPreviewFullscreen((value) => !value)}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-container-high text-on-surface-variant transition-colors hover:bg-surface-dim hover:text-on-surface"
              >
                <span className="material-symbols-outlined text-[20px]">
                  {previewFullscreen ? 'close_fullscreen' : 'open_in_full'}
                </span>
              </button>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col p-3">
            {previewContent}
          </div>
        </section>
          </>
        )}
      </div>

      {showUploadModal && (
        <div className="dialog-overlay fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-hidden p-3 sm:p-4">
          <div className="wizard-modal-surface w-full max-w-2xl h-[calc(100vh-1.5rem)] sm:h-[calc(100vh-2rem)] max-h-[calc(100vh-1.5rem)] sm:max-h-[calc(100vh-2rem)] bg-surface-container-lowest rounded-xl border border-surface-container-high flex flex-col overflow-hidden animate-float-in">
            <div className="px-5 sm:px-6 py-4 border-b border-surface-container-high flex items-center justify-between shrink-0">
              <h2 className="text-lg font-headline font-bold text-on-surface">上传{activeBidType}原始素材</h2>
              <button onClick={closeUploadModal} className="close-plain text-on-surface-variant hover:text-primary transition-colors" aria-label="关闭">
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-5 sm:p-6 space-y-4">
              <div className="max-w-sm">
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
                          className={`rounded-lg text-sm font-semibold transition-colors ${active ? 'bg-white text-primary shadow-[0_1px_2px_rgba(17,34,51,0.08)]' : 'text-on-surface-variant hover:bg-surface-container-high'}`}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                </div>
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

              {uploadBidType === '商务标' && (
                <div className="text-sm text-on-surface-variant block">
                  <span className="block mb-1">素材标签</span>
                  <TagInput
                    value={uploadTags}
                    inputValue={uploadTagsInput}
                    onChange={setUploadTags}
                    onInputChange={setUploadTagsInput}
                    placeholder="例如：资质，承诺函，商务附件"
                  />
                  <span className="mt-1 block text-xs text-outline">
                    支持中文逗号、中文分号、英文逗号、英文分号、换行或 Enter 拆分，最多 20 个。
                  </span>
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
                          className={`rounded-lg text-sm font-semibold transition-colors ${active ? 'bg-white text-primary shadow-[0_1px_2px_rgba(17,34,51,0.08)]' : 'text-on-surface-variant hover:bg-surface-container-high'}`}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                </div>
                {uploadBidType === '商务标' && (
                  <label className="rounded-lg bg-primary/5 px-3 py-2 text-sm text-on-surface-variant">
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={uploadAfterSplit}
                        onChange={(event) => setUploadAfterSplit(event.target.checked)}
                        className="h-4 w-4 accent-primary"
                      />
                      上传后打开切分审核
                    </span>
                    <span className="mt-1 block text-xs text-outline">
                      仅对商务标 docx 生效；原文件保留，审核后生成子素材。
                    </span>
                  </label>
                )}
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
                    <div key={`${item.webkitRelativePath || item.name}-${item.size}-${item.lastModified}`} className="flex items-center justify-between gap-2 py-1">
                      <span className="min-w-0 flex-1 truncate" title={item.webkitRelativePath || item.name}>{item.webkitRelativePath || item.name}</span>
                      <span className="shrink-0">{toSizeLabel(item.size)}</span>
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs text-outline">
                白名单：pdf/doc/docx/xls/xlsx/xlsm/png/jpg/jpeg/webp/bmp/tif/tiff；单文件 30GB。图片类素材仅保留原件，不触发自动清洗。其他格式及系统隐藏文件自动忽略。
              </p>

              {uploadError && (
                <div className="text-sm text-error bg-error-container/30 border border-error/30 rounded-lg px-3 py-2 whitespace-pre-line">
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
        <div className="dialog-overlay fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="wizard-modal-surface w-full max-w-md bg-surface-container-lowest rounded-xl border border-surface-container-high animate-float-in">
            <div className="px-6 py-4 border-b border-surface-container-high">
              <h3 className="text-lg font-semibold text-on-surface">发现命名冲突</h3>
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

      {tagEditorItem && (
        <div className="dialog-overlay fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="wizard-modal-surface w-full max-w-lg bg-surface-container-lowest rounded-xl border border-surface-container-high animate-float-in">
            <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-on-surface">编辑素材标签</h3>
                <p className="mt-1 truncate text-xs text-outline">{tagEditorItem.name || tagEditorItem.id}</p>
              </div>
              <button
                onClick={closeTagEditor}
                disabled={tagEditorSaving}
                className="close-plain text-on-surface-variant hover:text-primary transition-colors disabled:opacity-50"
                aria-label="关闭"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className="p-6 space-y-3">
              <div className="block text-sm text-on-surface-variant">
                <span className="block mb-1">标签</span>
                <TagInput
                  value={tagEditorTags}
                  inputValue={tagEditorValue}
                  onChange={(nextTags) => {
                    setTagEditorTags(nextTags)
                    setTagEditorError('')
                  }}
                  onInputChange={(nextValue) => {
                    setTagEditorValue(nextValue)
                    setTagEditorError('')
                  }}
                  disabled={tagEditorSaving}
                  autoFocus
                  placeholder="资质，承诺函，商务附件"
                />
                <span className="mt-1 block text-xs text-outline">
                  支持粘贴整串标签，系统会按中英文逗号和分号自动拆分。
                </span>
              </div>
              {tagEditorError && (
                <div className="rounded-lg border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
                  {tagEditorError}
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-surface-container-high bg-surface-container-low flex justify-end gap-2 rounded-b-xl">
              <button
                onClick={closeTagEditor}
                disabled={tagEditorSaving}
                className="px-4 py-2 text-sm rounded-lg text-on-surface-variant hover:bg-surface-container-high disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={saveMaterialTags}
                disabled={tagEditorSaving}
                className="px-4 py-2 text-sm rounded-lg bg-primary text-on-primary hover:bg-primary-container disabled:opacity-50"
              >
                {tagEditorSaving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {splitModalOpen && (
        <div className="dialog-overlay fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-hidden p-3 sm:p-4">
          <div className="wizard-modal-surface w-full max-w-5xl h-[calc(100vh-1.5rem)] sm:h-[calc(100vh-2rem)] bg-surface-container-lowest rounded-xl border border-surface-container-high flex flex-col overflow-hidden animate-float-in">
            <div className="px-5 sm:px-6 py-4 border-b border-surface-container-high flex items-center justify-between shrink-0">
              <div className="min-w-0">
                <h2 className="text-lg font-headline font-bold text-on-surface">商务素材切分审核</h2>
                <p className="mt-1 truncate text-xs text-outline">
                  母文件：{splitSourceItem?.name || '-'}；确认后将生成子素材并进入商务标原始素材库。
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={rerunBusinessSplitWithAi}
                  disabled={splitLoading || splitConfirming}
                  className="rounded-lg bg-primary/10 px-3 py-2 text-xs font-semibold text-primary hover:bg-primary/15 disabled:opacity-50"
                >
                  {splitLoading ? '识别中...' : 'AI增强识别'}
                </button>
                <button onClick={closeBusinessSplitModal} className="close-plain text-on-surface-variant hover:text-primary transition-colors" aria-label="关闭">
                  <span className="material-symbols-outlined">close</span>
                </button>
              </div>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-5 sm:p-6">
              {splitLoading ? (
                <div className="flex min-h-[360px] items-center justify-center rounded-lg border border-dashed border-surface-container-high text-sm text-on-surface-variant">
                  正在生成切分建议...
                </div>
              ) : splitError && !splitPlan ? (
                <div className="rounded-lg border border-error/30 bg-error-container/20 px-4 py-3 text-sm text-error">
                  {splitError}
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-xs leading-5 text-on-surface-variant">
                    系统会先用规则和本地语义切分；如果文件像订单/业绩集合且切分数量偏少，会自动调用 AI 增强。若结果仍少，可点击右上角“AI增强识别”强制复核。
                    <span className="ml-2 font-semibold">当前策略：{splitPlan?.diagnostics?.strategy || '-'}</span>
                    {splitPlan?.diagnostics?.aiAttempted ? <span className="ml-2">AI 已尝试</span> : null}
                    {splitPlan?.diagnostics?.aiError ? <span className="ml-2 text-error">AI错误：{splitPlan.diagnostics.aiError}</span> : null}
                  </div>

                  {splitError && (
                    <div className="rounded-lg border border-error/30 bg-error-container/20 px-4 py-3 text-sm text-error">
                      {splitError}
                    </div>
                  )}

                  {(splitPlan?.fragments || []).length ? (
                    <div className="space-y-3">
                      {(splitPlan?.fragments || []).map((fragment, index) => (
                        <div key={fragment.id || index} className={`rounded-lg border p-4 ${fragment.selected ? 'border-primary/30 bg-white' : 'border-surface-container-high bg-surface-container-low'}`}>
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <label className="flex min-w-0 flex-1 items-start gap-2">
                              <input
                                type="checkbox"
                                checked={Boolean(fragment.selected)}
                                onChange={(event) => updateSplitFragment(fragment.id, { selected: event.target.checked })}
                                className="mt-1 h-4 w-4 accent-primary"
                              />
                              <span className="min-w-0">
                                <span className="block text-sm font-semibold text-on-surface">{fragment.title || `片段 ${index + 1}`}</span>
                                <span className="mt-1 block text-xs text-outline">
                                  {fragment.materialType || '商务素材片段'} · 置信度 {Math.round(Number(fragment.confidence || 0) * 100)}%
                                </span>
                              </span>
                            </label>
                            <span className="max-w-[8rem] shrink-0 truncate rounded-full bg-surface-container-high px-2 py-1 text-[11px] font-semibold text-on-surface-variant" title={fragment.id}>
                              {fragment.id}
                            </span>
                          </div>

                          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
                            <label className="text-xs text-on-surface-variant">
                              子素材文件名
                              <input
                                value={fragment.fileName || ''}
                                onChange={(event) => updateSplitFragment(fragment.id, { fileName: event.target.value })}
                                className="mt-1 h-9 w-full rounded-lg border border-surface-container-high bg-white px-3 text-sm text-on-surface"
                              />
                            </label>
                            <label className="text-xs text-on-surface-variant">
                              入库路径
                              <input
                                value={fragment.targetPath || ''}
                                onChange={(event) => updateSplitFragment(fragment.id, { targetPath: event.target.value })}
                                className="mt-1 h-9 w-full rounded-lg border border-surface-container-high bg-white px-3 text-sm text-on-surface"
                              />
                            </label>
                          </div>

                          <div className="mt-3 rounded-lg bg-surface-container-low px-3 py-2">
                            <div className="text-[11px] font-semibold text-on-surface-variant">片段预览</div>
                            <pre className="mt-1 max-h-28 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-on-surface-variant">
                              {fragment.contentPreview || '暂无预览文本'}
                            </pre>
                          </div>

                          {!!(fragment.riskTips || []).length && (
                            <div className="mt-3 rounded-lg border border-tertiary/30 bg-tertiary-container/60 px-3 py-2 text-xs leading-5 text-on-tertiary-container">
                              {(fragment.riskTips || []).map((tip) => (
                                <div key={tip}>风险提示：{tip}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-surface-container-high px-4 py-8 text-center text-sm text-on-surface-variant">
                      未识别到可切分边界。建议人工拆分后再上传，或后续接入 OCR/AI 边界增强。
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="px-5 sm:px-6 py-4 border-t border-surface-container-high flex flex-wrap items-center justify-between gap-3 bg-surface-container-low rounded-b-xl shrink-0">
              <div className="text-xs text-on-surface-variant">
                已勾选 {(splitPlan?.fragments || []).filter((fragment) => fragment.selected).length} / {(splitPlan?.fragments || []).length} 个片段
              </div>
              <div className="flex justify-end gap-3">
                <button onClick={closeBusinessSplitModal} className="px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-high rounded-lg">
                  取消
                </button>
                <button
                  onClick={confirmBusinessSplit}
                  disabled={splitLoading || splitConfirming || !(splitPlan?.fragments || []).some((fragment) => fragment.selected)}
                  className="px-4 py-2 text-sm bg-primary text-on-primary rounded-lg hover:bg-primary-container disabled:opacity-50"
                >
                  {splitConfirming ? '入库中...' : '确认生成子素材'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
