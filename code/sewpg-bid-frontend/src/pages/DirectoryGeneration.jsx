import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { directoryAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { brandFutureCode, brandFutureCodeOrFallback } from '../utils/branding'

const formatDateTime = (value) => {
  if (!value) return '未生成'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未生成'
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

export default function DirectoryGeneration({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [advancing, setAdvancing] = useState(false)
  const [streamFailed, setStreamFailed] = useState(false)
  const eventSourceRef = useRef(null)
  const eventSourceSupported =
    typeof window !== 'undefined' && typeof window.EventSource === 'function'
  const opencodeConsoleRef = useRef(null)

  const closeEventStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const response = await directoryAPI.status(id)
      setData(response)
    } catch (e) {
      if (!silent) setError(e?.message || '目录生成状态加载失败')
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
  const opencodeConsoleSignature = opencodeParts
    .map((part) => `${part?.type || 'part'}:${String(part?.text || '')}`)
    .join('||')

  useEffect(() => {
    if (!isRunning) {
      closeEventStream()
      return undefined
    }

    if (!eventSourceSupported) {
      return undefined
    }

    let closed = false
    const source = directoryAPI.stream(id, {
      onState: (payload) => {
        if (closed) return
        setData(payload)
        setStreamFailed(false)
        if (payload?.status && payload.status !== 'running') {
          closed = true
          source.close()
          if (eventSourceRef.current === source) {
            eventSourceRef.current = null
          }
        }
      },
      onError: () => {
        if (closed) return
        closed = true
        source.close()
        if (eventSourceRef.current === source) {
          eventSourceRef.current = null
        }
        setStreamFailed(true)
      },
    })
    eventSourceRef.current = source

    return () => {
      closed = true
      if (eventSourceRef.current === source) {
        eventSourceRef.current = null
      }
      source.close()
    }
  }, [closeEventStream, eventSourceSupported, id, isRunning])

  const usePollingFallback = isRunning && (!eventSourceSupported || streamFailed)

  useEffect(() => {
    if (!isRunning || !usePollingFallback) return undefined
    const timer = window.setInterval(() => {
      loadData({ silent: true })
    }, 1000)

    return () => window.clearInterval(timer)
  }, [isRunning, loadData, usePollingFallback])

  useEffect(() => {
    const element = opencodeConsoleRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }, [opencodeConsoleSignature, opencodeStatus, latestEvent?.at])

  const handleGenerateDirectory = async () => {
    if (generating || isRunning) return
    setGenerating(true)
    try {
      const response = await directoryAPI.run(id)
      setStreamFailed(false)
      setData(response)
      showToast?.(response?.message || '已开始生成目录，请稍候。')
    } catch (e) {
      showToast?.(e?.message || '目录生成失败，请稍后重试', 'error')
    } finally {
      setGenerating(false)
    }
  }

  const handleGoOutline = async () => {
    if (!isCompleted) {
      showToast?.('请先完成 S2 目录生成后再进入 S3。', 'error')
      return
    }
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 2, { status: 'completed' })
      showToast?.('已进入 S3 目录审核')
      navigate(`/projects/${id}/outline`)
    } catch (e) {
      showToast?.(e?.message || '进入 S3 失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S2 目录生成状态..." />
  if (error) return <PageError title="目录生成状态加载失败" description={error} onRetry={loadData} />

  const taskStatusLabelMap = {
    pending: '待处理',
    running: '进行中',
    done: '已完成',
    failed: '失败',
  }

  const taskStatusTextClassMap = {
    pending: 'text-on-surface-variant',
    running: 'text-primary',
    done: 'text-secondary',
    failed: 'text-error',
  }

  const opencodeStatusLabelMap = {
    idle: '未开始',
    waiting: '等待返回',
    streaming: '流式输出中',
    received: '已返回',
    failed: '调用失败',
  }

  const opencodePartLabelMap = {
    reasoning: '思考片段',
    text: '原始文本',
    'step-start': 'Step Start',
    'step-finish': 'Step Finish',
  }

  const opencodePartToneMap = {
    reasoning: {
      dot: 'bg-amber-500',
      label: 'text-amber-700',
      body: 'text-amber-950',
    },
    text: {
      dot: 'bg-emerald-500',
      label: 'text-emerald-700',
      body: 'text-slate-800',
    },
    'step-start': {
      dot: 'bg-sky-500',
      label: 'text-sky-700',
      body: 'text-sky-900',
    },
    'step-finish': {
      dot: 'bg-fuchsia-500',
      label: 'text-fuchsia-700',
      body: 'text-fuchsia-900',
    },
  }

  const renderOpencodeOutputCard = () => (
    <div className="rounded-lg border border-surface-container-high bg-white overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-surface-container-high bg-white">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="h-2.5 w-2.5 rounded-full bg-rose-400/90" />
            <span className="h-2.5 w-2.5 rounded-full bg-amber-300/90" />
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400/90" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-900">futurecode Live Output</h3>
            <p className="text-xs text-slate-500 mt-1">
              持续显示 futurecode 返回内容和原始片段。
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] px-2 py-1 rounded-full border ${
            opencodeStatus === 'failed'
              ? 'border-rose-300 bg-rose-50 text-rose-700'
              : opencodeStatus === 'received'
                ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                : 'border-sky-300 bg-sky-50 text-sky-700'
          }`}>
            {opencodeStatusLabelMap[opencodeStatus] || '未开始'}
          </span>
          {isRunning && latestEvent ? (
            <span className="text-xs text-slate-500 whitespace-nowrap">
              已停留 {formatElapsedSince(latestEvent.at)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 px-4 py-3 border-b border-surface-container-high bg-white">
        <div className="rounded-md bg-[#f8fafc] border border-surface-container-high px-3 py-2">
          <div className="text-[11px] text-slate-500 mb-1">Provider</div>
          <div className="text-sm text-slate-900 break-all">{brandFutureCodeOrFallback(opencodeOutput?.providerId)}</div>
        </div>
        <div className="rounded-md bg-[#f8fafc] border border-surface-container-high px-3 py-2">
          <div className="text-[11px] text-slate-500 mb-1">Model</div>
          <div className="text-sm text-slate-900 break-all">{opencodeOutput?.modelId || '-'}</div>
        </div>
        <div className="rounded-md bg-[#f8fafc] border border-surface-container-high px-3 py-2">
          <div className="text-[11px] text-slate-500 mb-1">Session</div>
          <div className="text-sm text-slate-900 break-all">{opencodeOutput?.sessionId || '-'}</div>
        </div>
      </div>

      <div
        ref={opencodeConsoleRef}
        className="max-h-[460px] overflow-y-auto px-4 py-4 font-mono text-xs leading-6 bg-white"
      >
        {opencodeStatus === 'waiting' && !opencodeParts.length ? (
          <div className="text-slate-700">
            <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-sky-700">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-500" />
              <span>system</span>
              <span className="text-slate-400">{latestEvent?.at ? formatEventTime(latestEvent.at) : '--:--:--'}</span>
            </div>
            <pre className="whitespace-pre-wrap break-words text-slate-700">
              {brandFutureCode(latestEvent?.message) || '会话已创建，正在等待 futurecode 返回原始片段。'}
            </pre>
          </div>
        ) : opencodeStatus === 'streaming' && !opencodeParts.length ? (
          <div className="text-slate-700">
            <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-sky-700">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-500" />
              <span>system</span>
              <span className="text-slate-400">{latestEvent?.at ? formatEventTime(latestEvent.at) : '--:--:--'}</span>
            </div>
            <pre className="whitespace-pre-wrap break-words text-slate-700">
              futurecode 已进入流式阶段，正在等待首个可展示片段。
            </pre>
          </div>
        ) : !opencodeParts.length ? (
          <div className="text-slate-700">
            <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
              <span className="h-1.5 w-1.5 rounded-full bg-slate-500" />
              <span>system</span>
            </div>
            <pre className="whitespace-pre-wrap break-words text-slate-500">
              暂无 futurecode 原始输出。
            </pre>
          </div>
        ) : (
          <div className="space-y-5">
          {opencodeParts.map((part, index) => (
            <div
              key={`${part.type || 'part'}-${index}`}
              className="last:pb-0"
            >
              <div className={`mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] ${
                opencodePartToneMap[part.type]?.label || 'text-slate-400'
              }`}>
                <span className={`h-1.5 w-1.5 rounded-full ${opencodePartToneMap[part.type]?.dot || 'bg-slate-500'}`} />
                <span className="font-semibold">
                  {opencodePartLabelMap[part.type] || part.type || 'Part'}
                </span>
                <span className="text-slate-400">
                  {opencodeOutput?.receivedAt ? formatEventTime(opencodeOutput.receivedAt) : '--:--:--'}
                </span>
              </div>
              <pre className={`whitespace-pre-wrap break-words ${
                opencodePartToneMap[part.type]?.body || 'text-slate-100'
              }`}>
                {formatOpencodePartText(part)}
              </pre>
            </div>
          ))}
          </div>
        )}

        {isRunning ? (
          <div className="mt-5 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-emerald-700">
            <span className="inline-block w-2 animate-pulse">▍</span>
            <span>
              {opencodeStatus === 'waiting'
                ? '等待 futurecode 返回更多内容'
                : 'futurecode 持续输出中'}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  )

  const taskItems = Array.isArray(data?.tasks) ? data.tasks : []

  const renderTasksCard = (className = '') => (
    <div className={`rounded-lg border border-surface-container-high bg-white p-4 ${className}`.trim()}>
      <h4 className="text-sm font-semibold text-on-surface">处理任务</h4>
      <div className="mt-3">
        {taskItems.length ? taskItems.map((task, index) => (
          <div
            key={task.id}
            className={`flex items-center justify-between gap-3 py-2.5 ${index < taskItems.length - 1 ? 'border-b border-surface-container-high' : ''}`}
          >
            <div className="flex items-center gap-2 text-sm text-on-surface min-w-0">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                task.status === 'done'
                  ? 'bg-secondary'
                  : task.status === 'failed'
                    ? 'bg-error'
                    : task.status === 'running'
                      ? 'bg-primary'
                      : 'bg-outline'
              }`} />
              <span className="truncate">{task.label}</span>
            </div>
            <span className={`text-xs font-medium ${taskStatusTextClassMap[task.status] || taskStatusTextClassMap.pending}`}>
              {taskStatusLabelMap[task.status] || '待处理'}
            </span>
          </div>
        )) : (
          <div className="text-sm text-on-surface-variant py-3">
            暂无任务明细
          </div>
        )}
      </div>
    </div>
  )

  const renderResultCard = (className = '') => {
    const rows = [
      { label: '文件名', value: data?.output?.fileName || '-' },
      { label: '章节数', value: data?.output?.chapterCount || '-' },
      { label: '生成时间', value: formatDateTime(data?.generatedAt) },
    ]

    return (
      <div className={`rounded-lg border border-surface-container-high bg-white p-4 ${className}`.trim()}>
        <h3 className="text-sm font-semibold text-on-surface mb-3">目录生成结果</h3>
        <div>
          {rows.map((row, index) => (
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
    )
  }

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
              onClick={handleGenerateDirectory}
              disabled={generating || isRunning}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {generating || isRunning ? '生成中...' : isCompleted ? '重新生成目录' : '生成目录'}
            </button>
            <button
              onClick={handleGoOutline}
              disabled={!isCompleted || advancing}
              title={!isCompleted ? '目录生成完成后可进入 S3' : ''}
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
              <h2 className="text-lg font-headline font-bold text-on-surface">目录生成状态</h2>
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

        {isRunning ? (
          <div className="pt-12 pb-1 flex flex-col gap-10">
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
              <div className="xl:col-span-7 rounded-lg border border-surface-container-high bg-white p-4">
                <h3 className="text-sm font-semibold text-on-surface mb-3">当前执行状态</h3>
                <div className="flex flex-col gap-3 text-sm">
                  <div className="rounded-md border border-primary/20 bg-primary/5 px-3 py-3 text-on-surface">
                    {brandFutureCode(latestEvent?.message) || '正在调用目录生成任务，请稍候。'}
                  </div>
                  <div className="text-on-surface-variant">
                    页面会实时接收流式进度，不需要手动反复点击。
                    {latestEvent ? ` 如果长时间停留在“${brandFutureCode(latestEvent.message)}”，通常说明当前步骤还没返回。` : ''}
                    {usePollingFallback ? ' 当前流式连接不可用，已自动切回轮询补偿。' : ''}
                  </div>
                </div>
              </div>
              <div className="xl:col-span-5">
                {renderTasksCard()}
              </div>
            </div>
            <div>
              {renderOpencodeOutputCard()}
            </div>
          </div>
        ) : !isCompleted ? (
          <div className="pt-12 pb-1 grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
            <div className="xl:col-span-7">
              <div className="rounded-lg border border-surface-container-high bg-white p-5 min-h-[228px] h-full flex flex-col">
                <h4 className="text-sm font-semibold text-on-surface">目录列表</h4>
                <div className="flex-1 flex items-center justify-center">
                  <button
                    onClick={handleGenerateDirectory}
                    disabled={generating}
                    className="stage-action-btn h-10 px-5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {generating ? '生成中...' : isFailed ? '重新生成目录' : '生成目录'}
                  </button>
                </div>
              </div>
            </div>

            <div className="xl:col-span-5 h-full">
              {renderTasksCard('h-full min-h-[228px]')}
            </div>
          </div>
        ) : (
          <div className="pt-12 pb-1 flex flex-col gap-10">
            <div className="flex flex-col xl:flex-row xl:items-stretch xl:justify-between gap-8">
              <div className="xl:w-[47%] flex">
                {renderResultCard('w-full h-full')}
              </div>
              <div className="xl:w-[47%] flex">
                {renderTasksCard('w-full h-full')}
              </div>
            </div>
            <div>
              {renderOpencodeOutputCard()}
            </div>
          </div>
        )}
      </DataCard>
    </div>
  )
}
