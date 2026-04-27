import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { generateAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { brandFutureCode, brandFutureCodeOrFallback } from '../utils/branding'
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

const formatOpencodePartText = (part) => {
  const rawText = String(part?.text || '').trim()
  if (!rawText) {
    if (part?.type === 'step-start') return 'step-start'
    if (part?.type === 'step-finish') return 'step-finish'
    return '（空片段）'
  }
  if (part?.type === 'text') {
    try {
      return brandFutureCode(JSON.stringify(JSON.parse(rawText), null, 2))
    } catch {
      return brandFutureCode(rawText)
    }
  }
  return brandFutureCode(rawText)
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
    generate_draft: '生成初稿',
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [runningAction, setRunningAction] = useState(false)
  const [advancing, setAdvancing] = useState(false)

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const payload = await generateAPI.status(id)
      setData(payload)
    } catch (e) {
      if (!silent) setError(e?.message || 'S7 填充状态加载失败')
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
  const opencodeParts = Array.isArray(opencodeOutput?.parts) ? opencodeOutput.parts : []
  const opencodeStatus = opencodeOutput?.status || 'idle'

  useEffect(() => {
    if (!isRunning) return undefined

    const timer = window.setInterval(() => {
      loadData({ silent: true })
    }, 1000)

    return () => window.clearInterval(timer)
  }, [isRunning, loadData])

  const handleRunFill = async () => {
    if (runningAction || isRunning) return
    setRunningAction(true)
    try {
      const payload = await generateAPI.run(id)
      setData(payload)
      showToast?.(payload?.message || '已开始生成初稿，请稍候。')
    } catch (e) {
      showToast?.(e?.message || '触发填充失败，请稍后重试', 'error')
    } finally {
      setRunningAction(false)
    }
  }

  const handleGoCoverage = async () => {
    if (!isCompleted) {
      showToast?.('请先完成 S7 填充后再进入 S8。', 'error')
      return
    }
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 7, { status: 'completed' })
      showToast?.('已进入 S8 覆盖校验')
      navigate(projectRoute(id, '/coverage', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入下一阶段失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S7 填充状态..." />
  if (error) return <PageError title="S7 填充状态加载失败" description={error} onRetry={loadData} />

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

  const eventLevelClassMap = {
    info: 'bg-primary/15 text-primary border-primary/20',
    success: 'bg-secondary-container text-on-secondary-container border-secondary/20',
    error: 'bg-error/10 text-error border-error/20',
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

  const opencodeStatusLabelMap = {
    idle: '未开始',
    waiting: '等待返回',
    received: '已返回',
    failed: '调用失败',
  }

  const opencodePartLabelMap = {
    reasoning: '思考片段',
    text: '原始文本',
    'step-start': 'Step Start',
    'step-finish': 'Step Finish',
  }

  const opencodePartClassMap = {
    reasoning: 'border-amber-200 bg-amber-50 text-amber-950',
    text: 'border-primary/20 bg-primary/5 text-on-surface',
    'step-start': 'border-surface-container-high bg-surface-container-low text-on-surface-variant',
    'step-finish': 'border-surface-container-high bg-surface-container-low text-on-surface-variant',
  }

  const tasks = Array.isArray(data?.tasks) ? data.tasks : []
  const taskCount = tasks.length
  const taskTimelineInset = taskCount > 0 ? (340 / taskCount) / 2 : 0

  const renderOpencodeOutputCard = () => (
    <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-on-surface">futurecode 输出</h3>
          <p className="text-xs text-on-surface-variant mt-1">
            这里直接显示 S7 初稿生成返回的原始片段；如果还没返回，会明确提示当前正在等待。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] px-2 py-1 rounded-full border ${eventLevelClassMap[opencodeStatus === 'failed' ? 'error' : opencodeStatus === 'received' ? 'success' : 'info']}`}>
            {opencodeStatusLabelMap[opencodeStatus] || '未开始'}
          </span>
          {isRunning && latestEvent ? (
            <span className="text-xs text-outline whitespace-nowrap">
              已停留 {formatElapsedSince(latestEvent.at)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
        <div className="rounded-lg bg-surface-container-lowest px-3 py-2">
          <div className="text-[11px] text-outline mb-1">Provider</div>
          <div className="text-sm text-on-surface break-all">{brandFutureCodeOrFallback(opencodeOutput?.providerId)}</div>
        </div>
        <div className="rounded-lg bg-surface-container-lowest px-3 py-2">
          <div className="text-[11px] text-outline mb-1">Model</div>
          <div className="text-sm text-on-surface break-all">{opencodeOutput?.modelId || '-'}</div>
        </div>
        <div className="rounded-lg bg-surface-container-lowest px-3 py-2">
          <div className="text-[11px] text-outline mb-1">Session</div>
          <div className="text-sm text-on-surface break-all">{opencodeOutput?.sessionId || '-'}</div>
        </div>
      </div>

      {opencodeStatus === 'waiting' && !opencodeParts.length ? (
        <div className="rounded-lg border border-dashed border-primary/20 bg-primary/5 px-3 py-4 text-sm text-on-surface">
          <div className="font-medium">会话已创建，正在等待 futurecode 返回章节草稿。</div>
          <div className="mt-2 text-on-surface-variant">
            {brandFutureCode(latestEvent?.message) || '当前还没有收到 reasoning/text 片段，请稍候。'}
          </div>
        </div>
      ) : !opencodeParts.length ? (
        <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
          暂无 futurecode 原始输出。
        </div>
      ) : (
        <div className="flex flex-col gap-3 max-h-[360px] overflow-y-auto pr-1">
          {opencodeParts.map((part, index) => (
            <div
              key={`${part.type || 'part'}-${index}`}
              className={`rounded-lg border p-3 ${opencodePartClassMap[part.type] || opencodePartClassMap.text}`}
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="text-xs font-semibold uppercase tracking-wide">
                  {opencodePartLabelMap[part.type] || part.type || 'Part'}
                </span>
                <span className="text-[11px] opacity-70">
                  {opencodeOutput?.receivedAt ? formatEventTime(opencodeOutput.receivedAt) : '--:--:--'}
                </span>
              </div>
              <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed font-mono">
                {formatOpencodePartText(part)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={handleRunFill}
              disabled={runningAction || isRunning}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRunning ? '生成中...' : isCompleted ? '重新触发填充' : '触发填充'}
            </button>
            <button
              onClick={handleGoCoverage}
              disabled={!isCompleted || advancing}
              title={!isCompleted ? '填充完成后可进入 S8' : ''}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {advancing ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 !bg-white !border-0 !shadow-none overflow-visible min-h-[360px]">
        <div className="px-0 py-1 bg-white">
          <div className="flex flex-col lg:flex-row lg:items-center gap-3">
            <div className="flex items-center gap-3 shrink-0">
              <h2 className="text-lg font-headline font-bold text-on-surface">填充执行状态</h2>
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
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">S7 尚未触发</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              点击“触发填充”后会异步调用后端初稿生成链路，并持续显示当前步骤、执行过程和 futurecode 原始输出。
            </p>
            <button
              onClick={handleRunFill}
              disabled={runningAction}
              className="stage-action-btn mt-6 px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {runningAction ? '提交中...' : '触发填充'}
            </button>
          </div>
        ) : (
          <div className="pt-12 pb-1 flex flex-col gap-10">
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
              <div className="xl:col-span-7 rounded-lg border border-surface-container-high bg-surface-container-low p-4">
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

              <div className="xl:col-span-5 rounded-lg border border-surface-container-high bg-surface-container-low p-4">
                <h3 className="text-sm font-semibold text-on-surface mb-3">章节结果概览</h3>
                {!Array.isArray(data?.sections) || data.sections.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
                    初稿尚未输出章节结果。
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

            <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
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
                <div className="rounded-lg border border-surface-container-high bg-white p-4">
                  <h3 className="text-sm font-semibold text-on-surface mb-3">运行信息</h3>
                  <div>
                    {[
                      { label: '执行结果', value: '填充成功' },
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

                <div className="rounded-lg border border-surface-container-high bg-white p-4">
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

            <div>
              {renderOpencodeOutputCard()}
            </div>
          </div>
        )}
      </DataCard>
    </div>
  )
}
