import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { projectsAPI } from '../../api'
import { PageError, PageLoading } from '../../components/states/PageState'
import { normalizeBidType, projectRoute } from '../../utils/workspace'

export default function LegacyProjectPathRedirect({ path = '' }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const redirect = useCallback(async () => {
    if (!id) {
      setError('项目 ID 缺失，请返回项目列表重试。')
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')
    try {
      const project = await projectsAPI.get(id)
      const workspaceSlug = normalizeBidType(project?.bidType) === '商务标' ? 'business' : 'tech'
      navigate(projectRoute(id, path, workspaceSlug), { replace: true })
    } catch (e) {
      setError(e?.message || '项目加载失败，请稍后重试。')
      setLoading(false)
    }
  }, [id, navigate, path])

  useEffect(() => {
    const timer = setTimeout(() => {
      redirect()
    }, 0)
    return () => clearTimeout(timer)
  }, [redirect])

  if (loading) {
    return <PageLoading title="正在进入项目..." description="正在迁移到对应标类工作区。" />
  }

  return (
    <PageError
      title="进入项目失败"
      description={error}
      onRetry={redirect}
    />
  )
}
