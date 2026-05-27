import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { technicalParseAPI, technicalProjectsAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import DataCard from '../../../components/shared/DataCard'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../../../components/shared/OnlyOfficeWorkspace'
import PageHeader from '../../../components/shared/PageHeader'
import TechnicalProjectWizardModal from './TechnicalProjectWizardModal'
import Button from '../../../components/ui/Button'
import { normalizeBidType, projectRoute } from '../../../utils/workspace'

const MAX_FILE_SIZE = 500 * 1024 * 1024
const MAX_BATCH_FILES = 5
const FILE_ACCEPT = '.pdf,.doc,.docx,.md,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'md', 'xls', 'xlsx', 'zip',
  'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff',
])

const EMPTY_APPENDICES = []

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

const groupValue = (field) => {
  if (!field) return '-'
  const value = String(field.value || '').trim()
  return value || '未识别'
}

const presenceLabel = (status) => (status === 'present' ? '有明确要求' : '未识别')

const appendixKey = (appendix, index = 0) =>
  String(appendix?.id || appendix?.title || `appendix-${index}`)

const TECHNICAL_REVIEW_CONFIG = {
  bidType: '技术标',
  pageTitle: '技术标解析',
  pageDescription: '',
  createProjectNamePrefix: '技术标解析暂存',
  createButtonLabel: '解析新的招标文件',
  createSuccessMessage: '已准备好上传解析，请选择技术招标文件。',
  emptyTitle: '正在准备上传解析',
  emptyDescription: '系统正在准备技术招标文件上传入口。',
  currentProjectLabel: '当前解析',
  uploadSectionTitle: '技术招标文件上传与关键参数解析',
  uploadSectionDescription: '本模块负责上传技术招标文件并解析结构化要求，供技术标项目立项和后续目录生成使用。',
  uploadFileLabel: '技术招标文件（必选）',
  sourceFilesLabel: '已上传技术招标文件',
  resultTitle: '技术标结构化解析结果',
  pendingParseHint: '请点击上方“上传并解析”开始提取技术标结构化要求。',
  noSourceHint: '当前尚未上传技术招标文件。',
  appendixTitle: '附表空表产物',
  appendixSwitchHint: '空表 Word 已生成，可切换预览。',
  appendixEmptyHint: '未识别到附表要求。',
  scoringGroups: [
    ['technical', '技术评分标准'],
    ['price', '投标报价评分标准'],
    ['lcoe', '投标度电成本评分标准'],
    ['compliance', '符合性审查标准'],
  ],
  fallbackScoringTitle: '评分细则',
  fieldGroupSections: [
    ['projectBasics', '项目基础信息'],
    ['turbineCoreParameters', '风机核心参数'],
    ['performanceGuarantees', '性能保证指标'],
    ['environmentAdaptation', '环境适应性'],
  ],
  presenceTitle: '专题方案 / 供货范围 / 考核条款',
  buildPresenceRows: (presence = {}) => ([
    { label: '专题方案', item: presence.topicPlans },
    { label: '供货范围', item: presence.supplyScope },
    { label: '考核条款', item: presence.assessmentTerms },
  ]),
}

const assetReviewStatusLabel = (value = '') => {
  if (value === 'approved') return '已审核'
  if (value === 'pending_review') return '待审核'
  return '待审核'
}

const assetSyncStatusLabel = (value = '') => {
  if (value === 'synced') return '已同步素材库'
  if (value === 'failed') return '同步失败'
  if (value === 'pending') return '待同步'
  return '待确认参与后同步'
}

const appendixQualityLabel = (value = '') => {
  if (value === 'complete') return '提取完整'
  if (value === 'probably_incomplete') return '疑似不完整'
  if (value === 'title_only') return '仅标题'
  if (value === 'needs_review') return '需复核'
  return value || '未校验'
}

const appendixExtractionModeLabel = (value = '') => {
  if (value === 'source_docx_slice') return '原文切片'
  if (value === 'source_docx_rebuild_fallback') return '切片失败重建'
  if (value === 'markdown_slice') return '文本切片'
  if (value === 'text_slice') return '文本识别'
  return value || '未识别'
}

