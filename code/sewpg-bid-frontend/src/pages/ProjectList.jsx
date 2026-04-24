import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { projectsAPI } from '../api'
import Pagination from '../components/shared/Pagination'
import ProjectWizardModal from '../components/modals/ProjectWizardModal'
import { PageLoading, PageEmpty, PageError } from '../components/states/PageState'
import FilterBar from '../components/shared/FilterBar'
import { getStageRoute } from '../utils/stageFlow'

export default function ProjectList({ showToast }) {
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [bidTypeFilter, setBidTypeFilter] = useState('all')
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
        bidType: bidTypeFilter !== 'all' ? bidTypeFilter : '',
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
  }, [bidTypeFilter, currentPage, dateFilter, pagination.pageSize, statusFilter])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjects()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProjects])

  const getProjectEntryRoute = (project) => {
    const reviewDecision = String(project?.reviewDecision || 'participate')
    if (reviewDecision !== 'participate') return `/review?projectId=${project?.id || ''}`
    const stage = Number(project?.currentStage) || 1
    const stageRoute = getStageRoute(project?.id, stage)
    if (stageRoute) return stageRoute
    return `/projects/${project.id}`
  }

  const formatDateTime = (value) => {
    if (!value) return '-'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return String(value)
    const pad = (num) => String(num).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
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
    <div className="project-list-page flex flex-col gap-4 max-w-none mx-auto animate-fade-in h-full min-h-0 bg-white">
      {/* Filter Bar */}
      <FilterBar
        className="mt-0"
        left={(
          <>
            <div className="flex items-center gap-2">
              <span className="text-[14px] text-on-surface-variant whitespace-nowrap">筛选</span>
              <div className="relative min-w-[170px]">
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value)
                    setCurrentPage(1)
                  }}
                  className="w-full min-h-0 h-[30px] appearance-none bg-[#e8eef2] border border-[#c3ced8] px-3.5 pr-9 text-[14px] text-on-surface focus:ring-0 transition-all cursor-pointer"
                >
                  <option value="all">所有状态</option>
                  <option value="active">编写中</option>
                  <option value="review">审批中</option>
                  <option value="completed">已完成</option>
                  <option value="archived">已归档</option>
                </select>
                <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-[#14A83B]">arrow_drop_down</span>
              </div>
            </div>
            <div className="relative min-w-[170px]">
              <select
                value={bidTypeFilter}
                onChange={(e) => {
                  setBidTypeFilter(e.target.value)
                  setCurrentPage(1)
                }}
                className="w-full min-h-0 h-[30px] appearance-none bg-[#e8eef2] border border-[#c3ced8] px-3.5 pr-9 text-[14px] text-on-surface focus:ring-0 transition-all cursor-pointer"
              >
                <option value="all">全部类型</option>
                <option value="技术标">技术标</option>
                <option value="商务标">商务标</option>
              </select>
              <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-[#14A83B]">arrow_drop_down</span>
            </div>
            <div className="relative min-w-[170px]">
              <select
                value={dateFilter}
                onChange={(e) => {
                  setDateFilter(e.target.value)
                  setCurrentPage(1)
                }}
                className="w-full min-h-0 h-[30px] appearance-none bg-[#e8eef2] border border-[#c3ced8] px-3.5 pr-9 text-[14px] text-on-surface focus:ring-0 transition-all cursor-pointer"
              >
                <option value="all">时间范围</option>
                <option value="7d">最近7天</option>
                <option value="30d">最近30天</option>
                <option value="quarter">本季度</option>
              </select>
              <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-[#14A83B]">arrow_drop_down</span>
            </div>
          </>
        )}
        right={(
          <button
            onClick={() => setShowWizard(true)}
            className="h-[30px] px-4 flex items-center gap-1.5 bg-[#0067B6] text-on-primary font-semibold border border-[#0f77c4] hover:bg-[#0b74c8] transition-colors"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            新建项目
          </button>
        )}
      />

      {/* Active Filter Tags */}
      {statusFilter !== 'all' && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-secondary-container text-on-secondary-container text-xs font-medium border border-secondary/25">
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
      {bidTypeFilter !== 'all' && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-secondary-container text-on-secondary-container text-xs font-medium border border-secondary/25">
            <span>标书类型: {bidTypeFilter}</span>
            <button onClick={() => {
              setBidTypeFilter('all')
              setCurrentPage(1)
            }} className="hover:text-error">
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        </div>
      )}

      {/* Project Table */}
      {!projects.length ? (
        <PageEmpty
          title="当前没有项目数据"
          description="你可以先创建一个项目，或者调整筛选条件后重试。"
          actionText="重新加载"
          onAction={loadProjects}
        />
      ) : (
        <div className="project-table-frame mt-2 bg-surface-container-lowest border border-outline-variant/50 flex-1 min-h-0 flex flex-col">
          <div className="overflow-x-auto overflow-y-auto flex-1 min-h-0">
            <table className="w-full min-w-[1080px]">
              <thead>
                <tr>
                  <th className="px-6 text-left text-[14px]">项目编号</th>
                  <th className="px-6 text-left text-[14px]">项目名称</th>
                  <th className="px-6 text-left text-[14px]">业主</th>
                  <th className="px-6 text-left text-[14px]">负责人</th>
                  <th className="px-6 text-left text-[14px]">标书类型</th>
                  <th className="px-6 text-left text-[14px]">当前阶段</th>
                  <th className="px-6 text-left text-[14px]">截止日期</th>
                  <th className="px-6 text-left text-[14px]">更新时间</th>
                  <th className="px-4 text-center text-[14px] w-[80px]">操作</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((project) => {
                  const isActionLoading = actionLoadingId === project.id
                  const menuOpen = activeMenuId === project.id
                  return (
                    <tr
                      key={project.id}
                      className="cursor-pointer"
                      onClick={() => navigate(getProjectEntryRoute(project))}
                    >
                      <td className="px-6 text-[14px] text-on-surface-variant font-medium">{project.id}</td>
                      <td className="px-6 text-[14px] text-on-surface">{project.name || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.owner || project.customerName || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.manager || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.bidType || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface">{project.stageLabel || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.deadline || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{formatDateTime(project.updatedAt)}</td>
                      <td className="px-4 text-center relative">
                        <button
                          className="px-1 py-0 !border-0 !bg-transparent text-on-surface-variant hover:text-primary transition-colors"
                          onClick={(e) => {
                            e.stopPropagation()
                            setActiveMenuId(menuOpen ? '' : project.id)
                          }}
                        >
                          <span className="material-symbols-outlined text-[20px]">more_vert</span>
                        </button>
                        {menuOpen && (
                          <div
                            className="absolute right-2 top-10 w-32 bg-surface-container-lowest border border-surface-container-high z-20 py-1 shadow-[0_1px_2px_rgba(11,27,44,0.08)]"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <button
                              className="w-full text-left px-3 py-1.5 text-sm text-error hover:bg-error-container/20 transition-colors disabled:opacity-50"
                              disabled={isActionLoading}
                              onClick={() => handleDelete(project.id)}
                            >
                              删除项目
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="border-t border-outline-variant/45 px-4 py-3">
            <Pagination
              current={pagination.page}
              total={Math.max(1, Math.ceil((pagination.total || projects.length) / (pagination.pageSize || 12)))}
              onPageChange={setCurrentPage}
            />
          </div>
        </div>
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
