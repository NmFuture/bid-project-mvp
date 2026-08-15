// 素材库（技术标/商务标原始素材页）共享纯逻辑。
// 两条轨道的页面共用同一份实现，轨道差异通过参数传入，
// 行为口径与合并前 TechnicalMaterialDB / BusinessMaterialDB 完全一致。

export const MAX_FILE_SIZE = 30 * 1024 * 1024 * 1024
export const FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
export const UPLOAD_KIND_STORAGE_KEY = 'materials.raw.upload.kind'
export const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'xlsm', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

// 原件直预览：PDF/图片走浏览器内联渲染，Excel 走 OnlyOffice 直开原件
export const INLINE_PREVIEW_EXTS = ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff']
export const ONLYOFFICE_ORIGINAL_EXTS = ['xls', 'xlsx', 'xlsm']

const splitTagSource = (value) => (
  Array.isArray(value) ? value : String(value || '').split(/[,，;；\n\r\t]+/)
)

const normalizeTags = (value, limit) => {
  const source = splitTagSource(value)
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
  return tags.slice(0, limit)
}

export const normalizeTagList = (value) => normalizeTags(value, 20)

export const normalizeTagOptions = (value) => normalizeTags(value, 100)

export const tagInputPreview = (committedTags, draftValue) => normalizeTagList([
  ...normalizeTagList(committedTags),
  ...normalizeTagList(draftValue),
])

export const canPreviewCleaned = (item) => item?.cleanStatus === 'cleaned' && Boolean(item?.hasCleanedWord)

export const extOf = (name) => {
  const parts = String(name || '').split('.')
  if (parts.length < 2) return ''
  return String(parts.pop() || '').toLowerCase()
}

export const canPreviewOriginal = (item) => {
  const ext = extOf(item?.name)
  return INLINE_PREVIEW_EXTS.includes(ext) || ONLYOFFICE_ORIGINAL_EXTS.includes(ext)
}

export const canPreview = (item) => canPreviewCleaned(item) || canPreviewOriginal(item)

export const cleanedPreviewBlockedMessage = (item) => {
  if (!item) return '选择已清洗文件后预览。'
  if (item.cleanStatus === 'original_only') return '该类型暂不支持在线预览，可下载查看。'
  if (item.cleanStatus === 'failed') return '清洗失败，暂无预览。'
  if (item.cleanStatus === 'cleaning') return '清洗中，完成后可预览。'
  if (item.cleanStatus === 'pending') return '等待清洗，完成后可预览。'
  if (item.cleanStatus === 'cleaned' && !item.hasCleanedWord) return '清洗文件丢失，请联系管理员重新处理。'
  return '暂无清洗稿。'
}

export const displayFolderName = (name, path, rootLabels = {}) => {
  const value = String(name || '')
  const normalizedPath = String(path || '').replace(/^\/+|\/+$/g, '')
  return rootLabels[normalizedPath] || rootLabels[value] || value
}

export const readStoredUploadKind = () => {
  if (typeof window === 'undefined') return 'files'
  try {
    const value = window.localStorage.getItem(UPLOAD_KIND_STORAGE_KEY)
    return value === 'folder' ? 'folder' : 'files'
  } catch {
    return 'files'
  }
}

export const persistUploadKind = (value) => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(UPLOAD_KIND_STORAGE_KEY, value === 'folder' ? 'folder' : 'files')
  } catch {
    // ignore storage failures
  }
}

export const safeMessage = (error, fallback) => error?.payload?.detail || error?.message || fallback

