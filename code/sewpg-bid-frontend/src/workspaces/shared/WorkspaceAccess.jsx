import { Navigate } from 'react-router-dom'
import { canAccessWorkspace, defaultWorkspaceFor } from '../../utils/permissions'

export default function WorkspaceAccess({ user, workspace, children }) {
  if (!workspace) return children
  if (canAccessWorkspace(user, workspace)) return children
  const fallback = defaultWorkspaceFor(user)
  return <Navigate to={`/workspace/${fallback}/projects`} replace />
}
