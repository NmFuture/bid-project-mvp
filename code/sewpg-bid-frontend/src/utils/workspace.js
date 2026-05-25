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

export const workspaceFromPathname = (pathname = '') => {
  const match = String(pathname || '').match(/^\/workspace\/([^/]+)/)
  const workspace = workspaceFromSlug(match?.[1] || '')
  return workspace?.slug || ''
}

export const useWorkspaceSlug = () => {
  const params = useParams()
  const location = useLocation()
  return workspaceFromSlug(params.workspace || '')?.slug || workspaceFromPathname(location.pathname)
}