export const toSizeLabel = (bytes) => {
  const value = Number(bytes || 0)
  if (!Number.isFinite(value) || value <= 0) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(2)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export const normalizePath = (path) => String(path || '').replace(/^\/+|\/+$/g, '')

export const parentPath = (path) => {
  const normalized = normalizePath(path)
  if (!normalized) return ''
  const parts = normalized.split('/')
  if (parts.length <= 1) return ''
  return parts.slice(0, -1).join('/')
}

// 商务标上传流的素材层级：按根目录下的档位目录名推导 tier。
// tierDirMap: { 目录名: tier 值 }，rootPaths: 素材库根（如 ['商务标']）。
export const materialTierFromRootPath = (path, rootPaths = [], tierDirMap = {}) => {
  const normalized = normalizePath(path)
  const parts = normalized.split('/').filter(Boolean)
  const tierName = rootPaths.includes(parts[0]) ? parts[1] : parts[0]
  return tierDirMap[tierName] || ''
}

export const normalizeTreeNodes = (nodes = [], rootLabels = {}) =>
  (Array.isArray(nodes) ? nodes : []).map((node) => ({
    id: String(node?.id || node?.path || node?.name || `node-${Math.random().toString(36).slice(2, 8)}`),
    name: displayFolderName(node?.name || node?.title || node?.path || '未命名目录', node?.path || node?.name || '', rootLabels),
    path: String(node?.path || node?.name || ''),
    directFileCount: Number(node?.directFileCount || 0),
    fileCount: Number(node?.fileCount || 0),
    children: normalizeTreeNodes(node?.children || [], rootLabels),
  }))

export const ensureMaterialRootNodes = (nodes = [], rootPath = '') => {
  const byPath = new Map()
  ;(Array.isArray(nodes) ? nodes : []).forEach((node) => {
    const path = String(node?.path || node?.name || '').replace(/^\/+|\/+$/g, '')
    if (path) byPath.set(path, node)
  })
  return [
    byPath.get(rootPath) || {
      id: rootPath,
      name: rootPath,
      path: rootPath,
      directFileCount: 0,
      fileCount: 0,
      children: [],
    },
  ]
}

export const flattenTreePaths = (nodes = []) => {
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

export const pathMatchesBidType = (path, bidType) => {
  const normalized = normalizePath(path)
  if (!normalized) return false
  const parts = normalized.split('/')
  return parts[0] === bidType
}

export const collectCollapsiblePaths = (nodes = []) => {
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

export const buildDefaultCollapsedMap = (nodes = [], level = 0, map = {}) => {
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

export const expandPathInMap = (map, path) => {
  const parts = normalizePath(path).split('/').filter(Boolean)
  parts.forEach((_, index) => {
    map[parts.slice(0, index + 1).join('/')] = false
  })
  return map
}

// 目录删除/移动保护口径。两轨差异通过参数收敛：
// - protectedPaths / standardProtectedPaths：全路径保护集合；
// - 客户/项目档位下的自动预置目录（第 4 段）按名字保护；
// - protectTierRoot（商务标）：档位目录的直接子目录（3 段）整层保护。
export const createFolderDeleteProtection = ({
  bidType,
  protectedPaths,
  standardProtectedPaths,
  customerProtectedNames,
  projectProtectedNames,
  customerTierDirs,
  projectTierDirs,
  protectTierRoot = false,
}) => (path) => {
  const normalized = normalizePath(path)
  if (protectedPaths.has(normalized) || standardProtectedPaths.has(normalized)) {
    return true
  }
  const parts = normalized.split('/').filter(Boolean)
  if (
    protectTierRoot
    && parts.length === 3
    && parts[0] === bidType
    && (customerTierDirs.includes(parts[1]) || projectTierDirs.includes(parts[1]))
  ) {
    return true
  }
  if (parts.length !== 4 || parts[0] !== bidType) return false
  if (customerTierDirs.includes(parts[1])) return customerProtectedNames.has(parts[3])
  if (projectTierDirs.includes(parts[1])) return projectProtectedNames.has(parts[3])
  return false
}

// 重命名保护口径与后端一致：仅根目录和默认档位目录（如 标准文件/客户定制/项目定制）禁止改名
export const createFolderRenameProtection = (protectedPaths) => (path) =>
  protectedPaths.has(normalizePath(path))

export const pickDefaultFolder = (nodes = [], bidType = '', rootPath = '') => {
  const paths = flattenTreePaths(nodes)
  if (!paths.length) return ''
  const exact = paths.find((path) => path === rootPath)
  if (exact) return exact
  const scoped = paths.find((path) => pathMatchesBidType(path, bidType))
  if (scoped) return scoped
  return paths[0] || ''
}

export const groupFilesByFolderPath = (items = []) => {
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

export const filterTreeByMatchedFiles = (nodes = [], filesByFolderPath = new Map()) =>
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

export const getVisibleFileCount = (nodes = []) =>
  (Array.isArray(nodes) ? nodes : []).reduce((sum, node) => sum + Number(node?.fileCount || 0), 0)

export const statusColor = (status) => {
  if (status === 'running') return 'bg-primary/10 text-primary'
  if (status === 'success') return 'bg-secondary-container text-on-secondary-container'
  if (status === 'failed') return 'bg-error-container text-on-error-container'
  return 'bg-surface-container-high text-on-surface-variant'
}

export const listItems = (payload) => {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.items)) return payload.items
  return []
}

const IDENTITY_IGNORED_CHARS = new Set([
  ',', '，', '、', '.', '。', ':', '：', ';', '；', '(', ')', '（', '）',
  '[', ']', '【', '】', '{', '}', '<', '>', '《', '》', '"', "'", '`',
  '·', '_', '-', '—', '/', '\\', '|',
])

export const identityKey = (value) =>
  String(value || '')
    .trim()
    .toLowerCase()
    .split('')
    .filter((char) => char !== '\u3000' && !/\s/.test(char) && !IDENTITY_IGNORED_CHARS.has(char))
    .join('')

export const normalizeCustomerOptions = (customersPayload, projectsPayload) => {
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

export const normalizeProjectOptions = (payload) =>
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

export const customerOptionMatches = (option, value) => {
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

export const customerLabel = (option) => {
  const id = option.customerId ? ` / ${option.customerId}` : ''
  return `${option.name}${id}`
}

export const projectLabel = (option) => {
  const parts = [
    option.id,
    option.projectCode && option.projectCode !== option.id ? option.projectCode : '',
    option.customerCanonicalName || option.customerName,
  ].filter(Boolean)
  return `${option.name}（${parts.join(' / ')}）`
}
