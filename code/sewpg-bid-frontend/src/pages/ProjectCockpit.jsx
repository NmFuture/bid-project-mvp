import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { projectsAPI, stagesAPI } from '../api'
import ExportModal from '../components/modals/ExportModal'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import StageProgress from '../components/shared/StageProgress'
import DataCard from '../components/shared/DataCard'
import { getStageRoute, getStrictStageLockReason } from '../utils/stageFlow'
import { projectRoute, useWorkspaceSlug, workspaceRoute } from '../utils/workspace'

export default function ProjectCockpit({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [project, setProject] = useState(null)
  const [stages, setStages] = useState([])
  const [cockpit, setCockpit] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showExport, setShowExport] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [p, s, c] = await Promise.all([projectsAPI.get(id), stagesAPI.list(id), projectsAPI.cockpit(id)])
      setProject(p)
      setStages(s || [])
      setCockpit(c || null)
    } catch (e) {
      setError(e?.message || '项目数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const getStageLockReason = useCallback(
    (targetStageId) => getStrictStageLockReason(stages, targetStageId),
    [stages],
  )

  const openExportWithGuard = useCallback(() => {
    const lockReason = getStageLockReason(10)
    if (lockReason) {
      showToast(lockReason, 'error')
      return
    }
    setShowExport(true)
  }, [getStageLockReason, showToast])

  const goEditorWithGuard = useCallback(() => {
    const lockReason = getStageLockReason(9)
    if (lockReason) {
      showToast(lockReason, 'error')
      return
    }
    navigate(projectRoute(id, '/editor', workspaceSlug))
  }, [getStageLockReason, id, navigate, showToast, workspaceSlug])

  if (loading) return <PageLoading title="正在加载项目驾驶舱..." />

  if (error) {
    return (
      <PageError
        title="项目驾驶舱加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  const tasks = Array.isArray(cockpit?.tasks) ? cockpit.tasks : []
  const stageSummary = String(cockpit?.summary || '请根据当前阶段推进任务，关键阻塞项会在此汇总。')
  const stageStartDate = String(cockpit?.startDate || project?.startDate || '-')
  const stageDeadline = String(cockpit?.endDate || cockpit?.deadline || project?.endDate || project?.deadline || '-')

  const exportLockReason = getStageLockReason(10)
  const editorLockReason = getStageLockReason(9)

  return (
    <div className="flex flex-col gap-8 animate-fade-in">
      <PageHeader
        className="mb-2"
        title={project?.name}
        leftExtra={(
          <div className="flex items-center gap-3 mb-2">
            <span className="px-3 py-1 bg-secondary-container text-on-secondary-container text-xs font-semibold rounded-full tracking-wide">进行中</span>
            <span className="text-sm text-outline">ID: {project?.id}</span>
          </div>
        )}
        actions={(
          <>
            <button
              onClick={openExportWithGuard}
              disabled={Boolean(exportLockReason)}
              title={exportLockReason}
              className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant font-medium rounded-lg hover:bg-surface-dim transition-colors text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-lg">download</span>
              导出报告
            </button>
            <button
              onClick={goEditorWithGuard}
              disabled={Boolean(editorLockReason)}
              title={editorLockReason}
              className="px-5 py-2.5 bg-gradient-to-r from-primary to-primary-container text-on-primary font-medium rounded-lg shadow-lg shadow-primary/20 hover:shadow-xl hover:-translate-y-0.5 transition-all text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-lg"
            >
              <span className="material-symbols-outlined text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>edit_document</span>
              编制投标文件
            </button>
          </>
        )}
      />

      <StageProgress
        stages={stages}
        getStageLockReason={getStageLockReason}
        onStageClick={(stage) => {
          const lockReason = getStageLockReason(stage.id)
          if (lockReason) {
            showToast(lockReason, 'error')
            return
          }
          if (stage.id === 10) {
            openExportWithGuard()
            return
          }
          const route = getStageRoute(id, stage.id, workspaceSlug)
          if (route) {
            navigate(route)
            return
          }
          showToast(`S${stage.id} 页面正在建设中`, 'error')
        }}
      />

      {/* Dashboard */}
      <div className="flex flex-col gap-8">
        <DataCard className="overflow-hidden border-l-4 border-secondary !p-0">
          <div className="p-6 border-b border-surface-container-high/50 bg-gradient-to-r from-surface-container-lowest to-surface-bright flex justify-between items-center">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-secondary-fixed/30 flex items-center justify-center text-secondary">
                <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>pending_actions</span>
              </div>
              <h2 className="text-xl font-headline font-bold text-on-surface">当前阶段: {project?.stageLabel}</h2>
            </div>
            <div className="text-sm text-outline flex flex-wrap items-center justify-end gap-x-4 gap-y-1">
              <span className="inline-flex items-center gap-1">
                <span className="material-symbols-outlined text-sm">event</span>
                起始日期: {stageStartDate}
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="material-symbols-outlined text-sm">schedule</span>
                截止日期: {stageDeadline}
              </span>
            </div>
          </div>
          <div className="p-6 flex flex-col gap-4">
            <p className="text-on-surface-variant text-sm mb-2 leading-relaxed">
              {stageSummary}
            </p>
            {!tasks.length ? (
              <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4 text-sm text-on-surface-variant">
                当前阶段暂无待办项，刷新后可获取最新任务状态。
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {tasks.map((task) => (
                  <div key={task.id || task.title} className={`group flex items-center justify-between p-4 rounded-lg transition-colors border border-transparent ${
                    task.status === 'done' ? 'bg-surface-bright border-surface-container-high opacity-70' : 'bg-surface-container-low hover:bg-surface-container hover:border-outline-variant/20'
                  }`}>
                    <div className="flex items-center gap-4">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                        task.status === 'done' ? 'bg-secondary-container text-secondary' : 'bg-error-container/50 text-error'
                      }`}>
                        <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>{task.icon || (task.status === 'done' ? 'check' : 'error')}</span>
                      </div>
                      <div>
                        <h3 className={`text-sm font-semibold tracking-wide ${task.status === 'done' ? 'text-outline line-through' : 'text-on-surface'}`}>{task.title || '未命名任务'}</h3>
                        <p className="text-xs text-outline mt-0.5">{task.desc || '-'}</p>
                      </div>
                    </div>
                    {task.status === 'done' ? (
                      <span className="text-xs text-secondary font-medium px-3 py-1 bg-secondary-container/30 rounded-full">已完成</span>
                    ) : (
                      <button
                        onClick={() => {
                          const route = task.actionRoute
                            ? (workspaceSlug ? workspaceRoute(workspaceSlug, task.actionRoute) : task.actionRoute)
                            : projectRoute(id, '/gaps', workspaceSlug)
                          navigate(route)
                        }}
                        className="px-4 py-1.5 bg-primary/10 text-primary hover:bg-primary/20 font-medium rounded-lg transition-colors text-xs flex items-center gap-1 whitespace-nowrap"
                      >
                        {task.actionLabel || '去处理'}
                        <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </DataCard>
      </div>

      {showExport && (
        <ExportModal
          projectId={id}
          onClose={() => setShowExport(false)}
          onExport={() => {
            setShowExport(false)
            showToast('标书导出成功！')
          }}
        />
      )}
    </div>
  )
}
