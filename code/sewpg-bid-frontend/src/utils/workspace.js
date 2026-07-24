import { useLocation, useParams } from 'react-router-dom'

export const WORKSPACE_TYPES = {
  tech: {
    slug: 'tech',
    bidType: '技术标',
    label: '技术标',
    icon: 'engineering',
  },
  business: {
    slug: 'business',
    bidType: '商务标',
    label: '商务标',
    icon: 'request_quote',
  },
}

export const workspaceFromSlug = (slug = '') => WORKSPACE_TYPES[String(slug || '')] || null

export const normalizeBidType = (bidType = '') => {
  const text = String(bidType || '').trim()
  if (text === '商务标' || text.includes('商务')) return '商务标'
  if (text === '技术标' || text.includes('技术')) return '技术标'
  return ''
}

export const slugFromBidType = (bidType = '') => {
  const normalized = normalizeBidType(bidType)
  if (normalized === '商务标') return 'business'
  if (normalized === '技术标') return 'tech'
  return ''
}

export const bidTypeFromWorkspace = (slug = '') => workspaceFromSlug(slug)?.bidType || ''

export const parseRouteFromBidType = (bidType = '', projectId = '') => {
  const normalized = normalizeBidType(bidType)
  const basePath = normalized === '商务标' ? '/parse/business' : normalized === '技术标' ? '/parse/technical' : ''
  if (!basePath) return ''
  if (!projectId) return basePath
  return `${basePath}?projectId=${encodeURIComponent(projectId)}`
}

export const workspaceBasePath = (slug = '') => {
  const workspace = workspaceFromSlug(slug)
  return workspace ? `/workspace/${workspace.slug}` : ''
}

export const workspaceRoute = (slug = '', path = '') => {
  const base = workspaceBasePath(slug)
  if (!base) return '/'
  if (!path) return base
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

export const projectRoute = (projectId = '', suffix = '', slug = '') => {
  const normalizedSuffix = suffix ? (suffix.startsWith('/') ? suffix : `/${suffix}`) : ''
  const projectPath = `/projects/${projectId}${normalizedSuffix}`
  return workspaceRoute(slug, projectPath)
}

const splitPath = (path = '') => {
  const raw = String(path || '')
  const hashIndex = raw.indexOf('#')
  const hash = hashIndex >= 0 ? raw.slice(hashIndex) : ''
  const withoutHash = hashIndex >= 0 ? raw.slice(0, hashIndex) : raw
  const queryIndex = withoutHash.indexOf('?')
  return {
    pathname: queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash,
    search: queryIndex >= 0 ? withoutHash.slice(queryIndex) : '',
    hash,
  }
}

export const workspaceFromPathname = (pathname = '') => {
  const cleanPathname = splitPath(pathname).pathname
  const match = cleanPathname.match(/^\/workspace\/([^/]+)/)
  const workspace = workspaceFromSlug(match?.[1] || '')
  if (workspace?.slug) return workspace.slug

  const parseMatch = cleanPathname.match(/^\/parse\/(business|technical)(?:\/|$)/)
  if (parseMatch?.[1] === 'business') return 'business'
  if (parseMatch?.[1] === 'technical') return 'tech'
  return ''
}

export const workspaceSwitchRoute = (currentPath = '', targetSlug = '') => {
  const targetWorkspace = workspaceFromSlug(targetSlug)
  if (!targetWorkspace) return ''

  const { pathname, search, hash } = splitPath(currentPath)
  if (/^\/parse\/(business|technical)(?:\/|$)/.test(pathname)) {
    return targetWorkspace.slug === 'business' ? '/parse/business' : '/parse/technical'
  }

  const workspaceMatch = pathname.match(/^\/workspace\/([^/]+)(.*)$/)
  if (!workspaceFromSlug(workspaceMatch?.[1] || '')) return ''
  return `/workspace/${targetWorkspace.slug}${workspaceMatch?.[2] || ''}${search}${hash}`
}

export const useWorkspaceSlug = () => {
  const params = useParams()
  const location = useLocation()
  return workspaceFromSlug(params.workspace || '')?.slug || workspaceFromPathname(location.pathname)
}
