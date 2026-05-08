import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { parseAPI, projectsAPI } from '../api'
import { PageEmpty, PageError, PageLoading } from '../components/states/PageState'
import DataCard from '../components/shared/DataCard'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import OnlyOfficeWorkspace from '../components/shared/OnlyOfficeWorkspace'
import PageHeader from '../components/shared/PageHeader'
import ProjectWizardModal from '../components/modals/ProjectWizardModal'
import { normalizeBidType, projectRoute, slugFromBidType } from '../utils/workspace'

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

const TECHNICAL_REVIEW_CONFIG = {
  bidType: '技术标',
  pageTitle: '技术标解析模块',
  pageDescription: '上传技术招标文件，提取评分标准、项目基础参数、附表与关键技术要求，为技术标项目后续链路提供入口数据。',
  createProjectNamePrefix: '技术标待解析项目',
  createButtonLabel: '新建技术标解析项目',
  createSuccessMessage: '已新建技术标解析项目，请上传招标文件并解析。',
  emptyTitle: '暂无待解析技术标项目',
  emptyDescription: '你可以在这里先新建技术标解析项目，再上传技术招标文件进行判断。',
  currentProjectLabel: '当前技术标解析项目',
  uploadSectionTitle: '技术招标文件上传与关键参数解析',
  uploadSectionDescription: '本模块负责上传技术招标文件并解析结构化要求，供技术标项目立项和后续目录生成使用。',
  uploadFileLabel: '技术招标文件（必选）',
  sourceFilesLabel: '已上传技术招标文件（当前项目）',
  resultTitle: '技术标结构化解析结果',
  pendingParseHint: '请点击上方“上传并解析”开始提取技术标结构化要求。',
  noSourceHint: '当前项目尚未上传技术招标文件。',
  appendixTitle: '附表空表产物',
  appendixSwitchHint: '空表 Word 已生成，可切换预览。',
  appendixEmptyHint: '未识别到附表要求。',
  scoringGroups: [
    ['technical', '技术评分标准'],
    ['business', '商务评分标准'],
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

const BUSINESS_REVIEW_CONFIG = {
  bidType: '商务标',
  pageTitle: '商务标解析模块',
  pageDescription: '上传商务招标文件，提取商务评分、响应要求、资格支撑、保证金与承诺函线索，为商务标项目后续编制提供入口数据。',
  createProjectNamePrefix: '商务标待解析项目',
  createButtonLabel: '新建商务标解析项目',
  createSuccessMessage: '已新建商务标解析项目，请上传商务招标文件并解析。',
  emptyTitle: '暂无待解析商务标项目',
  emptyDescription: '你可以在这里先新建商务标解析项目，再上传商务招标文件进行判断。',
  currentProjectLabel: '当前商务标解析项目',
  uploadSectionTitle: '商务招标文件上传与关键参数解析',
  uploadSectionDescription: '本模块负责上传商务招标文件并解析商务响应、资格支撑、附表与承诺函要求，供商务标项目后续使用。',
  uploadFileLabel: '商务招标文件（必选）',
  sourceFilesLabel: '已上传商务招标文件（当前项目）',
  resultTitle: '商务标结构化解析结果',
  pendingParseHint: '请点击上方“上传并解析”开始提取商务标结构化要求。',
  noSourceHint: '当前项目尚未上传商务招标文件。',
  appendixTitle: '商务附表与附件产物',
  appendixSwitchHint: '商务附表 Word 已生成，可切换预览。',
  appendixEmptyHint: '未识别到商务附表要求。',
  scoringGroups: [
    ['business', '商务评分标准'],
    ['price', '投标报价评分标准'],
    ['compliance', '符合性审查标准'],
  ],
  fallbackScoringTitle: '商务评分细则',
  fieldGroupSections: [
    ['projectBasics', '项目基础信息'],
    ['businessResponse', '商务响应要求'],
    ['qualificationSupport', '资格与支撑要求'],
    ['commitmentRequirements', '承诺事项要求'],
  ],
  presenceTitle: '商务要求覆盖情况',
  buildPresenceRows: (presence = {}) => ([
    { label: '资格文件要求', item: presence.qualificationDocuments },
    { label: '业绩证明要求', item: presence.performanceDocuments },
    { label: '偏差响应要求', item: presence.deviationResponse },
    { label: '投标保证金要求', item: presence.bidSecurity },
    { label: '其他承诺要求', item: presence.otherCommitments },
    { label: '否决项承诺要求', item: presence.disqualificationClauses },
  ]),
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

function FieldGroupTable({ title, fields = [] }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-left font-semibold text-on-surface">字段</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">解析内容</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">来源</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">证据位置</th>
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
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{field.evidenceLocation || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ScoringCriteriaTable({ title, rows = [], emptyText = '未识别到相关评分细则。' }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
        <span className="text-xs text-outline">{rows.length} 条</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[980px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-left font-semibold text-on-surface">序号</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">评分/审查项</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">分值</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">得分点/要求</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">证明材料要求</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">来源</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">章节</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">证据位置</th>
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((item, index) => (
              <tr key={item.id || `${title}-${index}`} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.order || index + 1}</td>
                <td className="px-4 py-2 text-on-surface font-medium min-w-[160px]">{item.scoringItem || '-'}</td>
                <td className="px-4 py-2 text-primary whitespace-nowrap">{item.score || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[260px]">{item.scorePoint || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[220px]">{item.proofRequirement || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{item.sourceFile || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{item.section || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.evidenceLocation || '-'}</td>
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={8}>{emptyText}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function PresenceTable({ title = '专题方案 / 供货范围 / 考核条款', rows = [] }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low">
        <h4 className="text-sm font-semibold text-on-surface">{title}</h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-left font-semibold text-on-surface">项目</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">识别结果</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">摘要</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">来源</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">证据位置</th>
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
                  <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{evidence?.evidenceLocation || '-'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CommitmentLetterTable({ letters = [] }) {
  return (
    <div className="border border-surface-container-high rounded-md overflow-hidden bg-white">
      <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
        <h4 className="text-sm font-semibold text-on-surface">自动生成承诺文件</h4>
        <span className="text-xs text-outline">{letters.length} 个</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[1040px]">
          <thead>
            <tr className="border-b border-surface-container-high">
              <th className="px-4 py-2 text-left font-semibold text-on-surface">名称</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">类型</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">状态</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">放置章节</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">触发词</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">来源</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">证据位置</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">风险标记</th>
            </tr>
          </thead>
          <tbody>
            {letters.length ? letters.map((item) => (
              <tr key={item.id || item.title} className="border-b border-surface-container-high last:border-b-0">
                <td className="px-4 py-2 text-on-surface font-medium min-w-[180px]">{item.title || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{commitmentTypeLabel(item.commitmentType)}</td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <span className={`text-xs px-2 py-0.5 rounded-md font-semibold ${item.status === 'generated' ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                    {commitmentStatusLabel(item.status)}
                  </span>
                </td>
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.placementHint || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.triggerText || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[180px]">{item.sourceFile || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.evidenceLocation || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[220px]">{Array.isArray(item.riskFlags) && item.riskFlags.length ? item.riskFlags.join('，') : '-'}</td>
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={8}>未识别到可自动生成的承诺文件。</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CommitmentClueTable({ clues = [] }) {
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
              <th className="px-4 py-2 text-left font-semibold text-on-surface">线索</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">状态</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">触发词</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">建议动作</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">来源</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">证据位置</th>
              <th className="px-4 py-2 text-left font-semibold text-on-surface">风险标记</th>
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
                <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{item.evidenceLocation || '-'}</td>
                <td className="px-4 py-2 text-on-surface-variant min-w-[220px]">{Array.isArray(item.riskFlags) && item.riskFlags.length ? item.riskFlags.join('，') : '-'}</td>
              </tr>
            )) : (
              <tr>
                <td className="px-4 py-3 text-outline" colSpan={7}>未识别到待确认承诺线索。</td>
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

export default function TenderReview({ showToast, config = TECHNICAL_REVIEW_CONFIG }) {
  const reviewConfig = normalizeBidType(config?.bidType) === '商务标'
    ? { ...BUSINESS_REVIEW_CONFIG, ...config, bidType: '商务标' }
    : { ...TECHNICAL_REVIEW_CONFIG, ...config, bidType: '技术标' }
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

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true)
    setError('')
    try {
      const data = await projectsAPI.list({ page: 1, pageSize: 200, bidType: reviewConfig.bidType })
      const items = (Array.isArray(data?.items) ? data.items : []).filter(
        (item) => normalizeBidType(item?.bidType || reviewConfig.bidType) === reviewConfig.bidType,
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
        projectsAPI.get(selectedProjectId),
        parseAPI.results(selectedProjectId),
        parseAPI.progress(selectedProjectId).catch(() => null),
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

  const createReviewProject = useCallback(async ({ toastMessage } = {}) => {
    setCreatingReview(true)
    try {
      const now = new Date()
      const pad = (num) => String(num).padStart(2, '0')
      const created = await projectsAPI.create({
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
        const progress = await parseAPI.progress(selectedProjectId)
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
      parseAPI.appendixPreview(selectedProjectId, appendixId)
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

  useEffect(() => {
    const letterId = selectedCommitmentLetter?.id
    if (!selectedProjectId || !letterId || reviewConfig.bidType !== '商务标') {
      return undefined
    }

    let cancelled = false
    const timer = setTimeout(() => {
      setCommitmentLetterPreviewLoading(true)
      setCommitmentLetterPreview(null)
      setCommitmentLetterPreviewError('')
      parseAPI.commitmentLetterPreview(selectedProjectId, letterId)
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
  }, [reviewConfig.bidType, selectedCommitmentLetter?.docxPath, selectedCommitmentLetter?.id, selectedProjectId])

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
      showToast?.(`当前没有可解析${reviewConfig.bidType}项目，请先新建解析项目。`, 'error')
      return
    }
    if (reviewDecision === 'abandon') {
      showToast?.('当前项目已标记为不参与，如需继续请先切换为“参与投标”。', 'error')
      return
    }
    if (!tenderFiles.length) {
      const message = `请先上传${reviewConfig.bidType === '商务标' ? '商务' : '技术'}招标文件后再解析。`
      setUploadError(message)
      showToast?.(message, 'error')
      return
    }

    setUploading(true)
    setUploadError('')
    setParseProgress({
      status: 'running',
      percentage: 3,
      summary: `正在上传${reviewConfig.bidType === '商务标' ? '商务' : '技术'}招标文件。`,
      events: [{ step: 'upload', level: 'info', message: `正在上传${reviewConfig.bidType === '商务标' ? '商务' : '技术'}招标文件。` }],
      opencodeOutput: { parts: [] },
    })
    try {
      const formData = new FormData()
      tenderFiles.forEach((file) => formData.append('tenderFiles', file))
      const response = await parseAPI.uploadAndRun(selectedProjectId, { formData })
      setParseData(response)
      const latestProgress = await parseAPI.progress(selectedProjectId).catch(() => null)
      if (latestProgress) setParseProgress(latestProgress)
      const latestProject = await projectsAPI.get(selectedProjectId)
      setProject(latestProject)
      setProjects((prev) => prev.map((item) => (
        item.id === latestProject.id ? { ...item, ...latestProject } : item
      )))
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
      await projectsAPI.delete(selectedProjectId)
      setProjects((prev) => prev.filter((item) => item.id !== selectedProjectId))
      setProject(null)
      setParseData(null)
      setTenderFiles([])
      setUploadError('')
      await createReviewProject({
        toastMessage: `该${reviewConfig.bidType}项目已设为不参与并移出项目总览，已自动新建解析项目。`,
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

  const renderParseProgress = () => {
    if (!parseProgress || (parseProgress.status === 'idle' && !uploading)) return null
    const events = Array.isArray(parseProgress.events) ? parseProgress.events.slice(-6).reverse() : []
    const parts = Array.isArray(parseProgress.opencodeOutput?.parts)
      ? parseProgress.opencodeOutput.parts.filter((part) => part?.text).slice(-3)
      : []
    const percentage = Math.max(0, Math.min(100, Number(parseProgress.percentage || 0)))
    return (
      <DataCard className="!p-5 flex flex-col gap-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">解析进度</h3>
            <p className="text-xs text-outline mt-1">{parseProgress.summary || `正在解析${reviewConfig.bidType}招标文件。`}</p>
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

  if (loadingProjects) return <PageLoading title="正在加载解析模块..." />
  if (error) return <PageError title="解析模块加载失败" description={error} onRetry={loadProjects} />
  if (!reviewProjects.length) {
    return (
      <div className="review-page flex flex-col gap-6 animate-fade-in max-w-none">
        <PageHeader
          title={reviewConfig.pageTitle}
          description={reviewConfig.pageDescription}
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
            title={reviewConfig.emptyTitle}
            description={reviewConfig.emptyDescription}
          />
          <div className="flex justify-center">
            <button
              onClick={handleCreateReviewProject}
              disabled={creatingReview}
              className="stage-action-btn h-[34px] px-5 bg-[#0067B6] text-white text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creatingReview ? '新建中...' : reviewConfig.createButtonLabel}
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
        title={reviewConfig.pageTitle}
        description={reviewConfig.pageDescription}
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={handleCreateReviewProject}
              disabled={creatingReview}
              className="px-5 py-2.5 bg-[#0067B6] text-white font-medium rounded-lg hover:bg-[#0b74c8] transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {creatingReview ? '新建中...' : reviewConfig.createButtonLabel}
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

      {renderParseProgress()}

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-container-high flex items-center justify-between">
          <h3 className="text-sm font-semibold text-on-surface">{reviewConfig.resultTitle}</h3>
          <span className={`text-xs px-2.5 py-1 rounded-md font-medium ${isParseCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {isParseCompleted ? `解析完成${structuredCategories.length ? ` · ${structuredCategories.length} 类` : ''}` : '待解析'}
          </span>
        </div>

        {!sourceFiles.length ? (
          <div className="p-6 text-sm text-on-surface-variant">{reviewConfig.noSourceHint}</div>
        ) : !isParseCompleted ? (
          <div className="p-6 text-sm text-on-surface-variant">{reviewConfig.pendingParseHint}</div>
        ) : (
          <div className="p-5 flex flex-col gap-5">
            <div className="flex flex-col gap-4">
              {scoringGroups.map((group) => (
                <ScoringCriteriaTable key={group.key} title={group.title} rows={group.rows} />
              ))}
            </div>

            <div className="grid grid-cols-1 2xl:grid-cols-2 gap-4">
              {reviewConfig.fieldGroupSections.map(([key, title]) => (
                <FieldGroupTable key={key} title={title} fields={fieldGroups[key] || []} />
              ))}
            </div>

            <PresenceTable title={reviewConfig.presenceTitle} rows={presenceRows} />

            {reviewConfig.bidType === '商务标' ? (
              <>
                <CommitmentLetterTable letters={commitmentLetters} />
                <CommitmentClueTable clues={commitmentClues} />
                <div className="border border-surface-container-high rounded-md overflow-hidden">
                  <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-on-surface">承诺函 Word 预览</h4>
                    <span className="text-xs text-outline">{commitmentLetters.length} 个</span>
                  </div>
                  {commitmentLetters.length ? (
                    <OnlyOfficeWorkspace
                      className="m-4 appendix-preview-workspace"
                      heightClass="appendix-preview-shell"
                      gridClassName="grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]"
                      sidebarClassName="appendix-preview-aside"
                      documentAreaClassName="appendix-preview-document"
                      documentTitle={selectedCommitmentLetter?.title || '承诺函预览'}
                      documentSubtitle={selectedCommitmentLetter?.workspacePath || selectedCommitmentLetter?.sourceFile || ''}
                      documentMeta={(
                        <span className="whitespace-nowrap rounded-md bg-surface-container-high px-2.5 py-1 text-xs font-semibold text-on-surface-variant">
                          {commitmentStatusLabel(selectedCommitmentLetter?.status)}
                        </span>
                      )}
                      sidebar={(
                        <div className="appendix-preview-sidebar flex h-full min-h-0 flex-col">
                          <div className="border-b border-surface-container-high px-4 py-3">
                            <p className="text-sm font-semibold text-on-surface">承诺函条目</p>
                            <p className="mt-1 text-xs text-outline">已生成解析草稿，可切换预览并复核。</p>
                          </div>
                          <div className="appendix-preview-list min-h-0 flex-1 overflow-y-auto p-2">
                            {commitmentLetters.map((letter, index) => {
                              const key = commitmentLetterKey(letter, index)
                              const active = key === activeCommitmentLetterId
                              return (
                                <button
                                  key={key}
                                  type="button"
                                  aria-pressed={active}
                                  onClick={() => setSelectedCommitmentLetterId(key)}
                                  className={[
                                    'mb-2 flex w-full flex-col items-start gap-1 rounded-md border px-3 py-2 text-left transition-colors',
                                    active
                                      ? 'border-primary bg-primary/5 text-primary'
                                      : 'border-surface-container-high bg-white text-on-surface hover:border-outline-variant hover:bg-surface-container-low',
                                  ].join(' ')}
                                >
                                  <span className="line-clamp-2 text-sm font-semibold">{letter.title || '-'}</span>
                                  <span className="text-xs text-on-surface-variant">{commitmentTypeLabel(letter.commitmentType)}</span>
                                  <span className="text-xs text-outline">{letter.workspacePath || letter.docxPath || '-'}</span>
                                </button>
                              )
                            })}
                          </div>
                        </div>
                      )}
                    >
                      {commitmentLetterPreviewLoading ? (
                        <div className="flex h-full min-h-0 items-center justify-center text-sm text-on-surface-variant">
                          正在加载承诺函预览...
                        </div>
                      ) : commitmentLetterPreview?.onlyoffice?.fileUrl && commitmentLetterPreview?.onlyoffice?.callbackUrl && !commitmentLetterPreviewError ? (
                        <OnlyOfficeEmbed
                          session={commitmentLetterPreview.onlyoffice}
                          mode="view"
                          className="h-full min-h-0 w-full rounded-md border border-surface-container-high bg-white"
                          onError={(message) => setCommitmentLetterPreviewError(message || 'OnlyOffice 承诺函预览加载失败')}
                        />
                      ) : (
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
                      )}
                    </OnlyOfficeWorkspace>
                  ) : (
                    <div className="px-4 py-3 text-sm text-outline">未识别到可自动生成的承诺文件。</div>
                  )}
                </div>
              </>
            ) : null}

            <div className="border border-surface-container-high rounded-md overflow-hidden">
              <div className="px-4 py-3 border-b border-surface-container-high bg-surface-container-low flex items-center justify-between">
                <h4 className="text-sm font-semibold text-on-surface">{reviewConfig.appendixTitle}</h4>
                <span className="text-xs text-outline">{appendices.length} 个</span>
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
                    <span className="whitespace-nowrap rounded-md bg-surface-container-high px-2.5 py-1 text-xs font-semibold text-on-surface-variant">
                      {selectedAppendix?.rowCount ?? 0} 行
                    </span>
                  )}
                  sidebar={(
                    <div className="appendix-preview-sidebar flex h-full min-h-0 flex-col">
                      <div className="border-b border-surface-container-high px-4 py-3">
                        <p className="text-sm font-semibold text-on-surface">附表条目</p>
                        <p className="mt-1 text-xs text-outline">{reviewConfig.appendixSwitchHint}</p>
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
                              <span className="text-xs text-outline">{appendix.workspacePath || appendix.docxPath || '-'}</span>
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
            </div>

            <details className="rounded-md border border-surface-container-high bg-white">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-on-surface">证据明细</summary>
              <div className="overflow-x-auto border-t border-surface-container-high">
                <table className="w-full text-sm min-w-[1120px]">
                  <thead>
                    <tr className="bg-surface-container-low border-b border-surface-container-high">
                      <th className="px-4 py-2 text-left font-semibold text-on-surface">类别</th>
                      <th className="px-4 py-2 text-left font-semibold text-on-surface">字段</th>
                      <th className="px-4 py-2 text-left font-semibold text-on-surface">提取值</th>
                      <th className="px-4 py-2 text-left font-semibold text-on-surface">来源文件</th>
                      <th className="px-4 py-2 text-left font-semibold text-on-surface">证据位置</th>
                      <th className="px-4 py-2 text-left font-semibold text-on-surface">证据文本</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id} className="border-b border-surface-container-high hover:bg-surface-container-low/60">
                        <td className="px-4 py-2 text-on-surface whitespace-nowrap">{row.category}</td>
                        <td className="px-4 py-2 text-on-surface-variant min-w-[160px]">{row.field}</td>
                        <td className="px-4 py-2 text-primary font-medium min-w-[220px]">{row.value}</td>
                        <td className="px-4 py-2 text-on-surface-variant min-w-[220px]">{row.fileName}</td>
                        <td className="px-4 py-2 text-on-surface-variant whitespace-nowrap">{row.evidenceLocation}</td>
                        <td className="px-4 py-2 text-on-surface-variant min-w-[300px]">{row.evidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
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
          defaultBidType={reviewConfig.bidType}
          lockBidType
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
            navigate(projectRoute(updatedProject.id, '/template-directory', slugFromBidType(updatedProject.bidType)))
          }}
        />
      )}
    </div>
  )
}
