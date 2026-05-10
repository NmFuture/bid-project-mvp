import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { projectsAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import GapRecognition from './GapRecognition'
import BusinessGapRecognition from './BusinessGapRecognition'

export default function GapEntry({ showToast }) {
  const { id } = useParams()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProject = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await projectsAPI.get(id)
      setProject(payload)
    } catch (e) {
      setError(e?.message || '项目加载失败。')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProject()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProject])

  if (loading) return <PageLoading title="正在加载缺口处理" description="正在确认项目类型。" />
  if (error) return <PageError title="加载失败" description={error} onRetry={loadProject} />
  if (String(project?.bidType || '').includes('商务')) {
    return <BusinessGapRecognition showToast={showToast} project={project} />
  }
  return <GapRecognition showToast={showToast} project={project} />
}
