import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { parseAPI, projectsAPI } from '../api'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import PageHeader from '../components/shared/PageHeader'
import ProjectWizardModal from '../components/modals/ProjectWizardModal'
import { projectRoute, slugFromBidType } from '../utils/workspace'

const MAX_FILE_SIZE = 500 * 1024 * 1024
const MAX_BATCH_FILES = 5
const FILE_ACCEPT = '.pdf,.doc,.docx,.md,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'md', 'xls', 'xlsx', 'zip',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

const REVIEW_DECISION_LABELS = {
  pending: '待解析',
  participate: '参与投标',
  abandon: '不参与',
}

const REVIEW_DECISION_BADGE_CLASSES = {
  pending: 'bg-[#e8eef2] text-on-surface-variant',
  participate: 'bg-secondary-container text-on-secondary-container',
  abandon: 'bg-error-container text-error',
}

const extensionOf = (name) => {
  const parts = String(name || '').split('.')
  if (parts.length < 2) return ''
  return String(parts.pop() || '').toLowerCase()
}

const getFileTypeLabel = (fileName = '') => {
  const ext = extensionOf(fileName)
  if (ext === 'pdf') return 'PDF'
  if (ext === 'docx' || ext === 'doc') return 'DOCX'
  if (ext === 'md') return 'MD'
  if (ext === 'xlsx' || ext === 'xls') return 'XLSX'
  return '文件'
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

const buildFallbackSourceFiles = (fileNames = []) =>
  fileNames.map((name, index) => ({
    id: `SRC-${index + 1}`,
    name,
    type: getFileTypeLabel(name),
    pageCount: '-',
    size: '-',
  }))

export default function TenderReview({ showToast }) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const queryProjectId = String(searchParams.get('projectId') || '').trim()
  const [projects, setProjects] = useState([])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [project, setProject] = useState(null)
  const [parseData, setParseData] = useState(null)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [tenderFiles, setTenderFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [deciding, setDeciding] = useState('')
  const [creatingReview, setCreatingReview] = useState(false)
  const [showProjectInfoModal, setShowProjectInfoModal] = useState(false)
  const [projectToComplete, setProjectToComplete] = useState(null)

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true)
    setError('')
    try {
      const data = await projectsAPI.list({ page: 1, pageSize: 200 })
      const items = Array.isArray(data?.items) ? data.items : []
      const reviewItemsBase = items.filter((item) => String(item?.reviewDecision || 'pending') !== 'participate')
      const forced = queryProjectId ? items.find((item) => item.id === queryProjectId) : null
      const reviewItems = forced && !reviewItemsBase.some((item) => item.id === forced.id)
        ? [forced, ...reviewItemsBase]
        : reviewItemsBase
      setProjects(items)
      setSelectedProjectId((current) => {
        if (queryProjectId && reviewItems.some((item) => item.id === queryProjectId)) return queryProjectId
        if (current && reviewItems.some((item) => item.id === current)) return current
        return reviewItems[0]?.id || ''
      })
    } catch (e) {
      setError(e?.message || '解析项目列表加载失败')
    } finally {
      setLoadingProjects(false)
    }
  }, [queryProjectId])

  const loadCurrentProject = useCallback(async () => {
    if (!selectedProjectId) {
      setProject(null)
      setParseData(null)
      return
    }
    setLoadingDetail(true)
    setError('')
    try {
      const [projectData, parseResult] = await Promise.all([
        projectsAPI.get(selectedProjectId),
        parseAPI.results(selectedProjectId),
      ])
      setProject(projectData)
      setParseData(parseResult)
    } catch (e) {
      setError(e?.message || '解析详情加载失败')
    } finally {
      setLoadingDetail(false)
    }
  }, [selectedProjectId])

  const createReviewProject = useCallback(async ({ toastMessage } = {}) => {
    setCreatingReview(true)
    try {
      const now = new Date()
      const pad = (num) => String(num).padStart(2, '0')
      const name = `待解析项目-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
      const created = await projectsAPI.create({
        name,
        customerName: '',
        owner: '',
        manager: '',
        bidType: '技术标',
        deadline: '',
        reviewDecision: 'pending',
      })
      await loadProjects()
      setSelectedProjectId(created?.id || '')
      if (toastMessage) {
        showToast?.(toastMessage)
      } else {
        showToast?.('已新建解析项目，请上传招标文件并解析。')
      }
      return created
    } catch (e) {
      showToast?.(e?.message || '新建解析项目失败', 'error')
      return null
    } finally {
      setCreatingReview(false)
    }
  }, [loadProjects, showToast])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadProjects()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadProjects])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadCurrentProject()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadCurrentProject])

  const sourceFiles = Array.isArray(parseData?.sourceFiles) && parseData.sourceFiles.length
    ? parseData.sourceFiles
    : buildFallbackSourceFiles(project?.files || [])
  const reviewProjects = useMemo(() => {
    const base = projects.filter((item) => String(item?.reviewDecision || 'pending') !== 'participate')
    const forced = queryProjectId ? projects.find((item) => item.id === queryProjectId) : null
    if (forced && !base.some((item) => item.id === forced.id)) return [forced, ...base]
    return base
  }, [projects, queryProjectId])

  const parsedItems = useMemo(() => parseData?.items || [], [parseData?.items])
  const structuredCategories = useMemo(
    () => (Array.isArray(parseData?.structured?.categories) ? parseData.structured.categories : []),
    [parseData],
  )
  const parsedDates = parseData?.structured?.projectDates || parseData?.summary?.projectDates || {}
  const structuredRows = useMemo(() => {
    if (!parsedItems.length) return []
    return parsedItems.map((item, index) => {
      const fileName = item.sourceFile || sourceFiles[0]?.name || '-'
      const fileMeta = sourceFiles.find((file) => file.name === fileName)
      const value = item.keyEntity && item.keyValue
        ? `${item.keyEntity}：${item.keyValue}`
        : item.keyValue || item.keyEntity || item.title || '-'
      return {
        id: item.id || `TP-${index + 1}`,
        category: item.type || item.category || '-',
        field: item.keyEntity || item.title || '-',
        value,
        fileName,
        fileType: fileMeta?.type || getFileTypeLabel(fileName),
        evidenceLocation: item.evidenceLocation || (item.page ? `P.${item.page}` : '-'),
        evidence: item.evidence || '-',
      }
    })
  }, [parsedItems, sourceFiles])

  const fallbackRows = useMemo(() => {
    if (!sourceFiles.length) return []
    return sourceFiles.map((file) => ({
      id: file.id || file.name,
      category: '-',
      field: file.name,
      value: parseData?.status === 'completed' ? '未提取到结构化结果' : '待触发解析',
      fileName: file.name,
      fileType: file.type || getFileTypeLabel(file.name),
      evidenceLocation: file.pageCount || '-',
      evidence: '-',
    }))
  }, [sourceFiles, parseData?.status])

  const rows = structuredRows.length ? structuredRows : fallbackRows
  const isParseCompleted = parseData?.status === 'completed'
  const reviewDecision = String(project?.reviewDecision || 'pending')
  const reviewDecisionLabel = REVIEW_DECISION_LABELS[reviewDecision] || REVIEW_DECISION_LABELS.pending

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
    setTenderFiles(picked)
  }

  const removePickedFile = (index) => {
    setTenderFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleUploadAndParse = async () => {
    if (!selectedProjectId) {
      showToast?.('当前没有可解析项目，请先新建解析项目。', 'error')
      return
    }
    if (reviewDecision === 'abandon') {
      showToast?.('当前项目已标记为不参与，如需继续请先切换为“参与投标”。', 'error')
      return
    }
    if (!tenderFiles.length) {
      const message = '请先上传招标文件后再解析。'
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }

    setUploading(true)
    setUploadError('')
    try {
      const formData = new FormData()
      tenderFiles.forEach((file) => formData.append('tenderFiles', file))
      const response = await parseAPI.uploadAndRun(selectedProjectId, { formData })
      setParseData(response)
      const latestProject = await projectsAPI.get(selectedProjectId)
      setProject(latestProject)
      setProjects((prev) => prev.map((item) => (
        item.id === latestProject.id ? { ...item, ...latestProject } : item
      )))
      setTenderFiles([])
      showToast?.(response?.message || '招标文件解析完成。')
    } catch (e) {
      const message = e?.message || '上传并解析失败'
      setUploadError(message)
      showToast?.(message, 'error')
    } finally {
      setUploading(false)
    }
  }

  const handleDecision = async (decision) => {
    if (!selectedProjectId) return
    if (decision === 'participate' && !isParseCompleted) {
      showToast?.('请先完成招标文件解析，再确认参与投标。', 'error')
      return
    }
    if (decision === 'participate') {
      setProjectToComplete(project)
      setShowProjectInfoModal(true)
      return
    }

    setDeciding(decision)
    try {
      await projectsAPI.delete(selectedProjectId)
      setProjects((prev) => prev.filter((item) => item.id !== selectedProjectId))
      setProject(null)
      setParseData(null)
      setTenderFiles([])
      setUploadError('')
      await createReviewProject({
        toastMessage: '该项目已设为不参与并移出项目总览，已自动新建解析项目。',
      })
    } catch (e) {
      showToast?.(e?.message || '处理不参与流程失败', 'error')
    } finally {
      setDeciding('')
    }
  }

  const handleCreateReviewProject = async () => {
    await createReviewProject()
  }

  const renderPickedFiles = () => {
    if (!tenderFiles.length) return null
    return (
      <div className="flex flex-col gap-2">
        {tenderFiles.map((file, index) => (
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
    )
  }

  if (loadingProjects) return <PageLoading title="正在加载解析模块..." />
  if (error) return <PageError title="解析模块加载失败" description={error} onRetry={loadProjects} />
  if (!reviewProjects.length) {
    return (
      <div className="review-page flex flex-col gap-6 animate-fade-in max-w-none">
        <PageHeader
          actionsClassName="stage-header-actions"
          actions={(
            <button
              onClick={loadProjects}
              className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant font-medium rounded-lg hover:bg-surface-dim transition-colors text-sm"
            >
              刷新
            </button>
          )}
        />
        <DataCard className="!p-6 flex flex-col gap-4">
          <PageEmpty
            title="暂无待解析项目"
            description="你可以在这里先新建解析项目，再上传招标文件进行判断。"
          />
          <div className="flex justify-center">
            <button
              onClick={handleCreateReviewProject}
              disabled={creatingReview}
              className="stage-action-btn h-[34px] px-5 bg-[#0067B6] text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creatingReview ? '新建中...' : '新建解析项目'}
            </button>
          </div>
        </DataCard>
      </div>
    )
  }
  if (loadingDetail) return <PageLoading title="正在加载项目解析详情..." />

  return (
    <div className="review-page flex flex-col gap-6 animate-fade-in max-w-none">
      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={handleCreateReviewProject}
              disabled={creatingReview}
              className="px-5 py-2.5 bg-[#0067B6] text-white font-medium rounded-lg hover:bg-[#0b74c8] transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creatingReview ? '新建中...' : '新建解析项目'}
            </button>
            <button
              onClick={() => {
                loadProjects()
                loadCurrentProject()
              }}
              className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant font-medium rounded-lg hover:bg-surface-dim transition-colors text-sm"
            >
              刷新
            </button>
          </>
        )}
      />

      <DataCard className="!p-6 flex flex-col gap-5">
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
          <div className="xl:col-span-8 rounded-md bg-[#f7f7f7] border border-surface-container-high px-4 py-3">
            <p className="text-xs text-outline mb-1">当前解析项目</p>
            <p className="text-sm font-semibold text-on-surface">{project?.id || '-'} · {project?.name || '未命名项目'}</p>
          </div>
          <div className="xl:col-span-4 rounded-md bg-[#f7f7f7] border border-surface-container-high px-4 py-3 flex items-center justify-between">
            <span className="text-sm text-on-surface-variant">解析状态</span>
            <span className={`text-xs px-2.5 py-1 rounded-md font-semibold ${REVIEW_DECISION_BADGE_CLASSES[reviewDecision] || REVIEW_DECISION_BADGE_CLASSES.pending}`}>
              {reviewDecisionLabel}
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">招标文件上传与关键参数解析</h3>
            <p className="text-xs text-outline mt-1">本模块负责上传多份招标文件并解析结构化要求，供投标决策判断。</p>
          </div>
          <button
            onClick={handleUploadAndParse}
            disabled={uploading || reviewDecision === 'abandon'}
            className="stage-action-btn px-5 py-2.5 bg-primary text-on-primary font-semibold rounded-lg transition-colors hover:bg-primary/90 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? '上传并解析中...' : '上传并解析'}
          </button>
        </div>

        <div className="border border-surface-container-high rounded-md p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-on-surface">招标文件（必选）</h4>
            <span className="text-xs px-2 py-0.5 rounded-md bg-error-container/30 text-error">必选</span>
          </div>
          <button
            onClick={() => document.getElementById('review-tender-upload')?.click()}
            className="stage-action-btn h-9 px-4 border border-dashed border-outline-variant hover:border-primary hover:bg-primary/5 transition-colors text-sm text-on-surface"
          >
            选择招标文件
          </button>
          <input
            id="review-tender-upload"
            type="file"
            className="hidden"
            accept={FILE_ACCEPT}
            multiple
            onChange={handleFilesPicked}
          />
          {renderPickedFiles()}
        </div>

        {uploadError && (
          <div className="rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
            {uploadError}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 text-xs text-outline">
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">已上传招标文件（当前项目）</p>
            <p>{sourceFiles.length ? sourceFiles.map((file) => file.name).join('，') : '暂无'}</p>
          </div>
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">解析时间</p>
            <p>{formatDateTime(parseData?.parsedAt)}</p>
          </div>
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">项目起始日期</p>
            <p>{parsedDates?.startDate || project?.startDate || '-'}</p>
          </div>
          <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
            <p className="font-medium text-on-surface mb-1">项目截止日期</p>
            <p>{parsedDates?.endDate || project?.endDate || project?.deadline || '-'}</p>
          </div>
        </div>
      </DataCard>

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
          <h3 className="text-sm font-semibold text-on-surface">结构化解析结果</h3>
          <span className={`text-xs px-2.5 py-1 rounded-md font-medium ${isParseCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {isParseCompleted ? `解析完成${structuredCategories.length ? ` · ${structuredCategories.length} 类` : ''}` : '待解析'}
          </span>
        </div>

        {!sourceFiles.length ? (
          <div className="p-6 text-sm text-on-surface-variant">当前项目尚未上传招标文件。</div>
        ) : !isParseCompleted ? (
          <div className="p-6 text-sm text-on-surface-variant">请点击上方“上传并解析”开始提取结构化要求。</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[1120px]">
              <thead>
                <tr className="bg-surface-container-low border-b border-surface-container-high">
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">类别</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">字段</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">提取值</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">来源文件</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">证据位置</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">证据文本</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-surface-container-high hover:bg-surface-container-low/60">
                    <td className="px-6 py-3 text-on-surface whitespace-nowrap">{row.category}</td>
                    <td className="px-6 py-3 text-on-surface-variant min-w-[160px]">{row.field}</td>
                    <td className="px-6 py-3 text-primary font-medium min-w-[220px]">{row.value}</td>
                    <td className="px-6 py-3 text-on-surface-variant min-w-[220px]">{row.fileName}</td>
                    <td className="px-6 py-3 text-on-surface-variant whitespace-nowrap">{row.evidenceLocation}</td>
                    <td className="px-6 py-3 text-on-surface-variant min-w-[300px]">{row.evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DataCard>

      <div className="w-full pt-1">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            onClick={() => handleDecision('abandon')}
            disabled={Boolean(deciding)}
            className="stage-action-btn h-[34px] px-5 bg-[#b6babd] text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deciding === 'abandon' ? '提交中...' : '不参与该项目'}
          </button>
          <button
            onClick={() => handleDecision('participate')}
            disabled={Boolean(deciding) || !isParseCompleted}
            className="stage-action-btn h-[34px] px-5 bg-[#0067B6] text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deciding === 'participate' ? '提交中...' : '参与该项目并进入工作区'}
          </button>
        </div>
        {reviewDecision === 'abandon' && (
          <div className="mt-2 text-sm text-error">当前项目已标记为不参与，流程在解析阶段结束。</div>
        )}
      </div>

      {showProjectInfoModal && projectToComplete && (
        <ProjectWizardModal
          mode="update"
          project={projectToComplete}
          forceReviewDecision="participate"
          onClose={() => {
            setShowProjectInfoModal(false)
            setProjectToComplete(null)
          }}
          onCreated={(updatedProject) => {
            setShowProjectInfoModal(false)
            setProjectToComplete(null)
            setProject(updatedProject)
            setProjects((prev) => prev.map((item) => (
              item.id === updatedProject.id ? { ...item, ...updatedProject } : item
            )))
            showToast?.('已确认参与投标，正在进入对应工作区。')
            navigate(projectRoute(updatedProject.id, '/parse', slugFromBidType(updatedProject.bidType)))
          }}
        />
      )}
    </div>
  )
}
