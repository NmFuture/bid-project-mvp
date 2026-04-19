import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { projectsAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import { getStageRoute } from '../utils/stageFlow'

const resolveStage = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 1
  return Math.max(1, Math.min(10, Math.floor(parsed)))
}

export default function ProjectEntryRedirect() {
  const { id } = useParams()
  const navigate = useNavigate()
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
      const project = await projectsAPI.get(id)
      const stage = resolveStage(project?.currentStage)
      const route = getStageRoute(id, stage) || `/projects/${id}/parse`
      navigate(route, { replace: true })
    } catch (e) {
      setError(e?.message || '项目加载失败，请稍后重试。')
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
