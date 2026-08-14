import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { dashboardAPI } from '../api'
import { usePageData } from '../utils/pageCache'
import { workspaceRoute } from '../utils/workspace'
import StatusBadge from '../components/shared/StatusBadge'
import RoleChip from '../components/shared/RoleChip'
import EmptyState from '../components/shared/EmptyState'
import PageHeader from '../components/shared/PageHeader'
import Skeleton, { SkeletonCard } from '../components/shared/Skeleton'
import Button from '../components/ui/Button'

const METRIC_TONE = {
  primary: 'bg-primary-fixed text-primary',
  success: 'bg-secondary-fixed text-secondary',
  warn: 'bg-tertiary-fixed text-on-tertiary-fixed-variant',
  error: 'bg-error-container text-error',
  info: 'bg-ai-accent-light text-tertiary',
}

const fmtPct = (p) => `${Math.round((p || 0) * 100)}%`

const formatCurrentTime = (date) => {
  const pad = (value) => String(value).padStart(2, '0')
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${weekdays[date.getDay()]} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function Greeting({ name, role }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <PageHeader
      variant="panel"
      title="工作台"
      description={`${name}，欢迎回来`}
      actions={(
        <div className="flex w-full flex-wrap items-center gap-3 text-xs text-on-surface-variant md:w-auto md:justify-end">
          {role && <RoleChip role={role} />}
          <time dateTime={now.toISOString()}>{formatCurrentTime(now)}</time>
        </div>
      )}
    />
  )
}

