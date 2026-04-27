import { useParams } from 'react-router-dom'

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

export const slugFromBidType = (bidType = '') => (bidType === '商务标' ? 'business' : 'tech')

export const bidTypeFromWorkspace = (slug = '') => workspaceFromSlug(slug)?.bidType || ''

export const workspaceBasePath = (slug = '') => {
  const workspace = workspaceFromSlug(slug)
  return workspace ? `/workspace/${workspace.slug}` : ''
}

export const workspaceRoute = (slug = '', path = '') => {
  const base = workspaceBasePath(slug)
  if (!base) return path || '/'
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
  return workspaceFromSlug(params.workspace || '')?.slug || ''
}
