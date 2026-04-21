import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { parseAPI, projectsAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'

const MAX_FILE_SIZE = 1024 * 1024 * 1024
const MAX_BATCH_FILES = 5
const FILE_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

const getFileTypeLabel = (fileName = '') => {
  const ext = String(fileName).split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return 'PDF'
  if (ext === 'docx' || ext === 'doc') return 'DOCX'
  if (ext === 'xlsx' || ext === 'xls') return 'XLSX'
  return '文件'
}

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

const numberLabel = (value) => {
  const number = Number(value || 0)
  if (!Number.isFinite(number) || number <= 0) return '0'
  return number.toLocaleString('zh-CN')
}

const buildFallbackSourceFiles = (fileNames = []) =>
  fileNames.map((name, index) => ({
    id: `SRC-${index + 1}`,
    name,
    type: getFileTypeLabel(name),
    pageCount: '-',
    size: '-',
  }))

const formatDateTime = (value) => {
  if (!value) return '未解析'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未解析'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const validatePickedFiles = (picked = []) => {
  if (picked.length > MAX_BATCH_FILES) return `单次最多上传 ${MAX_BATCH_FILES} 个文件。`

  for (const file of picked) {
    if (Number(file.size || 0) > MAX_FILE_SIZE) {
      return `文件 ${file.name} 超过 1024MB 上限。`
    }
    const ext = extensionOf(file.name)
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      return `文件 ${file.name} 类型不在白名单中。`
    }
  }

  return ''
}

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

