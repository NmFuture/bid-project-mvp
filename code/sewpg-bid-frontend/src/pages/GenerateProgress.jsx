import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { generateAPI, projectsAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import Button from '../components/ui/Button'
import { Dialog, DialogBody, DialogFooter, DialogHeader } from '../components/ui/Dialog'
import Toolbar from '../components/ui/Toolbar'
import { brandFutureCode } from '../utils/branding'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const formatDateTime = (value) => {
  if (!value) return '未完成'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未完成'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const formatEventTime = (value) => {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

const formatElapsedSince = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const diffMs = Date.now() - date.getTime()
  if (diffMs < 0) return '刚刚'
  const totalSec = Math.floor(diffMs / 1000)
  const minutes = Math.floor(totalSec / 60)
  const seconds = totalSec % 60
  if (minutes <= 0) return `${seconds} 秒`
  return `${minutes} 分 ${seconds} 秒`
}

const localizeExecutionStep = (step) => {
  const normalized = String(step || '').trim().toLowerCase()
  const map = {
    bootstrap: '初始化',
    init: '初始化',
    initialize: '初始化',
    prepare: '准备数据',
    parse: '解析内容',
    parse_outline: '解析目录',
    write: '写入文档',
    write_doc: '写入文档',
    generate: '生成内容',
    generate_draft: '生成正文',
    save: '保存结果',
    done: '完成',
    failed: '失败',
  }
  if (!normalized) return '通用'
  return map[normalized] || brandFutureCode(step)
}

export default function GenerateProgress({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [runningAction, setRunningAction] = useState(false)
  const [advancing, setAdvancing] = useState(false)
  const [businessProgressOpen, setBusinessProgressOpen] = useState(false)

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const [payload, projectPayload] = await Promise.all([
        generateAPI.status(id),
        projectsAPI.get(id).catch(() => null),
      ])
      setData(payload)
      if (projectPayload) setProject(projectPayload)
    } catch (e) {
      if (!silent) setError(e?.message || '标书生成状态加载失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const status = data?.status || 'idle'
  const isRunning = status === 'running'
  const isCompleted = status === 'completed'
  const progress = Math.max(0, Math.min(100, Number(data?.percentage) || 0))
  const executionEvents = Array.isArray(data?.events) ? data.events : []
  const latestEvent = executionEvents.length ? executionEvents[executionEvents.length - 1] : null
  const opencodeOutput = data?.opencodeOutput || {}
  const opencodeStatus = opencodeOutput?.status || 'idle'
  const isBusinessBid = String(project?.bidType || '').includes('商务')
  const bidLabel = isBusinessBid ? '商务标' : '技术标'
  const generationLabels = isBusinessBid
    ? {
        idleDescription: '点击“生成标书”后会异步调用后端商务标响应文件装配链路，并用弹窗持续展示当前步骤、执行过程和结果概览。',
        overviewTitle: '响应件结果概览',
        emptySections: '商务响应件尚未输出装配结果。',
        toast: '已开始装配商务标响应文件，请稍候。',
        success: '装配成功',
      }
    : {
        idleDescription: '点击“生成标书”后会异步调用后端技术标正文拼装链路，并用弹窗持续展示当前步骤、执行过程和结果概览。',
        overviewTitle: '章节结果概览',
        emptySections: '正文尚未输出章节结果。',
        toast: '已开始拼装正文，请稍候。',
        success: '拼装成功',
    }

  useEffect(() => {
    if (!isRunning) return undefined

    const timer = window.setInterval(() => {
      loadData({ silent: true })
    }, 1000)

    return () => window.clearInterval(timer)
  }, [isRunning, loadData])

  useEffect(() => {
    if (!isRunning && !runningAction) return undefined
    const timer = window.setTimeout(() => {
      setBusinessProgressOpen(true)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [isRunning, runningAction])

  const handleRunFill = async () => {
    if (runningAction || isRunning) return
    setBusinessProgressOpen(true)
    setRunningAction(true)
    try {
      const payload = await generateAPI.run(id)
      setData(payload)
      showToast?.(payload?.message || generationLabels.toast)
    } catch (e) {
      showToast?.(e?.message || '触发标书生成失败，请稍后重试', 'error')
    } finally {
      setRunningAction(false)
    }
  }

  const handleGoEditor = async () => {
    if (!isCompleted) {
      showToast?.('请先完成标书生成后再进入共创。', 'error')
      return
    }
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 4, { status: 'completed' })
      showToast?.('已进入共创导出')
      navigate(projectRoute(id, '/editor', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入下一阶段失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <PageLoading title="正在加载素材匹配状态..." />
  if (error) return <PageError title="素材匹配状态加载失败" description={error} onRetry={loadData} />

  const taskStatusLabelMap = {
    pending: '待处理',
    running: '进行中',
    done: '已完成',
    failed: '失败',
  }

  const taskStatusClassMap = {
    pending: 'bg-surface-container-high text-on-surface-variant',
    running: 'bg-primary/15 text-primary',
    done: 'bg-secondary-container text-on-secondary-container',
    failed: 'bg-error/10 text-error',
  }

  const taskTimelineDotClassMap = {
    pending: 'bg-[#b6babd]',
    running: 'bg-[#0BAFFF]',
    done: 'bg-[#14A83B]',
    failed: 'bg-[#d93025]',
  }

  const sectionStatusLabelMap = {
    generated: '已生成',
    generated_with_placeholder: '部分生成',
    failed: '失败',
  }

  const sectionStatusClassMap = {
    generated: 'bg-secondary-container text-on-secondary-container',
    generated_with_placeholder: 'bg-tertiary-fixed text-on-tertiary-fixed',
    failed: 'bg-error-container text-on-error-container',
  }

  const eventLevelToneMap = {
    info: {
      dot: 'bg-primary',
      label: 'text-primary',
    },
    success: {
      dot: 'bg-secondary',
      label: 'text-secondary',
    },
    error: {
      dot: 'bg-error',
      label: 'text-error',
    },
  }

  const tasks = Array.isArray(data?.tasks) ? data.tasks : []
  const taskCount = tasks.length
  const taskTimelineInset = taskCount > 0 ? (340 / taskCount) / 2 : 0

  const renderProgressDialog = () => {
    const failed = status === 'failed' || opencodeStatus === 'failed'
    const dialogTitle = failed
      ? `${bidLabel}正文生成失败`
      : isCompleted
        ? `${bidLabel}正文已生成`
        : isRunning || runningAction
          ? `正在生成${bidLabel}正文`
          : `${bidLabel}正文生成进度`
    const dialogSummary = failed
      ? latestEvent?.message || '生成任务未完成，请检查执行过程后重新生成。'
      : isCompleted
        ? `已完成${bidLabel}正文生成，可进入共创导出继续核对和定稿。`
        : isRunning || runningAction
          ? latestEvent?.message || `系统正在根据当前素材匹配和事实表结果生成${bidLabel}正文。`
          : `当前没有运行中的${bidLabel}正文生成任务。`
    const dialogCanClose = !isRunning && !runningAction
    const closeDialog = () => {
      if (dialogCanClose) setBusinessProgressOpen(false)
    }
    const visibleTasks = tasks.slice(0, 8)
    const visibleEvents = executionEvents.slice(-5)
    const sections = Array.isArray(data?.sections) ? data.sections : []

    return (
      <Dialog open={businessProgressOpen} onClose={closeDialog} size="lg">
        <DialogHeader onClose={dialogCanClose ? closeDialog : undefined}>
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-headline font-bold text-on-surface">{dialogTitle}</h3>
              <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                failed
                  ? 'bg-error-container text-on-error-container'
                  : isCompleted
                    ? 'bg-secondary-container text-on-secondary-container'
                    : 'bg-primary/15 text-primary'
              }`}>
                {failed ? '失败' : isCompleted ? '已完成' : isRunning || runningAction ? '生成中' : '待生成'}
              </span>
            </div>
            <p className="text-sm text-on-surface-variant">{brandFutureCode(dialogSummary)}</p>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-5">
          <div className="rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm font-semibold text-on-surface">生成进度</div>
              <span className="text-xs text-outline">当前完成度：{progress}%</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-container-high">
                <div
                  className={`h-full transition-all duration-700 ${failed ? 'bg-error' : 'bg-primary'}`}
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="w-12 text-right text-xs font-semibold text-outline">{progress}%</span>
            </div>
            {latestEvent ? (
              <div className="mt-3 rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface">
                <span className="mr-2 text-xs font-semibold text-primary">{localizeExecutionStep(latestEvent.step)}</span>
                {brandFutureCode(latestEvent.message) || '-'}
              </div>
            ) : null}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h4 className="text-sm font-semibold text-on-surface">任务进度</h4>
                <span className="text-xs text-outline">{tasks.length} 项</span>
              </div>
              {visibleTasks.length ? (
                <div className="space-y-2">
                  {visibleTasks.map((task, index) => (
                    <div key={task.id || `${task.label || 'task'}-${index}`} className="flex items-center justify-between gap-3 rounded-md bg-surface-container-low px-3 py-2">
                      <div className="min-w-0 truncate text-sm font-medium text-on-surface">{task.label || `任务 ${index + 1}`}</div>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${taskStatusClassMap[task.status] || taskStatusClassMap.pending}`}>
                        {taskStatusLabelMap[task.status] || '待处理'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-surface-container-high px-3 py-6 text-center text-sm text-on-surface-variant">
                  暂无任务进度数据。
                </div>
              )}
            </div>

            <div className="rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h4 className="text-sm font-semibold text-on-surface">执行事件</h4>
                <span className="text-xs text-outline">最近 {visibleEvents.length} 条</span>
              </div>
              {visibleEvents.length ? (
                <div className="space-y-3">
                  {visibleEvents.map((event, index) => (
                    <div key={`${event.step || 'event'}-${index}-${event.at || ''}`} className="rounded-md bg-surface-container-low px-3 py-2">
                      <div className="mb-1 flex items-center justify-between gap-3">
                        <span className={`text-xs font-semibold ${(eventLevelToneMap[event.level] || eventLevelToneMap.info).label}`}>
                          {localizeExecutionStep(event.step)}
                        </span>
                        <span className="text-[11px] text-outline">{formatEventTime(event.at)}</span>
                      </div>
                      <div className="text-sm leading-relaxed text-on-surface">{brandFutureCode(event.message) || '-'}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-surface-container-high px-3 py-6 text-center text-sm text-on-surface-variant">
                  暂无执行事件。
                </div>
              )}
            </div>
          </div>

          <div className="rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h4 className="text-sm font-semibold text-on-surface">结果概览</h4>
              <span className="text-xs text-outline">{sections.length} 个章节/附件</span>
            </div>
            {sections.length ? (
              <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
                {sections.slice(0, 12).map((section, index) => (
                  <div key={section.nodeId || `${section.title || 'section'}-${index}`} className="flex items-center justify-between gap-3 rounded-md bg-surface-container-low px-3 py-2">
                    <div className="min-w-0 truncate text-sm text-on-surface">
                      <span className="mr-2 text-xs font-semibold text-outline">{String(index + 1).padStart(2, '0')}</span>
                      {section.title || '未命名章节'}
                    </div>
                    <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] ${sectionStatusClassMap[section.generationMode] || sectionStatusClassMap.generated_with_placeholder}`}>
                      {sectionStatusLabelMap[section.generationMode] || section.generationMode || '未知'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-surface-container-high px-3 py-6 text-center text-sm text-on-surface-variant">
                {generationLabels.emptySections}
              </div>
            )}
          </div>
        </DialogBody>

        <DialogFooter>
          {isCompleted ? (
            <Button type="button" onClick={handleGoEditor} disabled={advancing} variant="primary">
              {advancing ? '进入中...' : '进入共创导出'}
            </Button>
          ) : null}
          <Button type="button" onClick={closeDialog} disabled={!dialogCanClose} variant={isCompleted ? 'quiet' : 'primary'}>
            {dialogCanClose ? '关闭' : '生成中...'}
          </Button>
        </DialogFooter>
      </Dialog>
    )
  }

  return (
    <div className="stage-page business-ui-shell flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <Toolbar>
            <Button
              type="button"
              onClick={loadData}
              size="stage"
              variant="quiet"
            >
              刷新
            </Button>
            {status !== 'idle' ? (
              <Button
                type="button"
                onClick={() => setBusinessProgressOpen(true)}
                size="stage"
                variant="quiet"
              >
                查看进度
              </Button>
            ) : null}
            <Button
              type="button"
              onClick={handleRunFill}
              disabled={runningAction || isRunning}
              size="stage"
              variant="primary"
            >
              {isRunning ? '生成中...' : isCompleted ? '重新生成标书' : '生成标书'}
            </Button>
            <Button
              type="button"
              onClick={handleGoEditor}
              disabled={!isCompleted || advancing}
              title={!isCompleted ? '标书生成完成后可进入共创导出' : ''}
              size="stage"
              variant="success"
            >
              {advancing ? '进入中...' : '进入共创导出'}
            </Button>
          </Toolbar>
        )}
      />

      <DataCard className="!p-0 overflow-hidden business-panel min-h-[360px]">
        <div className="business-section-head border-b border-surface-container-high px-4 py-3">
          <div className="flex flex-col lg:flex-row lg:items-center gap-3">
            <div className="flex items-center gap-3 shrink-0">
              <h2 className="text-lg font-headline font-bold text-on-surface">标书生成状态</h2>
            </div>
            <div className="flex-1 flex items-center gap-3 min-w-0">
              <div className="w-full h-2.5 bg-[#e8eef2] rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-700"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="text-xs text-outline whitespace-nowrap">当前完成度：{progress}%</span>
            </div>
          </div>
        </div>

        {status === 'idle' ? (
          <div className="h-[320px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">draw</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">标书尚未生成</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              {generationLabels.idleDescription}
            </p>
            <button
              onClick={handleRunFill}
              disabled={runningAction}
              className="stage-action-btn mt-6 px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {runningAction ? '提交中...' : '生成标书'}
            </button>
          </div>
        ) : (
          <div className="bg-surface-container-low px-4 py-4 flex flex-col gap-4">
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
              <div className="business-panel xl:col-span-7 rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <h3 className="text-sm font-semibold text-on-surface">任务进度</h3>
                  {isRunning && latestEvent ? (
                    <span className="text-xs text-outline">当前步骤已停留 {formatElapsedSince(latestEvent.at)}</span>
                  ) : null}
                </div>
                {taskCount === 0 ? (
                  <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
                    暂无任务进度数据。
                  </div>
                ) : (
                  <div className="relative h-[340px]">
                    {taskCount > 1 ? (
                      <span
                        className="absolute left-[9px] w-px bg-[#b7d2e8]"
                        style={{ top: `${taskTimelineInset}px`, bottom: `${taskTimelineInset}px` }}
                      />
                    ) : null}
                    <div
                      className="h-full grid"
                      style={{ gridTemplateRows: `repeat(${taskCount}, minmax(0, 1fr))` }}
                    >
                    {tasks.map((task, index) => (
                      <div
                        key={task.id || `${task.label || 'task'}-${index}`}
                        className="relative pl-6 pr-0 flex items-center"
                      >
                        <span className={`absolute left-0 top-1/2 -translate-y-1/2 h-[18px] w-[18px] rounded-full border-2 border-white ${taskTimelineDotClassMap[task.status] || taskTimelineDotClassMap.pending}`} />
                        <div className="w-full rounded-md bg-[#f7f9fb] px-3 py-2.5 flex items-center justify-between gap-3">
                          <div className="text-sm text-on-surface font-medium">{task.label}</div>
                          <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${taskStatusClassMap[task.status] || taskStatusClassMap.pending}`}>
                            {taskStatusLabelMap[task.status] || '待处理'}
                          </span>
                        </div>
                      </div>
                    ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="business-panel xl:col-span-5 rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
                <h3 className="text-sm font-semibold text-on-surface mb-3">{generationLabels.overviewTitle}</h3>
                {!Array.isArray(data?.sections) || data.sections.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
                    {generationLabels.emptySections}
                  </div>
                ) : (
                  <div
                    className="flex flex-col gap-2.5 h-[320px] overflow-y-auto pr-1"
                    style={{ scrollbarGutter: 'stable' }}
                  >
                    {data.sections.map((section, index) => (
                      <div
                        key={section.nodeId || `${section.title || 'section'}-${index}`}
                        className="rounded-md bg-[#f7f7f7] px-3 py-2 flex items-center justify-between gap-3"
                      >
                        <div className="min-w-0 flex items-center gap-2">
                          <span className="text-xs font-semibold text-outline tabular-nums shrink-0">
                            {String(index + 1).padStart(2, '0')}
                          </span>
                          <span className="text-sm font-medium text-on-surface truncate">
                            {section.title || '未命名章节'}
                          </span>
                        </div>
                        <span className={`text-[11px] px-2 py-0.5 rounded-md shrink-0 ${
                          sectionStatusClassMap[section.generationMode] || sectionStatusClassMap.generated_with_placeholder
                        }`}>
                          {sectionStatusLabelMap[section.generationMode] || section.generationMode || '未知'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
              <div className="flex items-center justify-between gap-3 mb-4">
                <h3 className="text-sm font-semibold text-on-surface">执行过程</h3>
                <span className="text-xs text-outline">{executionEvents.length} 条事件</span>
              </div>
              {!executionEvents.length ? (
                <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
                  暂无执行事件。
                </div>
              ) : (
                <div className="flex flex-col">
                  {executionEvents.map((event, index) => (
                    <div
                      key={`${event.step || 'event'}-${index}-${event.at || ''}`}
                      className={`relative pl-7 pr-1 pb-5 ${index === executionEvents.length - 1 ? 'pb-0' : ''}`}
                    >
                      {index !== executionEvents.length - 1 ? (
                        <span className="absolute left-[5px] top-4 bottom-0 w-px bg-[#c5d8e8]" />
                      ) : null}
                      <span className={`absolute left-0 top-1.5 h-[10px] w-[10px] rounded-full ${(eventLevelToneMap[event.level] || eventLevelToneMap.info).dot}`} />
                      <div className="flex items-center justify-between gap-3">
                        <span className={`text-xs font-semibold tracking-wide ${(eventLevelToneMap[event.level] || eventLevelToneMap.info).label}`}>
                          {localizeExecutionStep(event.step)}
                        </span>
                        <span className="text-[11px] text-outline">{formatEventTime(event.at)}</span>
                      </div>
                      <div className="mt-1.5 text-sm text-on-surface leading-relaxed">{brandFutureCode(event.message) || '-'}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {isCompleted ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="business-panel rounded-md border border-surface-container-high bg-white p-4">
                  <h3 className="text-sm font-semibold text-on-surface mb-3">运行信息</h3>
                  <div>
                    {[
                      { label: '执行结果', value: generationLabels.success },
                      { label: '运行时长', value: data?.runDuration || `${data?.runDurationSec || 0} 秒` },
                      { label: '完成时间', value: formatDateTime(data?.filledAt) },
                    ].map((row, index, rows) => (
                      <div
                        key={row.label}
                        className={`flex items-center justify-between gap-4 py-3 ${index < rows.length - 1 ? 'border-b border-surface-container-high' : ''}`}
                      >
                        <div className="flex items-center gap-2 text-sm text-on-surface-variant">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#19c3d8]" />
                          <span>{row.label}</span>
                        </div>
                        <span className="text-sm text-on-surface font-medium text-right">{row.value}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="business-panel rounded-md border border-surface-container-high bg-white p-4">
                  <h3 className="text-sm font-semibold text-on-surface mb-3">输出文件信息</h3>
                  <div>
                    {[
                      { label: '文件名', value: data?.output?.fileName || '-' },
                      { label: '文件类型', value: (data?.output?.fileType || '-').toUpperCase() },
                      { label: '文件大小', value: data?.output?.size || '-' },
                    ].map((row, index, rows) => (
                      <div
                        key={row.label}
                        className={`flex items-center justify-between gap-4 py-3 ${index < rows.length - 1 ? 'border-b border-surface-container-high' : ''}`}
                      >
                        <div className="flex items-center gap-2 text-sm text-on-surface-variant">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#19c3d8]" />
                          <span>{row.label}</span>
                        </div>
                        <span className="text-sm text-on-surface font-medium text-right">{row.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}

          </div>
        )}
      </DataCard>
      {renderProgressDialog()}
    </div>
  )
}