function MetricCard({ metric }) {
  const tone = METRIC_TONE[metric.tone] || METRIC_TONE.primary
  return (
    <div className="flex min-h-[84px] items-center gap-3 rounded-lg border border-outline-variant/70 bg-white px-4 py-3 shadow-[0_1px_2px_rgba(13,33,55,0.04)] lg:px-5">
      <span
        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md ${tone}`}
        aria-hidden="true"
      >
        <span
          className="material-symbols-outlined text-[20px]"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {metric.icon}
        </span>
      </span>
      <div className="min-w-0">
        <div className="text-xs font-medium text-on-surface-variant">{metric.label}</div>
        <div className="mt-0.5 flex items-baseline gap-2">
          <span className="text-[26px] font-headline font-semibold leading-none text-on-surface tabular-nums">
            {metric.value}
          </span>
          {metric.trend && <span className="text-xs text-outline">{metric.trend}</span>}
        </div>
      </div>
    </div>
  )
}

function ProjectCard({ project, workspaceSlug }) {
  const stagePct = project.progress
  const stageColor =
    stagePct >= 0.8
      ? 'bg-secondary'
      : stagePct >= 0.5
        ? 'bg-primary'
        : 'bg-tertiary'
  return (
    <Link
      to={workspaceRoute(workspaceSlug || project.workspace, `/projects/${project.id}`)}
      className="group block rounded-lg border border-outline-variant bg-white p-4 transition-colors hover:border-primary/60 hover:bg-primary-fixed/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-xs text-outline font-mono">{project.id}</span>
            {project.keyAccount && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-tertiary-container px-2 py-0.5 text-xs font-semibold text-on-tertiary-container">
                <span className="material-symbols-outlined text-[14px]" style={{ fontVariationSettings: "'FILL' 1" }} aria-hidden="true">
                  star
                </span>
                重要客户
              </span>
            )}
          </div>
          <h3 className="text-sm font-semibold text-on-surface line-clamp-2 group-hover:text-primary transition-colors">
            {project.name}
          </h3>
          <div className="mt-1 text-xs text-on-surface-variant">{project.customer}</div>
        </div>
        <span className="material-symbols-outlined text-outline transition-colors group-hover:text-primary" aria-hidden="true">
          arrow_forward
        </span>
      </div>

      <div className="mt-3 space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-1.5">
            <StatusBadge variant="running" icon={null}>
              {project.stage} · {project.stageLabel}
            </StatusBadge>
          </div>
          <span className="font-mono text-on-surface-variant tabular-nums">{fmtPct(stagePct)}</span>
        </div>
        <div className="h-1.5 w-full bg-surface-container-high rounded-full overflow-hidden">
          <div
            className={`h-full ${stageColor} transition-[width] duration-700`}
            style={{ width: `${stagePct * 100}%` }}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-outline">
        <span className="inline-flex items-center gap-1">
          <span className="material-symbols-outlined text-[14px]" aria-hidden="true">event</span>
          截止 {project.deadline}
        </span>
        <span>{project.updatedAt}</span>
      </div>
    </Link>
  )
}

function ParallelProjectCard({ project }) {
  const wsBlock = (kind, ws) => {
    if (!ws) {
      return (
        <div className="flex min-h-20 flex-1 items-center justify-center rounded-lg border border-dashed border-outline-variant/60 bg-surface-container-low/50 p-3 text-xs text-outline">
          {kind === 'tech' ? '本项目无技术标' : '本项目无商务标'}
        </div>
      )
    }
    return (
      <Link
        to={workspaceRoute(kind, `/projects/${project.id}`)}
        className="group min-w-0 flex-1 rounded-lg border border-outline-variant bg-white p-3 transition-colors hover:border-primary/60 hover:bg-primary-fixed/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        <div className="flex items-center gap-1.5 mb-1.5 text-xs">
          <span className="font-semibold text-on-surface">{kind === 'tech' ? '技术标' : '商务标'}</span>
          <StatusBadge variant={ws.status} icon={null} className="ml-auto">
            {ws.stage} · {ws.stageLabel}
          </StatusBadge>
        </div>
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-on-surface-variant">进度</span>
          <span className="font-mono text-on-surface tabular-nums">{fmtPct(ws.progress)}</span>
        </div>
        <div className="h-1.5 w-full bg-surface-container-high rounded-full overflow-hidden">
          <div
            className="h-full bg-primary transition-[width] duration-700"
            style={{ width: `${ws.progress * 100}%` }}
          />
        </div>
      </Link>
    )
  }

  return (
    <div className="rounded-lg border border-outline-variant bg-white p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-xs text-outline font-mono">{project.id}</span>
            <span className="text-xs text-outline">·</span>
            <span className="text-xs text-outline inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px]" aria-hidden="true">event</span>
              截止 {project.deadline}
            </span>
          </div>
          <h3 className="break-words text-sm font-semibold text-on-surface">{project.name}</h3>
          <div className="mt-0.5 break-words text-xs text-on-surface-variant">{project.customer}</div>
        </div>
      </div>
      <div className="flex flex-col items-stretch gap-3 sm:flex-row">
        {wsBlock('tech', project.tech)}
        {wsBlock('business', project.business)}
      </div>
    </div>
  )
}

function PanelHeader({ title, hint, action }) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <h2 className="text-lg font-headline font-semibold text-on-surface">{title}</h2>
        {hint && <span className="text-xs text-outline">{hint}</span>}
      </div>
      {action}
    </div>
  )
}

export default function Dashboard({ currentUser }) {
  const navigate = useNavigate()
  // 会话缓存：二次进入工作台直接渲染上次数据，后台静默刷新
  const { data, loading, error } = usePageData(
    `dashboard:${currentUser?.id || 'guest'}`,
    () => dashboardAPI.get(),
  )

  const role = data?.role || currentUser?.role
  const userName = currentUser?.name || '用户'

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-[1600px] space-y-4">
        <Skeleton className="h-[88px] w-full rounded-lg" />
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,16rem),1fr))] gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[84px] w-full rounded-lg" />
          ))}
        </div>
        <SkeletonCard />
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="mx-auto w-full max-w-[1600px]">
        <EmptyState
          icon="error"
          title="工作台加载失败"
          description={error}
          action={
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="min-h-11 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary transition-colors hover:bg-on-primary-fixed-variant focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
            >
              重新加载
            </button>
          }
        />
      </div>
    )
  }

  const isTB = role === 'TB'
  const projects = data?.projects || []
  const projectsParallel = data?.projectsParallel || []
  const metrics = (data?.metrics || []).filter((metric) => !['aiSaved', 'todo'].includes(metric.key))

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-4">
      <Greeting name={userName} role={role} />

      {/* 顶部统计 */}
      {metrics.length > 0 && (
        <section
          aria-label="项目概览"
          className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,16rem),1fr))] gap-3"
        >
          {metrics.map((m) => (
            <MetricCard key={m.key} metric={m} />
          ))}
        </section>
      )}

      {/* 项目列表 / 双流程并列 */}
      <section className="min-w-0 space-y-3">
          <PanelHeader
            title={isTB ? '在跑项目（双流程并列）' : `我负责的${role === 'B' ? '商务标' : '技术标'}项目`}
            hint={isTB ? `${projectsParallel.length} 个项目` : `${projects.length} 个项目`}
            action={
              (isTB ? projectsParallel.length : projects.length) > 0 ? (
                <button
                  type="button"
                  onClick={() => navigate(workspaceRoute(role === 'B' ? 'business' : 'tech', '/projects'))}
                  className="min-h-11 rounded-md px-2 text-sm font-medium text-primary hover:bg-primary-fixed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <span>查看全部</span>
                </button>
              ) : null
            }
          />
          {isTB ? (
            <div className="space-y-3 stagger">
              {projectsParallel.length === 0 ? (
                <EmptyState
                  icon="folder_off"
                  title="暂无在跑项目"
                  description="从解析一份招标文件开始，确认参与后项目会出现在这里。"
                  action={(
                    <Button onClick={() => navigate('/parse/technical')}>
                      去解析招标文件
                    </Button>
                  )}
                />
              ) : (
                projectsParallel.map((p) => <ParallelProjectCard key={p.id} project={p} />)
              )}
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,30rem),1fr))] gap-3 stagger">
              {projects.length === 0 ? (
                <EmptyState
                  icon="folder_off"
                  title="暂无在跑项目"
                  description="从解析一份招标文件开始，确认参与后项目会出现在这里。"
                  className="col-span-full"
                  action={(
                    <Button onClick={() => navigate(role === 'B' ? '/parse/business' : '/parse/technical')}>
                      去解析招标文件
                    </Button>
                  )}
                />
              ) : (
                projects.map((p) => (
                  <ProjectCard key={p.id} project={p} workspaceSlug={role === 'B' ? 'business' : 'tech'} />
                ))
              )}
            </div>
          )}
      </section>
    </div>
  )
}
