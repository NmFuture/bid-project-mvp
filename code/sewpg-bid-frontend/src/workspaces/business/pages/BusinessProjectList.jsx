import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { businessProjectsAPI } from '../../../api'
import FilterBar from '../../../components/shared/FilterBar'
import Pagination from '../../../components/shared/Pagination'
import PageHeader from '../../../components/shared/PageHeader'
import { PageEmpty, PageError, PageLoading } from '../../../components/states/PageState'
import Button from '../../../components/ui/Button'
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
    <div className="project-list-page flex min-h-0 w-full flex-col gap-4 animate-fade-in">
      <PageHeader
        variant="panel"
        title="商务标项目"
        description="当前工作区只展示商务标项目，素材库、Wiki 和日志也按商务标隔离。"
        actions={(
          <Button
            type="button"
            onClick={() => setShowWizard(true)}
            className="w-full sm:w-48"
            size="stage"
          >
            新建商务标项目
          </Button>
        )}
      />

      <FilterBar
        className="mt-0"
        left={(
          <>
            <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 md:flex md:w-auto md:items-center">
              <label className="relative min-w-0 sm:min-w-[170px]">
                <span className="sr-only">项目状态</span>
                <select
                  aria-label="项目状态"
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value)
                    setCurrentPage(1)
                  }}
                  className="h-11 w-full appearance-none rounded-md border border-control-muted-border-strong bg-white px-3.5 pr-9 text-base text-on-surface transition-colors focus:ring-2 focus:ring-primary/20 sm:h-10 sm:text-sm"
                >
                  <option value="all">所有状态</option>
                  <option value="active">编写中</option>
                  <option value="review">审批中</option>
                  <option value="completed">已完成</option>
                  <option value="archived">已归档</option>
                </select>
                <span aria-hidden="true" className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary">arrow_drop_down</span>
              </label>
              <label className="relative min-w-0 sm:min-w-[170px]">
                <span className="sr-only">时间范围</span>
              <select
                aria-label="时间范围"
                value={dateFilter}
                onChange={(e) => {
                  setDateFilter(e.target.value)
                  setCurrentPage(1)
                }}
                className="h-11 w-full appearance-none rounded-md border border-control-muted-border-strong bg-white px-3.5 pr-9 text-base text-on-surface transition-colors focus:ring-2 focus:ring-primary/20 sm:h-10 sm:text-sm"
              >
                <option value="all">时间范围</option>
                <option value="7d">最近7天</option>
                <option value="30d">最近30天</option>
                <option value="quarter">本季度</option>
              </select>
                <span aria-hidden="true" className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-secondary">arrow_drop_down</span>
              </label>
            </div>
          </>
        )}
      />

      {statusFilter !== 'all' && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-secondary-container text-on-secondary-container text-xs font-medium border border-secondary/25">
            <span>状态: {statusFilter === 'active' ? '编写中' : statusFilter === 'review' ? '审批中' : statusFilter === 'completed' ? '已完成' : '已归档'}</span>
            <button type="button" aria-label="清除状态筛选" onClick={() => {
              setStatusFilter('all')
              setCurrentPage(1)
            }} className="hover:text-error">
              <span aria-hidden="true" className="material-symbols-outlined text-sm">close</span>
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
        <div className="mt-2 flex min-h-0 flex-1 flex-col gap-3">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,22rem),1fr))] gap-3 xl:hidden" aria-label="商务标项目列表">
            {projects.map((project) => {
              const isActionLoading = actionLoadingId === project.id
              const details = [
                ['项目编号', project.id],
                ['业主', project.owner || project.customerName || '-'],
                ['负责人', project.manager || '-'],
                ['标书类型', project.bidType || BUSINESS_BID_TYPE],
                ['当前阶段', stageLabelForProject(project)],
                ['起始日期', project.startDate || '-'],
                ['截止日期', project.endDate || project.deadline || '-'],
                ['更新时间', formatDateTime(project.updatedAt)],
              ]
              return (
                <article key={project.id} className="overflow-hidden rounded-md border border-outline-variant/60 bg-surface-container-lowest shadow-[0_1px_2px_rgba(13,33,55,0.06)]">
                  <div className="border-b border-outline-variant/45 px-4 py-3">
                    <button
                      type="button"
                      onClick={() => openProject(project)}
                      className="min-h-10 w-full break-words text-left text-base font-semibold text-on-surface hover:text-primary"
                    >
                      {project.name || '-'}
                    </button>
                  </div>
                  <dl className="grid grid-cols-1 gap-x-4 gap-y-3 px-4 py-3 min-[430px]:grid-cols-2">
                    {details.map(([label, value]) => (
                      <div key={label} className="min-w-0">
                        <dt className="text-xs font-medium text-on-surface-variant">{label}</dt>
                        <dd className="mt-1 break-words text-sm text-on-surface">{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <div className="grid grid-cols-1 gap-2 border-t border-outline-variant/45 bg-surface-container-low/55 p-3 min-[430px]:grid-cols-3">
                    <Button onClick={() => openProject(project)} className="w-full">
                      打开项目
                    </Button>
                    <Button variant="quiet" onClick={(event) => openParseResult(project.id, event)} className="w-full">
                      查看解析
                    </Button>
                    <Button variant="dangerQuiet" disabled={isActionLoading} onClick={() => handleDelete(project.id)} className="w-full">
                      {isActionLoading ? '删除中…' : '删除项目'}
                    </Button>
                  </div>
                </article>
              )
            })}
          </div>

          <div className="project-table-frame hidden min-h-0 flex-1 flex-col border border-outline-variant/50 bg-surface-container-lowest xl:flex">
            <div className="min-h-0 flex-1 overflow-x-auto overflow-y-auto" tabIndex={0} aria-label="商务标项目数据表，可水平滚动">
            <table className="w-full min-w-[1180px]">
              <thead>
                <tr>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">项目编号</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">项目名称</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">业主</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">负责人</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">标书类型</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">当前阶段</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">起始日期</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">截止日期</th>
                  <th scope="col" className="whitespace-nowrap px-4 text-left text-sm">更新时间</th>
                  <th scope="col" className="w-[80px] px-4 text-center text-sm">操作</th>
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
                      <td className="whitespace-nowrap px-4 text-sm font-medium text-on-surface-variant">{project.id}</td>
                      <td className="max-w-[20rem] px-4 text-sm text-on-surface"><span className="block truncate" title={project.name || '-'}>{project.name || '-'}</span></td>
                      <td className="max-w-[16rem] px-4 text-sm text-on-surface-variant"><span className="block truncate" title={project.owner || project.customerName || '-'}>{project.owner || project.customerName || '-'}</span></td>
                      <td className="whitespace-nowrap px-4 text-sm text-on-surface-variant">{project.manager || '-'}</td>
                      <td className="whitespace-nowrap px-4 text-sm text-on-surface-variant">{project.bidType || BUSINESS_BID_TYPE}</td>
                      <td className="whitespace-nowrap px-4 text-sm text-on-surface">
                        {stageLabelForProject(project)}
                      </td>
                      <td className="whitespace-nowrap px-4 text-sm text-on-surface-variant">{project.startDate || '-'}</td>
                      <td className="whitespace-nowrap px-4 text-sm text-on-surface-variant">{project.endDate || project.deadline || '-'}</td>
                      <td className="whitespace-nowrap px-4 text-sm text-on-surface-variant">{formatDateTime(project.updatedAt)}</td>
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

          </div>
          <div className="rounded-md border border-outline-variant/45 bg-surface-container-lowest px-3 py-3 md:border-t md:px-4">
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
