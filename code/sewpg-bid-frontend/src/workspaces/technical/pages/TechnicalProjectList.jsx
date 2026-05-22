import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { projectsAPI } from '../../../api'
import Pagination from '../../../components/shared/Pagination'
import ProjectWizardModal from '../../../components/modals/ProjectWizardModal'
import { PageLoading, PageEmpty, PageError } from '../components/TechnicalPageState'
import { getCompactStageLabel, getStageRoute } from '../../../utils/stageFlow'
import { bidTypeFromWorkspace, parseRouteFromBidType, projectRoute, useWorkspaceSlug } from '../../../utils/workspace'

const STATUS_FILTER_LABELS = {
  all: '所有状态',
  active: '编写中',
  review: '审批中',
  completed: '已完成',
  archived: '已归档',
}

const DATE_FILTER_LABELS = {
  all: '时间范围',
  '7d': '最近7天',
  '30d': '最近30天',
  quarter: '本季度',
}

const PROJECT_FILTER_SELECT_CLASS = 'h-[34px] w-full min-h-0 appearance-none rounded-md border border-outline-variant/80 bg-white px-3.5 pr-9 text-[14px] text-on-surface transition-colors focus:ring-0 cursor-pointer hover:border-primary/35'

function ProjectFilterSelect({ value, onChange, ariaLabel, children, className = '' }) {
  return (
    <div className={`relative min-w-[160px] sm:min-w-[176px] ${className}`.trim()}>
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={onChange}
        className={PROJECT_FILTER_SELECT_CLASS}
      >
        {children}
      </select>
      <span className="material-symbols-outlined pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[18px] text-primary">
        arrow_drop_down
      </span>
    </div>
  )
}

function ProjectFilterChip({ label, onClear }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/15 bg-primary-fixed px-2.5 py-1 text-xs font-semibold text-primary">
      {label}
      <button
        type="button"
        aria-label={`清除筛选 ${label}`}
        onClick={onClear}
        className="grid h-4 w-4 place-items-center rounded-full text-primary hover:bg-white/70 hover:text-error"
      >
        <span className="material-symbols-outlined text-[13px]">close</span>
      </button>
    </span>
  )
}

