import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalDirectoryAPI, technicalParseAPI, technicalProjectsAPI, technicalStagesAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import DataCard from '../../../components/shared/DataCard'
import PageHeader from '../../../components/shared/PageHeader'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
import StageBreadcrumb from '../../../components/shared/StageBreadcrumb'
import Button from '../../../components/ui/Button'
import { bidTypeFromWorkspace, projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import {
  directoryDisplayPercentage,
  directoryElapsedSeconds,
  formatDirectoryDuration,
  isDirectoryProgressFailed,
  isDirectoryProgressRunning,
  mergeMonotonicDirectoryProgress,
  shouldShowTemplateDirectoryGenerationButton,
  summarizeDirectoryProgress,
} from '../technicalDirectoryProgress'
import { subscribeDirectoryProgress } from '../technicalDirectoryProgressStream'

const MAX_FILE_SIZE = 500 * 1024 * 1024
const MAX_BATCH_FILES = 5
const FILE_ACCEPT = '.pdf,.doc,.docx,.md,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'md', 'xls', 'xlsx', 'zip',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

const normalizeUploadedTemplateFiles = (files = []) =>
  (Array.isArray(files) ? files : [])
    .map((entry, index) => {
      if (typeof entry === 'string') {
        return {
          id: `TPL-${index + 1}`,
          name: entry,
          size: '-',
        }
      }
      return {
        id: entry?.id || `TPL-${index + 1}`,
        name: entry?.name || `模板文件-${index + 1}`,
        size: entry?.sizeLabel || entry?.size || '-',
      }
    })

const extensionOf = (name) => {
  const parts = String(name || '').split('.')
  if (parts.length < 2) return ''
  return String(parts.pop() || '').toLowerCase()
}

const fileSizeLabel = (size) => {
  const value = Number(size || 0)
  if (!Number.isFinite(value) || value <= 0) return '0 MB'
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

const validatePickedFiles = (picked = []) => {
  if (picked.length > MAX_BATCH_FILES) return `单次最多上传 ${MAX_BATCH_FILES} 个文件。`
  for (const file of picked) {
    if (Number(file.size || 0) > MAX_FILE_SIZE) return `文件 ${file.name} 超过 500MB 上限。`
    const ext = extensionOf(file.name)
    if (!ALLOWED_EXTENSIONS.has(ext)) return `文件 ${file.name} 类型不在白名单中。`
  }
  return ''
}

export default function TechnicalParseResult({ showToast, workspaceKind = 'tech' }) {
  const navigate = useNavigate()
  const { id } = useParams()
  const routeWorkspaceSlug = useWorkspaceSlug()
  const workspaceSlug = workspaceKind || routeWorkspaceSlug
  const workspaceBidType = bidTypeFromWorkspace(workspaceSlug)
  const bidLabel = workspaceBidType || '技术标'
  const [project, setProject] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [advancing, setAdvancing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [templateFiles, setTemplateFiles] = useState([])
  const [templateFallback, setTemplateFallback] = useState(null)
  const [directoryState, setDirectoryState] = useState(null)
  const [generatingDirectory, setGeneratingDirectory] = useState(false)
  const [autoAdvanceAfterDirectory, setAutoAdvanceAfterDirectory] = useState(false)
  const [directoryProgressClock, setDirectoryProgressClock] = useState(() => Date.now())

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [projectResponse, parseResponse, fallbackResponse, directoryResponse] = await Promise.all([
        technicalProjectsAPI.get(id),
        technicalParseAPI.results(id),
        technicalProjectsAPI.templateFallback(id),
        technicalDirectoryAPI.status(id).catch(() => null),
      ])
      setProject(projectResponse)
      setData(parseResponse)
      setTemplateFallback(fallbackResponse)
      setDirectoryState((previous) => mergeMonotonicDirectoryProgress(previous, directoryResponse))
    } catch (e) {
      setError(e?.message || 'S1 模板上传信息加载失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData])

  const sourceFiles = Array.isArray(data?.sourceFiles) && data.sourceFiles.length
    ? data.sourceFiles
    : (Array.isArray(project?.files) ? project.files.map((name, index) => ({ id: `SRC-${index + 1}`, name })) : [])

  const uploadedTemplateFiles = useMemo(
    () => normalizeUploadedTemplateFiles(project?.templateFiles),
    [project?.templateFiles],
  )
  const fallbackTemplate = templateFallback?.template || {}
  const fallbackEnabled = Boolean(templateFallback?.enabled ?? project?.templateFallback?.enabled ?? true)
  const fallbackAvailable = Boolean(fallbackTemplate?.available)
  const fallbackWillBeUsed = fallbackEnabled && fallbackAvailable && uploadedTemplateFiles.length === 0

  // 缺字段时默认按未参与处理，避免临时/暂存项目被误判为已参与
  const reviewDecision = String(project?.reviewDecision || 'pending')
  const isParseCompleted = data?.status === 'completed'
  // 只认后端明确的参与决策，不再以"解析完成+有源文件"放宽，否则参与闸门被旁路
  const isReviewApproved = reviewDecision === 'participate'
  const isProjectInfoComplete = Boolean(
    String(project?.name || '').trim()
    && String(project?.customerName || '').trim()
    && String(project?.manager || '').trim()
    && String(project?.startDate || '').trim()
    && String(project?.endDate || project?.deadline || '').trim(),
  )
  const canGoNextStage = isReviewApproved && isParseCompleted && isProjectInfoComplete
  const directoryStatus = directoryState?.status || 'idle'
  const isDirectoryRunning = isDirectoryProgressRunning(directoryState)
  const isDirectoryCompleted = directoryStatus === 'completed'
  const isDirectoryFailed = isDirectoryProgressFailed(directoryState)
  const showDirectoryGenerationButton = shouldShowTemplateDirectoryGenerationButton(directoryState || {})
  const directoryProgressSummary = summarizeDirectoryProgress(directoryState || {})
  const directoryProgressBadgeClass = directoryProgressSummary.tone === 'danger'
    ? 'bg-error-container text-error'
    : directoryProgressSummary.tone === 'success'
      ? 'bg-secondary-container text-on-secondary-container'
      : directoryProgressSummary.tone === 'running'
        ? 'bg-primary/10 text-primary'
        : 'bg-surface-container-high text-on-surface-variant'
  const directoryProgressBarClass = directoryProgressSummary.tone === 'danger'
    ? 'bg-error'
    : directoryProgressSummary.tone === 'success'
      ? 'bg-secondary'
      : 'bg-primary'
  const elapsedDirectorySeconds = directoryElapsedSeconds(directoryState || {}, directoryProgressClock)
  const displayPercentage = directoryDisplayPercentage(directoryState || {}, directoryProgressClock)
  const elapsedDurationText = formatDirectoryDuration(elapsedDirectorySeconds)
  const elapsedLineText = elapsedDurationText
    ? `${isDirectoryCompleted ? '总耗时' : '已运行'} ${elapsedDurationText}`
    : ''

  useEffect(() => {
    if (!isDirectoryRunning) return undefined
    const timer = window.setInterval(() => setDirectoryProgressClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isDirectoryRunning])

  useEffect(() => {
    if (!isDirectoryRunning) return undefined
    return subscribeDirectoryProgress({
      openStream: (handlers) => technicalDirectoryAPI.stream(id, handlers),
      fetchStatus: () => technicalDirectoryAPI.status(id),
      onState: (payload) => {
        setDirectoryState((previous) => mergeMonotonicDirectoryProgress(previous, payload))
      },
    })
  }, [id, isDirectoryRunning])

  useEffect(() => {
    if (!autoAdvanceAfterDirectory || !isDirectoryCompleted) return undefined
    let cancelled = false
    const timer = window.setTimeout(async () => {
      setAdvancing(true)
      try {
        await technicalStagesAPI.update(id, 1, { status: 'completed' })
        if (!cancelled) {
          setAutoAdvanceAfterDirectory(false)
          showToast?.('目录生成完成，已进入目录确认')
          navigate(projectRoute(id, '/outline', workspaceSlug))
        }
      } catch (e) {
        if (!cancelled) {
          setAutoAdvanceAfterDirectory(false)
          showToast?.(e?.message || '自动进入目录确认失败，请点击按钮进入。', 'error')
        }
      } finally {
        if (!cancelled) setAdvancing(false)
      }
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [autoAdvanceAfterDirectory, id, isDirectoryCompleted, navigate, showToast, workspaceSlug])

  const handleFilesPicked = (event) => {
    const picked = Array.from(event.target.files || [])
    event.target.value = ''
    if (!picked.length) return

    const validationError = validatePickedFiles(picked)
    if (validationError) {
      setUploadError(validationError)
      return
    }
    setUploadError('')
    setTemplateFiles(picked)
  }

  const removePickedFile = (index) => {
    setTemplateFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const uploadSelectedTemplateFiles = async () => {
    const formData = new FormData()
    templateFiles.forEach((file) => formData.append('templateFiles', file))
    await technicalParseAPI.uploadTemplates(id, { formData })
    setTemplateFiles([])
    await loadData()
  }

  const handleUploadTemplateFiles = async () => {
    if (!isProjectInfoComplete) {
      showToast?.('请先返回“解析”模块，重新确认参与并补全项目信息。', 'error')
      return
    }
    if (!isReviewApproved) {
      showToast?.('请先在“解析”模块确认“参与投标”。', 'error')
      return
    }
    if (!sourceFiles.length || !isParseCompleted) {
      showToast?.('请先在“解析”模块完成招标文件解析。', 'error')
      return
    }
    if (!templateFiles.length) {
      const message = '请先选择模板文件。'
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }

    setUploading(true)
    setUploadError('')
    try {
      await uploadSelectedTemplateFiles()
      showToast?.('模板文件上传成功。')
    } catch (e) {
      const message = e?.message || '模板文件上传失败'
      setUploadError(message)
      showToast?.(message, 'error')
    } finally {
      setUploading(false)
    }
  }

  const handleGoNextStage = async () => {
    if (!isProjectInfoComplete) {
      showToast?.('请先返回“解析”模块，重新确认参与并补全项目信息。', 'error')
      return
    }
    if (!isReviewApproved) {
      showToast?.('当前项目尚未确认参与投标，请先前往“解析”模块处理。', 'error')
      return
    }
    if (!isParseCompleted) {
      showToast?.('请先在“解析”模块完成招标文件解析。', 'error')
      return
    }
    // 目录未生成完成时不推进阶段，避免出现"阶段已完成但目录未生成"的不一致状态
    if (!isDirectoryCompleted) {
      showToast?.('请先在当前页生成目录')
      return
    }
    setAdvancing(true)
    try {
      await technicalStagesAPI.update(id, 1, { status: 'completed' })
      showToast?.('已进入目录确认')
      navigate(projectRoute(id, '/outline', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入下一阶段失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  const handleGenerateDirectory = async () => {
    if (!canGoNextStage) {
      showToast?.('请先完成解析、确认参与并补全项目信息。', 'error')
      return
    }
    if (generatingDirectory || isDirectoryRunning) return
    setGeneratingDirectory(true)
    try {
      if (templateFiles.length) {
        await uploadSelectedTemplateFiles()
        showToast?.('模板文件已上传，开始生成目录。')
      } else if (!uploadedTemplateFiles.length && !fallbackWillBeUsed) {
        showToast?.(`请先上传${bidLabel}模板文件。`, 'error')
        return
      }
      // 目录 run 成功后再由完成轮询触发阶段推进（见 autoAdvanceAfterDirectory effect），
      // 不在 run 之前提前置阶段 completed，避免 run 失败时阶段已被错误推进
      const payload = await technicalDirectoryAPI.run(id)
      setDirectoryState(payload)
      setAutoAdvanceAfterDirectory(true)
      showToast?.(payload?.message || '已开始生成目录。')
    } catch (e) {
      setAutoAdvanceAfterDirectory(false)
      showToast?.(e?.message || '目录生成失败', 'error')
    } finally {
      setGeneratingDirectory(false)
    }
  }

  if (loading) return <PageLoading title="正在加载目录生成..." />
  if (error) return <PageError title="目录生成加载失败" description={error} onRetry={loadData} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <TechnicalProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        className="mb-2"
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <Button
              onClick={handleGoNextStage}
              disabled={!canGoNextStage || !isDirectoryCompleted || advancing}
              title={!isDirectoryCompleted ? '目录生成完成后可进入目录确认' : ''}
              size="lg"
              variant="success"
            >
              {advancing ? '进入中...' : '进入目录确认'}
            </Button>
          </>
        )}
      />

      <div className="business-ui-shell mx-auto w-full max-w-[1120px]">
        <DataCard className="!p-0 overflow-hidden">
          <div className="business-section-head flex items-center px-6 py-5">
            <div className="flex items-center">
              <h2 className="text-2xl font-headline font-extrabold text-primary">生成投标文件目录</h2>
            </div>
          </div>
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.82fr)]">
          <div className="flex min-h-[388px] flex-col gap-4 border-b border-surface-container-high p-6 lg:border-b-0 lg:border-r">
        {!isReviewApproved && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error flex items-center justify-between gap-3">
            <span>当前项目尚未确认参与投标，请先到“解析”模块完成决策。</span>
            <Button
              onClick={() => navigate(`/parse/technical?projectId=${id}`)}
              size="sm"
              variant="primary"
            >
              前往解析模块
            </Button>
          </div>
        )}
        {isReviewApproved && !isProjectInfoComplete && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error flex items-center justify-between gap-3">
            <span>当前项目信息未补全，请返回“解析”模块重新确认参与并补全项目信息。</span>
            <Button
              onClick={() => navigate(`/parse/technical?projectId=${id}`)}
              size="sm"
              variant="primary"
            >
              前往解析模块
            </Button>
          </div>
        )}

        <div className="business-panel flex min-h-[208px] flex-col gap-3 rounded-md border border-surface-container-high bg-surface-container-lowest p-4">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="text-sm font-semibold text-on-surface">模板文件</h4>
            </div>
            <span className="text-xs px-2 py-0.5 rounded-md bg-surface-container-high text-on-surface-variant">可选</span>
          </div>
          <div className="business-dropzone flex min-h-[116px] flex-1 items-center justify-center rounded-md border border-dashed">
            <Button
              onClick={() => document.getElementById('s1-template-upload')?.click()}
              className="min-w-[180px] bg-white text-on-surface shadow-sm hover:bg-surface-container-low"
              icon="upload_file"
              size="lg"
              variant="quiet"
            >
              选择模板文件
            </Button>
          </div>
          <input
            id="s1-template-upload"
            type="file"
            className="hidden"
            accept={FILE_ACCEPT}
            multiple
            onChange={handleFilesPicked}
          />
          {templateFiles.length > 0 && (
            <div className="flex flex-col gap-2">
              {templateFiles.map((file, index) => (
                <div key={`${file.name}-${index}`} className="flex items-center gap-3 p-3 bg-surface-container-low rounded-md border border-surface-container-high">
                  <span className="text-sm text-on-surface flex-1 truncate" title={file.name}>{file.name}</span>
                  <span className="text-xs text-outline">{fileSizeLabel(file.size)}</span>
                  <button
                    onClick={() => removePickedFile(index)}
                    className="text-error hover:bg-error-container/30 w-6 h-6 flex items-center justify-center"
                  >
                    <span className="material-symbols-outlined text-sm">close</span>
                  </button>
                </div>
              ))}
            </div>
          )}
          {uploadedTemplateFiles.length > 0 && (
            <div className="flex flex-col gap-2" aria-label="已上传项目模板">
              {uploadedTemplateFiles.map((file) => (
                <div key={file.id} className="flex items-center gap-3 rounded-md bg-surface-container-low px-3 py-2.5">
                  <span className="material-symbols-outlined text-[18px] text-primary" aria-hidden="true">description</span>
                  <span className="min-w-0 flex-1 truncate text-sm text-on-surface" title={file.name}>{file.name}</span>
                  <span className="shrink-0 text-xs text-outline">{file.size}</span>
                  <span className="shrink-0 rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">项目模板</span>
                </div>
              ))}
            </div>
          )}
          {fallbackWillBeUsed && (
            <div className="flex items-center gap-3 rounded-md bg-surface-container-low px-3 py-2.5" aria-label="当前默认模板">
              <span className="material-symbols-outlined text-[18px] text-primary" aria-hidden="true">description</span>
              <span className="min-w-0 flex-1 truncate text-sm text-on-surface" title={fallbackTemplate.name}>
                {fallbackTemplate.name || '默认技术标模板'}
              </span>
              <span className="shrink-0 text-xs text-outline">{fallbackTemplate.sizeLabel || '-'}</span>
              <span className="shrink-0 rounded-md bg-surface-container-high px-2 py-0.5 text-xs font-medium text-on-surface-variant">默认模板</span>
            </div>
          )}
          {!uploadedTemplateFiles.length && !fallbackWillBeUsed ? (
            <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
              未检测到项目模板，且默认模板不可用。请先上传{bidLabel}模板文件。
            </div>
          ) : null}
        </div>
        <div className="flex h-[34px] justify-center">
          <Button
            onClick={handleUploadTemplateFiles}
            disabled={uploading || isDirectoryRunning || !templateFiles.length}
            size="stage"
            variant="primary"
          >
            {uploading ? '上传中...' : '上传模板文件'}
          </Button>
        </div>

        {uploadError && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
            {uploadError}
          </div>
        )}

          </div>

          <div className="flex min-h-[388px] flex-col gap-4 p-6">
            <h3 className="text-base font-headline font-bold text-on-surface">目录生成</h3>

          <div className="flex min-h-[132px] items-center">
            {(isDirectoryRunning || isDirectoryCompleted || isDirectoryFailed) ? (
              <div className={[
                'w-full border-y px-4 py-4',
                isDirectoryFailed
                  ? 'border-error/30 bg-error-container/10'
                  : 'border-surface-container-high bg-surface-container-low',
              ].join(' ')}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <span
                      aria-hidden="true"
                      className={[
                        'material-symbols-outlined mt-0.5 text-[20px]',
                        isDirectoryFailed
                          ? 'text-error'
                          : isDirectoryCompleted
                            ? 'text-secondary'
                            : 'animate-spin-slow text-primary',
                      ].join(' ')}
                    >
                      {isDirectoryFailed ? 'error' : isDirectoryCompleted ? 'check_circle' : 'progress_activity'}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold tabular-nums text-on-surface">
                        {directoryProgressSummary.summary}
                      </p>
                      {elapsedLineText ? (
                        <p className="mt-1 text-xs leading-5 tabular-nums text-outline">{elapsedLineText}</p>
                      ) : null}
                    </div>
                  </div>
                  <span className={[
                    'shrink-0 self-start rounded-md px-2.5 py-1 text-xs font-semibold tabular-nums',
                    directoryProgressBadgeClass,
                  ].join(' ')}>
                    {directoryProgressSummary.statusText} · {Math.floor(displayPercentage)}%
                  </span>
                </div>

                <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-container-high">
                  <div
                    className={[
                      'h-full rounded-full transition-all duration-1000 ease-linear',
                      directoryProgressBarClass,
                      isDirectoryRunning ? 'bg-stripes' : '',
                    ].join(' ')}
                    style={{ width: `${displayPercentage}%` }}
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex h-[34px] justify-center">
            {showDirectoryGenerationButton ? (
              <Button
                onClick={handleGenerateDirectory}
                disabled={!canGoNextStage || generatingDirectory || isDirectoryRunning}
                size="stage"
                variant="primary"
              >
                {generatingDirectory || isDirectoryRunning
                  ? '生成中...'
                  : isDirectoryFailed
                    ? '重试生成目录'
                    : '生成目录'}
              </Button>
            ) : null}
          </div>

          </div>
        </div>
        </DataCard>
      </div>
    </div>
  )
}