function FieldGroupTable({ title, fields = [], showEvidenceLocationColumn = true }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface">字段</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">解析内容</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">来源</th>
              {showEvidenceLocationColumn ? (
                <th className="px-4 py-2 text-center font-semibold text-on-surface">证据位置</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <tr key={field.key || field.label} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-on-surface whitespace-nowrap">{field.label || '-'}</td>
                <td className={`px-4 py-2 min-w-[220px] ${field.status === 'found' ? 'text-primary font-medium' : 'text-outline'}`}>
                  {groupValue(field)}
                </td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{field.sourceFile || '-'}</td>
                {showEvidenceLocationColumn ? (
                  <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{field.evidenceLocation || '-'}</td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ScoringCriteriaTable({
  title,
  rows = [],
  emptyText = '未识别到相关评分细则。',
  showEvidenceLocationColumn = true,
  showSourceColumns = true,
  showCount = true,
  showScoreColumn = true,
  showRequirementColumn = true,
  showProofRequirementColumn = true,
  scoringItemAlign = 'center',
  headerAction = null,
}) {
  const emptyColSpan = 2
    + (showScoreColumn ? 1 : 0)
    + (showRequirementColumn ? 1 : 0)
    + (showProofRequirementColumn ? 1 : 0)
    + (showSourceColumns ? 2 : 0)
    + (showEvidenceLocationColumn ? 1 : 0)

  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
        {headerAction || (showCount ? <span className="text-xs text-outline">{rows.length} 条</span> : null)}
      </div>
      <div className="overflow-x-auto">
        <table className={`business-scoring-table w-full table-fixed text-sm ${showSourceColumns ? 'min-w-[980px]' : 'min-w-[860px]'}`}>
          <colgroup>
            <col className="w-16" />
            <col className={showSourceColumns ? 'w-44' : 'w-52'} />
            {showScoreColumn ? <col className="w-32" /> : null}
            {showRequirementColumn ? <col className="w-96" /> : null}
            {showProofRequirementColumn ? <col className="w-72" /> : null}
            {showSourceColumns ? (
              <>
                <col className="w-56" />
                <col className="w-48" />
              </>
            ) : null}
            {showEvidenceLocationColumn ? <col className="w-44" /> : null}
          </colgroup>
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">序号</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">评分/审查项</th>
              {showScoreColumn ? <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">分值</th> : null}
              {showRequirementColumn ? <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">得分点/要求</th> : null}
              {showProofRequirementColumn ? <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">证明材料要求</th> : null}
              {showSourceColumns ? (
                <>
                  <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">来源</th>
                  <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">章节</th>
                </>
              ) : null}
              {showEvidenceLocationColumn ? (
                <th className="px-4 py-2 text-center font-semibold text-on-surface whitespace-nowrap">证据位置</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((item, index) => (
              <tr key={item.id || `${title}-${index}`} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-center text-on-surface-variant whitespace-nowrap">{item.order || index + 1}</td>
                <td className={`business-scoring-text-cell px-4 py-2 text-on-surface font-medium align-middle ${scoringItemAlign === 'left' ? 'text-left' : 'text-center'}`}>{item.scoringItem || '-'}</td>
                {showScoreColumn ? <td className="business-scoring-text-cell px-4 py-2 text-center text-primary align-top">{item.score || '-'}</td> : null}
                {showRequirementColumn ? <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.scorePoint || '-'}</td> : null}
                {showProofRequirementColumn ? <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.proofRequirement || '-'}</td> : null}
                {showSourceColumns ? (
                  <>
                    <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.sourceFile || '-'}</td>
                    <td className="business-scoring-text-cell px-4 py-2 text-on-surface-variant align-top">{item.section || '-'}</td>
                  </>
                ) : null}
                {showEvidenceLocationColumn ? (
                  <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.evidenceLocation || '-'}</td>
                ) : null}
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={emptyColSpan}>{emptyText}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PresenceTable({ title = '专题方案 / 供货范围 / 考核条款', rows = [], showEvidenceLocationColumn = true }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface">项目</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">识别结果</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">摘要</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">来源</th>
              {showEvidenceLocationColumn ? (
                <th className="px-4 py-2 text-center font-semibold text-on-surface">证据位置</th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const evidence = Array.isArray(row.item?.evidences) ? row.item.evidences[0] : null
              return (
                <tr key={row.label} className="border-b border-surface-container-high last:border-b-0">
                  <td className="px-4 py-2 text-on-surface font-medium whitespace-nowrap">{row.label}</td>
                  <td className="px-4 py-2 whitespace-nowrap">
                    <span className={`text-xs px-2 py-0.5 rounded-md font-semibold ${row.item?.status === 'present' ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                      {presenceLabel(row.item?.status)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-on-surface-variant min-w-[340px]">{row.item?.summary || '未识别到明确要求。'}</td>
                  <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{evidence?.sourceFile || '-'}</td>
                  {showEvidenceLocationColumn ? (
                    <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{evidence?.evidenceLocation || '-'}</td>
                  ) : null}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function TechnicalTenderReview({ showToast }) {
  const reviewConfig = TECHNICAL_REVIEW_CONFIG
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const queryProjectId = String(searchParams.get('projectId') || '').trim()
  const [, setProjects] = useState([])
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [project, setProject] = useState(null)
  const [parseData, setParseData] = useState(null)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [error, setError] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [tenderFiles, setTenderFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [parseProgress, setParseProgress] = useState(null)
  const [deciding, setDeciding] = useState('')
  const [creatingReview, setCreatingReview] = useState(false)
  const [showProjectInfoModal, setShowProjectInfoModal] = useState(false)
  const [projectToComplete, setProjectToComplete] = useState(null)
  const [selectedAppendixId, setSelectedAppendixId] = useState('')
  const [appendixPreview, setAppendixPreview] = useState(null)
  const [appendixPreviewLoading, setAppendixPreviewLoading] = useState(false)
  const [appendixPreviewError, setAppendixPreviewError] = useState('')
  const [savingAppendixId, setSavingAppendixId] = useState('')
  const [savingAllAppendices, setSavingAllAppendices] = useState(false)

  const refreshParseResult = useCallback(async () => {
    if (!selectedProjectId) return null
    const data = await technicalParseAPI.results(selectedProjectId)
    setParseData(data)
    return data
  }, [selectedProjectId])

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true)
    setError('')
    try {
      const data = await technicalProjectsAPI.list({ page: 1, pageSize: 200, bidType: reviewConfig.bidType })
      const items = (Array.isArray(data?.items) ? data.items : []).filter(
        (item) => normalizeBidType(item?.bidType) === reviewConfig.bidType,
      )
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
      setError(e?.message || '解析列表加载失败')
    } finally {
      setLoadingProjects(false)
    }
  }, [queryProjectId, reviewConfig.bidType])

  const loadCurrentProject = useCallback(async () => {
    if (!selectedProjectId) {
      setProject(null)
      setParseData(null)
      return
    }
    setLoadingDetail(true)
    setError('')
    try {
      const [projectData, parseResult, progressResult] = await Promise.all([
        technicalProjectsAPI.get(selectedProjectId),
        technicalParseAPI.results(selectedProjectId),
        technicalParseAPI.progress(selectedProjectId).catch(() => null),
      ])
      setProject(projectData)
      setParseData(parseResult)
      setParseProgress(progressResult)
    } catch (e) {
      setError(e?.message || '解析详情加载失败')
    } finally {
      setLoadingDetail(false)
    }
  }, [selectedProjectId])

  const createReviewProject = useCallback(async ({ toastMessage, silent = false } = {}) => {
    setCreatingReview(true)
    try {
      const now = new Date()
      const pad = (num) => String(num).padStart(2, '0')
      const created = await technicalProjectsAPI.create({
        name: `${reviewConfig.createProjectNamePrefix}-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`,
        customerName: '',
        owner: '',
        manager: '',
        bidType: reviewConfig.bidType,
        deadline: '',
        reviewDecision: 'pending',
      })
      await loadProjects()
      setSelectedProjectId(created?.id || '')
      if (!silent) {
        if (toastMessage) {
          showToast?.(toastMessage)
        } else {
          showToast?.(reviewConfig.createSuccessMessage)
        }
      }
      return created
    } catch (e) {
      const message = e?.message || '准备上传解析失败'
      if (silent) setError(message)
      else showToast?.(message, 'error')
      return null
    } finally {
      setCreatingReview(false)
    }
  }, [loadProjects, reviewConfig.bidType, reviewConfig.createProjectNamePrefix, reviewConfig.createSuccessMessage, showToast])

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

  useEffect(() => {
    if (!uploading || !selectedProjectId) return undefined
    let stopped = false
    const loadProgress = async () => {
      try {
        const progress = await technicalParseAPI.progress(selectedProjectId)
        if (!stopped) setParseProgress(progress)
      } catch {
        // Keep the previous progress snapshot while the upload request owns the main path.
      }
    }
    loadProgress()
    const timer = setInterval(loadProgress, 1000)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [selectedProjectId, uploading])

  const sourceFiles = Array.isArray(parseData?.sourceFiles) && parseData.sourceFiles.length
    ? parseData.sourceFiles
    : buildFallbackSourceFiles(project?.files || [])
  const parsedItems = useMemo(() => parseData?.items || [], [parseData?.items])
  const fieldGroups = parseData?.structured?.fieldGroups || {}
  const structuredScoring = useMemo(
    () => parseData?.structured?.scoringCriteria || {},
    [parseData?.structured?.scoringCriteria],
  )
  const scoringGroups = useMemo(() => {
    const fallbackRows = Array.isArray(fieldGroups.scoringCriteria) ? fieldGroups.scoringCriteria : []
    const groups = reviewConfig.scoringGroups.map(([key, title]) => ({
      key,
      title,
      rows: Array.isArray(structuredScoring[key]) ? structuredScoring[key] : [],
    }))
    if (groups.some((group) => group.rows.length)) return groups
    return [{ key: 'flat', title: reviewConfig.fallbackScoringTitle, rows: fallbackRows }]
  }, [fieldGroups.scoringCriteria, reviewConfig.fallbackScoringTitle, reviewConfig.scoringGroups, structuredScoring])
  const requirementPresence = useMemo(
    () => parseData?.structured?.requirementPresence || {},
    [parseData?.structured?.requirementPresence],
  )
  const presenceRows = useMemo(
    () => reviewConfig.buildPresenceRows(requirementPresence),
    [requirementPresence, reviewConfig],
  )
  const appendices = Array.isArray(parseData?.structured?.appendices)
    ? parseData.structured.appendices
    : EMPTY_APPENDICES
  const activeAppendixId = appendices.length && appendices.some((appendix, index) => appendixKey(appendix, index) === selectedAppendixId)
    ? selectedAppendixId
    : appendices.length
      ? appendixKey(appendices[0], 0)
      : ''
  const selectedAppendix = useMemo(
    () => appendices.find((appendix, index) => appendixKey(appendix, index) === activeAppendixId) || appendices[0] || null,
    [activeAppendixId, appendices],
  )
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
  const showTechnicalCompactUpload = !isParseCompleted

  useEffect(() => {
    const appendixId = selectedAppendix?.id
    if (!selectedProjectId || !appendixId) {
      return undefined
    }

    let cancelled = false
    const timer = setTimeout(() => {
      setAppendixPreviewLoading(true)
      setAppendixPreview(null)
      setAppendixPreviewError('')
      technicalParseAPI.appendixPreview(selectedProjectId, appendixId)
        .then((data) => {
          if (!cancelled) setAppendixPreview(data)
        })
        .catch((e) => {
          if (!cancelled) {
            setAppendixPreview(null)
            setAppendixPreviewError(e?.message || '附表 Word 预览加载失败')
          }
        })
        .finally(() => {
          if (!cancelled) setAppendixPreviewLoading(false)
        })
    }, 0)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [selectedProjectId, selectedAppendix?.docxPath, selectedAppendix?.id])

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
    if (!tenderFiles.length) {
      const message = '请先上传技术招标文件后再解析。'
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }
    let targetProjectId = selectedProjectId
    if (!targetProjectId) {
      const created = await createReviewProject({ silent: true })
      targetProjectId = created?.id || ''
      if (!targetProjectId) {
        const message = '上传解析入口准备失败，请刷新后重试。'
        setUploadError(message)
        showToast?.(message, 'error')
        return
      }
    }
    if (reviewDecision === 'abandon') {
      showToast?.('本次解析已标记为不参与，如需继续请先切换为“参与投标”。', 'error')
      return
    }

    setUploading(true)
    setUploadError('')
    setParseProgress({
      status: 'running',
      percentage: 3,
      summary: '正在上传技术招标文件。',
      events: [{ step: 'upload', level: 'info', message: '正在上传技术招标文件。' }],
      opencodeOutput: { parts: [] },
    })
    try {
      const formData = new FormData()
      tenderFiles.forEach((file) => formData.append('tenderFiles', file))
      const response = await technicalParseAPI.uploadAndRun(targetProjectId, { formData })
      setParseData(response)
      const latestProgress = await technicalParseAPI.progress(targetProjectId).catch(() => null)
      if (latestProgress) setParseProgress(latestProgress)
      const latestProject = await technicalProjectsAPI.get(targetProjectId)
      setSelectedProjectId(targetProjectId)
      setProject(latestProject)
      setProjects((prev) => {
        const next = prev.map((item) => (item.id === latestProject.id ? { ...item, ...latestProject } : item))
        return next.some((item) => item.id === latestProject.id) ? next : [latestProject, ...prev]
      })
      setTenderFiles([])
      showToast?.(response?.message || `${reviewConfig.bidType}招标文件解析完成。`)
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
      await technicalProjectsAPI.delete(selectedProjectId)
      setProjects((prev) => prev.filter((item) => item.id !== selectedProjectId))
      setSelectedProjectId('')
      setProject(null)
      setParseData(null)
      setParseProgress(null)
      setTenderFiles([])
      setUploadError('')
      showToast?.(`本次${reviewConfig.bidType}解析已设为不参与并移出项目总览，可继续上传新的招标文件。`)
    } catch (e) {
      showToast?.(e?.message || '处理不参与流程失败', 'error')
    } finally {
      setDeciding('')
    }
  }

  const handleCreateReviewProject = async () => {
    setCreatingReview(true)
    try {
      if (selectedProjectId && String(project?.reviewDecision || 'pending') !== 'participate') {
        await technicalProjectsAPI.delete(selectedProjectId)
        setProjects((prev) => prev.filter((item) => item.id !== selectedProjectId))
      }
      setSelectedProjectId('')
      setProject(null)
      setParseData(null)
      setParseProgress(null)
      setTenderFiles([])
      setUploadError('')
    } catch (e) {
      showToast?.(e?.message || '准备新的解析失败', 'error')
    } finally {
      setCreatingReview(false)
    }
  }

  const handleApproveAppendixAsset = async (appendixId) => {
    if (!selectedProjectId || !appendixId) return
    setSavingAppendixId(appendixId)
    try {
      const result = await technicalParseAPI.approveAppendixAsset(selectedProjectId, appendixId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '附表 Word 已审核通过。')
    } catch (e) {
      showToast?.(e?.message || '附表 Word 审核失败', 'error')
    } finally {
      setSavingAppendixId('')
    }
  }

  const handleApproveAllAppendixAssets = async () => {
    if (!selectedProjectId || !appendices.length) return
    setSavingAllAppendices(true)
    try {
      const result = await technicalParseAPI.approveAllAppendixAssets(selectedProjectId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '附表 Word 已批量审核通过。')
    } catch (e) {
      showToast?.(e?.message || '附表 Word 批量审核失败', 'error')
    } finally {
      setSavingAllAppendices(false)
    }
  }

  const renderPickedFiles = () => {
    if (!tenderFiles.length) return null
    return (
      <div className="flex flex-col gap-2">
        {tenderFiles.map((file, index) => (
          <div key={`${file.name}-${index}`} className="flex items-center gap-3 rounded-lg border border-outline-variant/55 bg-white px-3 py-2">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-primary-fixed text-primary">
              <span className="material-symbols-outlined text-[18px]">description</span>
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-on-surface" title={file.name}>{file.name}</span>
            <span className="shrink-0 rounded-full bg-surface-container-low px-2 py-0.5 text-xs text-outline">{fileSizeLabel(file.size)}</span>
            <button
              type="button"
              onClick={() => removePickedFile(index)}
              className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-error hover:bg-error-container/30"
              aria-label={`移除文件 ${file.name}`}
            >
              <span className="material-symbols-outlined text-[17px]">close</span>
            </button>
          </div>
        ))}
      </div>
    )
  }

  const renderTechnicalCompactProgress = () => {
    if (!uploading && (!parseProgress || parseProgress.status === 'idle')) return null
    const status = uploading ? 'running' : (parseProgress?.status || 'idle')
    const percentage = Math.max(0, Math.min(100, Number(parseProgress?.percentage || (uploading ? 3 : 0))))
    const statusText = status === 'completed' ? '解析完成' : status === 'failed' ? '解析失败' : status === 'running' ? '解析中' : '等待上传'
    const summary = parseProgress?.summary === '尚未触发招标文件解析。'
      ? '正在上传并解析技术招标文件，请稍候。'
      : (parseProgress?.summary || '正在上传并解析技术招标文件，请稍候。')

    return (
      <div className="mt-4 rounded-md border border-surface-container-high bg-surface-container-low px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-on-surface">解析进度</p>
            <p className="mt-1 text-xs text-outline">{summary}</p>
          </div>
          <span className={[
            'shrink-0 rounded-md px-2.5 py-1 text-xs font-semibold',
            status === 'failed'
              ? 'bg-error-container text-error'
              : status === 'running'
                ? 'bg-primary/10 text-primary'
                : 'bg-surface-container-high text-on-surface-variant',
          ].join(' ')}
          >
            {statusText} · {percentage}%
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-container-high">
          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percentage}%` }} />
        </div>
      </div>
    )
  }

  if (loadingProjects) return <PageLoading title="正在加载解析模块..." />
  if (error) return <PageError title="解析模块加载失败" description={error} onRetry={loadProjects} />
  if (loadingDetail) return <PageLoading title="正在加载解析详情..." />

  if (showTechnicalCompactUpload) {
    return (
      <div className="review-page business-ui-shell flex flex-col gap-6 animate-fade-in max-w-none">
        <DataCard className="mt-6 w-full max-w-[760px] !p-0 overflow-hidden self-center">
          <div className="business-section-head flex items-center px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-xl font-headline font-bold text-[#0067B6]">技术标解析</h3>
              <span className="text-xs text-outline">上传招标文件后自动解析</span>
            </div>
          </div>

          <div className="px-5 py-5">
            <label
              htmlFor="technical-review-tender-upload"
              className={[
                'business-dropzone flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-md border border-dashed px-6 py-8 text-center transition-colors',
                uploading || reviewDecision === 'abandon' ? 'pointer-events-none opacity-60' : 'hover:border-primary hover:bg-primary/5',
              ].join(' ')}
            >
              <span className="material-symbols-outlined text-2xl text-primary">upload_file</span>
              <span className="mt-2 text-sm font-semibold text-on-surface">选择技术招标文件</span>
              <span className="mt-1 text-xs text-outline">支持 Word、PDF、Excel 等招标附件</span>
            </label>
            <input
              id="technical-review-tender-upload"
              type="file"
              className="hidden"
              accept={FILE_ACCEPT}
              multiple
              disabled={uploading || reviewDecision === 'abandon'}
              onChange={handleFilesPicked}
            />
            <div className="mt-3">
              {renderPickedFiles()}
            </div>
            <div className="mt-4 flex justify-center">
              <Button
                type="button"
                onClick={handleUploadAndParse}
                disabled={uploading || creatingReview || reviewDecision === 'abandon'}
                size="stage"
                variant="primary"
              >
                {creatingReview ? '准备中...' : uploading ? '上传解析中...' : '上传并解析'}
              </Button>
            </div>
            {uploadError && (
              <div className="mt-3 rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
                {uploadError}
              </div>
            )}
            {uploading && (
              <div className="mt-3 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary">
                正在上传并解析技术招标文件，请稍候。
              </div>
            )}
            {renderTechnicalCompactProgress()}
          </div>
        </DataCard>
      </div>
    )
  }

  return (
    <div className="review-page flex flex-col gap-6 animate-fade-in max-w-none">
      <PageHeader
        title={reviewConfig.pageTitle}
        description={isParseCompleted ? '' : reviewConfig.pageDescription}
        actionsClassName="stage-header-actions"
        actions={(
          <Button
            onClick={handleCreateReviewProject}
            disabled={creatingReview}
            size="lg"
            variant="primary"
          >
            {creatingReview ? '准备中...' : reviewConfig.createButtonLabel}
          </Button>
        )}
      />

      <DataCard className={isParseCompleted ? '!border-0 !bg-transparent !p-0 !shadow-none overflow-visible' : '!p-0 overflow-hidden'}>
        {!sourceFiles.length ? (
          <div className="p-6 text-sm text-on-surface-variant">{reviewConfig.noSourceHint}</div>
        ) : !isParseCompleted ? (
          <div className="p-6 text-sm text-on-surface-variant">{reviewConfig.pendingParseHint}</div>
        ) : (
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-4">
              {scoringGroups.map((group) => (
                <ScoringCriteriaTable
                  key={group.key}
                  title={group.title}
                  rows={group.rows}
                  showEvidenceLocationColumn={reviewConfig.showEvidenceLocationColumn !== false && group.key !== 'compliance'}
                  showSourceColumns={group.key !== 'compliance'}
                  showCount={!['price', 'compliance'].includes(group.key)}
                  showScoreColumn={group.key !== 'compliance'}
                  showRequirementColumn={group.key !== 'compliance'}
                  showProofRequirementColumn={!['price', 'compliance'].includes(group.key)}
                  scoringItemAlign={group.key === 'compliance' ? 'left' : 'center'}
                />
              ))}
            </div>

            {reviewConfig.fieldGroupSections.length ? (
              <div className="grid grid-cols-1 2xl:grid-cols-2 gap-4">
                {reviewConfig.fieldGroupSections.map(([key, title]) => (
                  <FieldGroupTable
                    key={key}
                    title={title}
                    fields={fieldGroups[key] || []}
                    showEvidenceLocationColumn={reviewConfig.showEvidenceLocationColumn !== false}
                  />
                ))}
              </div>
            ) : null}

            {reviewConfig.showPresence !== false && (
              <PresenceTable
                title={reviewConfig.presenceTitle}
                rows={presenceRows}
                showEvidenceLocationColumn={reviewConfig.showEvidenceLocationColumn !== false}
              />
            )}

            <section className="border border-surface-container-high rounded-md overflow-hidden">
              <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px] text-primary">article</span>
                  <h4 className="text-sm font-semibold text-on-surface">附表 Word</h4>
                </div>
                <div className="flex items-center gap-2">
                  {reviewConfig.showApproveAppendices && appendices.length ? (
                    <>
                      <button
                        type="button"
                        onClick={() => handleApproveAppendixAsset(selectedAppendix?.id)}
                        disabled={savingAllAppendices || Boolean(savingAppendixId) || !selectedAppendix?.id}
                        className="rounded-md bg-surface-container-high px-2.5 py-1 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {savingAppendixId ? '审核中...' : '审核当前'}
                      </button>
                      <button
                        type="button"
                        onClick={handleApproveAllAppendixAssets}
                        disabled={savingAllAppendices || Boolean(savingAppendixId)}
                        className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-on-primary hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {savingAllAppendices ? '审核中...' : '审核全部'}
                      </button>
                    </>
                  ) : null}
                  <span className="text-xs text-outline">{appendices.length} 个</span>
                </div>
              </div>
              {appendices.length ? (
                <OnlyOfficeWorkspace
                  className="m-4 appendix-preview-workspace"
                  heightClass="appendix-preview-shell"
                  gridClassName="grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]"
                  sidebarClassName="appendix-preview-aside"
                  documentAreaClassName="appendix-preview-document"
                  documentTitle={selectedAppendix?.title || '附表预览'}
                  documentSubtitle={selectedAppendix?.workspacePath || selectedAppendix?.sourceFile || ''}
                  documentMeta={(
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="whitespace-nowrap rounded-md bg-surface-container-high px-2.5 py-1 text-xs font-semibold text-on-surface-variant">
                        {selectedAppendix?.rowCount ?? 0} 行
                      </span>
                      {selectedAppendix?.templateTypeLabel ? (
                        <span className="whitespace-nowrap rounded-md bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
                          {selectedAppendix.templateTypeLabel}
                        </span>
                      ) : null}
                      {selectedAppendix?.extractionQuality ? (
                        <span
                          className={[
                            'whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-semibold',
                            selectedAppendix.extractionQuality === 'complete'
                              ? 'bg-secondary-container text-on-secondary-container'
                              : 'bg-error-container text-error',
                          ].join(' ')}
                        >
                          {appendixQualityLabel(selectedAppendix.extractionQuality)}
                        </span>
                      ) : null}
                    </div>
                  )}
                  sidebar={(
                    <div className="appendix-preview-sidebar flex h-full min-h-0 flex-col">
                      <div className="border-b border-surface-container-high px-4 py-3">
                        <p className="text-sm font-semibold text-on-surface">附表条目</p>
                      </div>
                      <div className="appendix-preview-list min-h-0 flex-1 overflow-y-auto p-2">
                        {appendices.map((appendix, index) => {
                          const key = appendixKey(appendix, index)
                          const active = key === activeAppendixId
                          return (
                            <button
                              key={key}
                              type="button"
                              aria-pressed={active}
                              onClick={() => setSelectedAppendixId(key)}
                              className={[
                                'mb-2 flex w-full flex-col items-start gap-1 rounded-md border px-3 py-2 text-left transition-colors',
                                active
                                  ? 'border-primary bg-primary/5 text-primary'
                                  : 'border-surface-container-high bg-white text-on-surface hover:border-outline-variant hover:bg-surface-container-low',
                              ].join(' ')}
                            >
                              <span className="line-clamp-2 text-sm font-semibold">{appendix.title || '-'}</span>
                              <span className="text-xs text-on-surface-variant">{appendix.sourceFile || '-'}</span>
                              {appendix.templateTypeLabel || appendix.extractionQuality || appendix.extractionMode ? (
                                <span className="text-xs text-on-surface-variant">
                                  {[appendix.templateTypeLabel, appendixExtractionModeLabel(appendix.extractionMode), appendixQualityLabel(appendix.extractionQuality)]
                                    .filter(Boolean)
                                    .join(' · ')}
                                </span>
                              ) : null}
                              <span className="text-xs text-outline">{appendix.workspacePath || appendix.docxPath || '-'}</span>
                              {Array.isArray(appendix.qualityIssues) && appendix.qualityIssues.length ? (
                                <span className="line-clamp-2 text-xs text-error">
                                  {appendix.qualityIssues.join('；')}
                                </span>
                              ) : null}
                              {reviewConfig.showApproveAppendices ? (
                                <span className="text-xs text-outline">
                                  {assetReviewStatusLabel(appendix.assetReviewStatus)}
                                  {' · '}
                                  {assetSyncStatusLabel(appendix.assetSyncStatus)}
                                </span>
                              ) : null}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                >
                  {appendixPreviewLoading ? (
                    <div className="flex h-full min-h-0 items-center justify-center text-sm text-on-surface-variant">
                      正在加载附表预览...
                    </div>
                  ) : appendixPreview?.onlyoffice?.fileUrl && appendixPreview?.onlyoffice?.callbackUrl && !appendixPreviewError ? (
                    <OnlyOfficeEmbed
                      session={appendixPreview.onlyoffice}
                      mode="view"
                      className="h-full min-h-0 w-full rounded-md border border-surface-container-high bg-white"
                      onError={(message) => setAppendixPreviewError(message || 'OnlyOffice 附表预览加载失败')}
                    />
                  ) : (
                    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 text-center text-sm text-on-surface-variant">
                      <p>{appendixPreviewError || '当前附表暂时无法载入 OnlyOffice 预览。'}</p>
                      {appendixPreview?.onlyoffice?.browserFileUrl ? (
                        <a
                          href={appendixPreview.onlyoffice.browserFileUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-on-primary"
                        >
                          打开 Word 文件
                        </a>
                      ) : null}
                    </div>
                  )}
                </OnlyOfficeWorkspace>
              ) : (
                <div className="px-4 py-3 text-sm text-outline">{reviewConfig.appendixEmptyHint}</div>
              )}
            </section>

            {reviewConfig.showEvidenceDetails !== false && (
              <details className="rounded-md border border-surface-container-high bg-white">
                <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-on-surface">
                  <span className="mr-2 align-middle material-symbols-outlined text-[18px] text-primary">travel_explore</span>
                  证据明细
                </summary>
                <div className="overflow-x-auto border-t border-surface-container-high">
                  <table className="w-full text-sm min-w-[1120px]">
                    <thead>
                      <tr className="bg-surface-container-low border-b border-surface-container-high">
                        <th className="px-4 py-2 text-center font-semibold text-on-surface">类别</th>
                        <th className="px-4 py-2 text-center font-semibold text-on-surface">字段</th>
                        <th className="px-4 py-2 text-center font-semibold text-on-surface">提取值</th>
                        <th className="px-4 py-2 text-center font-semibold text-on-surface">来源文件</th>
                        {reviewConfig.showEvidenceLocationColumn !== false ? (
                          <th className="px-4 py-2 text-center font-semibold text-on-surface">证据位置</th>
                        ) : null}
                        <th className="px-4 py-2 text-center font-semibold text-on-surface">证据文本</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.id} className="border-b border-surface-container-high hover:bg-surface-container-low/60">
                          <td className="px-4 py-2 text-on-surface whitespace-nowrap">{row.category}</td>
                          <td className="px-4 py-2 text-on-surface-variant min-w-[160px]">{row.field}</td>
                          <td className="px-4 py-2 text-primary font-medium min-w-[220px]">{row.value}</td>
                          <td className="px-4 py-2 text-on-surface-variant min-w-[220px]">{row.fileName}</td>
                          {reviewConfig.showEvidenceLocationColumn !== false ? (
                            <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{row.evidenceLocation}</td>
                          ) : null}
                          <td className="px-4 py-2 text-on-surface-variant min-w-[300px]">{row.evidence}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>
        )}
      </DataCard>

      <div className="w-full pt-1">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Button
            onClick={() => handleDecision('abandon')}
            disabled={Boolean(deciding)}
            size="stage"
            variant="quiet"
          >
            {deciding === 'abandon' ? '提交中...' : '不参与该项目'}
          </Button>
          <Button
            onClick={() => handleDecision('participate')}
            disabled={Boolean(deciding) || !isParseCompleted}
            size="stage"
            variant="primary"
          >
            {deciding === 'participate' ? '提交中...' : '参与该项目并进入工作区'}
          </Button>
        </div>
        {reviewDecision === 'abandon' && (
          <div className="mt-2 text-sm text-error">本次解析已标记为不参与，流程在解析阶段结束。</div>
        )}
      </div>

      {showProjectInfoModal && projectToComplete && (
        <TechnicalProjectWizardModal
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
            navigate(projectRoute(updatedProject.id, '/template-directory', 'tech'))
          }}
        />
      )}
    </div>
  )
}
