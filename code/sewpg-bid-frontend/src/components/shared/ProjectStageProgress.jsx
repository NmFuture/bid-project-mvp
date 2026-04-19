import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { stagesAPI } from '../../api'
import StageProgress from './StageProgress'
import { getStageRoute, getStrictStageLockReason } from '../../utils/stageFlow'

export default function ProjectStageProgress({
  projectId,
  showToast,
  title = '项目进度概览',
  onStageTenClick,
}) {
  const navigate = useNavigate()
  const [stages, setStages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadStages = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError('')
    try {
      const payload = await stagesAPI.list(projectId)
      setStages(Array.isArray(payload) ? payload : [])
    } catch (e) {
      setError(e?.message || '进度加载失败')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadStages()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadStages])

  const getStageLockReason = useCallback(
    (targetStageId) => getStrictStageLockReason(stages, targetStageId),
    [stages],
  )

  const handleStageClick = useCallback(
    (stage) => {
      const lockReason = getStageLockReason(stage.id)
      if (lockReason) {
        showToast?.(lockReason, 'error')
        return
      }

      if (Number(stage.id) === 10) {
        if (typeof onStageTenClick === 'function') {
          onStageTenClick()
          return
        }
      }

      const route = getStageRoute(projectId, stage.id)
      if (!route) {
        showToast?.(`S${stage.id} 页面正在建设中`, 'error')
        return
      }
      navigate(route)
    },
    [getStageLockReason, navigate, onStageTenClick, projectId, showToast],
  )

  if (loading) {
    return (
      <section className="bg-surface-container-lowest p-6 rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.08)]">
        <div className="text-sm font-semibold text-on-surface-variant mb-4 font-headline tracking-wide uppercase">
          {title}
        </div>
        <div className="animate-shimmer w-full h-10 rounded-lg"></div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="bg-surface-container-lowest p-6 rounded-xl shadow-[0_8px_24px_-12px_rgba(0,62,111,0.08)]">
        <div className="text-sm font-semibold text-on-surface-variant mb-3 font-headline tracking-wide uppercase">
          {title}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-error-container/20 border border-error/20 px-4 py-3">
          <div className="text-sm text-error">阶段进度加载失败：{error}</div>
          <button
            onClick={loadStages}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-error text-on-error"
          >
            重试
          </button>
        </div>
      </section>
    )
  }

  return (
    <StageProgress
      stages={stages}
      title={title}
      getStageLockReason={getStageLockReason}
      onStageClick={handleStageClick}
    />
  )
}
