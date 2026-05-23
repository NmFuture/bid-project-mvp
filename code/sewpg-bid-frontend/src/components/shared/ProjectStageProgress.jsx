import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { stagesAPI } from '../../api'
import StageProgress from './StageProgress'
import { getStageNavigationRoute, getStrictStageLockReason } from '../../utils/stageFlow'
import { useWorkspaceSlug } from '../../utils/workspace'

const COMPACT_STAGE_GROUPS = [
  { id: 1, name: '目录生成', stageIds: [1], pendingRouteStageId: 1, completedRouteStageId: 1 },
  { id: 2, name: '目录确认', stageIds: [2], pendingRouteStageId: 2, completedRouteStageId: 2 },
  { id: 3, name: '素材匹配', stageIds: [3, 4], pendingRouteStageId: 3, completedRouteStageId: 4 },
  { id: 4, name: '共创导出', stageIds: [5, 6], pendingRouteStageId: 5, completedRouteStageId: 6 },
]

const toStageId = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

const stageStatusRank = {
  completed: 3,
  active: 2,
  running: 2,
  pending: 1,
}

const compactProjectStages = (rawStages = []) => {
  if (!Array.isArray(rawStages) || !rawStages.length) return []

  if (rawStages.some((stage) => Array.isArray(stage?.sourceStages))) {
    return rawStages.map((stage) => ({
      ...stage,
      id: toStageId(stage?.id),
      routeStageId: toStageId(stage?.routeStageId || stage?.id),
      sourceStageIds: Array.isArray(stage?.sourceStages)
        ? stage.sourceStages.map(toStageId).filter(Boolean)
        : [],
    }))
  }

  const rawById = new Map(rawStages.map((stage) => [toStageId(stage?.id), stage]).filter(([id]) => id))
  const activeRawStage = rawStages.find((stage) => stage?.status === 'active')
  const activeRawStageId = toStageId(activeRawStage?.id)

  return COMPACT_STAGE_GROUPS.map((group) => {
    const groupStages = group.stageIds.map((stageId) => rawById.get(stageId)).filter(Boolean)
    const activeStage = groupStages.find((stage) => stage?.status === 'active')
    const hasActiveStage = Boolean(activeStage)
    const hasKnownStage = groupStages.length > 0
    const isCompleted = hasKnownStage && groupStages.every((stage) => stage?.status === 'completed')
    const isPastGroup = activeRawStageId > Math.max(...group.stageIds)

    let status = 'pending'
    if (hasActiveStage) {
      status = 'active'
    } else if (isCompleted || isPastGroup) {
      status = 'completed'
    }

    const routeStageId = activeStage
      ? toStageId(activeStage.routeStageId || activeStage.id)
      : status === 'completed'
        ? group.completedRouteStageId
        : group.pendingRouteStageId

    const strongestStage = groupStages
      .slice()
      .sort((a, b) => (stageStatusRank[b?.status] || 0) - (stageStatusRank[a?.status] || 0))[0]

    return {
      id: group.id,
      name: group.name,
      status,
      routeStageId,
      sourceStageIds: group.stageIds,
      isSkipped: groupStages.length > 0 && groupStages.every((stage) => Boolean(stage?.isSkipped)),
      sourceStatus: strongestStage?.status || status,
    }
  })
}

export default function ProjectStageProgress({
  projectId,
  showToast,
  onStageSixClick,
}) {
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [stages, setStages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadStages = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError('')
    try {
      const payload = await stagesAPI.list(projectId)
      setStages(compactProjectStages(payload))
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

      if (Number(stage.routeStageId || stage.id) === 6) {
        if (typeof onStageSixClick === 'function') {
          onStageSixClick()
          return
        }
      }

      const route = getStageNavigationRoute(projectId, stage, workspaceSlug)
      if (!route) {
        showToast?.(`${stage.name || `S${stage.id}`} 页面正在建设中`, 'error')
        return
      }
      navigate(route)
    },
    [getStageLockReason, navigate, onStageSixClick, projectId, showToast, workspaceSlug],
  )

  if (loading) {
    return (
      <section className="bg-white px-0 py-2">
        <div className="animate-shimmer w-full h-10"></div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="bg-white px-0 py-2">
        <div className="flex flex-wrap items-center justify-between gap-3 bg-error-container/20 border border-error/20 px-4 py-3">
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
      getStageLockReason={getStageLockReason}
      onStageClick={handleStageClick}
    />
  )
}
