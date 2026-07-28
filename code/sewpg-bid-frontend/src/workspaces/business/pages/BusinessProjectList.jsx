import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { businessProjectsAPI } from '../../../api'
import FilterBar from '../../../components/shared/FilterBar'
import Pagination from '../../../components/shared/Pagination'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import { projectRoute } from '../../../utils/workspace'
import { getBusinessCompactStageLabel, getBusinessStageRoute } from '../businessStageFlow'
import { businessProjectParseResultMenuRoute } from '../businessProjectRoutes'
import BusinessProjectWizardModal from './BusinessProjectWizardModal'
import ProjectActionMenu from '../../shared/components/ProjectActionMenu'

const BUSINESS_BID_TYPE = '商务标'
const BUSINESS_WORKSPACE = 'business'

const businessParseRoute = (projectId = '') => {
  if (!projectId) return '/parse/business'
  return `/parse/business?projectId=${encodeURIComponent(projectId)}`
}

// 与 EntryRedirect 保持一致：阶段值 clamp 到 1-6，异常值不落到空路由
const resolveStage = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 1
  return Math.max(1, Math.min(6, Math.floor(parsed)))
}

const formatDateTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (num) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export default function BusinessProjectList({ showToast }) {
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
      const data = await businessProjectsAPI.list({
        status: statusFilter !== 'all' ? statusFilter : '',
        bidType: BUSINESS_BID_TYPE,
        reviewDecision: 'participate',
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
      setError(e?.message || '商务标项目列表加载失败')
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

  const getProjectEntryRoute = (project) => {
    const reviewDecision = String(project?.reviewDecision || 'participate')
    if (reviewDecision !== 'participate') return businessParseRoute(project?.id || '')
    const stage = resolveStage(project?.currentStage)
    const stageRoute = getBusinessStageRoute(project?.id, stage)
    if (stageRoute) return stageRoute
    return projectRoute(project.id, '', BUSINESS_WORKSPACE)
  }

  const openProject = (project) => {
    navigate(getProjectEntryRoute(project))
  }

  const openParseResult = (projectId, event = null) => {
    setActiveMenuId('')
    navigate(businessProjectParseResultMenuRoute(projectId, event))
  }

  const stageLabelForProject = (project) =>
    getBusinessCompactStageLabel(project.currentStage, project.stageLabel || '-')

  const handleDelete = async (projectId) => {
    const project = projects.find((item) => item.id === projectId)
    const label = project?.name || projectId
    const confirmed = window.confirm(`确认删除商务标项目「${label}」？\n\n删除后该项目相关流程数据将不可恢复。`)
    if (!confirmed) {
      setActiveMenuId('')
      return
    }
    setActionLoadingId(projectId)
    try {
      await businessProjectsAPI.delete(projectId)
      showToast('商务标项目已删除')
      await loadProjects()
    } catch (e) {
      if (e?.status === 404) {
        showToast('删除失败：商务标项目不存在或已被移除，请刷新列表后重试。', 'error')
      } else if (e?.code === 'NETWORK_ERROR' || e?.code === 'TIMEOUT') {
        showToast('删除失败：接口不可达，请先确认正式 FastAPI 后端已启动。', 'error')
      } else {
        showToast(e?.message || '删除商务标项目失败', 'error')
      }
    } finally {
      setActionLoadingId('')
      setActiveMenuId('')
    }
  }

  if (loading) {
    return <PageLoading title="正在加载商务标项目..." />
  }

  if (error) {
    return (
      <PageError
        title="商务标项目加载失败"
        description={error}
        onRetry={loadProjects}
      />
    )
  }

  return (
    <div className="project-list-page flex flex-col gap-4 max-w-none mx-auto animate-fade-in h-full min-h-0 bg-white">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-headline font-bold text-primary">商务标项目</h1>
        <p className="text-sm text-on-surface-variant">
          当前工作区只展示商务标项目，素材库、Wiki 和日志也按商务标隔离。
        </p>
      </div>

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
            新建商务标项目
          </button>
        )}
      />

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

      {!projects.length ? (
        <PageEmpty
          title="当前没有商务标项目"
          description="你可以先创建一个商务标项目，或者调整筛选条件后重试。"
          actionText="重新加载"
          onAction={loadProjects}
        />
      ) : (
        <div className="project-table-frame mt-2 bg-surface-container-lowest border border-outline-variant/50 flex-1 min-h-0 flex flex-col">
          <div className="overflow-x-auto overflow-y-auto flex-1 min-h-0">
            <table className="w-full min-w-[1180px]">
              <thead>
                <tr>
                  <th className="px-6 text-left text-[14px]">项目编号</th>
                  <th className="px-6 text-left text-[14px]">项目名称</th>
                  <th className="px-6 text-left text-[14px]">业主</th>
                  <th className="px-6 text-left text-[14px]">负责人</th>
                  <th className="px-6 text-left text-[14px]">标书类型</th>
                  <th className="px-6 text-left text-[14px]">当前阶段</th>
                  <th className="px-6 text-left text-[14px]">起始日期</th>
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
                      className="project-row"
                      tabIndex={0}
                      role="link"
                      aria-label={`打开商务标项目 ${project.name || project.id}`}
                      onClick={() => openProject(project)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') openProject(project)
                      }}
                    >
                      <td className="px-6 text-[14px] text-on-surface-variant font-medium">{project.id}</td>
                      <td className="px-6 text-[14px] text-on-surface">{project.name || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.owner || project.customerName || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.manager || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.bidType || BUSINESS_BID_TYPE}</td>
                      <td className="px-6 text-[14px] text-on-surface">
                        {stageLabelForProject(project)}
                      </td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.startDate || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{project.endDate || project.deadline || '-'}</td>
                      <td className="px-6 text-[14px] text-on-surface-variant">{formatDateTime(project.updatedAt)}</td>
                      <td className="px-4 text-center">
                        <ProjectActionMenu
                          project={project}
                          open={menuOpen}
                          loading={isActionLoading}
                          onToggle={() => setActiveMenuId(menuOpen ? '' : project.id)}
                          onClose={() => setActiveMenuId('')}
                          onViewParseResult={(event) => openParseResult(project.id, event)}
                          onDelete={() => handleDelete(project.id)}
                        />
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

      {showWizard && (
        <BusinessProjectWizardModal
          onClose={() => setShowWizard(false)}
          onCreated={() => {
            setShowWizard(false)
            showToast('商务标项目创建成功！')
            loadProjects()
          }}
        />
      )}
    </div>
  )
}
