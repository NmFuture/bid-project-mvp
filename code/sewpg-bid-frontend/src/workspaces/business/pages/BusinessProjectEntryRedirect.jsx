import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { businessProjectsAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import { projectRoute } from '../../../utils/workspace'
import { getBusinessStageRoute } from '../businessStageFlow'

const BUSINESS_WORKSPACE = 'business'

const resolveStage = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 1
  return Math.max(1, Math.min(6, Math.floor(parsed)))
}

const businessParseRoute = (projectId = '') => {
  if (!projectId) return '/parse/business'
  return `/parse/business?projectId=${encodeURIComponent(projectId)}`
}

export default function BusinessProjectEntryRedirect() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProjectAndRedirect = useCallback(async () => {
    if (!id) {
      setError('项目 ID 缺失，请返回商务标项目列表重试。')
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')
    try {
      const project = await businessProjectsAPI.get(id)
      const reviewDecision = String(project?.reviewDecision || 'participate')
      if (reviewDecision !== 'participate') {
        navigate(businessParseRoute(id), { replace: true })
        return
      }

      const stage = resolveStage(project?.currentStage)
      const route = getBusinessStageRoute(id, stage)
        || projectRoute(id, '/template-directory', BUSINESS_WORKSPACE)
      navigate(route, { replace: true })
    } catch (e) {
      setError(e?.message || '商务标项目加载失败，请稍后重试。')
      setLoading(false)
    }
  }, [id, navigate])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjectAndRedirect()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProjectAndRedirect])

  if (loading) {
    return <PageLoading title="正在进入商务标项目..." description="正在根据当前阶段跳转页面。" />
  }

  return (
    <PageError
      title="进入商务标项目失败"
      description={error}
      onRetry={loadProjectAndRedirect}
    />
  )
}
