import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalProjectsAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import { parseRouteFromBidType, projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import { getTechnicalStageRoute } from '../technicalStageFlow'

const resolveStage = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 1
  return Math.max(1, Math.min(6, Math.floor(parsed)))
}

export default function TechnicalProjectEntryRedirect({ workspaceKind = 'tech' }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const routeWorkspaceSlug = useWorkspaceSlug()
  const workspaceSlug = workspaceKind || routeWorkspaceSlug
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProjectAndRedirect = useCallback(async () => {
    if (!id) {
      setError('项目 ID 缺失，请返回项目列表重试。')
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')
    try {
      const project = await technicalProjectsAPI.get(id)
      // 缺字段时默认按未参与处理，避免临时/暂存项目被误放行进入撰写流程
      const reviewDecision = String(project?.reviewDecision || 'pending')
      if (reviewDecision !== 'participate') {
        navigate(parseRouteFromBidType('技术标', id), { replace: true })
        return
      }
      const stage = resolveStage(project?.currentStage)
      const routeWorkspaceSlug = workspaceSlug || 'tech'
      const route = getTechnicalStageRoute(id, stage, routeWorkspaceSlug) || projectRoute(id, '/template-directory', routeWorkspaceSlug)
      navigate(route, { replace: true })
    } catch (e) {
      setError(e?.message || '项目加载失败，请稍后重试。')
      setLoading(false)
    }
  }, [id, navigate, workspaceSlug])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjectAndRedirect()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProjectAndRedirect])

  if (loading) {
    return <PageLoading title="正在进入项目..." description="正在根据当前阶段跳转页面。" />
  }

  return (
    <PageError
      title="进入项目失败"
      description={error}
      onRetry={loadProjectAndRedirect}
    />
  )
}
