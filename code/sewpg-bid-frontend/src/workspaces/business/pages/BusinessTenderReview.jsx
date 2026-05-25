import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { businessMaterialsAPI, businessParseAPI, businessProjectsAPI } from '../../../api'
import { PageError, PageLoading } from '../../../components/states/PageState'
import DataCard from '../../../components/shared/DataCard'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../../../components/shared/OnlyOfficeWorkspace'
import PageHeader from '../../../components/shared/PageHeader'
import ProjectWizardModal from '../../../components/modals/ProjectWizardModal'
import Button from '../../../components/ui/Button'
import { normalizeBidType, projectRoute } from '../../../utils/workspace'

const MAX_FILE_SIZE = 500 * 1024 * 1024
const MAX_BATCH_FILES = 5
const FILE_ACCEPT = '.pdf,.doc,.docx,.md,.xls,.xlsx,.zip,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const BUSINESS_BID_TYPE = '商务标'
const BUSINESS_FILE_LABEL = '商务'
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

const groupValue = (field) => {
  if (!field) return '-'
  const value = String(field.value || '').trim()
  return value || '未识别'
}

const presenceLabel = (status) => (status === 'present' ? '有明确要求' : '未识别')

const appendixKey = (appendix, index = 0) =>
  String(appendix?.id || appendix?.title || `appendix-${index}`)

const BUSINESS_REVIEW_CONFIG = {
  bidType: BUSINESS_BID_TYPE,
  pageTitle: '商务标解析',
  pageDescription: '',
  createProjectNamePrefix: '商务标待解析项目',
  createButtonLabel: '新建项目',
  createSuccessMessage: '已新建商务标解析项目，请上传商务招标文件并解析。',
  emptyTitle: '暂无待解析商务标项目',
  emptyDescription: '你可以在这里先新建商务标解析项目，再上传商务招标文件进行判断。',
  currentProjectLabel: '当前商务标解析项目',
  uploadSectionTitle: '商务招标文件上传与关键参数解析',
  uploadSectionDescription: '本模块负责上传商务招标文件并解析商务响应、资格支撑、附表与承诺函要求，供商务标项目后续使用。',
  uploadFileLabel: '商务招标文件（必选）',
  sourceFilesLabel: '已上传商务招标文件（当前项目）',
  resultTitle: '商务标解析结果',
  pendingParseHint: '请点击上方“上传并解析”开始提取商务标结构化要求。',
  noSourceHint: '当前项目尚未上传商务招标文件。',
  appendixTitle: '商务附件模板产物',
  appendixSwitchHint: '已提取招标文件中的商务附件模板，可切换预览并审核；确认参与投标后自动同步至项目素材库。',
  appendixEmptyHint: '未识别到可保存的商务附件模板。',
  scoringGroups: [
    ['business', '商务评分标准'],
    ['price', '投标报价评分标准'],
    ['compliance', '符合性审查标准'],
  ],
  fallbackScoringTitle: '商务评分细则',
  fieldGroupSections: [],
  showPresence: false,
  showCommitmentClues: false,
  showEvidenceDetails: false,
  showEvidenceLocationColumn: false,
  showApproveBusinessScoring: true,
  showApproveAppendices: true,
  showApproveCommitmentLetters: true,
  buildPresenceRows: () => [],
}

const commitmentTypeLabel = (value = '') => {
  if (value === 'disqualification') return '否决项承诺函'
  if (value === 'general_commitment') return '一般承诺函/承诺书'
  return value || '-'
}

