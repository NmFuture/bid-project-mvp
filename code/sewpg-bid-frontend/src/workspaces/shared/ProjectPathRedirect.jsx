import { Navigate, useParams } from 'react-router-dom'
import { projectRoute, useWorkspaceSlug } from '../../utils/workspace'

export default function ProjectPathRedirect({ path }) {
  const { id } = useParams()
  const workspaceSlug = useWorkspaceSlug()
  return <Navigate to={projectRoute(id, path, workspaceSlug)} replace />
}