export default function ProjectList({ showToast, viewMode = 'projects' }) {
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const lockedBidType = bidTypeFromWorkspace(workspaceSlug)
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
  const effectiveBidType = lockedBidType || (bidTypeFilter !== 'all' ? bidTypeFilter : '')
  const pageTitle = lockedBidType
    ? `${lockedBidType}${viewMode === 'flow' ? '撰写流程' : '项目'}`
    : '全部项目'
  const pageDescription = lockedBidType
    ? `当前工作区只展示${lockedBidType}项目，素材库、Wiki 和日志也按同一标类隔离。`
    : '集中查看技术标与商务标项目，按状态、类型和时间范围快速定位。'

  const loadProjects = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await projectsAPI.list({
        status: statusFilter !== 'all' ? statusFilter : '',
        bidType: effectiveBidType,
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
  }, [currentPage, dateFilter, effectiveBidType, pagination.pageSize, statusFilter])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjects()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProjects])

  const getProjectEntryRoute = (project) => {
    const reviewDecision = String(project?.reviewDecision || 'participate')
    if (reviewDecision !== 'participate') return parseRouteFromBidType(project?.bidType || '技术标', project?.id || '')
    const stage = Number(project?.currentStage) || 1
    const stageRoute = getStageRoute(project?.id, stage, workspaceSlug)
    if (stageRoute) return stageRoute
    return projectRoute(project.id, '', workspaceSlug)
  }

  const formatDateTime = (value) => {
    if (!value) return '-'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return String(value)
    const pad = (num) => String(num).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  }

  const formatDate = (value) => {
    if (!value) return '-'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return String(value)
    const pad = (num) => String(num).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  }

  const handleDelete = async (projectId) => {
    const project = projects.find((item) => item.id === projectId)
    const label = project?.name || projectId
    const confirmed = window.confirm(`确认删除项目「${label}」？\n\n删除后该项目相关流程数据将不可恢复。`)
    if (!confirmed) {
      setActiveMenuId('')
      return
    }
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

  useEffect(() => {
    if (!activeMenuId) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setActiveMenuId('')
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [activeMenuId])

  const openProject = (project) => {
    navigate(getProjectEntryRoute(project))
  }

  const hasActiveFilters = statusFilter !== 'all'
    || (!lockedBidType && bidTypeFilter !== 'all')
    || dateFilter !== 'all'

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
    <div className="project-list-page flex h-full min-h-0 max-w-none flex-col gap-4 animate-fade-in bg-transparent">
      <div className="command-surface rounded-xl px-5 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-headline font-bold text-ink-strong">
                {pageTitle}
              </h1>
              <span className="rounded-full bg-primary-fixed px-2.5 py-1 text-xs font-semibold text-primary">
                {pagination.total || projects.length} 项
              </span>
            </div>
            <p className="text-sm text-on-surface-variant">
              {pageDescription}
            </p>
          </div>
          <button
            onClick={() => setShowWizard(true)}
            className="command-button command-button-primary h-9 self-start lg:self-auto"
          >
            <span className="material-symbols-outlined text-lg">add</span>
            新建项目
          </button>
        </div>
      </div>

      {/* Project Table */}
      {!projects.length ? (
        <PageEmpty
          title="当前没有项目数据"
          description="你可以先创建一个项目，或者调整筛选条件后重试。"
          actionText="重新加载"
          onAction={loadProjects}
        />
      ) : (
        <>
        <section className="project-list-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-outline-variant/55 bg-white shadow-[0_18px_40px_-34px_rgba(13,33,55,0.35)]">
          <div className="flex flex-col gap-3 border-b border-outline-variant/45 bg-surface-container-lowest px-4 py-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-3">
                <span className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-on-surface-variant whitespace-nowrap">
                  <span className="material-symbols-outlined text-[17px] text-primary">tune</span>
                  筛选
                </span>
                <ProjectFilterSelect
                  value={statusFilter}
                  ariaLabel="项目状态筛选"
                  onChange={(e) => {
                    setStatusFilter(e.target.value)
                    setCurrentPage(1)
                  }}
                >
                  <option value="all">所有状态</option>
                  <option value="active">编写中</option>
                  <option value="review">审批中</option>
                  <option value="completed">已完成</option>
                  <option value="archived">已归档</option>
                </ProjectFilterSelect>
                {!lockedBidType && (
                  <ProjectFilterSelect
                    value={bidTypeFilter}
                    ariaLabel="标书类型筛选"
                    onChange={(e) => {
                      setBidTypeFilter(e.target.value)
                      setCurrentPage(1)
                    }}
                  >
                    <option value="all">全部类型</option>
                    <option value="技术标">技术标</option>
                    <option value="商务标">商务标</option>
                  </ProjectFilterSelect>
                )}
                <ProjectFilterSelect
                  value={dateFilter}
                  ariaLabel="项目时间范围筛选"
                  onChange={(e) => {
                    setDateFilter(e.target.value)
                    setCurrentPage(1)
                  }}
                >
                  <option value="all">时间范围</option>
                  <option value="7d">最近7天</option>
                  <option value="30d">最近30天</option>
                  <option value="quarter">本季度</option>
                </ProjectFilterSelect>
              </div>
              <div className="flex items-center justify-between gap-3 text-xs text-on-surface-variant xl:justify-end">
                <span className="whitespace-nowrap">
                  共 <span className="font-mono font-semibold text-ink-strong tabular-nums">{pagination.total || projects.length}</span> 个项目
                </span>
                {hasActiveFilters && (
                  <button
                    type="button"
                    className="command-button command-button-secondary !min-h-[30px] !px-3 text-xs"
                    onClick={() => {
                      setStatusFilter('all')
                      setBidTypeFilter('all')
                      setDateFilter('all')
                      setCurrentPage(1)
                    }}
                  >
                    清除筛选
                  </button>
                )}
              </div>
            </div>

            {hasActiveFilters && (
              <div className="flex flex-wrap items-center gap-2">
                {statusFilter !== 'all' && (
                  <ProjectFilterChip
                    label={`状态: ${STATUS_FILTER_LABELS[statusFilter] || statusFilter}`}
                    onClear={() => {
                      setStatusFilter('all')
                      setCurrentPage(1)
                    }}
                  />
                )}
                {!lockedBidType && bidTypeFilter !== 'all' && (
                  <ProjectFilterChip
                    label={`标书类型: ${bidTypeFilter}`}
                    onClear={() => {
                      setBidTypeFilter('all')
                      setCurrentPage(1)
                    }}
                  />
                )}
                {dateFilter !== 'all' && (
                  <ProjectFilterChip
                    label={`时间: ${DATE_FILTER_LABELS[dateFilter] || dateFilter}`}
                    onClear={() => {
                      setDateFilter('all')
                      setCurrentPage(1)
                    }}
                  />
                )}
              </div>
            )}
          </div>

          <div className="grid gap-3 p-3 md:hidden">
            {projects.map((project) => (
              <article
                key={project.id}
                role="link"
                tabIndex={0}
                aria-label={`打开项目 ${project.name || project.id}`}
                onClick={() => openProject(project)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') openProject(project)
                }}
                className="interactive-lift rounded-lg border border-outline-variant/55 bg-white p-4 outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-medium text-outline">{project.id}</span>
                      <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${String(project.bidType || '').includes('商务') ? 'bg-secondary-container text-on-secondary-container' : 'bg-primary-fixed text-primary'}`}>
                        {project.bidType || '-'}
                      </span>
                    </div>
                    <h2 className="mt-2 line-clamp-2 text-[15px] font-semibold leading-snug text-ink-strong">
                      {project.name || '-'}
                    </h2>
                  </div>
                  <button
                    type="button"
                    aria-label={`打开 ${project.name || project.id} 的操作菜单`}
                    className="shrink-0 rounded-md px-1 text-on-surface-variant hover:bg-surface-container-low hover:text-primary"
                    onClick={(event) => {
                      event.stopPropagation()
                      setActiveMenuId(activeMenuId === project.id ? '' : project.id)
                    }}
                  >
                    <span className="material-symbols-outlined text-[20px]">more_vert</span>
                  </button>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-on-surface-variant">
                  <div className="min-w-0">
                    <div className="text-outline">业主</div>
                    <div className="mt-0.5 truncate text-on-surface">{project.owner || project.customerName || '-'}</div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-outline">负责人</div>
                    <div className="mt-0.5 truncate text-on-surface">{project.manager || '-'}</div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-outline">截止日期</div>
                    <div className="mt-0.5 font-mono text-on-surface tabular-nums">{formatDate(project.endDate || project.deadline)}</div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-outline">更新时间</div>
                    <div className="mt-0.5 font-mono text-on-surface tabular-nums">{formatDateTime(project.updatedAt)}</div>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between gap-3 border-t border-outline-variant/45 pt-3">
                  <span className="inline-flex min-w-0 items-center gap-1.5 rounded-full bg-surface-container-low px-2 py-0.5 text-xs font-semibold text-on-surface-variant">
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span className="truncate">{getCompactStageLabel(project.currentStage, project.stageLabel || '-')}</span>
                  </span>
                  <span className="material-symbols-outlined shrink-0 text-outline">arrow_forward</span>
                </div>

                {activeMenuId === project.id && (
                  <div className="mt-3 rounded-md border border-error/20 bg-error-container/20 p-1" onClick={(event) => event.stopPropagation()}>
                    <button
                      type="button"
                      className="flex h-9 w-full items-center justify-center rounded text-sm font-semibold text-error hover:bg-error-container/50 disabled:opacity-50"
                      disabled={actionLoadingId === project.id}
                      onClick={() => handleDelete(project.id)}
                    >
                      删除项目
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>

          <div className="hidden min-h-0 flex-1 flex-col md:flex">
            <div className="overflow-x-auto overflow-y-auto flex-1 min-h-0">
              <table className="project-table w-full min-w-[1040px] xl:min-w-[1180px]">
                <colgroup>
                  <col className="w-[112px]" />
                  <col />
                  <col className="w-[130px]" />
                  <col className="w-[104px]" />
                  <col className="w-[88px]" />
                  <col className="w-[128px]" />
                  <col className="w-[108px]" />
                  <col className="w-[108px]" />
                  <col className="w-[128px]" />
                  <col className="w-[72px]" />
                </colgroup>
                <thead>
                  <tr>
                    <th className="px-4 text-left text-[14px]">项目编号</th>
                    <th className="px-4 text-left text-[14px]">项目名称</th>
                    <th className="px-4 text-left text-[14px]">业主</th>
                    <th className="px-4 text-left text-[14px]">负责人</th>
                    <th className="px-3 text-left text-[14px]">标书类型</th>
                    <th className="px-4 text-left text-[14px]">当前阶段</th>
                    <th className="px-3 text-left text-[14px]">起始日期</th>
                    <th className="px-3 text-left text-[14px]">截止日期</th>
                    <th className="px-3 text-left text-[14px]">更新时间</th>
                    <th className="px-3 text-center text-[14px]">操作</th>
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
                        aria-label={`打开项目 ${project.name || project.id}`}
                        onClick={() => openProject(project)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') openProject(project)
                        }}
                      >
                        <td className="px-4 text-[14px] text-on-surface-variant font-mono font-medium whitespace-nowrap">{project.id}</td>
                        <td className="px-4 text-[14px] text-on-surface">
                          <div className="font-semibold text-ink-strong leading-snug line-clamp-2">{project.name || '-'}</div>
                        </td>
                        <td className="px-4 text-[14px] text-on-surface-variant">
                          <span className="block truncate">{project.owner || project.customerName || '-'}</span>
                        </td>
                        <td className="px-4 text-[14px] text-on-surface-variant">
                          <span className="block truncate">{project.manager || '-'}</span>
                        </td>
                        <td className="px-3 text-[14px] text-on-surface-variant">
                          <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${String(project.bidType || '').includes('商务') ? 'bg-secondary-container text-on-secondary-container' : 'bg-primary-fixed text-primary'}`}>
                            {project.bidType || '-'}
                          </span>
                        </td>
                        <td className="px-4 text-[14px] text-on-surface">
                          <span className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-surface-container-low px-2 py-0.5 text-xs font-semibold text-on-surface-variant">
                            <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                            <span className="truncate">{getCompactStageLabel(project.currentStage, project.stageLabel || '-')}</span>
                          </span>
                        </td>
                        <td className="px-3 text-[14px] text-on-surface-variant whitespace-nowrap font-mono tabular-nums">{formatDate(project.startDate)}</td>
                        <td className="px-3 text-[14px] text-on-surface-variant whitespace-nowrap font-mono tabular-nums">{formatDate(project.endDate || project.deadline)}</td>
                        <td className="px-3 text-[14px] text-on-surface-variant whitespace-nowrap font-mono tabular-nums">{formatDateTime(project.updatedAt)}</td>
                        <td className="px-3 text-center relative">
                          <button
                            className="px-1 py-0 !border-0 !bg-transparent text-on-surface-variant hover:text-primary transition-colors"
                            type="button"
                            aria-label={`打开 ${project.name || project.id} 的操作菜单`}
                            aria-haspopup="menu"
                            aria-expanded={menuOpen}
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
                              role="menu"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <button
                                type="button"
                                role="menuitem"
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
          </div>

          <div className="border-t border-outline-variant/45 px-4 py-3">
            <Pagination
              current={pagination.page}
              total={Math.max(1, Math.ceil((pagination.total || projects.length) / (pagination.pageSize || 12)))}
              onPageChange={setCurrentPage}
            />
          </div>
        </section>
        </>
      )}

      {/* New Project Wizard Modal */}
      {showWizard && (
        <ProjectWizardModal
          onClose={() => setShowWizard(false)}
          defaultBidType={lockedBidType || undefined}
          lockBidType={Boolean(lockedBidType)}
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
