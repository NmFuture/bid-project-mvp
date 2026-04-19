import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { projectsAPI } from '../api'
import Pagination from '../components/shared/Pagination'
import ProjectWizardModal from '../components/modals/ProjectWizardModal'
import { PageLoading, PageEmpty, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import FilterBar from '../components/shared/FilterBar'
import DataCard from '../components/shared/DataCard'
import { getStageRoute } from '../utils/stageFlow'

export default function ProjectList({ showToast }) {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [dateFilter, setDateFilter] = useState('all')
  const [currentPage, setCurrentPage] = useState(1)
  const [pagination, setPagination] = useState({ page: 1, pageSize: 12, total: 0 })
  const [showWizard, setShowWizard] = useState(false)
  const [activeMenuId, setActiveMenuId] = useState('')
  const [actionLoadingId, setActionLoadingId] = useState('')

  const loadProjects = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await projectsAPI.list({
        status: statusFilter !== 'all' ? statusFilter : '',
        dateRange: dateFilter !== 'all' ? dateFilter : '',
        page: currentPage,
        pageSize: pagination.pageSize,
      })
      const items = Array.isArray(data?.items) ? data.items : []
      const total = Number(data?.total ?? items.length)
      const pageSize = Number(data?.pageSize || pagination.pageSize || 12)
      setProjects(items)
      setPagination({ page: currentPage, pageSize, total })
    } catch (e) {
      setError(e?.message || '项目列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [currentPage, dateFilter, pagination.pageSize, statusFilter])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjects()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProjects])

  const getProgressSegments = (completedStages) =>
    Array.from({ length: 10 }, (_, i) => i < completedStages)

  const getProjectEntryRoute = (project) => {
    const stage = Number(project?.currentStage) || 1
    const stageRoute = getStageRoute(project?.id, stage)
    if (stageRoute) return stageRoute
    return `/projects/${project.id}`
  }

  const handleDelete = async (projectId) => {
    setActionLoadingId(projectId)
    try {
      await projectsAPI.delete(projectId)
      showToast('项目已删除')
      await loadProjects()
    } catch (e) {
      console.error(e)
      if (e?.status === 404) {
        showToast('删除失败：项目不存在或已被移除，请刷新列表后重试。', 'error')
      } else if (e?.code === 'NETWORK_ERROR' || e?.code === 'TIMEOUT') {
        showToast('删除失败：接口不可达，请先确认正式 FastAPI 后端已启动。', 'error')
      } else {
        showToast(e?.message || '删除项目失败', 'error')
      }
    } finally {
      setActionLoadingId('')
      setActiveMenuId('')
    }
  }

  if (loading) {
    return <PageLoading title="正在加载项目列表..." />
  }

  if (error) {
    return (
      <PageError
        title="项目列表加载失败"
        description={error}
        onRetry={loadProjects}
      />
    )
  }

  return (
    <div className="flex flex-col gap-8 max-w-7xl mx-auto animate-fade-in">
      <PageHeader
        className="mb-4"
        title="投标项目"
        description="管理和追踪所有风电投标项目的生命周期，从立项到最终归档。"
        actions={(
          <button
            onClick={() => setShowWizard(true)}
            className="flex items-center gap-2 bg-gradient-to-r from-primary to-primary-container text-on-primary px-6 py-3 rounded-md font-semibold hover:shadow-[0_8px_24px_-8px_rgba(0,62,111,0.5)] transition-all active:scale-95 shadow-sm"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            新建项目
          </button>
        )}
      />

      {/* Filter Bar */}
      <FilterBar
        left={(
          <>
            <div className="relative flex-1 min-w-[140px] max-w-[200px]">
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value)
                  setCurrentPage(1)
                }}
                className="w-full h-11 appearance-none bg-surface-container-highest border-none rounded-md px-4 pr-10 text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
              >
                <option value="all">所有状态</option>
                <option value="active">编写中</option>
                <option value="review">审批中</option>
                <option value="completed">已完成</option>
                <option value="archived">已归档</option>
              </select>
              <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-on-surface-variant">arrow_drop_down</span>
            </div>
            <div className="relative flex-1 min-w-[140px] max-w-[200px]">
              <select
                value={dateFilter}
                onChange={(e) => {
                  setDateFilter(e.target.value)
                  setCurrentPage(1)
                }}
                className="w-full h-11 appearance-none bg-surface-container-highest border-none rounded-md px-4 pr-10 text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
              >
                <option value="all">时间范围</option>
                <option value="7d">最近7天</option>
                <option value="30d">最近30天</option>
                <option value="quarter">本季度</option>
              </select>
              <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-on-surface-variant">arrow_drop_down</span>
            </div>
          </>
        )}
      />

      {/* Active Filter Tags */}
      {statusFilter !== 'all' && (
        <div className="flex items-center gap-2 flex-wrap -mt-4">
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-secondary-container text-on-secondary-container rounded-full text-xs font-medium shadow-sm">
            <span>状态: {statusFilter === 'active' ? '编写中' : statusFilter === 'review' ? '审批中' : statusFilter === 'completed' ? '已完成' : '已归档'}</span>
            <button onClick={() => {
              setStatusFilter('all')
              setCurrentPage(1)
            }} className="hover:text-error">
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        </div>
      )}

      {/* Project Cards Grid */}
      {!projects.length ? (
        <PageEmpty
          title="当前没有项目数据"
          description="你可以先创建一个项目，或者调整筛选条件后重试。"
          actionText="重新加载"
          onAction={loadProjects}
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {projects.map((project) => {
            const isActionLoading = actionLoadingId === project.id
            const menuOpen = activeMenuId === project.id
            return (
              <DataCard
                key={project.id}
                onClick={() => navigate(getProjectEntryRoute(project))}
                className="group flex flex-col gap-6 relative overflow-visible"
                hover
              >
                {/* Hover Accent Line */}
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary to-primary-container opacity-0 group-hover:opacity-100 transition-opacity"></div>

                <div className="flex justify-between items-start">
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-on-surface-variant uppercase tracking-widest font-semibold">{project.id}</span>
                    <h3 className="text-xl font-headline font-bold text-on-surface leading-tight group-hover:text-primary transition-colors">
                      {project.name}
                    </h3>
                    <p className="text-xs text-outline">业主：{project.owner || '待补充'}</p>
                  </div>
                  <div className="relative">
                    <button
                      className="text-on-surface-variant hover:text-primary transition-colors"
                      onClick={(e) => {
                        e.stopPropagation()
                        setActiveMenuId(menuOpen ? '' : project.id)
                      }}
                    >
                      <span className="material-symbols-outlined">more_vert</span>
                    </button>
                    {menuOpen && (
                      <div className="absolute right-0 top-8 w-32 bg-surface-container-lowest border border-surface-container-high rounded-lg shadow-lg z-20 py-1">
                        <button
                          className="w-full text-left px-3 py-2 text-sm text-error hover:bg-error-container/20 transition-colors disabled:opacity-50"
                          disabled={isActionLoading}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(project.id)
                          }}
                        >
                          删除项目
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  <div className="flex justify-between items-end mb-1">
                    <span className="text-sm font-medium text-on-surface">{project.stageLabel}</span>
                    <span className="text-xs font-bold text-secondary">{project.progress}%</span>
                  </div>
                  {/* 10-Segment Progress Bar */}
                  <div className="flex gap-1 h-2 w-full">
                    {getProgressSegments(project.completedStages).map((filled, index) => (
                      <div key={index} className={`flex-1 rounded-full ${filled ? 'bg-secondary' : 'bg-surface-dim'}`}></div>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 mt-auto pt-4 border-t border-surface-dim/30">
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-on-surface-variant">截止日期</span>
                    <span className="text-sm font-medium text-on-surface flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-[16px] text-primary">event</span>
                      {project.deadline}
                    </span>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="text-xs text-on-surface-variant">负责人</span>
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-primary-container text-on-primary flex items-center justify-center text-[10px] font-bold">
                        {project.managerAvatar || '未'}
                      </div>
                      <span className="text-sm font-medium text-on-surface">{project.manager || '未分配'}</span>
                    </div>
                  </div>
                </div>
              </DataCard>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {!!projects.length && (
        <Pagination
          current={pagination.page}
          total={Math.max(1, Math.ceil((pagination.total || projects.length) / (pagination.pageSize || 12)))}
          onPageChange={setCurrentPage}
        />
      )}

      {/* New Project Wizard Modal */}
      {showWizard && (
        <ProjectWizardModal
          onClose={() => setShowWizard(false)}
          onCreated={() => {
            setShowWizard(false)
            showToast('项目创建成功！')
            loadProjects()
          }}
        />
      )}
    </div>
  )
}
