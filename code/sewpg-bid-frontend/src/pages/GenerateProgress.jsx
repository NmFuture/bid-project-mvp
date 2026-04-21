import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { generateAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import { brandFutureCode, brandFutureCodeOrFallback } from '../utils/branding'

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

export default function GenerateProgress({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
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
  const isFailed = status === 'failed'
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
      navigate(`/projects/${id}/coverage`)
    } catch (e) {
      showToast?.(e?.message || '进入下一阶段失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S7 填充状态..." />
  if (error) return <PageError title="S7 填充状态加载失败" description={error} onRetry={loadData} />

  const statusTextMap = {
    idle: '未开始',
    running: '生成中',
    completed: '已完成',
    failed: '生成失败',
  }

  const statusClassMap = {
    idle: 'bg-surface-container-high text-on-surface-variant',
    running: 'bg-primary/15 text-primary',
    completed: 'bg-secondary-container text-on-secondary-container',
    failed: 'bg-error/10 text-error',
  }

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

  const eventLevelClassMap = {
    info: 'bg-primary/15 text-primary border-primary/20',
    success: 'bg-secondary-container text-on-secondary-container border-secondary/20',
    error: 'bg-error/10 text-error border-error/20',
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
    <div className="flex flex-col gap-6 animate-fade-in max-w-6xl mx-auto w-full">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        title="S7 填充"
        description="当前版本会异步触发 S7 初稿生成，并持续显示执行进度、任务状态和 futurecode 原始输出；完成后即可进入 S8。"
        leftExtra={(
          <button
            onClick={() => window.history.back()}
            className="text-primary hover:bg-surface-container-low rounded-full w-10 h-10 flex items-center justify-center transition-colors"
          >
            <span className="material-symbols-outlined">arrow_back</span>
          </button>
        )}
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-sm">refresh</span>
              刷新
            </button>
            <button
              onClick={handleRunFill}
              disabled={runningAction || isRunning}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">bolt</span>
              {isRunning ? '生成中...' : isCompleted ? '重新触发填充' : '触发填充'}
            </button>
            <button
              onClick={handleGoCoverage}
              disabled={!isCompleted || advancing}
              title={!isCompleted ? '填充完成后可进入 S8' : ''}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">arrow_forward</span>
              {advancing ? '进入中...' : '进入下一阶段（S8）'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-5 border-b border-surface-container-high bg-surface-container-low">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-headline font-bold text-on-surface">填充执行状态</h2>
              <p className="text-sm text-on-surface-variant mt-1">
                {brandFutureCode(data?.summary) || '尚未触发填充。'}
              </p>
            </div>
            <span className={`text-xs font-semibold px-3 py-1 rounded-full ${statusClassMap[status] || statusClassMap.idle}`}>
              {statusTextMap[status] || '未开始'}
            </span>
          </div>

          <div className="mt-4">
            <div className="w-full h-2 rounded-full bg-surface-container-high overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${isFailed ? 'bg-error' : 'bg-primary'}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-outline">
              <span>{progress}%</span>
              <span>{brandFutureCode(latestEvent?.message) || '等待执行事件...'}</span>
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
              className="mt-6 px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {runningAction ? '提交中...' : '触发填充'}
            </button>
          </div>
        ) : (
          <div className="px-6 py-6 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-6">
            <div className="flex flex-col gap-6">
              <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <h3 className="text-sm font-semibold text-on-surface">任务进度</h3>
                  {isRunning && latestEvent ? (
                    <span className="text-xs text-outline">当前步骤已停留 {formatElapsedSince(latestEvent.at)}</span>
                  ) : null}
                </div>
                <div className="flex flex-col gap-3">
                  {(data?.tasks || []).map((task) => (
                    <div
                      key={task.id}
                      className="rounded-lg border border-surface-container-high bg-surface-container-lowest px-4 py-3 flex items-center justify-between gap-3"
                    >
                      <div className="text-sm text-on-surface font-medium">{task.label}</div>
                      <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${taskStatusClassMap[task.status] || taskStatusClassMap.pending}`}>
                        {taskStatusLabelMap[task.status] || '待处理'}
                      </span>
                    </div>
                  ))}
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
                  <div className="flex flex-col gap-3">
                    {executionEvents.map((event, index) => (
                      <div
                        key={`${event.step || 'event'}-${index}-${event.at || ''}`}
                        className={`rounded-lg border px-3 py-3 ${eventLevelClassMap[event.level] || eventLevelClassMap.info}`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-xs font-semibold uppercase tracking-wide">{brandFutureCode(event.step) || 'general'}</span>
                          <span className="text-[11px] opacity-75">{formatEventTime(event.at)}</span>
                        </div>
                        <div className="mt-2 text-sm leading-relaxed">{brandFutureCode(event.message) || '-'}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {isCompleted ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
                    <h3 className="text-sm font-semibold text-on-surface mb-3">运行信息</h3>
                    <div className="flex flex-col gap-2 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-on-surface-variant">执行结果</span>
                        <span className="text-on-surface font-medium">填充成功</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-on-surface-variant">运行时长</span>
                        <span className="text-on-surface font-medium">
                          {data?.runDuration || `${data?.runDurationSec || 0} 秒`}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-on-surface-variant">完成时间</span>
                        <span className="text-on-surface font-medium">{formatDateTime(data?.filledAt)}</span>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
                    <h3 className="text-sm font-semibold text-on-surface mb-3">输出文件信息</h3>
                    <div className="flex flex-col gap-2 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-on-surface-variant">文件名</span>
                        <span className="text-on-surface font-medium text-right">{data?.output?.fileName || '-'}</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-on-surface-variant">文件类型</span>
                        <span className="text-on-surface font-medium uppercase">{data?.output?.fileType || '-'}</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-on-surface-variant">文件大小</span>
                        <span className="text-on-surface font-medium">{data?.output?.size || '-'}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="flex flex-col gap-6">
              {renderOpencodeOutputCard()}

              <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
                <h3 className="text-sm font-semibold text-on-surface mb-3">章节结果概览</h3>
                {!Array.isArray(data?.sections) || data.sections.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
                    初稿尚未输出章节结果。
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 max-h-[320px] overflow-y-auto pr-1">
                    {data.sections.map((section) => (
                      <div
                        key={section.nodeId || section.title}
                        className="rounded-lg border border-surface-container-high bg-surface-container-lowest px-3 py-3"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-medium text-on-surface">{section.title || '未命名章节'}</div>
                          <span className={`text-[11px] px-2 py-1 rounded-full ${
                            section.generationMode === 'generated'
                              ? 'bg-secondary-container text-on-secondary-container'
                              : section.generationMode === 'generated_with_placeholder'
                                ? 'bg-tertiary-fixed text-on-tertiary-fixed'
                                : 'bg-error-container text-on-error-container'
                          }`}>
                            {section.generationMode || 'unknown'}
                          </span>
                        </div>
                        {Array.isArray(section.riskFlags) && section.riskFlags.length ? (
                          <div className="mt-2 text-xs text-outline break-words">
                            风险标记：{section.riskFlags.join(' / ')}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </DataCard>
    </div>
  )
}
