import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'

export default function TechnicalFactTable() {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()

  useEffect(() => {
    navigate(projectRoute(id, '/gaps', workspaceSlug), { replace: true })
  }, [id, navigate, workspaceSlug])

  return null
}
