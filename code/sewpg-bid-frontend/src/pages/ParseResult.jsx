import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { parseAPI, projectsAPI, stagesAPI } from '../api'
import { PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const MAX_FILE_SIZE = 1024 * 1024 * 1024
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

const formatDateTime = (value) => {
  if (!value) return '未解析'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未解析'
  return date.toLocaleString('zh-CN', { hour12: false })
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

const REVIEW_DECISION_LABELS = {
  pending: '待解析',
  participate: '参与投标',
  abandon: '不参与',
}

export default function ParseResult({ showToast }) {
  const navigate = useNavigate()
  const { id } = useParams()
  const workspaceSlug = useWorkspaceSlug()
  const [project, setProject] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [advancing, setAdvancing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [templateFiles, setTemplateFiles] = useState([])

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [projectResponse, parseResponse] = await Promise.all([
        projectsAPI.get(id),
        parseAPI.results(id),
      ])
      setProject(projectResponse)
      setData(parseResponse)
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

  const reviewDecision = String(project?.reviewDecision || 'participate')
  const reviewDecisionLabel = REVIEW_DECISION_LABELS[reviewDecision] || REVIEW_DECISION_LABELS.pending
  const isParseCompleted = data?.status === 'completed'
  const isReviewApproved = reviewDecision === 'participate' || (isParseCompleted && sourceFiles.length > 0)
  const isProjectInfoComplete = Boolean(
    String(project?.name || '').trim()
    && String(project?.customerName || '').trim()
    && String(project?.manager || '').trim()
    && String(project?.deadline || '').trim(),
  )
  const canGoNextStage = isReviewApproved && isParseCompleted && isProjectInfoComplete

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
      const formData = new FormData()
      templateFiles.forEach((file) => formData.append('templateFiles', file))
      await parseAPI.uploadTemplates(id, { formData })
      setTemplateFiles([])
      await loadData()
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
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 1, { status: 'completed' })
      showToast?.('已进入 S2 目录生成')
      navigate(projectRoute(id, '/directory', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入下一阶段失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  if (loading) return <PageLoading title="正在加载 S1 模板上传信息..." />
  if (error) return <PageError title="S1 模板上传信息加载失败" description={error} onRetry={loadData} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        className="mb-2"
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={loadData}
              className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant font-medium rounded-lg hover:bg-surface-dim transition-colors text-sm"
            >
              刷新
            </button>
            <button
              onClick={handleGoNextStage}
              disabled={!canGoNextStage || advancing}
              title={!canGoNextStage ? '完成解析后可进入 S2（模板文件可选）' : ''}
              className="px-5 py-2.5 bg-secondary text-on-secondary font-medium rounded-lg shadow-sm hover:bg-secondary/90 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {advancing ? '进入中...' : '进入下一阶段'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-6 flex flex-col gap-5">
        <div className="flex items-center justify-end gap-4">
          <button
            onClick={handleUploadTemplateFiles}
            disabled={uploading || !templateFiles.length}
            className="stage-action-btn px-5 py-2.5 bg-primary text-on-primary font-semibold rounded-lg transition-colors hover:bg-primary/90 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? '上传中...' : '上传模板文件'}
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">解析决策状态</p>
            <p className="text-on-surface-variant">{reviewDecisionLabel}</p>
          </div>
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">招标文件解析状态</p>
            <p className="text-on-surface-variant">{isParseCompleted ? `已完成（${formatDateTime(data?.parsedAt)}）` : '未完成'}</p>
          </div>
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">已上传招标文件（只读）</p>
            <p className="text-on-surface-variant">{sourceFiles.length ? sourceFiles.map((item) => item.name).join('，') : '暂无'}</p>
          </div>
        </div>

        {!isReviewApproved && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error flex items-center justify-between gap-3">
            <span>当前项目尚未确认参与投标，请先到“解析”模块完成决策。</span>
            <button
              onClick={() => navigate(`/parse?projectId=${id}`)}
              className="h-[30px] px-3 bg-[#0067B6] text-white text-xs font-semibold"
            >
              前往解析模块
            </button>
          </div>
        )}
        {isReviewApproved && !isProjectInfoComplete && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error flex items-center justify-between gap-3">
            <span>当前项目信息未补全，请返回“解析”模块重新确认参与并补全项目信息。</span>
            <button
              onClick={() => navigate(`/parse?projectId=${id}`)}
              className="h-[30px] px-3 bg-[#0067B6] text-white text-xs font-semibold"
            >
              前往解析模块
            </button>
          </div>
        )}

        <div className="border border-surface-container-high rounded-md p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-on-surface">模板文件（可选）</h4>
            <span className="text-xs px-2 py-0.5 rounded-md bg-surface-container-high text-on-surface-variant">可选</span>
          </div>
          <div className="rounded-md border border-dashed border-[#8eb8de] bg-[#f2f8fd] p-3 flex justify-center">
            <button
              onClick={() => document.getElementById('s1-template-upload')?.click()}
              className="stage-action-btn h-10 min-w-[220px] px-5 bg-[#0067B6] text-white text-sm font-semibold hover:bg-[#0b74c8] transition-colors flex items-center justify-center gap-2"
            >
              <span className="material-symbols-outlined text-[18px]">upload_file</span>
              点击选择模版文件
            </button>
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
        </div>

        {uploadError && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
            {uploadError}
          </div>
        )}

        <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high text-xs text-outline">
          <p className="font-medium text-on-surface mb-1">已上传模板文件（当前项目）</p>
          <p>{uploadedTemplateFiles.length ? uploadedTemplateFiles.map((file) => file.name).join('，') : '暂无'}</p>
        </div>
      </DataCard>
    </div>
  )
}
