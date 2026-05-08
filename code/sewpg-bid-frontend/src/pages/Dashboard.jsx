import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { dashboardAPI } from '../api'
import { workspaceRoute } from '../utils/workspace'
import StatusBadge from '../components/shared/StatusBadge'
import RoleChip from '../components/shared/RoleChip'
import EmptyState from '../components/shared/EmptyState'
import Skeleton, { SkeletonCard } from '../components/shared/Skeleton'

const METRIC_TONE = {
  primary: 'from-primary-fixed to-primary-fixed-dim text-on-primary-fixed-variant',
  success: 'from-secondary-fixed to-secondary-fixed-dim text-on-secondary-fixed-variant',
  warn: 'from-tertiary-fixed to-tertiary-fixed-dim text-on-tertiary-fixed-variant',
  error: 'from-error-container to-error-container/80 text-error',
  info: 'from-ai-accent-light to-tertiary-fixed text-on-tertiary-container',
}

const SEVERITY_TO_VARIANT = {
  info: 'info',
  warn: 'warn',
  error: 'error',
  success: 'done',
}

const ACTIVITY_TONE = {
  ai: 'bg-ai-accent-light text-tertiary',
  success: 'bg-secondary-container text-secondary',
  info: 'bg-primary-fixed text-primary',
  warn: 'bg-tertiary-container text-on-tertiary-container',
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
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <h1 className="text-[22px] font-headline font-bold text-on-surface tracking-tight">
            {name}
          </h1>
          {role && <RoleChip role={role} />}
        </div>
      </div>
      <div className="text-[12px] text-outline">
        {formatCurrentTime(now)}
      </div>
    </div>
  )
}

function MetricCard({ metric }) {
  const tone = METRIC_TONE[metric.tone] || METRIC_TONE.primary
  return (
    <div className={`relative overflow-hidden rounded-xl bg-gradient-to-br ${tone} p-4 animate-count-up`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="text-xs font-medium opacity-80">{metric.label}</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-3xl font-headline font-bold tabular-nums">{metric.value}</span>
          </div>
        </div>
        <span
          className="material-symbols-outlined text-[26px] opacity-70"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {metric.icon}
        </span>
      </div>
    </div>
  )
}

function ProjectCard({ project, workspaceSlug }) {
  const stagePct = project.progress
  const stageColor =
    stagePct >= 0.8
      ? 'from-secondary to-secondary-fixed-dim'
      : stagePct >= 0.5
        ? 'from-primary to-primary-container'
        : 'from-tertiary to-tertiary-fixed-dim'
  return (
    <Link
      to={workspaceRoute(workspaceSlug || project.workspace, `/projects/${project.id}`)}
      className="group block rounded-xl border border-outline-variant/40 bg-white p-4 transition-all hover:border-primary/40 hover:shadow-[0_8px_24px_-12px_rgba(0,104,183,0.4)] hover:-translate-y-px"
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-xs text-outline font-mono">{project.id}</span>
            {project.keyAccount && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-tertiary-container px-1.5 py-0.5 text-[10px] font-semibold text-on-tertiary-container">
                <span className="material-symbols-outlined text-[12px]" style={{ fontVariationSettings: "'FILL' 1" }}>
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
        <span className="material-symbols-outlined text-outline group-hover:text-primary group-hover:translate-x-0.5 transition-all">
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
            className={`h-full bg-gradient-to-r ${stageColor} transition-all duration-700`}
            style={{ width: `${stagePct * 100}%` }}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-outline">
        <span className="inline-flex items-center gap-1">
          <span className="material-symbols-outlined text-[14px]">event</span>
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
        <div className="flex-1 rounded-lg border border-dashed border-outline-variant/60 bg-surface-container-low/50 p-3 flex items-center justify-center text-xs text-outline">
          {kind === 'tech' ? '本项目无技术标' : '本项目无商务标'}
        </div>
      )
    }
    return (
      <Link
        to={workspaceRoute(kind, `/projects/${project.id}`)}
        className="flex-1 group rounded-lg border border-outline-variant/40 bg-white p-3 transition-all hover:border-primary/40 hover:shadow-sm"
      >
        <div className="flex items-center gap-1.5 mb-1.5 text-xs">
          <span
            className="material-symbols-outlined text-[16px] text-primary"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            {kind === 'tech' ? 'engineering' : 'request_quote'}
          </span>
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
            className="h-full bg-gradient-to-r from-primary to-primary-container transition-all duration-700"
            style={{ width: `${ws.progress * 100}%` }}
          />
        </div>
      </Link>
    )
  }

  return (
    <div className="rounded-xl border border-outline-variant/40 bg-white p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-xs text-outline font-mono">{project.id}</span>
            <span className="text-xs text-outline">·</span>
            <span className="text-xs text-outline inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px]">event</span>
              截止 {project.deadline}
            </span>
          </div>
          <h3 className="text-sm font-semibold text-on-surface">{project.name}</h3>
          <div className="text-xs text-on-surface-variant mt-0.5">{project.customer}</div>
        </div>
      </div>
      <div className="flex items-stretch gap-3">
        {wsBlock('tech', project.tech)}
        {wsBlock('business', project.business)}
      </div>
    </div>
  )
}