export default function ParseResult({ showToast }) {
  const navigate = useNavigate()
  const { id } = useParams()
  const [project, setProject] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [advancing, setAdvancing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [tenderFiles, setTenderFiles] = useState([])
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
      setError(e?.message || '解析结果加载失败')
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

  const sourceFiles = useMemo(() => {
    if (Array.isArray(data?.sourceFiles) && data.sourceFiles.length) {
      return data.sourceFiles
    }
    return buildFallbackSourceFiles(project?.files || [])
  }, [data?.sourceFiles, project?.files])

  const uploadedTemplateFiles = useMemo(
    () => normalizeUploadedTemplateFiles(project?.templateFiles),
    [project?.templateFiles],
  )

  const hasSourceFiles = sourceFiles.length > 0
  const parsedItems = useMemo(() => data?.items || [], [data?.items])
  const technicalItems = useMemo(() => {
    const filtered = parsedItems.filter((item) => item.type === '技术参数')
    if (filtered.length) return filtered
    return parsedItems.filter((item) => item.keyEntity || item.keyValue || item.title)
  }, [parsedItems])

  const technicalRows = useMemo(() => {
    if (!technicalItems.length) return []
    return technicalItems.map((item, index) => {
      const fileName = item.sourceFile || sourceFiles[0]?.name || '-'
      const fileMeta = sourceFiles.find((file) => file.name === fileName)
      const technicalParam = item.keyEntity && item.keyValue
        ? `${item.keyEntity}：${item.keyValue}`
        : item.keyValue || item.keyEntity || item.title || '-'
      return {
        id: item.id || `TP-${index + 1}`,
        projectName: project?.name || '-',
        fileName,
        fileType: fileMeta?.type || getFileTypeLabel(fileName),
        pageLabel: item.page ? `P.${item.page}` : (fileMeta?.pageCount || '-'),
        technicalParam,
      }
    })
  }, [technicalItems, sourceFiles, project?.name])

  const fallbackRows = useMemo(() => {
    if (!sourceFiles.length) return []
    return sourceFiles.map((file) => ({
      id: file.id || file.name,
      projectName: project?.name || '-',
      fileName: file.name,
      fileType: file.type || getFileTypeLabel(file.name),
      pageLabel: file.pageCount || '-',
      technicalParam: data?.status === 'completed' ? '未提取到技术参数' : '待触发解析',
    }))
  }, [sourceFiles, project?.name, data?.status])

  const rows = technicalRows.length ? technicalRows : fallbackRows
  const isParseCompleted = data?.status === 'completed'
  const parseSummary = data?.summary || {}
  const parseWarnings = Array.isArray(parseSummary.warnings) ? parseSummary.warnings : []
  const canUploadAndParse = uploading || (!tenderFiles.length && !(templateFiles.length && hasSourceFiles))

  const handleFilesPicked = (kind, event) => {
    const picked = Array.from(event.target.files || [])
    event.target.value = ''
    if (!picked.length) return

    const validationError = validatePickedFiles(picked)
    if (validationError) {
      setUploadError(validationError)
      return
    }

    setUploadError('')
    if (kind === 'tender') {
      setTenderFiles(picked)
      return
    }
    setTemplateFiles(picked)
  }

  const removePickedFile = (kind, index) => {
    if (kind === 'tender') {
      setTenderFiles((prev) => prev.filter((_, i) => i !== index))
      return
    }
    setTemplateFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleUploadAndParse = async () => {
    if (!tenderFiles.length && !hasSourceFiles) {
      const message = '请先上传招标文件（必选）后再解析。'
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }

    if (!tenderFiles.length && !templateFiles.length) {
      const message = '当前没有新增文件可上传；如需重新解析，请先补充模板文件或重新选择招标文件。'
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }

    setUploading(true)
    setUploadError('')
    try {
      const formData = new FormData()
      tenderFiles.forEach((file) => formData.append('tenderFiles', file))
      templateFiles.forEach((file) => formData.append('templateFiles', file))
      const response = await parseAPI.uploadAndRun(id, {
        formData,
      })
      setData(response)
      if (response?.project) setProject(response.project)
      setTenderFiles([])
      setTemplateFiles([])
      showToast?.(response?.message || '上传成功，解析已完成。')
    } catch (e) {
      const message = e?.message || '上传并解析失败'
      setUploadError(message)
      showToast?.(message, 'error')
    } finally {
      setUploading(false)
    }
  }

  const handleGoNextStage = async () => {
    if (!isParseCompleted) {
      showToast?.('请先完成 S1 解析后再进入 S2。', 'error')
      return
    }
    setAdvancing(true)
    try {
      await stagesAPI.update(id, 1, { status: 'completed' })
      showToast?.('已进入 S2 目录生成')
      navigate(`/projects/${id}/directory`)
    } catch (e) {
      showToast?.(e?.message || '进入下一阶段失败', 'error')
    } finally {
      setAdvancing(false)
    }
  }

  const renderPickedFiles = (list, kind) => {
    if (!list.length) return null
    return (
      <div className="flex flex-col gap-2">
        {list.map((file, index) => (
          <div key={`${file.name}-${index}`} className="flex items-center gap-3 p-3 bg-surface-container-low rounded-lg border border-surface-container-high">
            <span className="material-symbols-outlined text-primary">description</span>
            <span className="text-sm text-on-surface flex-1 truncate" title={file.name}>{file.name}</span>
            <span className="text-xs text-outline">{fileSizeLabel(file.size)}</span>
            <button
              onClick={() => removePickedFile(kind, index)}
              className="text-error hover:bg-error-container/30 rounded-full w-6 h-6 flex items-center justify-center"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        ))}
      </div>
    )
  }

  if (loading) return <PageLoading title="正在加载解析结果..." />

  if (error) {
    return (
      <PageError
        title="解析结果加载失败"
        description={error}
        onRetry={loadData}
      />
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-fade-in max-w-6xl mx-auto w-full">
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        className="mb-2"
        title="S1 解析结果"
        description="先上传招标文件（必选）与模板文件（可选），上传成功后自动解析并展示核心字段。"
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
              className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant font-medium rounded-lg hover:bg-surface-dim transition-colors text-sm flex items-center gap-2"
            >
              <span className="material-symbols-outlined text-lg">refresh</span>
              刷新
            </button>
            <button
              onClick={handleGoNextStage}
              disabled={!isParseCompleted || advancing}
              title={!isParseCompleted ? '完成解析后可进入 S2' : ''}
              className="px-5 py-2.5 bg-secondary text-on-secondary font-medium rounded-lg shadow-sm hover:bg-secondary/90 transition-colors text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="material-symbols-outlined text-lg">arrow_forward</span>
              {advancing ? '进入中...' : '进入下一阶段（S2）'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-6 flex flex-col gap-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">S1 文件上传</h3>
            <p className="text-xs text-outline mt-1">招标文件必选，模板文件可选；上传成功后自动触发后台解析。</p>
          </div>
          <button
            onClick={handleUploadAndParse}
            disabled={canUploadAndParse}
            className="px-5 py-2.5 bg-gradient-to-r from-primary to-primary-container text-on-primary font-semibold rounded-lg shadow-lg shadow-primary/20 hover:shadow-xl transition-all text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="material-symbols-outlined text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>
              {uploading ? 'hourglass_top' : 'upload_file'}
            </span>
            {uploading ? '上传并解析中...' : '上传并自动解析'}
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="border border-surface-container-high rounded-lg p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold text-on-surface">招标文件（必选）</h4>
              <span className="text-xs px-2 py-0.5 rounded-full bg-error-container/30 text-error">必选</span>
            </div>
            <button
              onClick={() => document.getElementById('s1-tender-upload')?.click()}
              className="h-11 px-4 rounded-md border border-dashed border-outline-variant hover:border-primary hover:bg-primary/5 transition-colors text-sm text-on-surface"
            >
              选择招标文件
            </button>
            <input
              id="s1-tender-upload"
              type="file"
              className="hidden"
              accept={FILE_ACCEPT}
              multiple
              onChange={(event) => handleFilesPicked('tender', event)}
            />
            {renderPickedFiles(tenderFiles, 'tender')}
          </div>

          <div className="border border-surface-container-high rounded-lg p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold text-on-surface">模板文件（可选）</h4>
              <span className="text-xs px-2 py-0.5 rounded-full bg-surface-container-high text-on-surface-variant">可选</span>
            </div>
            <button
              onClick={() => document.getElementById('s1-template-upload')?.click()}
              className="h-11 px-4 rounded-md border border-dashed border-outline-variant hover:border-primary hover:bg-primary/5 transition-colors text-sm text-on-surface"
            >
              选择模板文件
            </button>
            <input
              id="s1-template-upload"
              type="file"
              className="hidden"
              accept={FILE_ACCEPT}
              multiple
              onChange={(event) => handleFilesPicked('template', event)}
            />
            {renderPickedFiles(templateFiles, 'template')}
          </div>
        </div>

        {uploadError && (
          <div className="rounded-lg border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
            {uploadError}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs text-outline">
          <div className="rounded-md bg-surface-container-low p-3">
            <p className="font-medium text-on-surface mb-1">已上传招标文件（当前项目）</p>
            <p>{sourceFiles.length ? sourceFiles.map((file) => file.name).join('，') : '暂无'}</p>
          </div>
          <div className="rounded-md bg-surface-container-low p-3">
            <p className="font-medium text-on-surface mb-1">已上传模板文件（当前项目）</p>
            <p>{uploadedTemplateFiles.length ? uploadedTemplateFiles.map((file) => file.name).join('，') : '暂无'}</p>
          </div>
        </div>
      </DataCard>

      <DataCard className="!p-0 overflow-hidden min-h-[420px]">
        <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
          <h3 className="text-sm font-semibold text-on-surface">解析输出（精简）</h3>
          <div className="flex items-center gap-3">
            <span className="text-xs text-outline">解析时间：{formatDateTime(data?.parsedAt)}</span>
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${isParseCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
              {isParseCompleted ? '解析完成' : '待解析'}
            </span>
          </div>
        </div>

        {isParseCompleted && (
          <div className="px-6 py-5 border-b border-surface-container-high bg-surface-container-low/40 flex flex-col gap-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="rounded-lg bg-surface-container-low p-4 border border-surface-container-high">
                <div className="text-xs text-outline mb-1">解析文件数</div>
                <div className="text-lg font-semibold text-on-surface">{numberLabel(parseSummary.fileCount)}</div>
              </div>
              <div className="rounded-lg bg-surface-container-low p-4 border border-surface-container-high">
                <div className="text-xs text-outline mb-1">提取字段数</div>
                <div className="text-lg font-semibold text-on-surface">{numberLabel(parseSummary.extractedCount)}</div>
              </div>
              <div className="rounded-lg bg-surface-container-low p-4 border border-surface-container-high">
                <div className="text-xs text-outline mb-1">文本总长度</div>
                <div className="text-lg font-semibold text-on-surface">{numberLabel(parseSummary.textLength)}</div>
              </div>
            </div>

            {parseWarnings.length > 0 && (
              <div className="rounded-lg border border-error/20 bg-error-container/15 px-4 py-3">
                <div className="text-sm font-semibold text-on-surface mb-2">解析警告</div>
                <div className="flex flex-col gap-1">
                  {parseWarnings.map((warning, index) => (
                    <div key={`${warning}-${index}`} className="text-sm text-on-surface-variant">
                      {warning}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!hasSourceFiles ? (
          <div className="p-6">
            <div className="rounded-lg border border-error/20 bg-error-container/15 px-4 py-3 text-sm text-on-surface-variant">
              当前项目还未上传招标文件。请先在上方上传招标文件（必选），系统会自动触发解析。
            </div>
          </div>
        ) : !isParseCompleted ? (
          <div className="h-[260px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">hourglass_top</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">等待解析完成</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              已检测到 {sourceFiles.length} 份招标文件。请点击上方“上传并自动解析”开始处理。
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-container-low border-b border-surface-container-high">
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">招标文件项目名称</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">文件名称</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">文件类型</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">页数</th>
                  <th className="px-6 py-3 text-left font-semibold text-on-surface">技术参数</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-surface-container-high hover:bg-surface-container-low/60">
                    <td className="px-6 py-3 text-on-surface font-medium whitespace-nowrap">{row.projectName}</td>
                    <td className="px-6 py-3 text-on-surface min-w-[240px]">{row.fileName}</td>
                    <td className="px-6 py-3 text-on-surface-variant whitespace-nowrap">{row.fileType}</td>
                    <td className="px-6 py-3 text-on-surface-variant whitespace-nowrap">{row.pageLabel}</td>
                    <td className="px-6 py-3 text-primary font-medium min-w-[260px]">{row.technicalParam}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DataCard>
    </div>
  )
}