const commitmentStatusLabel = (value = '') => {
  if (value === 'generated') return '已生成'
  if (value === 'pending_review') return '待复核'
  if (value === 'needs_review') return '待确认'
  return value || '-'
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

function CommitmentClueTable({ clues = [], showEvidenceLocationColumn = true }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
        <h4 className="text-sm font-semibold text-on-surface">待确认承诺线索</h4>
        <span className="text-xs text-outline">{clues.length} 个</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[1040px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-center font-semibold text-on-surface">线索</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">状态</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">触发词</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">建议动作</th>
              <th className="px-4 py-2 text-center font-semibold text-on-surface">来源</th>
              {showEvidenceLocationColumn ? (
                <th className="px-4 py-2 text-center font-semibold text-on-surface">证据位置</th>
              ) : null}
              <th className="px-4 py-2 text-center font-semibold text-on-surface">风险标记</th>
            </tr>
          </thead>
          <tbody>
            {clues.length ? clues.map((item) => (
              <tr key={item.id || item.title} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-on-surface font-medium min-w-[220px]">{item.title || '-'}</td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <span className="text-xs px-2 py-0.5 rounded-md font-semibold bg-surface-container-high text-on-surface-variant">
                    {commitmentStatusLabel(item.status)}
                  </span>
                </td>
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.triggerText || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[260px]">{item.recommendedAction || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{item.sourceFile || '-'}</td>
                {showEvidenceLocationColumn ? (
                  <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.evidenceLocation || '-'}</td>
                ) : null}
                <td className="px-4 py-2 text-on-surface-variant min-w-[220px]">{Array.isArray(item.riskFlags) && item.riskFlags.length ? item.riskFlags.join('，') : '-'}</td>
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={showEvidenceLocationColumn ? 7 : 6}>未识别到待确认承诺线索。</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const commitmentLetterKey = (letter, index = 0) =>
  String(letter?.id || letter?.title || `commitment-letter-${index}`)

export default function BusinessTenderReview({ showToast }) {
  const reviewConfig = BUSINESS_REVIEW_CONFIG
  const parseClient = businessParseAPI
  const projectsClient = businessProjectsAPI
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
  const [parseProgress, setParseProgress] = useState(null)
  const [deciding, setDeciding] = useState('')
  const [creatingReview, setCreatingReview] = useState(false)
  const [showProjectInfoModal, setShowProjectInfoModal] = useState(false)
  const [projectToComplete, setProjectToComplete] = useState(null)
  const [selectedAppendixId, setSelectedAppendixId] = useState('')
  const [appendixPreview, setAppendixPreview] = useState(null)
  const [appendixPreviewLoading, setAppendixPreviewLoading] = useState(false)
  const [appendixPreviewError, setAppendixPreviewError] = useState('')
  const [selectedCommitmentLetterId, setSelectedCommitmentLetterId] = useState('')
  const [commitmentLetterPreview, setCommitmentLetterPreview] = useState(null)
  const [commitmentLetterPreviewLoading, setCommitmentLetterPreviewLoading] = useState(false)
  const [commitmentLetterPreviewError, setCommitmentLetterPreviewError] = useState('')
  const [selectedBusinessDocumentKind, setSelectedBusinessDocumentKind] = useState('commitment')
  const [savingAppendixId, setSavingAppendixId] = useState('')
  const [savingAllAppendices, setSavingAllAppendices] = useState(false)
  const [savingBusinessScoring, setSavingBusinessScoring] = useState(false)
  const [savingCommitmentLetterId, setSavingCommitmentLetterId] = useState('')
  const [savingAllCommitmentLetters, setSavingAllCommitmentLetters] = useState(false)

  const refreshParseResult = useCallback(async () => {
    if (!selectedProjectId) return null
    const data = await parseClient.results(selectedProjectId)
    setParseData(data)
    return data
  }, [parseClient, selectedProjectId])

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true)
    setError('')
    try {
      const data = await projectsClient.list({ page: 1, pageSize: 200, bidType: BUSINESS_BID_TYPE })
      const items = (Array.isArray(data?.items) ? data.items : []).filter(
        (item) => normalizeBidType(item?.bidType) === BUSINESS_BID_TYPE,
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
      setError(e?.message || '解析项目列表加载失败')
    } finally {
      setLoadingProjects(false)
    }
  }, [projectsClient, queryProjectId])

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
        projectsClient.get(selectedProjectId),
        parseClient.results(selectedProjectId),
        parseClient.progress(selectedProjectId).catch(() => null),
      ])
      setProject(projectData)
      setParseData(parseResult)
      setParseProgress(progressResult)
    } catch (e) {
      setError(e?.message || '解析详情加载失败')
    } finally {
      setLoadingDetail(false)
    }
  }, [parseClient, projectsClient, selectedProjectId])

  const createReviewProject = useCallback(async ({ toastMessage } = {}) => {
    setCreatingReview(true)
    try {
      const now = new Date()
      const pad = (num) => String(num).padStart(2, '0')
      const created = await projectsClient.create({
        name: `${reviewConfig.createProjectNamePrefix}-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`,
        customerName: '',
        owner: '',
        manager: '',
        bidType: BUSINESS_BID_TYPE,
        deadline: '',
        reviewDecision: 'pending',
      })
      await loadProjects()
      setSelectedProjectId(created?.id || '')
      if (toastMessage) {
        showToast?.(toastMessage)
      } else {
        showToast?.(reviewConfig.createSuccessMessage)
      }
      return created
    } catch (e) {
      showToast?.(e?.message || '新建解析项目失败', 'error')
      return null
    } finally {
      setCreatingReview(false)
    }
  }, [loadProjects, projectsClient, reviewConfig.createProjectNamePrefix, reviewConfig.createSuccessMessage, showToast])

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
        const progress = await parseClient.progress(selectedProjectId)
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
  }, [parseClient, selectedProjectId, uploading])

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
  const commitmentLetters = Array.isArray(parseData?.structured?.commitmentLetters)
    ? parseData.structured.commitmentLetters
    : EMPTY_APPENDICES
  const commitmentClues = Array.isArray(parseData?.structured?.commitmentClues)
    ? parseData.structured.commitmentClues
    : EMPTY_APPENDICES
  const activeCommitmentLetterId = commitmentLetters.length
    && commitmentLetters.some((letter, index) => commitmentLetterKey(letter, index) === selectedCommitmentLetterId)
    ? selectedCommitmentLetterId
    : commitmentLetters.length
      ? commitmentLetterKey(commitmentLetters[0], 0)
      : ''
  const selectedCommitmentLetter = useMemo(
    () => commitmentLetters.find((letter, index) => commitmentLetterKey(letter, index) === activeCommitmentLetterId)
      || commitmentLetters[0]
      || null,
    [activeCommitmentLetterId, commitmentLetters],
  )
  const activeAppendixId = appendices.length && appendices.some((appendix, index) => appendixKey(appendix, index) === selectedAppendixId)
    ? selectedAppendixId
    : appendices.length
      ? appendixKey(appendices[0], 0)
      : ''
  const selectedAppendix = useMemo(
    () => appendices.find((appendix, index) => appendixKey(appendix, index) === activeAppendixId) || appendices[0] || null,
    [activeAppendixId, appendices],
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
  const showBusinessCompactUpload = !isParseCompleted
  const hasCommitmentLetters = commitmentLetters.length > 0
  const hasAppendices = appendices.length > 0
  const activeBusinessDocumentKind = selectedBusinessDocumentKind === 'appendix' && hasAppendices
    ? 'appendix'
    : selectedBusinessDocumentKind === 'commitment' && hasCommitmentLetters
      ? 'commitment'
      : hasCommitmentLetters
        ? 'commitment'
        : hasAppendices
          ? 'appendix'
          : 'commitment'
  const activeBusinessDocumentIsCommitment = activeBusinessDocumentKind === 'commitment'
  const businessDocumentCount = commitmentLetters.length + appendices.length
  const selectedBusinessDocumentTitle = activeBusinessDocumentIsCommitment
    ? selectedCommitmentLetter?.title || '承诺函预览'
    : selectedAppendix?.title || '商务附件预览'
  const selectedBusinessDocumentSubtitle = ''

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
      parseClient.appendixPreview(selectedProjectId, appendixId)
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
  }, [parseClient, selectedProjectId, selectedAppendix?.docxPath, selectedAppendix?.id])

  useEffect(() => {
    const letterId = selectedCommitmentLetter?.id
    if (!selectedProjectId || !letterId) {
      return undefined
    }

    let cancelled = false
    const timer = setTimeout(() => {
      setCommitmentLetterPreviewLoading(true)
      setCommitmentLetterPreview(null)
      setCommitmentLetterPreviewError('')
      parseClient.commitmentLetterPreview(selectedProjectId, letterId)
        .then((data) => {
          if (!cancelled) setCommitmentLetterPreview(data)
        })
        .catch((e) => {
          if (!cancelled) {
            setCommitmentLetterPreview(null)
            setCommitmentLetterPreviewError(e?.message || '承诺函 Word 预览加载失败')
          }
        })
        .finally(() => {
          if (!cancelled) setCommitmentLetterPreviewLoading(false)
        })
    }, 0)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [parseClient, selectedCommitmentLetter?.docxPath, selectedCommitmentLetter?.id, selectedProjectId])

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
      showToast?.(`当前没有可解析${BUSINESS_BID_TYPE}项目，请先新建解析项目。`, 'error')
      return
    }
    if (reviewDecision === 'abandon') {
      showToast?.('当前项目已标记为不参与，如需继续请先切换为“参与投标”。', 'error')
      return
    }
    if (!tenderFiles.length) {
      const message = `请先上传${BUSINESS_FILE_LABEL}招标文件后再解析。`
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }

    setUploading(true)
    setUploadError('')
    setParseProgress({
      status: 'running',
      percentage: 3,
      summary: `正在上传${BUSINESS_FILE_LABEL}招标文件。`,
      events: [{ step: 'upload', level: 'info', message: `正在上传${BUSINESS_FILE_LABEL}招标文件。` }],
      opencodeOutput: { parts: [] },
    })
    try {
      const formData = new FormData()
      tenderFiles.forEach((file) => formData.append('tenderFiles', file))
      const response = await parseClient.uploadAndRun(selectedProjectId, { formData })
      setParseData(response)
      const latestProgress = await parseClient.progress(selectedProjectId).catch(() => null)
      if (latestProgress) setParseProgress(latestProgress)
      const latestProject = await projectsClient.get(selectedProjectId)
      setProject(latestProject)
      setProjects((prev) => prev.map((item) => (
        item.id === latestProject.id ? { ...item, ...latestProject } : item
      )))
      setTenderFiles([])
      showToast?.(response?.message || `${BUSINESS_BID_TYPE}招标文件解析完成。`)
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
      await projectsClient.delete(selectedProjectId)
      setProjects((prev) => prev.filter((item) => item.id !== selectedProjectId))
      setProject(null)
      setParseData(null)
      setTenderFiles([])
      setUploadError('')
      await createReviewProject({
        toastMessage: `该${BUSINESS_BID_TYPE}项目已设为不参与并移出项目总览，已自动新建解析项目。`,
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

  const handleApproveAppendixAsset = async (appendixId) => {
    if (!selectedProjectId || !appendixId) return
    setSavingAppendixId(appendixId)
    try {
      const result = await parseClient.approveAppendixAsset(selectedProjectId, appendixId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '商务附件模板已审核通过。')
    } catch (e) {
      showToast?.(e?.message || '商务附件模板审核失败', 'error')
    } finally {
      setSavingAppendixId('')
    }
  }

  const handleApproveAllAppendixAssets = async () => {
    if (!selectedProjectId || !appendices.length) return
    setSavingAllAppendices(true)
    try {
      const result = await parseClient.approveAllAppendixAssets(selectedProjectId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '商务附件模板已批量审核通过。')
    } catch (e) {
      showToast?.(e?.message || '商务附件模板批量审核失败', 'error')
    } finally {
      setSavingAllAppendices(false)
    }
  }

  const handleApproveBusinessScoringAsset = async () => {
    if (!selectedProjectId) return
    setSavingBusinessScoring(true)
    try {
      const result = await parseClient.approveBusinessScoringAsset(selectedProjectId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '商务评分标准已审核通过。')
    } catch (e) {
      showToast?.(e?.message || '商务评分标准审核失败', 'error')
    } finally {
      setSavingBusinessScoring(false)
    }
  }

  const handleApproveCommitmentLetterAsset = async (letterId) => {
    if (!selectedProjectId || !letterId) return
    setSavingCommitmentLetterId(letterId)
    try {
      const result = await parseClient.approveCommitmentLetterAsset(selectedProjectId, letterId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '承诺函已审核通过。')
    } catch (e) {
      showToast?.(e?.message || '承诺函审核失败', 'error')
    } finally {
      setSavingCommitmentLetterId('')
    }
  }

  const handleApproveAllCommitmentLetterAssets = async () => {
    if (!selectedProjectId || !commitmentLetters.length) return
    setSavingAllCommitmentLetters(true)
    try {
      const result = await parseClient.approveAllCommitmentLetterAssets(selectedProjectId)
      if (result?.parseResult) setParseData(result.parseResult)
      else await refreshParseResult()
      showToast?.(result?.message || '承诺函已批量审核通过。')
    } catch (e) {
      showToast?.(e?.message || '承诺函批量审核失败', 'error')
    } finally {
      setSavingAllCommitmentLetters(false)
    }
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

  const renderParseProgress = () => {
    if (!parseProgress || (parseProgress.status === 'idle' && !uploading)) return null
    const events = Array.isArray(parseProgress.events) ? parseProgress.events.slice(-6).reverse() : []
    const parts = Array.isArray(parseProgress.opencodeOutput?.parts)
      ? parseProgress.opencodeOutput.parts.filter((part) => part?.text).slice(-3)
      : []
    const percentage = Math.max(0, Math.min(100, Number(parseProgress.percentage || 0)))
    const progressSummary = parseProgress.summary === '尚未触发招标文件解析。' ? '' : parseProgress.summary
    return (
      <DataCard className="!p-5 flex flex-col gap-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">解析进度</h3>
            <p className="text-xs text-outline mt-1">{progressSummary || `正在解析${BUSINESS_BID_TYPE}招标文件。`}</p>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-md font-semibold ${
            parseProgress.status === 'completed'
              ? 'bg-secondary-container text-on-secondary-container'
              : parseProgress.status === 'failed'
                ? 'bg-error-container text-error'
                : 'bg-surface-container-high text-on-surface-variant'
          }`}>
            {parseProgress.status === 'completed' ? '完成' : parseProgress.status === 'failed' ? '失败' : '进行中'} · {percentage}%
          </span>
        </div>
        <div className="h-2 bg-surface-container-high overflow-hidden">
          <div className="h-full bg-primary transition-all" style={{ width: `${percentage}%` }} />
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="rounded-md border border-surface-container-high bg-[#f7f7f7] p-3">
            <p className="text-xs font-semibold text-on-surface mb-2">步骤记录</p>
            <div className="flex flex-col gap-2">
              {events.length ? events.map((event, index) => (
                <div key={`${event.at || ''}-${index}`} className="text-xs text-on-surface-variant flex items-start gap-2">
                  <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${event.level === 'success' ? 'bg-secondary' : event.level === 'warning' ? 'bg-tertiary' : 'bg-primary'}`} />
                  <span>{event.message || '-'}</span>
                </div>
              )) : (
                <p className="text-xs text-outline">等待解析服务返回进度。</p>
              )}
            </div>
          </div>
          <div className="rounded-md border border-surface-container-high bg-[#f7f7f7] p-3">
            <p className="text-xs font-semibold text-on-surface mb-2">futurecode 输出</p>
            {parts.length ? (
              <div className="flex flex-col gap-2">
                {parts.map((part, index) => (
                  <pre key={`${part.type || 'text'}-${index}`} className="max-h-24 overflow-auto whitespace-pre-wrap break-words rounded bg-white px-2 py-1 text-[11px] leading-relaxed text-on-surface-variant">
                    {part.text}
                  </pre>
                ))}
              </div>
            ) : (
              <p className="text-xs text-outline">尚未收到 futurecode 流式片段；当前显示后端真实步骤进度。</p>
            )}
          </div>
        </div>
      </DataCard>
    )
  }

  const renderBusinessCompactProgress = () => {
    if (!uploading && (!parseProgress || parseProgress.status === 'idle')) return null
    const status = uploading ? 'running' : (parseProgress?.status || 'idle')
    const percentage = Math.max(0, Math.min(100, Number(parseProgress?.percentage || (uploading ? 3 : 0))))
    const statusText = status === 'completed' ? '解析完成' : status === 'failed' ? '解析失败' : status === 'running' ? '解析中' : '等待上传'
    const summary = parseProgress?.summary === '尚未触发招标文件解析。'
      ? '正在上传并解析商务招标文件，请稍候。'
      : (parseProgress?.summary || '正在上传并解析商务招标文件，请稍候。')

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

  const renderBusinessDocumentMeta = () => null

  const renderBusinessDocumentPreview = () => {
    if (activeBusinessDocumentIsCommitment) {
      if (commitmentLetterPreviewLoading) {
        return (
          <div className="flex h-full min-h-0 items-center justify-center text-sm text-on-surface-variant">
            正在加载承诺函预览...
          </div>
        )
      }
      if (commitmentLetterPreview?.onlyoffice?.fileUrl && commitmentLetterPreview?.onlyoffice?.callbackUrl && !commitmentLetterPreviewError) {
        return (
          <OnlyOfficeEmbed
            session={commitmentLetterPreview.onlyoffice}
            mode="view"
            className="h-full min-h-0 w-full rounded-md border border-surface-container-high bg-white"
            onError={(message) => setCommitmentLetterPreviewError(message || 'OnlyOffice 承诺函预览加载失败')}
          />
        )
      }
      return (
        <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 text-center text-sm text-on-surface-variant">
          <p>{commitmentLetterPreviewError || '当前承诺函暂时无法载入 OnlyOffice 预览。'}</p>
          {commitmentLetterPreview?.onlyoffice?.browserFileUrl ? (
            <a
              href={commitmentLetterPreview.onlyoffice.browserFileUrl}
              target="_blank"
              rel="noreferrer"
              className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-on-primary"
            >
              打开 Word 文件
            </a>
          ) : null}
        </div>
      )
    }

    if (appendixPreviewLoading) {
      return (
        <div className="flex h-full min-h-0 items-center justify-center text-sm text-on-surface-variant">
          正在加载附件预览...
        </div>
      )
    }
    if (appendixPreview?.onlyoffice?.fileUrl && appendixPreview?.onlyoffice?.callbackUrl && !appendixPreviewError) {
      return (
        <OnlyOfficeEmbed
          session={appendixPreview.onlyoffice}
          mode="view"
          className="h-full min-h-0 w-full rounded-md border border-surface-container-high bg-white"
          onError={(message) => setAppendixPreviewError(message || 'OnlyOffice 附件预览加载失败')}
        />
      )
    }
    return (
      <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 text-center text-sm text-on-surface-variant">
        <p>{appendixPreviewError || '当前附件暂时无法载入 OnlyOffice 预览。'}</p>
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
    )
  }

  if (loadingProjects) return <PageLoading title="正在加载解析模块..." />
  if (error) return <PageError title="解析模块加载失败" description={error} onRetry={loadProjects} />
  if (!reviewProjects.length) {
    return (
      <div className="review-page business-ui-shell flex flex-col gap-5 animate-fade-in max-w-none">
        <PageHeader
          title={reviewConfig.pageTitle}
          description=""
          actions={null}
        />
        <section className="business-parse-empty rounded-md border border-surface-container-high bg-surface-container-lowest px-6 py-8">
          <div className="mx-auto flex max-w-[720px] flex-col items-center text-center">
            <span className="material-symbols-outlined text-[32px] text-primary/70">document_scanner</span>
            <h2 className="mt-3 text-base font-headline font-bold text-on-surface">{reviewConfig.emptyTitle}</h2>
            <p className="mt-2 max-w-[520px] text-sm leading-relaxed text-on-surface-variant">{reviewConfig.emptyDescription}</p>
            <Button
              className="mt-5"
              onClick={handleCreateReviewProject}
              disabled={creatingReview}
              size="stage"
              variant="primary"
            >
              {creatingReview ? '新建中...' : reviewConfig.createButtonLabel}
            </Button>
          </div>
        </section>
      </div>
    )
  }
  if (loadingDetail) return <PageLoading title="正在加载项目解析详情..." />

  if (showBusinessCompactUpload) {
    return (
      <div className="review-page business-ui-shell flex flex-col gap-6 animate-fade-in max-w-none">
        <DataCard className="mt-6 w-full max-w-[760px] !p-0 overflow-hidden self-center">
          <div className="business-section-head flex items-center px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-xl font-headline font-bold text-[#0067B6]">商务标解析</h3>
              <span className="text-xs text-outline">{project?.name || '待解析商务标项目'}</span>
            </div>
          </div>

          <div className="px-5 py-5">
            <label
              htmlFor="business-review-tender-upload"
              className={[
                'business-dropzone flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-md border border-dashed px-6 py-8 text-center transition-colors',
                uploading || reviewDecision === 'abandon' ? 'pointer-events-none opacity-60' : 'hover:border-primary hover:bg-primary/5',
              ].join(' ')}
            >
              <span className="material-symbols-outlined text-2xl text-primary">upload_file</span>
              <span className="mt-2 text-sm font-semibold text-on-surface">选择商务招标文件</span>
              <span className="mt-1 text-xs text-outline">支持 Word、PDF、Excel 等招标附件</span>
            </label>
            <input
              id="business-review-tender-upload"
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
                disabled={uploading || reviewDecision === 'abandon'}
                size="stage"
                variant="primary"
              >
                {uploading ? '上传解析中...' : '上传并解析'}
              </Button>
            </div>
            {uploadError && (
              <div className="mt-3 rounded-md border border-error/30 bg-error-container/20 px-3 py-2 text-sm text-error">
                {uploadError}
              </div>
            )}
            {uploading && (
              <div className="mt-3 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary">
                正在上传并解析商务招标文件，请稍候。
              </div>
            )}
            {renderBusinessCompactProgress()}
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
          <>
            <Button
              onClick={handleCreateReviewProject}
              disabled={creatingReview}
              size="lg"
              variant="primary"
            >
              {creatingReview ? '新建中...' : reviewConfig.createButtonLabel}
            </Button>
            {isParseCompleted ? null : (
              <button
                onClick={() => {
                  loadProjects()
                  loadCurrentProject()
                }}
                className="px-5 py-2.5 bg-surface-container-high text-on-surface-variant font-medium rounded-lg hover:bg-surface-dim transition-colors text-sm"
              >
                刷新
              </button>
            )}
          </>
        )}
      />

      {!isParseCompleted ? (
        <DataCard className="!p-6 flex flex-col gap-5">
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            <div className="xl:col-span-8 rounded-md bg-[#f7f7f7] border border-surface-container-high px-4 py-3">
              <p className="text-xs text-outline mb-1">{reviewConfig.currentProjectLabel}</p>
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
              <h3 className="text-sm font-semibold text-on-surface">{reviewConfig.uploadSectionTitle}</h3>
              <p className="text-xs text-outline mt-1">{reviewConfig.uploadSectionDescription}</p>
            </div>
            <Button
              onClick={handleUploadAndParse}
              disabled={uploading || reviewDecision === 'abandon'}
              size="lg"
              variant="primary"
            >
              {uploading ? '上传并解析中...' : '上传并解析'}
            </Button>
          </div>

          <div className="border border-surface-container-high rounded-md p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold text-on-surface">{reviewConfig.uploadFileLabel}</h4>
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
              <p className="font-medium text-on-surface mb-1">{reviewConfig.sourceFilesLabel}</p>
              <p>{sourceFiles.length ? sourceFiles.map((file) => file.name).join('，') : '暂无'}</p>
            </div>
            <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
              <p className="font-medium text-on-surface mb-1">解析时间</p>
              <p>{formatDateTime(parseData?.parsedAt)}</p>
            </div>
            <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
              <p className="font-medium text-on-surface mb-1">投标起始日期</p>
              <p>{parsedDates?.startDate || '-'}</p>
            </div>
            <div className="rounded-md bg-[#f7f7f7] p-3 border border-surface-container-high">
              <p className="font-medium text-on-surface mb-1">投标截止日期</p>
              <p>{parsedDates?.endDate || '-'}</p>
            </div>
          </div>
        </DataCard>
      ) : null}

      {!isParseCompleted ? renderParseProgress() : null}

      <DataCard className={isParseCompleted ? '!border-0 !bg-transparent !p-0 !shadow-none overflow-visible' : '!p-0 overflow-hidden'}>
        {!sourceFiles.length ? (
          <div className="p-6 text-sm text-on-surface-variant">{reviewConfig.noSourceHint}</div>
        ) : !isParseCompleted ? (
          <div className="p-6 text-sm text-on-surface-variant">{reviewConfig.pendingParseHint}</div>
        ) : (
          <div className="flex flex-col gap-5">
            {reviewConfig.showApproveBusinessScoring && (
              null
            )}

            <div className="flex flex-col gap-4">
              {scoringGroups.map((group) => (
                <ScoringCriteriaTable
                  key={group.key}
                  title={group.title}
                  rows={group.rows}
                  showEvidenceLocationColumn={reviewConfig.showEvidenceLocationColumn !== false && group.key !== 'compliance'}
                  showSourceColumns={!['business', 'price', 'compliance'].includes(group.key)}
                  showCount={!['price', 'compliance'].includes(group.key)}
                  showScoreColumn={group.key !== 'compliance'}
                  showRequirementColumn={group.key !== 'compliance'}
                  showProofRequirementColumn={!['business', 'price', 'compliance'].includes(group.key)}
                  scoringItemAlign={group.key === 'compliance' ? 'left' : 'center'}
                  headerAction={group.key === 'business' ? (
                    <Button
                      onClick={handleApproveBusinessScoringAsset}
                      disabled={savingBusinessScoring || !isParseCompleted}
                      className="whitespace-nowrap"
                      size="sm"
                      variant="primary"
                    >
                      {savingBusinessScoring ? '审核中...' : '审核通过'}
                    </Button>
                  ) : null}
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

            <>
              {reviewConfig.showCommitmentClues !== false && (
                <CommitmentClueTable
                  clues={commitmentClues}
                  showEvidenceLocationColumn={reviewConfig.showEvidenceLocationColumn !== false}
                />
              )}
              <div className="border border-surface-container-high rounded-md overflow-hidden">
                  <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-on-surface">商务文档预览</h4>
                    <div className="flex items-center gap-2">
                      {activeBusinessDocumentIsCommitment && reviewConfig.showApproveCommitmentLetters && commitmentLetters.length ? (
                        <>
                          <button
                            type="button"
                            onClick={() => handleApproveCommitmentLetterAsset(selectedCommitmentLetter?.id)}
                            disabled={savingAllCommitmentLetters || Boolean(savingCommitmentLetterId) || !selectedCommitmentLetter?.id}
                            className="rounded-md bg-surface-container-high px-2.5 py-1 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {savingCommitmentLetterId ? '审核中...' : '审核当前'}
                          </button>
                          <button
                            type="button"
                            onClick={handleApproveAllCommitmentLetterAssets}
                            disabled={savingAllCommitmentLetters || Boolean(savingCommitmentLetterId)}
                            className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-on-primary hover:bg-primary-container disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {savingAllCommitmentLetters ? '审核中...' : '审核全部'}
                          </button>
                        </>
                      ) : null}
                      {!activeBusinessDocumentIsCommitment && reviewConfig.showApproveAppendices && appendices.length ? (
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
                      <span className="text-xs text-outline">{businessDocumentCount} 个</span>
                    </div>
                  </div>
                  {businessDocumentCount ? (
                    <OnlyOfficeWorkspace
                      className="m-4 appendix-preview-workspace"
                      heightClass="appendix-preview-shell"
                      gridClassName="grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]"
                      sidebarClassName="appendix-preview-aside"
                      documentAreaClassName="appendix-preview-document"
                      documentTitle={selectedBusinessDocumentTitle}
                      documentSubtitle={selectedBusinessDocumentSubtitle}
                      documentMeta={renderBusinessDocumentMeta()}
                      sidebar={(
                        <div className="appendix-preview-sidebar flex h-full min-h-0 flex-col">
                          <div className="border-b border-surface-container-high px-4 py-3">
                            <p className="text-sm font-semibold text-on-surface">文档条目</p>
                          </div>
                          <div className="appendix-preview-list min-h-0 flex-1 overflow-y-auto p-2">
                            {commitmentLetters.length ? (
                              <div className="mb-3">
                                <p className="px-1 pb-2 text-xs font-semibold text-outline">承诺函 Word 预览 · {commitmentLetters.length}</p>
                                {commitmentLetters.map((letter, index) => {
                                  const key = commitmentLetterKey(letter, index)
                                  const active = activeBusinessDocumentIsCommitment && key === activeCommitmentLetterId
                                  return (
                                    <button
                                      key={key}
                                      type="button"
                                      aria-pressed={active}
                                      onClick={() => {
                                        setSelectedBusinessDocumentKind('commitment')
                                        setSelectedCommitmentLetterId(key)
                                      }}
                                      className={[
                                        'mb-2 flex w-full flex-col items-start gap-1 rounded-md border px-3 py-2 text-left transition-colors',
                                        active
                                          ? 'border-primary bg-primary/5 text-primary'
                                          : 'border-surface-container-high bg-white text-on-surface hover:border-outline-variant hover:bg-surface-container-low',
                                      ].join(' ')}
                                    >
                                      <span className="line-clamp-2 text-sm font-semibold">{letter.title || '-'}</span>
                                      <span className="text-xs text-on-surface-variant">{commitmentTypeLabel(letter.commitmentType)}</span>
                                    </button>
                                  )
                                })}
                              </div>
                            ) : null}
                            {appendices.length ? (
                              <div>
                                <p className="px-1 pb-2 text-xs font-semibold text-outline">商务附件模板产物 · {appendices.length}</p>
                                {appendices.map((appendix, index) => {
                                  const key = appendixKey(appendix, index)
                                  const active = !activeBusinessDocumentIsCommitment && key === activeAppendixId
                                  return (
                                    <button
                                      key={key}
                                      type="button"
                                      aria-pressed={active}
                                      onClick={() => {
                                        setSelectedBusinessDocumentKind('appendix')
                                        setSelectedAppendixId(key)
                                      }}
                                      className={[
                                        'mb-2 flex w-full flex-col items-start gap-1 rounded-md border px-3 py-2 text-left transition-colors',
                                        active
                                          ? 'border-primary bg-primary/5 text-primary'
                                          : 'border-surface-container-high bg-white text-on-surface hover:border-outline-variant hover:bg-surface-container-low',
                                      ].join(' ')}
                                    >
                                      <span className="line-clamp-2 text-sm font-semibold">{appendix.title || '-'}</span>
                                      <span className="text-xs text-on-surface-variant">{appendix.sourceFile || '-'}</span>
                                      {Array.isArray(appendix.qualityIssues) && appendix.qualityIssues.length ? (
                                        <span className="line-clamp-2 text-xs text-error">
                                          {appendix.qualityIssues.join('；')}
                                        </span>
                                      ) : null}
                                    </button>
                                  )
                                })}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      )}
                    >
                      {renderBusinessDocumentPreview()}
                    </OnlyOfficeWorkspace>
                  ) : (
                    <div className="px-4 py-3 text-sm text-outline">未识别到可预览的承诺函或商务附件模板。</div>
                  )}
              </div>
            </>

            {reviewConfig.showEvidenceDetails !== false && (
              <details className="rounded-md border border-surface-container-high bg-white">
                <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-on-surface">证据明细</summary>
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
          <div className="mt-2 text-sm text-error">当前项目已标记为不参与，流程在解析阶段结束。</div>
        )}
      </div>

      {showProjectInfoModal && projectToComplete && (
        <ProjectWizardModal
          mode="update"
          project={projectToComplete}
          forceReviewDecision="participate"
          defaultBidType={BUSINESS_BID_TYPE}
          lockBidType
          projectsApi={businessProjectsAPI}
          materialsApi={businessMaterialsAPI}
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
            navigate(projectRoute(updatedProject.id, '/template-directory', 'business'))
          }}
        />
      )}
    </div>
  )
}
