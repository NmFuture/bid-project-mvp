import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { directoryAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'

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
      return JSON.stringify(JSON.parse(rawText), null, 2)
    } catch {
      return rawText
    }
  }
  return rawText
}

export default function DirectoryGeneration({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(false)
  const [advancing, setAdvancing] = useState(false)

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

  useEffect(() => {
    if (!isRunning) return undefined

    const timer = window.setInterval(() => {
      loadData({ silent: true })
    }, 1000)

    return () => window.clearInterval(timer)
  }, [isRunning, loadData])

  const handleGenerateDirectory = async () => {
    if (generating || isRunning) return
    setGenerating(true)
    try {
      const response = await directoryAPI.run(id)
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

  const statusTextMap = {
    idle: '未生成',
    running: '生成中',
    completed: '已生成',
    failed: '生成失败',
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
    failed: 'bg-error/15 text-error',
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
          <h3 className="text-sm font-semibold text-on-surface">opencode 输出</h3>
          <p className="text-xs text-on-surface-variant mt-1">
            这里直接显示 opencode 返回的原始片段；如果还没返回，会明确提示当前在等待。
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
          <div className="text-sm text-on-surface break-all">{opencodeOutput?.providerId || '-'}</div>
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
          <div className="font-medium">会话已创建，正在等待 opencode 返回原始片段。</div>
          <div className="mt-2 text-on-surface-variant">
            {latestEvent?.message || '当前还没有收到 reasoning/text 片段，请稍候。'}
          </div>
        </div>
      ) : !opencodeParts.length ? (
        <div className="rounded-lg border border-dashed border-surface-container-high px-3 py-4 text-sm text-on-surface-variant">
          暂无 opencode 原始输出。
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
        title="S2 目录生成"
        description="点击生成目录后调用后端接口，返回 docx 目录结果；完成后可进入 S3。"
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
              onClick={handleGenerateDirectory}
              disabled={generating || isRunning}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">auto_awesome</span>
              {generating || isRunning ? '生成中...' : isCompleted ? '重新生成目录' : '生成目录'}
            </button>
            <button
              onClick={handleGoOutline}
              disabled={!isCompleted || advancing}
              title={!isCompleted ? '目录生成完成后可进入 S3' : ''}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-sm">arrow_forward</span>
              {advancing ? '进入中...' : '进入下一阶段（S3）'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden min-h-[420px]">
        <div className="px-6 py-5 border-b border-surface-container-high bg-surface-container-low">
          <div className="flex items-center justify-between gap-4 mb-4">
            <div>
              <h2 className="text-lg font-headline font-bold text-on-surface">目录生成状态</h2>
              <p className="text-sm text-on-surface-variant mt-1">{data?.summary || '等待生成目录。'}</p>
            </div>
            <span className={`text-xs font-semibold px-3 py-1 rounded-full ${
              isCompleted
                ? 'bg-secondary-container text-on-secondary-container'
                : isRunning
                  ? 'bg-primary/15 text-primary'
                  : isFailed
                    ? 'bg-error/15 text-error'
                    : 'bg-surface-container-high text-on-surface-variant'
            }`}>
              {statusTextMap[status] || '未生成'}
            </span>
          </div>
          <div className="w-full h-2.5 bg-surface-container-high rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary to-secondary rounded-full transition-all duration-700"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="mt-2 text-xs text-outline">当前完成度：{progress}%</div>
        </div>

        {isRunning ? (
          <div className="px-6 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
              <h3 className="text-sm font-semibold text-on-surface mb-3">当前执行状态</h3>
              <div className="flex flex-col gap-3 text-sm">
                <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-3 text-on-surface">
                  {data?.summary || '正在调用目录生成任务，请稍候。'}
                </div>
                <div className="text-on-surface-variant">
                  页面会自动刷新进度，不需要手动反复点击。
                  {latestEvent ? ` 如果长时间停留在“${latestEvent.message}”，通常说明当前步骤还没返回。` : ''}
                </div>
                <div className="flex flex-col gap-2 pt-1">
                  <h4 className="text-sm font-semibold text-on-surface">处理任务</h4>
                  {(data?.tasks || []).map((task) => (
                    <div key={task.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-container-lowest">
                      <div className="flex items-center gap-2 text-sm text-on-surface">
                        <span className={`material-symbols-outlined text-sm ${
                          task.status === 'running' ? 'text-primary animate-pulse' : 'text-primary'
                        }`}
                        >
                          {task.status === 'done' ? 'check_circle' : task.status === 'failed' ? 'error' : task.status === 'running' ? 'progress_activity' : 'schedule'}
                        </span>
                        {task.label}
                      </div>
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${taskStatusClassMap[task.status] || taskStatusClassMap.pending}`}>
                        {taskStatusLabelMap[task.status] || '待处理'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {renderOpencodeOutputCard()}
          </div>
        ) : !isCompleted ? (
          <div className="h-[300px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className={`material-symbols-outlined text-3xl ${isFailed ? 'text-error' : 'text-primary'}`}>
                {isFailed ? 'error' : 'rule_folder'}
              </span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">
              {isFailed ? 'S2 目录生成失败' : 'S2 未生成目录'}
            </h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              {isFailed
                ? (data?.summary || '本次目录生成没有成功，你可以直接重新触发。')
                : '点击“生成目录”后，将调用后端目录生成接口，返回 `docx` 目录结果并展示给前端。'}
            </p>
            <button
              onClick={handleGenerateDirectory}
              disabled={generating}
              className="mt-6 px-5 py-2.5 bg-primary text-on-primary text-sm font-semibold rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {generating ? '生成中...' : isFailed ? '重新生成目录' : '生成目录'}
            </button>
          </div>
        ) : (
          <div className="px-6 py-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="rounded-lg border border-surface-container-high bg-surface-container-low p-4">
              <h3 className="text-sm font-semibold text-on-surface mb-3">目录生成结果（docx）</h3>
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-on-surface-variant">文件名</span>
                  <span className="text-on-surface font-medium">{data?.output?.fileName || '-'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-on-surface-variant">文件类型</span>
                  <span className="text-on-surface font-medium uppercase">{data?.output?.fileType || 'docx'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-on-surface-variant">章节数</span>
                  <span className="text-on-surface font-medium">{data?.output?.chapterCount || '-'}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-on-surface-variant">生成时间</span>
                  <span className="text-on-surface font-medium">{formatDateTime(data?.generatedAt)}</span>
                </div>
              </div>
              <div className="mt-4 pt-4 border-t border-surface-container-high flex flex-col gap-2">
                <h4 className="text-sm font-semibold text-on-surface">处理任务</h4>
                {(data?.tasks || []).map((task) => (
                  <div key={task.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-container-lowest">
                    <div className="flex items-center gap-2 text-sm text-on-surface">
                      <span className="material-symbols-outlined text-sm text-primary">checklist</span>
                      {task.label}
                    </div>
                    <span className={`text-xs font-medium px-2 py-1 rounded-full ${taskStatusClassMap[task.status] || taskStatusClassMap.pending}`}>
                      {taskStatusLabelMap[task.status] || '待处理'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {renderOpencodeOutputCard()}
          </div>
        )}
      </DataCard>
    </div>
  )
}