function TodoItem({ todo }) {
  const variant = SEVERITY_TO_VARIANT[todo.severity] || 'info'
  return (
    <Link
      to={todo.href}
      className="group flex items-start gap-3 rounded-lg border border-transparent px-3 py-2.5 hover:bg-surface-container-low hover:border-outline-variant/40 transition-all"
    >
      <span className={`shrink-0 mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full ${todo.severity === 'error' ? 'bg-error-container text-error' : todo.severity === 'warn' ? 'bg-tertiary-container text-on-tertiary-container' : 'bg-primary-fixed text-primary'}`}>
        <span className="material-symbols-outlined text-[16px]" style={{ fontVariationSettings: "'FILL' 1" }}>
          {todo.icon}
        </span>
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-on-surface group-hover:text-primary transition-colors">{todo.text}</div>
      </div>
      <StatusBadge variant={variant} className="shrink-0">
        {todo.severity === 'error' ? '紧急' : todo.severity === 'warn' ? '待处理' : '关注'}
      </StatusBadge>
    </Link>
  )
}

function ActivityItem({ act }) {
  const tone = ACTIVITY_TONE[act.tone] || ACTIVITY_TONE.info
  return (
    <li className="flex items-start gap-3 py-2">
      <span className={`shrink-0 mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full ${tone}`}>
        <span className="material-symbols-outlined text-[16px]" style={{ fontVariationSettings: "'FILL' 1" }}>
          {act.icon}
        </span>
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-on-surface">{act.text}</div>
        <div className="text-xs text-outline mt-0.5">{act.time}</div>
      </div>
    </li>
  )
}

function PanelHeader({ icon, title, hint, action }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <span
          className="material-symbols-outlined text-[20px] text-primary"
          style={{ fontVariationSettings: "'FILL' 1" }}
        >
          {icon}
        </span>
        <h2 className="text-base font-headline font-semibold text-on-surface">{title}</h2>
        {hint && <span className="text-xs text-outline">{hint}</span>}
      </div>
      {action}
    </div>
  )
}

export default function Dashboard({ currentUser }) {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let mounted = true
    dashboardAPI
      .get()
      .then((payload) => {
        if (!mounted) return
        setData(payload)
        setLoading(false)
      })
      .catch((err) => {
        if (!mounted) return
        setError(err?.message || '加载失败')
        setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [])

  const role = data?.role || currentUser?.role
  const userName = currentUser?.name || '用户'

  if (loading) {
    return (
      <div className="px-7 md:px-10 lg:px-12 xl:px-14 py-6 space-y-6">
        <Skeleton className="h-8 w-72" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <div className="grid lg:grid-cols-3 gap-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-7 md:px-10 lg:px-12 xl:px-14 py-6">
        <EmptyState
          icon="error"
          title="工作台加载失败"
          description={error}
          action={
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-container hover:text-on-primary-container transition-colors"
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
  const todos = data?.todos || []
  const activity = data?.activity || []
  const metrics = (data?.metrics || []).filter((metric) => metric.key !== 'aiSaved')

  return (
    <div className="px-7 md:px-10 lg:px-12 xl:px-14 py-6 space-y-6 animate-fade-in">
      <Greeting name={userName} role={role} />

      {/* 顶部统计 */}
      {metrics.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 stagger">
          {metrics.map((m) => (
            <MetricCard key={m.key} metric={m} />
          ))}
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-5">
        {/* 项目列表 / 双流程并列 */}
        <section className="lg:col-span-2 space-y-3">
          <PanelHeader
            icon="folder_open"
            title={isTB ? '在跑项目（双流程并列）' : `我负责的${role === 'B' ? '商务标' : '技术标'}项目`}
            hint={isTB ? `${projectsParallel.length} 个项目` : `${projects.length} 个项目`}
            action={
              <button
                type="button"
                onClick={() => navigate(isTB ? '/projects' : workspaceRoute(role === 'B' ? 'business' : 'tech', '/projects'))}
                className="text-xs text-primary hover:underline"
              >
                查看全部 →
              </button>
            }
          />
          {isTB ? (
            <div className="space-y-3 stagger">
              {projectsParallel.length === 0 ? (
                <EmptyState icon="folder_off" title="暂无在跑项目" />
              ) : (
                projectsParallel.map((p) => <ParallelProjectCard key={p.id} project={p} />)
              )}
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 gap-3 stagger">
              {projects.length === 0 ? (
                <EmptyState icon="folder_off" title="暂无在跑项目" className="col-span-full" />
              ) : (
                projects.map((p) => (
                  <ProjectCard key={p.id} project={p} workspaceSlug={role === 'B' ? 'business' : 'tech'} />
                ))
              )}
            </div>
          )}
        </section>

        {/* 右栏：待办 + 最近活动 */}
        <aside className="space-y-5">
          <section>
            <PanelHeader icon="pending_actions" title="今日待办" hint={`${todos.length} 条`} />
            <div className="rounded-xl border border-outline-variant/40 bg-white p-1.5 stagger">
              {todos.length === 0 ? (
                <EmptyState icon="task_alt" title="今日无待办" className="py-8" />
              ) : (
                todos.map((t) => <TodoItem key={t.id} todo={t} />)
              )}
            </div>
          </section>

          <section>
            <PanelHeader icon="history" title="最近活动" />
            <div className="rounded-xl border border-outline-variant/40 bg-white px-3 divide-y divide-surface-container-high">
              {activity.length === 0 ? (
                <EmptyState icon="history" title="暂无活动" className="py-8" />
              ) : (
                <ul>
                  {activity.map((a) => (
                    <ActivityItem key={a.id} act={a} />
                  ))}
                </ul>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
