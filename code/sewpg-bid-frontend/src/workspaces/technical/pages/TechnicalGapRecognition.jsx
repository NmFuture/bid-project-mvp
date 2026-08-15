import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalGapsAPI, technicalGenerateAPI, technicalMaterialsAPI, technicalOutlineAPI, technicalProjectsAPI, technicalStagesAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import DataCard from '../../../components/shared/DataCard'
import TechnicalGenerationProgressModal from '../components/TechnicalGenerationProgressModal'
import FactMaintenanceModal from './technicalGapFactModal'
import AiFillReferenceModal from './technicalGapAiFillModal'
import MaterialCandidateCard from './technicalGapMaterialCard'
import TechnicalPreviewModal from './technicalGapPreviewModal'
import {
  TechnicalGapActionControls,
  TechnicalGapQualityBadge,
  TechnicalGapQualityNotice,
  TechnicalTocActionBadge,
} from './technicalGapBadges'
import { subscribeTechnicalGenerationStatus } from '../technicalGenerationStatusPolling'
import { useGapPreviewSession } from './useGapPreviewSession'
import { useBackgroundTaskPolling } from './useBackgroundTaskPolling'
import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import Toolbar from '../../../components/ui/Toolbar'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import {
  asArray,
  asObjectArray,
  aiFillComparisonPair,
  appendixTaskForFillTask,
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
  currentResolvedArtifact,
  currentResolvedArtifacts,
  isFillTemplateMaterial,
  latestResolvedArtifact,
  matchedMaterialForItem,
  primaryBlankSource,
  recommendedSelectionsForItem,
  resultSummaryForItem,
  TECHNICAL_GAP_TAG_CONFIG,
  TECHNICAL_WORD_FILL_SKILL,
  technicalBodyFillCounts,
  technicalGapFillError,
  technicalGapProgressCounts,
  technicalGapQualityFlag,
  technicalGapTagBucketOf,
  technicalGapTagOf,
  technicalMatchScore,
  tenderDocumentStateForAiFill,
  uniqueStrings,
} from './technicalGapRecognitionHelpers'

const compactList = (items, limit = 4) => {
  const list = uniqueStrings(items)
  return {
    visible: list.slice(0, limit),
    overflow: Math.max(0, list.length - limit),
    total: list.length,
  }
}

const sourceRoutingForAppendixTasks = (tasks, item = null) => {
  const routing = asObjectArray(tasks)
    .map((task) => task?.sourceRouting)
    .find((item) => item && typeof item === 'object' && item.source === 'appendix_source_matrix')
  if (routing) return routing
  return item?.sourceRouting?.source === 'appendix_source_matrix' ? item.sourceRouting : null
}

const sourceRoutedMaterials = (tasks, item = null) => [
  ...asObjectArray(item?.sourceRoutedMaterials),
  ...asObjectArray(tasks)
    .filter((task) => task?.sourceRouting?.source === 'appendix_source_matrix')
    .flatMap((task) => asObjectArray(task?.recommendedMaterials)),
]

const sourceRoutingText = (routing) => {
  if (!routing) return ''
  const parts = []
  const projectSources = uniqueStrings(routing.projectSources)
  const standardSources = uniqueStrings(routing.standardSources)
  const otherSources = uniqueStrings(routing.otherSources)
  if (projectSources.length) parts.push(`项目定制：${projectSources.join('、')}`)
  if (standardSources.length) parts.push(`标准文件：${standardSources.join('、')}`)
  if (otherSources.length) parts.push(`其他：${otherSources.join('、')}`)
  return parts.join('；')
}

const normalizeItems = (payload) => {
  const planItems = payload?.gapPlan?.items
  if (Array.isArray(planItems) && planItems.length) return planItems
  return (Array.isArray(payload?.items) ? payload.items : []).map((item) => ({
    id: item.id,
    number: '',
    title: item.title,
    section: item.section,
    status: item.status === 'resolved' ? 'resolved' : item.status === 'skipped' ? 'ignored' : 'missing',
    gapReason: item.desc,
    matchedMaterials: [],
    fillTasks: [],
    resolvedArtifacts: [],
    reviewNotes: [],
  }))
}

// 合并清单条目的来源标签。
const artifactSourceLabels = {
  material_library: '选用素材',
  manual_upload: '人工上传',
  ai_fill: 'AI填写',
}

// 后台任务终态口径：AI 匹配填充只有成功/失败；一键填写（正文+附表）另有部分成功。
// 轮询的去重与通知逻辑见 useBackgroundTaskPolling / technicalGapTaskPolling。
const FACT_CURATE_TERMINAL_STATUSES = ['succeeded', 'failed']
const BODY_FILL_TERMINAL_STATUSES = ['succeeded', 'partial', 'failed']
const factCurateStateOf = (payload) => payload?.factCurateState || null
const bodyFillStateOf = (payload) => payload?.bodyFillState || null

export default function TechnicalGapRecognition({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [data, setData] = useState(null)
  const [selectedId, setSelectedId] = useState('')
  // 目录标签筛选（产品意见 2026-07-17）：点顶部统计标签只看对应目录项，再点一次取消。
  const [tagFilter, setTagFilter] = useState('')
  // 目录树展开态（key = 归一化目录号）；「忽略」父级时自动展开其子级。
  const [expandedTocKeys, setExpandedTocKeys] = useState(() => new Set())
  // 定案项的备选区默认收起，「更换素材」临时展开；切换目录项时复位。
  const [materialSwapOpen, setMaterialSwapOpen] = useState(false)
  // 多机型等场景下一个目录项要串行铺开多份素材：按勾选顺序提交，顺序即正文顺序。
  const [multiPickOpen, setMultiPickOpen] = useState(false)
  const [multiPickKeys, setMultiPickKeys] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [materialKeyword, setMaterialKeyword] = useState('')
  const [materialSearch, setMaterialSearch] = useState({ items: [], total: 0 })
  const [materialLoading, setMaterialLoading] = useState(false)
  const [materialScope, setMaterialScope] = useState(null)
  const [factModalOpen, setFactModalOpen] = useState(false)
  const [factTable, setFactTable] = useState(null)
  const [factFields, setFactFields] = useState([])
  const [factCurateReport, setFactCurateReport] = useState(null)
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationModalOpen, setGenerationModalOpen] = useState(false)
  // 生成在后台跑，弹窗允许关掉；关掉后不因为「还在运行」被重新弹出来。
  const [generationModalDismissed, setGenerationModalDismissed] = useState(false)
  const [aiFillReferenceSelections, setAiFillReferenceSelections] = useState({})
  // AI 填写弹窗：点素材卡上的 AI填写 打开，选参考素材后执行；null=关闭。
  const [aiFillModalTask, setAiFillModalTask] = useState(null)
  // AI 填写弹窗内手动上传的补充素材：入项目素材库后注入候选列表并默认勾选，
  // 关闭弹窗时清空，避免串到下一个附表任务。
  const [aiFillUploadedCandidates, setAiFillUploadedCandidates] = useState([])
  const [aiFillUploadBusy, setAiFillUploadBusy] = useState(false)
  // 事实表清单与附表填写规则的上传维护已迁至素材库 · 规则页（/workspace/tech/materials/rules），
  // 本页只读 facts() 返回的元数据做状态展示；factMaterialPaths 是用户自定义的参考资料目录。
  const [factSpecsMeta, setFactSpecsMeta] = useState({ imported: false, fileName: '' })
  const [sourceMatrixMeta, setSourceMatrixMeta] = useState({ imported: false, fileName: '' })
  // 目录前置守卫（R11-B07-03）：未生成/未确认/空目录时阻断素材匹配页，null 表示未加载（不阻断）
  const [outlineGuard, setOutlineGuard] = useState(null)
  const [factMaterialPaths, setFactMaterialPaths] = useState([])
  // 默认生效的素材范围（标准文件/客户定制/项目定制三层），由后端按项目身份给出
  const [factMaterialScopes, setFactMaterialScopes] = useState([])
  // AI 匹配填充任务状态：执行在后台 worker，弹窗关闭/页面刷新都不影响，靠轮询恢复
  const [factCurateState, setFactCurateState] = useState(null)
  const factCurateRunning = ['queued', 'running'].includes(String(factCurateState?.status || ''))
  // 一键填写（正文+附表）任务状态：同样跑在后台 worker，进度靠轮询恢复，关页面不影响
  const [bodyFillState, setBodyFillState] = useState(null)
  const bodyFillRunning = ['queued', 'running'].includes(String(bodyFillState?.status || ''))
  const bodyFillDone = Number(bodyFillState?.done || 0)
  const bodyFillTotal = Number(bodyFillState?.total || 0)

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const [payload, scopePayload, factsPayload] = await Promise.all([
        technicalGapsAPI.detectionStatus(id),
        technicalProjectsAPI.materialsPath(id),
        technicalGapsAPI.facts(id),
      ])
      const items = normalizeItems(payload)
      setData(payload)
      setMaterialScope(scopePayload)
      const nextFacts = factsPayload?.schemaVersion ? factsPayload : payload?.projectFactTable
      setFactTable(nextFacts || null)
      setFactFields(asObjectArray(nextFacts?.fields))
      setFactSpecsMeta({
        imported: Boolean(factsPayload?.specsImported),
        fileName: String(factsPayload?.specsFileName || ''),
      })
      setFactMaterialPaths(Array.isArray(factsPayload?.materialPaths) ? factsPayload.materialPaths : [])
      setFactMaterialScopes(Array.isArray(factsPayload?.materialScopes) ? factsPayload.materialScopes : [])
      // 页面刷新/重新进入时恢复任务状态：后台还在跑就继续轮询，跑完了直接看到结果
      // 目录前置守卫：拉目录状态用于阻断未确认目录的项目；拉取失败不阻断，由后端 run 接口兜底拦截
      try {
        const outlinePayload = await technicalOutlineAPI.get(id)
        setOutlineGuard(outlinePayload || null)
      } catch {
        setOutlineGuard(null)
      }
      try {
        const curateStatus = await technicalGapsAPI.curateFactsStatus(id)
        setFactCurateState(curateStatus?.factCurateState || null)
      } catch {
        setFactCurateState(null)
      }
      try {
        const bodyStatus = await technicalGapsAPI.bodyFillStatus(id)
        setBodyFillState(bodyStatus?.bodyFillState || null)
      } catch {
        setBodyFillState(null)
      }
      const matrixMeta = factsPayload?.appendixSourceMatrix
      setSourceMatrixMeta({
        // 附表规则已改按客户维护：meta 为 {rowCount, fileName, customerName,...}，无规则时是空 dict
        imported: Number(matrixMeta?.rowCount) > 0 || Boolean(matrixMeta?.path),
        fileName: String(matrixMeta?.fileName || ''),
        customerName: String(matrixMeta?.customerName || ''),
      })
      setSelectedId((prev) => (items.some((item) => item.id === prev) ? prev : items[0]?.id || ''))
    } catch (e) {
      if (!silent) setError(e?.message || '缺口识别与处理加载失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id])

  const loadGenerationStatus = useCallback(async () => {
    try {
      const payload = await technicalGenerateAPI.status(id)
      setGenerationStatus(payload)
      return payload
    } catch {
      return null
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
      loadGenerationStatus()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData, loadGenerationStatus])

  const items = useMemo(() => normalizeItems(data), [data])
  // 筛选按统计桶比对，与标签上的数字同源：点「已就绪」要能筛出归入该桶的仅留标题行。
  const filteredItems = useMemo(() => (
    tagFilter
      ? items.filter((item) => technicalGapTagBucketOf(technicalGapTagOf(item, items)) === tagFilter)
      : items
  ), [items, tagFilter])
  // 目录树（产品裁决 2026-08-04，v6.1 改 level 栈）：按计划顺序 + level 字段构建可折叠树，
  // 附表（编号不成链）同样归入「技术附表」根；默认只展开一级章；
  // 筛选态退化为平铺命中列表（跨层级命中在树里会被折叠遮住）。
  const treeRows = useMemo(() => {
    if (tagFilter) {
      return filteredItems.map((item) => ({
        item,
        key: String(item?.id || ''),
        depth: 0,
        hasChildren: false,
        expanded: false,
      }))
    }
    const childrenMap = new Map()
    const roots = []
    const stack = []
    items.forEach((item) => {
      const level = Number(item?.level) > 0 ? Number(item.level) : 1
      while (stack.length && stack[stack.length - 1].level >= level) stack.pop()
      const parent = stack[stack.length - 1]?.item
      if (parent) {
        const parentId = String(parent.id || '')
        if (!childrenMap.has(parentId)) childrenMap.set(parentId, [])
        childrenMap.get(parentId).push(item)
      } else {
        roots.push(item)
      }
      stack.push({ item, level })
    })
    const rows = []
    const walk = (item, depth) => {
      const key = String(item?.id || '')
      const children = childrenMap.get(key) || []
      const expanded = expandedTocKeys.has(key)
      rows.push({ item, key, depth, hasChildren: children.length > 0, expanded })
      if (children.length && expanded) children.forEach((child) => walk(child, depth + 1))
    }
    roots.forEach((item) => walk(item, 0))
    return rows
  }, [items, filteredItems, tagFilter, expandedTocKeys])
  const effectiveSelectedId = filteredItems.some((item) => item.id === selectedId)
    ? selectedId
    : (filteredItems[0]?.id || '')
  const selected = useMemo(
    () => filteredItems.find((item) => item.id === effectiveSelectedId) || null,
    [effectiveSelectedId, filteredItems],
  )
  const isCompleted = data?.status === 'completed'
  // 当前选中项的派生态：冻结项操作全禁用（只读查看），定案项备选区默认收起。
  const selectedTag = selected ? technicalGapTagOf(selected, items) : ''
  const frozenSelected = selectedTag === 'parent_covered' || selectedTag === 'title_only'
  const settledSelected = ['material_ready', 'template_ready', 'template_review'].includes(selectedTag)
  const readableScopes = useMemo(
    () => (Array.isArray(materialScope?.readableScopes) ? materialScope.readableScopes : []),
    [materialScope],
  )
  const scopePaths = useMemo(
    () => readableScopes.map((scope) => String(scope?.path || '')).filter(Boolean),
    [readableScopes],
  )
  const projectTurbineModel = data?.gapPlan?.projectTurbineModel || data?.projectTurbineModel || materialScope?.turbineModel || null
  const selectedAppendixTasks = asArray(selected?.appendixTasks)
  const selectedCandidateMaterials = asObjectArray(selected?.candidateMaterials)
  const selectedMaterialMatch = matchedMaterialForItem(selected, items)
  const selectedBlankSource = primaryBlankSource(selected)
  // 预览族状态与派生态（选项/会话/弹窗开关/防重载轮询）已收口到 useGapPreviewSession
  const {
    setPreviewChoiceKey,
    previewSession,
    setPreviewSession,
    previewLoading,
    previewError,
    setPreviewError,
    referencePreviewSession,
    referencePreviewLoading,
    referencePreviewError,
    setManualPreviewChoice,
    previewOpen,
    setPreviewOpen,
    selectedPreviewChoices,
    selectedPreviewChoice,
    previewComparison,
    resetPreviewChoice,
  } = useGapPreviewSession({ projectId: id, items, selected, onSilentReload: loadData })
  const selectedFillTasks = asObjectArray(selected?.fillTasks)
  const selectedFillTask = selectedFillTasks[0] || null
  const selectedAppendixTask = appendixTaskForFillTask(selected, selectedFillTask)
  const activeAppendixTasks = selectedAppendixTask ? [selectedAppendixTask] : selectedAppendixTasks
  const selectedSourceRouting = sourceRoutingForAppendixTasks(activeAppendixTasks, selected)
  const selectedSourceRoutingSummary = sourceRoutingText(selectedSourceRouting)
  const aiFillTenderDocumentState = tenderDocumentStateForAiFill(
    appendixTaskForFillTask(selected, aiFillModalTask),
  )
  const selectedReferenceCandidates = (() => {
    const seen = new Set()
    const routed = sourceRoutedMaterials(activeAppendixTasks, selected)
    const candidates = selectedSourceRouting
      ? routed
      : [
          ...activeAppendixTasks.flatMap((task) => asObjectArray(task?.recommendedMaterials)),
          selectedMaterialMatch?.material,
          ...asObjectArray(selected?.matchedMaterials),
          ...selectedCandidateMaterials,
        ].filter(Boolean)
    const base = candidates.filter((item) => {
      const key = String(item?.id || item?.materialId || item?.name || '').trim()
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    // 上限 20：兼顾「章节同名目录素材」拼装列表（可能 10+ 份，全部确定相关）与渲染开销。
    }).sort((a, b) => technicalMatchScore(b) - technicalMatchScore(a)).slice(0, 20)
    // 手动上传的补充素材排在最前，不受匹配度排序与 20 条上限影响
    const uploaded = aiFillUploadedCandidates.filter((item) => {
      const key = String(item?.id || item?.materialId || '').trim()
      return key && !seen.has(key)
    })
    return [...uploaded, ...base]
  })()
  // AI 填写参考素材勾选态按「目录项 × 填写任务」隔离；没勾选过时用该任务的推荐默认值。
  const aiFillSelectionKeyFor = (task) => (selected && task
    ? `${selected.id}:${task.id || task?.blankSource?.id || 'fill'}`
    : '')
  const aiFillReferenceIdsFor = (task) => {
    const key = aiFillSelectionKeyFor(task)
    return key && Object.prototype.hasOwnProperty.call(aiFillReferenceSelections, key)
      ? aiFillReferenceSelections[key]
      : defaultAiFillReferenceMaterialIds(selected, [], task)
  }
  const selectedResolvedArtifact = latestResolvedArtifact(selected)
  // 本章合并清单（产品意见 2026-07-17 方案A）：展示本章全部已选用素材/上传/AI 产物，
  // 替代只显示最新一条产物的旧结果行。2026-08-02：每个目录项只定案一份素材，无合并顺序概念。
  const mergeArtifacts = currentResolvedArtifacts(selected)
  // 已选用素材 id 集合：选用产物 source=material_library，对齐商务标已选高亮。
  const selectedMaterialIdSet = new Set(
    currentResolvedArtifacts(selected)
      .filter((artifact) => String(artifact?.source || '') === 'material_library')
      .map((artifact) => String(artifact?.materialId || '').trim())
      .filter(Boolean),
  )
  const selectedAiFillCompleted = Boolean(
    selectedResolvedArtifact?.source === 'ai_fill'
    || selectedFillTask?.status === 'completed',
  )
  const aiFillActionKey = selected ? `ai-fill:${selected.id}` : 'ai-fill'
  const aiFillBusy = busyAction === aiFillActionKey
  // 素材卡统一交互：待填写判定 = 命名纪律前缀，或该素材就是本目录项填写任务的空白模板
  //（兼容「待填写、待用印-」这类不合严格前缀的存量命名）。
  const fillTaskBlankMaterialIds = new Set(
    selectedFillTasks
      .map((task) => String(task?.blankSource?.materialId || task?.blankSource?.id || '').trim())
      .filter(Boolean),
  )
  const materialFillable = (material) => {
    const materialId = String(material?.id || material?.materialId || '').trim()
    return isFillTemplateMaterial(material) || (Boolean(materialId) && fillTaskBlankMaterialIds.has(materialId))
  }
  // AI填写按钮统一打开参考素材选择弹窗（产品裁决：先选参考素材再执行）；
  // 仅用于已选区的卡片（产品裁决 2026-07-21：候选池/搜索结果不出现 AI填写）。
  // 冻结（由父章覆盖/仅保留标题）的目录项只读，不给 AI填写 入口。
  const cardAiFillProps = (material) => ({
    fillable: materialFillable(material),
    onAiFill: selectedFillTask && !frozenSelected ? () => startAiFill(selectedFillTask) : null,
    aiFillBusy,
    aiFillCompleted: selectedAiFillCompleted,
    // 一键填写进行中禁用所有单条填写入口（与后端 409 互斥一致）
    aiFillDisabled: bodyFillRunning,
    aiFillDisabledReason: '一键填写进行中，暂不可单条填写',
  })
  // 合并清单里由「待填写-」模板选用而来的产物，继续提供 AI填写 入口（对应各自填写任务）。
  const fillTaskForMergeArtifact = (artifact) => {
    if (String(artifact?.source || '') === 'ai_fill') return null
    const materialId = String(artifact?.materialId || '').trim()
    const byBlank = materialId
      ? selectedFillTasks.find((task) => (
        String(task?.blankSource?.materialId || task?.blankSource?.id || '').trim() === materialId
      ))
      : null
    if (byBlank) return byBlank
    return isFillTemplateMaterial({ name: artifact?.fileName || '' }) ? selectedFillTask : null
  }
  const canCompareAiFillArtifact = (artifact) => {
    const artifactKey = `artifact:${String(artifact?.id || '').trim()}`
    const artifactChoice = selectedPreviewChoices.find((choice) => choice.key === artifactKey)
    return Boolean(aiFillComparisonPair(selectedPreviewChoices, artifactChoice))
  }
  // 待填写素材（解析空表/待填写模板）与普通参考素材平级进入统一候选池（产品意见 2026-07-17），
  // 不再单独一套「待填写对象」区块；每张卡绑定各自的填写任务。
  const fillBlankEntries = selectedFillTasks.map((task) => {
    const blank = task?.blankSource || {}
    const isMaterialBlank = blank.sourceType === 'material_fill_template'
      || String(blank.materialId || blank.id || '').startsWith('RAW-')
    return {
      key: String(blank.materialId || blank.id || task.id || '').trim(),
      task,
      blank,
      isMaterialBlank,
      material: {
        id: blank.materialId || blank.id,
        name: blank.title || blank.cleanedFileName || blank.id || '待填写空表/Word',
        folderPath: blank.folderPath || blank.sourceFile || blank.workspacePath || '招标文件解析产物',
        cleanedFileName: blank.cleanedFileName,
      },
    }
  })
  // 已选区组成（产品裁决 2026-07-21 交互重构）：
  // - 解析空副表（非素材空白）没有「选择」概念，天然常驻已选区，带 预览 + AI填写；
  // - 素材类候选（含「待填写-」模板与启发式匹配）一律先进备选池（预览 + 选择），
  //   点「选择」后进入本章合并清单；
  // - 仅文件名精确命中（0.99 后端定案）或父级覆盖的素材仍默认展示为已选中。
  // 解析空副表天然常驻已选区；素材类模板空白在「定案后」（待填写/待审核）也提升到已选区
  // ——否则定案项的备选池收起后，用户看不到定的是哪份模板（产品反馈 2026-08-04）。
  // 整章模板（chapter_fill）同一份素材会同时出现在 matchedMaterials 与 fillTask.blankSource：
  // matchedMaterials 卡（带分数/层级）已在已选区时，模板空白不再重复渲染（产品反馈 2026-08-04）。
  // planner 可能给出多份推荐（多机型时每个机型目录各一份），都要标成系统预选。
  const matchedMaterialIds = new Set(
    asObjectArray(selected?.matchedMaterials)
      .map((material) => String(material?.id || material?.materialId || '').trim())
      .filter(Boolean),
  )
  const topBlankEntries = fillBlankEntries.filter((entry) => {
    if (!entry.isMaterialBlank) return true
    if (!settledSelected) return false
    return !matchedMaterialIds.has(entry.key)
  })
  const poolBlankEntries = fillBlankEntries.filter((entry) => entry.isMaterialBlank && !settledSelected)
  const defaultSelections = recommendedSelectionsForItem(selected, items)
  const defaultSelection = defaultSelections[0] || null
  const selectedCardMaterialIds = new Set(
    defaultSelections
      .map((selection) => String(selection.material?.id || selection.material?.materialId || '').trim())
      .filter(Boolean),
  )
  // 备选素材 = 统一候选池剔除已选中项；解析空副表常驻已选区，不进备选池。
  const backupEntries = (() => {
    const seen = new Set()
    topBlankEntries.forEach((entry) => seen.add(entry.key))
    selectedCardMaterialIds.forEach((materialId) => seen.add(materialId))
    // 已并入合并清单的素材不再出现在备选（方案A：清单是唯一的已选用视图）。
    selectedMaterialIdSet.forEach((materialId) => seen.add(materialId))
    const wrappers = [
      ...poolBlankEntries.map((entry) => ({ kind: 'blank', entry, key: entry.key })),
      ...selectedReferenceCandidates.map((material) => ({
        kind: 'material',
        material,
        key: String(material?.id || material?.materialId || '').trim(),
      })),
    ]
    const deduped = wrappers.filter((wrapper) => {
      if (!wrapper.key || seen.has(wrapper.key)) return false
      seen.add(wrapper.key)
      return true
    })
    // 系统预选置顶（产品裁决 2026-08-04）：无论展示分高低，系统预选的那几份永远排在前面，
    // 多机型时按 planner 给出的机型顺序。
    if (!matchedMaterialIds.size) return deduped
    const pinned = deduped.filter((wrapper) => matchedMaterialIds.has(wrapper.key))
    return pinned.length
      ? [...pinned, ...deduped.filter((wrapper) => !matchedMaterialIds.has(wrapper.key))]
      : deduped
  })()
  const multiPickMaterialOf = (key) => {
    const wrapper = backupEntries.find((item) => item.key === key)
    if (!wrapper) return null
    return wrapper.kind === 'blank' ? wrapper.entry.material : wrapper.material
  }
  const multiPickMaterialName = (key) => {
    const material = multiPickMaterialOf(key)
    return material?.name || material?.cleanedFileName || key
  }
  const toggleMultiPick = (key) => {
    setMultiPickKeys((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]))
  }
  const moveMultiPick = (index, offset) => {
    setMultiPickKeys((prev) => {
      const target = index + offset
      if (target < 0 || target >= prev.length) return prev
      const next = [...prev]
      const [moved] = next.splice(index, 1)
      next.splice(target, 0, moved)
      return next
    })
  }
  const selectedPlaceholderLabels = compactList([
    ...asArray(selectedBlankSource?.placeholderLabels),
    ...selectedCandidateMaterials.flatMap((item) => asArray(item?.placeholderLabels)),
  ], 10)
  // 目录标签统计：每个标签两个数——任务数（人要动手的次数）+ 目录数（这些决策盖住多少行）。
  // 口径与不变量见 technicalGapProgressCounts。
  const { tasks: tagTasks, tocs: tagTocs } = useMemo(() => technicalGapProgressCounts(items), [items])
  // 目录数五桶求和恒等于目录总行数，所以「已就绪目录数 / 总行数」必然能走到 100%。
  const coverageTotal = items.length
  const coverageSettled = tagTocs.material_ready
  // 剩余活儿 = 前四个未定案标签的任务数之和，不受骨架章数量影响。
  const remainingTasks = tagTasks.manual_supplement
    + tagTasks.needs_choice
    + tagTasks.template_ready
    + tagTasks.template_review
  // 正文填写汇总：不区分单条填还是一键填，也不区分本轮还是历史
  const bodyFillCounts = useMemo(() => technicalBodyFillCounts(items), [items])
  // 填写条平时不占位：待填数已由上方标签栏表达，这条只承载批量入口、运行进度和失败提示。
  // 失败必须能在未筛选时看见——失败的项停在「待填写」标签里，不提示就得靠人自己点进去发现。
  const showBodyFillBar = isCompleted && (
    tagFilter === 'template_ready'
    || tagFilter === 'template_review'
    || bodyFillRunning
    || Boolean(bodyFillCounts.failed)
  )
  const factConfirmed = factTable?.status === 'confirmed'
  const hasTechnicalGapPlan = data?.status === 'completed' && Boolean(data?.gapPlan || items.length)
  const generationRunning = generationStatus?.status === 'running'
  const generationCompleted = generationStatus?.status === 'completed'

  const updatePayload = (payload) => {
    const next = payload?.payload || payload
    const nextData = next?.gapPlan && !next?.status
      ? {
          ...(data || {}),
          ...next,
          status: data?.status || 'completed',
          recognizedAt: data?.recognizedAt,
          items: next?.items || next?.gapPlan?.items || data?.items || [],
          gapPlan: next.gapPlan,
        }
      : next
    setData(nextData)
    const nextFacts = nextData?.projectFactTable || next?.projectFactTable
    if (nextFacts?.schemaVersion) {
      setFactTable(nextFacts)
      setFactFields(asObjectArray(nextFacts.fields))
    }
    const nextItems = normalizeItems(nextData)
    setSelectedId((prev) => (nextItems.some((item) => item.id === prev) ? prev : nextItems[0]?.id || ''))
  }

  const runAction = async (key, fn, success) => {
    if (busyAction) return
    setBusyAction(key)
    try {
      const payload = await fn()
      if (payload) updatePayload(payload)
      if (success) showToast?.(success(payload))
      return payload
    } catch (e) {
      showToast?.(e?.message || '操作失败，请稍后重试', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  const handleRunDetection = () => runAction(
    'detect',
    () => technicalGapsAPI.runDetection(id),
    (payload) => payload?.message || '缺口识别完成',
  )

  const ensureFactTableReady = async () => {
    if (factTable?.status === 'confirmed') return true
    // 清单全局唯一且尚未上传时不出字段：维护入口在素材库 · 规则页，引导跳转
    if (!factSpecsMeta.imported && !factFields.length) {
      if (window.confirm('尚未上传事实表清单，系统无法提取要填写的字段。是否前往素材库 · 规则页上传？')) {
        navigate('/workspace/tech/materials/rules')
      }
      return false
    }
    if (busyAction) return false

    setBusyAction('facts-auto')
    try {
      const currentFields = factFields.length
        ? factFields
        : asObjectArray((await technicalGapsAPI.buildFacts(id))?.fields)
      const fieldsToSave = currentFields.filter((field) => String(field.label || field.value || '').trim())
      const payload = await technicalGapsAPI.saveFacts(id, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      return true
    } catch (e) {
      showToast?.(e?.message || '内部项目数据准备失败，请稍后重试', 'error')
      return false
    } finally {
      setBusyAction('')
    }
  }

  const handleFactFieldChange = (index, key, value) => {
    setFactFields((current) => current.map((field, idx) => {
      if (idx !== index) return field
      if (key === 'status') {
        return { ...field, status: value }
      }
      // 人改过的格子打 manualEdit 标记：重建时只有人工值跨轮保留，
      // AI 与规则抽的值一律重来，没有标记就会被当成 AI 值冲掉
      const sourceRefs = key === 'value' && !asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualEdit')
        ? [{ type: 'manualEdit', title: '人工修改', field: field.label || '' }, ...asObjectArray(field.sourceRefs)]
        : field.sourceRefs
      return {
        ...field,
        [key]: value,
        sourceRefs,
        // 三态：有值即可用，清空即回落待填写（「不适用」只走上面的 status 分支）
        status: String(key === 'value' ? value : field.value || '').trim() ? 'confirmed' : 'unextracted',
      }
    }))
  }

  const handleAddFactField = () => {
    const createdAt = new Date().toISOString()
    setFactFields((current) => [
      ...current,
      {
        id: `FACT-MANUAL-${Date.now()}`,
        key: '',
        label: '',
        category: '人工补充事实',
        value: '',
        unit: '',
        required: false,
        status: 'unextracted',
        confidence: 1,
        sourcePriority: 360,
        sourceRefs: [{ type: 'manualFact', title: '人工新增', field: '' }],
        alternatives: [],
        notes: 'S3 人工补充',
        updatedAt: createdAt,
        updatedBy: '当前用户',
      },
    ])
  }

  const handleConfirmFactTable = async () => {
    if (busyAction || !factFields.length) return null
    const hasUnnamedManualValue = factFields.some((field) => {
      const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
      return isManualField && String(field.value || '').trim() && !String(field.label || '').trim()
    })
    if (hasUnnamedManualValue) {
      showToast?.('请先填写人工新增字段的字段名称', 'error')
      return null
    }
    const fieldsToSave = factFields.filter((field) => String(field.label || field.value || '').trim())
    setBusyAction('facts-confirm')
    try {
      const payload = await technicalGapsAPI.saveFacts(id, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      showToast?.('项目事实表已保存并定稿，正文填写将使用这一版')
      return payload
    } catch (e) {
      showToast?.(e?.message || '项目事实表保存失败', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  const handleSearchMaterials = async () => {
    setMaterialLoading(true)
    try {
      const targetPaths = scopePaths.length ? scopePaths : ['']
      const payloads = await Promise.all(targetPaths.map((folderPath) => technicalMaterialsAPI.raw.files({
        folderPath,
        keyword: materialKeyword,
        bidType: materialScope?.bidType || data?.bidType || '技术标',
        turbineModel: projectTurbineModel?.model || '',
        pageSize: 12,
        recursive: true,
      })))
      const seen = new Set()
      const items = payloads.flatMap((payload) => (Array.isArray(payload?.items) ? payload.items : []))
        .filter((item) => {
          const key = item?.id || `${item?.folderPath || ''}/${item?.name || ''}`
          if (!key || seen.has(key)) return false
          seen.add(key)
          return true
        })
      setMaterialSearch({
        items,
        total: items.length,
      })
    } catch (e) {
      showToast?.(e?.message || '查询素材失败', 'error')
    } finally {
      setMaterialLoading(false)
    }
  }

  // 按空表/待填写 Word 逐个预览：优先复用弹窗里已有的对应选项，否则手工构造（预览走同一接口）。
  const handlePreviewBlankFor = (blank) => {
    const blankId = String(blank?.id || '').trim()
    if (!selected || !blankId) return
    const existing = selectedPreviewChoices.find((choice) => (
      (choice.kind === 'appendix' || choice.kind === 'blankMaterial')
        && String(choice.blankSource?.id || '') === blankId
    ))
    if (existing) {
      setPreviewChoiceKey(existing.key)
      setPreviewOpen(true)
      return
    }
    const choice = {
      key: `appendix:${blankId}:manual`,
      kind: 'appendix',
      label: '空副表',
      title: blank.title || blankId,
      subtitle: blank.sourceFile || blank.workspacePath || '招标文件解析产物',
      blankSource: { id: blankId, title: blank.title },
      itemId: selected?.id,
    }
    setManualPreviewChoice(choice)
    setPreviewChoiceKey(choice.key)
    setPreviewOpen(true)
  }

  const handlePreviewMaterial = (material) => {
    const materialId = String(material?.id || material?.materialId || '').trim()
    if (!selected || !materialId) return
    const existing = selectedPreviewChoices.find((choice) => (
      choice.kind === 'material' && String(choice.material?.id || choice.material?.materialId || '') === materialId
    ))
    if (existing) {
      setPreviewChoiceKey(existing.key)
      setPreviewOpen(true)
      return
    }
    const choice = {
      key: `material:${materialId}:manual`,
      kind: 'material',
      label: '参考素材',
      title: material.name || material.cleanedFileName || materialId,
      subtitle: material.folderPath || material.path || '',
      material: { ...material, id: materialId },
      itemId: selected.id,
    }
    setManualPreviewChoice(choice)
    setPreviewChoiceKey(choice.key)
    setPreviewOpen(true)
  }

  const handleSelectTocItem = (itemId) => {
    setSelectedId(itemId)
    resetPreviewChoice()
    setPreviewOpen(false)
    setAiFillModalTask(null)
    setMaterialSwapOpen(false)
    setMultiPickOpen(false)
    setMultiPickKeys([])
  }

  const toggleTocKeyExpanded = (key) => {
    if (!key) return
    setExpandedTocKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 目录节点「确认」/撤销：人工背书系统匹配（30~98 档），撤销后回落分数档。
  const handleConfirmGapReady = (item, confirmed) => runAction(
    `confirm-ready:${item.id}`,
    () => technicalGapsAPI.confirmReady(id, item.id, { confirmed, operator: '当前用户' }),
    (result) => result?.message || (confirmed ? '已确认当前匹配' : '已撤销确认'),
  )

  // 目录节点「忽略」/取消（产品裁决 2026-08-04）：本级仅保留标题，子级释放各自匹配；
  // 忽略时自动展开子级，让下一层立即可处理。
  const handleSetTitleOnly = (item, enabled) => {
    if (enabled && item?.id) {
      setExpandedTocKeys((prev) => new Set(prev).add(String(item.id)))
    }
    return runAction(
      `title-only:${item.id}`,
      () => technicalGapsAPI.setTitleOnly(id, item.id, { enabled, operator: '当前用户' }),
      (result) => result?.message || (enabled ? '本级已忽略，仅保留标题' : '已取消忽略'),
    )
  }

  // 「复核通过」（产品裁决 2026-08-04 行为①）：确认全部 AI 填写产物，本条收口为已就绪素材。
  const handleReviewPassAiFill = (item) => {
    const artifact = asObjectArray(item?.resolvedArtifacts)
      .filter((entry) => currentResolvedArtifact(entry) && String(entry?.source || '') === 'ai_fill')
      .pop()
    if (!artifact?.id) return null
    return runAction(
      `review-pass:${item.id}`,
      () => technicalGapsAPI.confirmAiFillArtifact(id, item.id, artifact.id, { operator: '当前用户' }),
      (result) => result?.message || '复核通过，本条已定案',
    )
  }

  // 待审核队列：一键填完是一批产物，逐条点目录再点预览太慢，对比弹窗里直接连着审。
  const reviewQueue = useMemo(
    () => items.filter((item) => technicalGapTagOf(item, items) === 'template_review'),
    [items],
  )
  const reviewIndex = reviewQueue.findIndex((item) => item.id === effectiveSelectedId)

  const handleReviewStep = (step) => {
    if (reviewQueue.length < 2) return
    const from = reviewIndex >= 0 ? reviewIndex : 0
    const next = reviewQueue[(from + step + reviewQueue.length) % reviewQueue.length]
    if (!next) return
    setSelectedId(next.id)
    const artifact = latestResolvedArtifact(next)
    setPreviewChoiceKey(artifact?.id ? `artifact:${String(artifact.id)}` : '')
    setPreviewSession(null)
    setPreviewError('')
    setManualPreviewChoice(null)
  }

  // 批量复核通过：放行与否是人的决定，带未填字段的产物同样可批量定案（产品裁决 2026-08-09）。
  // 黄标条数仍在按钮 title 里点出来，让人知道自己在放过什么；口径与逐条徽标一致
  // （technicalGapQualityFlag：needs_review 或有未填字段）。
  const batchReviewables = reviewQueue
  const flaggedReviewCount = useMemo(
    () => reviewQueue.filter((item) => technicalGapQualityFlag(item)).length,
    [reviewQueue],
  )

  const handleBatchReviewPass = async () => {
    if (busyAction || !batchReviewables.length) return
    let passed = 0
    for (const item of batchReviewables) {
      const artifact = asObjectArray(item?.resolvedArtifacts)
        .filter((entry) => currentResolvedArtifact(entry) && String(entry?.source || '') === 'ai_fill')
        .pop()
      if (!artifact?.id) continue
      try {
        await technicalGapsAPI.confirmAiFillArtifact(id, item.id, artifact.id, { operator: '当前用户' })
        passed += 1
      } catch {
        // 单条失败不中断整批，最终按实际通过数提示
      }
    }
    await loadData({ silent: true })
    showToast?.(`已复核通过 ${passed}/${batchReviewables.length} 条`)
  }

  // 弹窗内复核通过：定案后当前项离开待审核队列，原位置就是下一条，直接顶上继续审；
  // 审完最后一条时关掉弹窗。
  const handleReviewPassInModal = async () => {
    if (!selected) return
    const index = reviewIndex >= 0 ? reviewIndex : 0
    const result = await handleReviewPassAiFill(selected)
    if (!result) return
    const rest = reviewQueue.filter((item) => item.id !== selected.id)
    const next = rest[Math.min(index, rest.length - 1)]
    if (!next) {
      setPreviewOpen(false)
      return
    }
    setSelectedId(next.id)
    const artifact = latestResolvedArtifact(next)
    setPreviewChoiceKey(artifact?.id ? `artifact:${String(artifact.id)}` : '')
    setPreviewSession(null)
    setPreviewError('')
    setManualPreviewChoice(null)
  }

  // 「重新AI填写」：复核不通过时原地重填（同任务产物替换）。
  const handleRefillAiFill = (item) => {
    const task = asObjectArray(item?.fillTasks)[0] || null
    if (task) startAiFill(task)
  }

  const handleSelectMaterial = async (material) => {
    const materialId = String(material?.id || material?.materialId || '').trim()
    if (!selected || !materialId) return null
    return runAction(
      `select-material:${selected.id}:${materialId}`,
      () => technicalGapsAPI.selectMaterial(id, selected.id, {
        materials: [{ ...material, id: materialId, materialId }],
        operator: '当前用户',
      }),
      (result) => result?.artifact?.fileName
        ? `已选用素材：${result.artifact.fileName}`
        : '已选用素材',
    )
  }

  // 一次提交多份：后端按数组顺序生成产物，顺序即正文里的铺开顺序。
  const handleSelectMaterials = async (materials) => {
    const payload = materials
      .map((material) => {
        const materialId = String(material?.id || material?.materialId || '').trim()
        return materialId ? { ...material, id: materialId, materialId } : null
      })
      .filter(Boolean)
    if (!selected || !payload.length) return null
    return runAction(
      `select-material:${selected.id}:multi`,
      () => technicalGapsAPI.selectMaterial(id, selected.id, {
        materials: payload,
        operator: '当前用户',
      }),
      () => `已按顺序选用 ${payload.length} 份素材`,
    )
  }

  // 上传即选用：文件以 data URL 提交到 gaps/{gapId}/upload，后端存为人工产物
  //（source=manual_upload，s7Ready），终审直接判就绪。后端按 ZIP 魔数校验，仅支持 .docx。
  const handleUploadGapMaterial = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !selected) return null
    if (!file.name.toLowerCase().endsWith('.docx')) {
      showToast?.('目前仅支持上传 .docx 素材，其他格式请先转换后再上传', 'error')
      return null
    }
    let dataUrl = ''
    try {
      dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result || ''))
        reader.onerror = () => reject(new Error('读取文件失败，请重试'))
        reader.readAsDataURL(file)
      })
    } catch (e) {
      showToast?.(e?.message || '读取文件失败，请重试', 'error')
      return null
    }
    if (!dataUrl) return null
    return runAction(
      `upload:${selected.id}`,
      () => technicalGapsAPI.upload(id, selected.id, {
        files: [{ name: file.name, data: dataUrl }],
        operator: '当前用户',
      }),
      (result) => (result?.artifact?.fileName
        ? `已上传并选用：${result.artifact.fileName}`
        : '已上传并选用素材'),
    )
  }

  // AI 填写弹窗内的补料上传：走素材库 raw upload 入「项目素材」目录（区别于目录项底部
  // 上传即定案的 gaps/{gid}/upload），拿到真实素材 id 后注入弹窗候选列表并默认勾选，
  // AI 填写链路（referenceMaterials）零改动——后端按 material_id 从 MinIO 下载，
  // 清洗未完成的素材回退原件也能用于填写。
  const handleAiFillUpload = async (files) => {
    const task = aiFillModalTask
    const fileList = Array.from(files || [])
    if (!task || !fileList.length) return
    const projectScope = readableScopes.find((scope) => String(scope?.key || '') === 'project')
    const targetPath = String(projectScope?.path || '').trim()
    if (!targetPath) {
      showToast?.('未找到项目素材目录，无法上传', 'error')
      return
    }
    const identity = materialScope?.identity || {}
    const buildForm = (onConflict) => {
      const form = new FormData()
      form.append('targetPath', targetPath)
      form.append('projectId', id)
      form.append('projectCode', String(identity.projectCode || ''))
      form.append('projectName', String(identity.projectName || ''))
      form.append('bidType', materialScope?.bidType || '技术标')
      form.append('materialTier', '')
      form.append('businessMaterialKind', 'other')
      form.append('customerId', '')
      form.append('customerName', '')
      if (onConflict) form.append('onConflict', onConflict)
      fileList.forEach((file) => {
        form.append('files', file, file.name)
        form.append('relativePaths', '')
      })
      return form
    }
    setAiFillUploadBusy(true)
    try {
      let result
      try {
        result = await technicalMaterialsAPI.raw.upload(buildForm(''))
      } catch (e) {
        // 同名冲突：归档旧版本后覆盖重试一次（对齐素材库页的 onConflict 语义）
        if (e?.status === 409 && e?.code === 'MATERIAL_CONFLICT') {
          result = await technicalMaterialsAPI.raw.upload(buildForm('replace'))
        } else {
          throw e
        }
      }
      const items = asObjectArray(result?.items)
      if (!items.length) {
        showToast?.('上传完成，但未拿到素材记录，请到素材库确认', 'error')
        return
      }
      setAiFillUploadedCandidates((current) => {
        const existing = new Set(current.map((item) => String(item?.id || item?.materialId || '').trim()))
        return [...current, ...items.filter((item) => !existing.has(String(item?.id || item?.materialId || '').trim()))]
      })
      const key = aiFillSelectionKeyFor(task)
      const uploadedIds = items.map((item) => String(item?.id || item?.materialId || '').trim()).filter(Boolean)
      if (key && uploadedIds.length) {
        setAiFillReferenceSelections((current) => {
          const active = Object.prototype.hasOwnProperty.call(current, key)
            ? current[key]
            : defaultAiFillReferenceMaterialIds(selected, [], task)
          return { ...current, [key]: uniqueStrings([...active, ...uploadedIds]) }
        })
      }
      showToast?.(`已上传 ${items.length} 份素材并加入本次 AI 填写参考`)
    } catch (e) {
      showToast?.(e?.message || '上传失败，请稍后重试', 'error')
    } finally {
      setAiFillUploadBusy(false)
    }
  }

  // task 缺省为首个填写任务；多空表目录项（如 附表F.5 双任务）由各自素材卡传入对应任务。
  const handleAiFill = async (task = selectedFillTask) => {
    if (!selected || !task) return null
    if (bodyFillRunning) {
      showToast?.('一键填写进行中，暂不可单条填写', 'error')
      return null
    }
    if (!factConfirmed && !(await ensureFactTableReady())) {
      return null
    }
    const referenceIds = aiFillReferenceIdsFor(task)
    const referenceMaterials = selectedReferenceCandidates.filter((material) => (
      referenceIds.includes(String(material?.id || material?.materialId || '').trim())
    ))
    const payload = await runAction(
      aiFillActionKey,
      () => technicalGapsAPI.aiFill(id, selected.id, {
        fillTaskId: task.id,
        referenceMaterialIds: referenceIds,
        referenceMaterials,
        parseFieldIds: defaultAiFillParseFieldIds(selected, task),
        operator: '当前用户',
      }),
      (result) => (result?.artifact?.fileName ? `AI填写完成：${result.artifact.fileName}` : 'AI填写完成'),
    )
    if (payload) {
      resetPreviewChoice()
      // 产品裁决 2026-08-04（行为①，推翻 2026-07-17 自动确认）：AI 填写完成后停在
      // 「待复核模板」，由人点「复核通过」定案；这里只弹出结果预览方便当场检查。
      const artifactId = String(payload?.artifact?.id || '').trim()
      if (artifactId) {
        // 填完这条就从「待填写」转入「待审核」。当前筛选容不下它时要跟着切过去并保持选中，
        // 否则它被挤出列表、选中项顺延到别的目录项，弹出的就不是刚填这条的对比了。
        const filledId = String(payload?.item?.id || selected?.id || '').trim()
        if (tagFilter && tagFilter !== 'template_review') setTagFilter('template_review')
        if (filledId) setSelectedId(filledId)
        setPreviewChoiceKey(`artifact:${artifactId}`)
        setPreviewOpen(true)
      }
    }
    return payload
  }

  // AI 填写入口：正文按事实表清单精确定位字段（占位符原文 → 字段），参考素材既不参与
  // 定位也不提供取值，点了直接跑；附表仍要先选参考素材，保持原有弹窗。
  const startAiFill = (task) => {
    if (!task) return
    // 一键填写进行中禁止单条填写（后端同样返回 409，这里提前拦截并提示原因）
    if (bodyFillRunning) {
      showToast?.('一键填写进行中，暂不可单条填写', 'error')
      return
    }
    if (String(task?.skill || '') === TECHNICAL_WORD_FILL_SKILL) {
      handleAiFill(task)
      return
    }
    setAiFillModalTask(task)
  }

  const handleToggleAiFillReference = (task, materialId) => {
    const key = aiFillSelectionKeyFor(task)
    if (!key || !materialId || busyAction) return
    const fallback = defaultAiFillReferenceMaterialIds(selected, [], task)
    setAiFillReferenceSelections((current) => {
      const active = Object.prototype.hasOwnProperty.call(current, key) ? current[key] : fallback
      const next = active.includes(materialId)
        ? active.filter((id) => id !== materialId)
        : [...active, materialId]
      return { ...current, [key]: uniqueStrings(next) }
    })
  }

  // 合并清单条目预览：优先该产物的 OnlyOffice 会话（AI 填写/上传产物），
  // 选用素材类产物无会话时回退到素材本体预览。
  const handlePreviewMergeArtifact = (artifact) => {
    const key = `artifact:${String(artifact?.id || '').trim()}`
    const choice = selectedPreviewChoices.find((item) => item.kind === 'artifact' && item.key === key)
    if (choice) {
      setPreviewChoiceKey(choice.key)
      setPreviewOpen(true)
      return
    }
    const materialId = String(artifact?.materialId || '').trim()
    if (materialId) handlePreviewMaterial({ id: materialId, name: artifact?.fileName || materialId })
  }

  useEffect(() => {
    if (!generationRunning) return undefined
    return subscribeTechnicalGenerationStatus({
      fetchStatus: () => technicalGenerateAPI.status(id),
      onStatus: setGenerationStatus,
    })
  }, [generationRunning, id])

  // AI 匹配填充轮询：任务在后台 worker 执行，这里只负责取进度；终态时把结果一次性落到界面。
  // 完成通知按 jobId+finishedAt 去重，避免收尾那一拍重复弹 toast。
  const fetchFactCurateStatus = useCallback(() => technicalGapsAPI.curateFactsStatus(id), [id])
  const handleFactCurateTerminal = useCallback(async (payload, state) => {
    const status = String(state?.status || '')
    if (payload?.projectFactTable?.schemaVersion) {
      setFactTable(payload.projectFactTable)
      setFactFields(asObjectArray(payload.projectFactTable.fields))
      setData((current) =>
        current ? { ...current, projectFactTable: payload.projectFactTable } : current,
      )
    }
    setFactCurateReport(payload?.curateReport || null)
    showToast?.(
      payload?.message || (status === 'succeeded' ? '匹配填充完成' : '匹配填充失败'),
      status === 'succeeded' ? undefined : 'error',
    )
  }, [showToast])
  useBackgroundTaskPolling({
    running: factCurateRunning,
    fetchStatus: fetchFactCurateStatus,
    extractState: factCurateStateOf,
    terminalStatuses: FACT_CURATE_TERMINAL_STATUSES,
    onState: setFactCurateState,
    onTerminal: handleFactCurateTerminal,
  })

  // 一键填写（正文+附表）轮询：与 AI 匹配填充同一套范式，终态按 jobId+finishedAt 去重通知，
  // 完成后拉一次最新数据把产物、标签、审核队列一起刷新。
  const fetchBodyFillStatus = useCallback(() => technicalGapsAPI.bodyFillStatus(id), [id])
  const handleBodyFillTerminal = useCallback(async (payload, state) => {
    const status = String(state?.status || '')
    await loadData({ silent: true })
    showToast?.(state?.message || '正文填写完成', status === 'failed' ? 'error' : undefined)
  }, [loadData, showToast])
  const { resetNotified: resetBodyFillNotified } = useBackgroundTaskPolling({
    running: bodyFillRunning,
    fetchStatus: fetchBodyFillStatus,
    extractState: bodyFillStateOf,
    terminalStatuses: BODY_FILL_TERMINAL_STATUSES,
    onState: setBodyFillState,
    onTerminal: handleBodyFillTerminal,
  })

  // 一键填写：范围取当前标签筛选后的可见目录项（没筛选就是全部待填写正文/附表）。
  // 提交后立即返回，不再逐条弹预览；产物统一停在「待审核」，由人集中复核。
  const handleBodyFillAll = async () => {
    if (busyAction || bodyFillRunning) return
    if (!factConfirmed && !(await ensureFactTableReady())) return
    const gapIds = tagFilter ? filteredItems.map((item) => String(item?.id || '')).filter(Boolean) : []
    // 不走 runAction：提交接口只返回任务状态（没有 gapPlan），而 runAction 会把返回值
    // 直接灌进页面 data，整页会被替换成一个只有 bodyFillState 的对象，退回空状态页。
    setBusyAction('body-fill')
    try {
      const payload = await technicalGapsAPI.bodyFill(id, { gapIds, operator: '当前用户' })
      resetBodyFillNotified()
      setBodyFillState(payload?.bodyFillState || null)
      showToast?.(`已提交 ${payload?.total || 0} 条正文填写，可离开页面`)
    } catch (e) {
      showToast?.(e?.message || '提交失败，请稍后重试', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const runTechnicalAssembly = async () => {
    if (busyAction) return
    if (!hasTechnicalGapPlan) {
      showToast?.('素材匹配完成后可生成技术标正文。', 'error')
      return
    }
    setBusyAction('technical-generate')
    setGenerationModalDismissed(false)
    setGenerationModalOpen(true)
    try {
      const payload = await technicalGenerateAPI.run(id)
      setGenerationStatus(payload)
      showToast?.(payload?.message || '已开始生成技术标正文。')
    } catch (e) {
      setGenerationModalOpen(false)
      showToast?.(e?.message || '生成技术标正文失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const advanceToTechnicalEditor = async () => {
    if (busyAction) return
    if (!generationCompleted) {
      showToast?.('请先完成技术标正文生成，再进入共创导出。', 'error')
      return
    }
    setBusyAction('advance-technical-editor')
    try {
      await technicalStagesAPI.update(id, 4, { status: 'completed', allowUnconfirmedTechnicalGap: true })
      showToast?.('已进入共创导出。')
      navigate(projectRoute(id, '/editor', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入共创导出失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const handleSaveMaterialPaths = async (paths) => {
    if (busyAction) return false
    setBusyAction('facts-material-sources')
    let pathsSaved = false
    try {
      const payload = await technicalGapsAPI.saveMaterialSources(id, { paths })
      setFactMaterialPaths(Array.isArray(payload?.paths) ? payload.paths : [])
      pathsSaved = true
      const table = await technicalGapsAPI.buildFacts(id)
      setFactTable(table)
      setFactFields(asObjectArray(table?.fields))
      setFactCurateReport(null)
      setData((current) => (current ? { ...current, projectFactTable: table } : current))
      showToast?.('参考范围已保存，事实表已自动更新')
      return true
    } catch (e) {
      showToast?.(
        pathsSaved
          ? `参考范围已保存，但事实表自动更新失败：${e?.message || '请重试保存范围'}`
          : (e?.message || '参考范围保存失败'),
        'error',
      )
      return false
    } finally {
      setBusyAction('')
    }
  }

  // 刷新并 AI 填充：保存当前编辑 → 按最新素材范围刷新事实表 → 事实表维护 Skill 按素材
  // 给字段补值/修正/口径建议，结果落为待人工确认
  const handleCurateFacts = async () => {
    if (busyAction) return
    const hasUnnamedManualValue = factFields.some((field) => {
      const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
      return isManualField && String(field.value || '').trim() && !String(field.label || '').trim()
    })
    if (hasUnnamedManualValue) {
      showToast?.('请先填写人工新增字段的字段名称', 'error')
      return
    }
    setBusyAction('facts-curate')
    try {
      const fieldsToSave = factFields.filter((field) => String(field.label || field.value || '').trim())
      const savedTable = await technicalGapsAPI.saveFacts(id, {
        fields: fieldsToSave,
        confirm: false,
        operator: '当前用户',
      })
      setFactTable(savedTable)
      setFactFields(asObjectArray(savedTable?.fields))
      setData((current) => (current ? { ...current, projectFactTable: savedTable } : current))
      // 先按最新素材范围刷新事实表（重跑规则抽取，并把无值的终态字段复位为未提取），
      // 再交给 AI 补抽——否则上一轮标成「缺少来源」的字段不会进 AI 的工作清单。
      const rebuiltTable = await technicalGapsAPI.buildFacts(id)
      setFactTable(rebuiltTable)
      setFactFields(asObjectArray(rebuiltTable?.fields))
      setData((current) => (current ? { ...current, projectFactTable: rebuiltTable } : current))
      // 提交后台任务后立即返回，执行进度由轮询接管；此后关弹窗、刷新页面都不影响
      const payload = await technicalGapsAPI.curateFacts(id, {})
      setFactCurateReport(null)
      setFactCurateState(payload?.factCurateState || null)
      showToast?.(payload?.message || '已提交 AI 匹配填充任务')
    } catch (e) {
      showToast?.(e?.message || '匹配填充失败，请稍后重试', 'error')
    } finally {
      setBusyAction('')
    }
  }

  if (loading) return <PageLoading title="正在加载素材匹配..." />
  if (error) return <PageError title="素材匹配加载失败" description={error} onRetry={loadData} />

  // 目录前置守卫（R11-B07-03）：目录未生成/未确认/为空时不进入素材匹配工作区，
  // 给出去目录页和返回项目的出口；outlineGuard 拉取失败（null）不阻断，由后端 run 接口兜底。
  const outlineBlocked = outlineGuard
    ? String(outlineGuard?.reviewStatus || '') !== 'confirmed' ||
      Number(outlineGuard?.summary?.totalNodeCount || 0) < 1
    : false

  if (outlineBlocked) {
    return (
      <div className="business-ui-shell flex flex-col gap-6">
        <TechnicalProjectStageProgress projectId={id} showToast={showToast} />
        <DataCard className="flex flex-col items-center px-6 py-12 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-surface-container-high">
            <span className="material-symbols-outlined text-3xl text-primary">account_tree</span>
          </div>
          <h4 className="mb-2 font-headline text-lg font-bold text-on-surface">请先生成并确认投标目录</h4>
          <p className="max-w-xl text-sm leading-relaxed text-on-surface-variant">
            素材匹配基于已确认的投标目录运行。当前项目尚未生成目录、目录未确认或目录为空，请先完成目录生成与确认。
          </p>
          <div className="mt-5 flex items-center gap-2">
            <Button
              type="button"
              variant="quiet"
              onClick={() => navigate(projectRoute(id, '', workspaceSlug))}
            >
              返回项目
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => navigate(projectRoute(id, '/outline', workspaceSlug))}
            >
              前往生成目录
            </Button>
          </div>
        </DataCard>
      </div>
    )
  }

  return (
    <div className="business-ui-shell flex flex-col gap-4 sm:gap-6">
      <PageHeader
        actionsClassName="w-full sm:w-auto"
        actions={(
          <Toolbar className="w-full sm:w-auto">
            {/* 规则维护入口已迁至素材库 · 规则页：附表规则按客户维护，保留一个跳转入口，
                样式与工具栏其他按钮（项目事实表等）一致。事实表清单入口已移除。
                「项目事实表」按钮保留——它打开的是字段维护弹窗，不是上传入口。 */}
            <Button
              type="button"
              onClick={() => navigate('/workspace/tech/materials/rules')}
              title={sourceMatrixMeta.imported ? `附表填写规则：${sourceMatrixMeta.fileName || '已维护'}（按客户${sourceMatrixMeta.customerName ? `「${sourceMatrixMeta.customerName}」` : ''}维护，到素材库 · 规则页维护）` : '该客户尚未维护附表填写规则，到素材库 · 规则页维护'}
              size="stage"
              variant="quiet"
              icon="open_in_new"
            >
              附表规则
            </Button>
            <Button
              type="button"
              onClick={() => setFactModalOpen(true)}
              disabled={Boolean(busyAction) || data?.status !== 'completed'}
              title={factSpecsMeta.imported ? `事实表清单：${factSpecsMeta.fileName}` : '尚未上传事实表清单，请先到素材库 · 规则页上传'}
              size="stage"
              variant={factConfirmed ? 'secondary' : 'quiet'}
            >
              {factConfirmed ? '项目事实表已确认' : '项目事实表'}
            </Button>
            {!generationCompleted ? (
              <Button
                type="button"
                onClick={runTechnicalAssembly}
                disabled={Boolean(busyAction) || !hasTechnicalGapPlan || generationRunning}
                title={!hasTechnicalGapPlan ? '素材匹配完成后可生成正文' : '允许带未确认项生成正文，生成结果会保留复核提示'}
                size="stage"
                variant="primary"
              >
                {generationRunning ? '生成中...' : '生成技术标正文'}
              </Button>
            ) : null}
            <Button
              type="button"
              onClick={advanceToTechnicalEditor}
              disabled={Boolean(busyAction) || !generationCompleted}
              size="stage"
              variant="success"
            >
              {busyAction === 'advance-technical-editor' ? '进入中...' : '进入共创导出'}
            </Button>
          </Toolbar>
        )}
      />

      {/* 单条统计栏：目录节点总数 + 五个工作态标签明细（v6，产品裁决 2026-08-04）。
          排列即流水线顺序：待补充 → 待确认 → 待填写 → 待审核 → 已就绪。 */}
      {isCompleted ? (
        <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex min-h-7 flex-wrap items-center gap-3">
            <div className="flex shrink-0 items-center gap-2 border-r border-surface-container-high pr-3">
              <span className="text-xs font-semibold text-on-surface-variant">剩余任务</span>
              <span className="text-lg font-headline font-bold tabular-nums text-primary">{remainingTasks}</span>
            </div>
            {/* 已就绪目录数 / 目录总行数：五桶目录数求和恒等于总行数，干完必然是 100% */}
            <div className="flex shrink-0 items-center gap-2 border-r border-surface-container-high pr-3">
              <span className="text-xs font-semibold text-on-surface-variant">目录覆盖</span>
              <span className="text-lg font-headline font-bold tabular-nums text-primary">{coverageSettled}</span>
              <span className="text-xs tabular-nums text-outline">/ {coverageTotal}</span>
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-container-high">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-300"
                  style={{ width: `${coverageTotal ? Math.round((coverageSettled / coverageTotal) * 100) : 0}%` }}
                />
              </div>
            </div>
            {/* 每个标签两个数：任务数（人要动手几次）+ 括号里的目录数（盖住几行目录）。
                父章配一份整章素材＝1 个任务盖整棵子树，两个数就此拉开。 */}
            <div className="grid min-w-0 flex-1 grid-cols-3 gap-1.5 text-center sm:grid-cols-5">
              {['manual_supplement', 'needs_choice', 'template_ready', 'template_review', 'material_ready'].map((key) => {
                const active = tagFilter === key
                const label = TECHNICAL_GAP_TAG_CONFIG[key].label
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTagFilter(active ? '' : key)}
                    title={active
                      ? '再点一次取消筛选'
                      : `只看「${label}」：${tagTasks[key] || 0} 个任务，覆盖 ${tagTocs[key] || 0} 行目录`}
                    className={`flex min-h-7 items-center justify-center gap-1 rounded-md px-2 py-0.5 transition-colors ${
                      active ? 'bg-primary-fixed ring-1 ring-primary' : 'bg-surface-container-low hover:bg-surface-container-high'
                    }`}
                  >
                    <span className="text-[11px] text-on-surface-variant">{label}</span>
                    <span className="text-sm font-headline font-bold tabular-nums text-primary">{tagTasks[key] || 0}</span>
                    <span className="text-[11px] tabular-nums text-outline">（{tagTocs[key] || 0}）</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      ) : null}

      {/* 一键填写条（正文 + 附表）：批量入口 + 运行进度 + 失败提示，按 showBodyFillBar 出现。
          任务跑在后台 worker，关页面不影响。 */}
      {showBodyFillBar ? (
        <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex min-h-8 flex-wrap items-center gap-3">
            <span
              className="shrink-0 text-xs font-semibold text-on-surface-variant"
              title={`待填写 ${bodyFillCounts.pending} 个：正文 ${bodyFillCounts.pendingBody} / 附表 ${bodyFillCounts.pendingAppendix}`}
            >
              正文/附表填写
            </span>
            {/* 待填写/已填写数字已由上方标签栏统一表达，此处不再重复；
                失败数标签栏看不出来（失败的项停在「待填写」），有才显示。 */}
            {bodyFillCounts.failed ? (
              <span className="shrink-0 border-r border-surface-container-high pr-3 text-xs text-error">
                失败 <b className="text-sm font-headline tabular-nums">{bodyFillCounts.failed}</b>
              </span>
            ) : null}
            {bodyFillRunning ? (
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <div className="h-1.5 min-w-24 flex-1 overflow-hidden rounded-full bg-surface-container-high">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-300"
                    style={{ width: `${bodyFillTotal ? Math.round((bodyFillDone / bodyFillTotal) * 100) : 0}%` }}
                  />
                </div>
                <span className="shrink-0 text-[11px] tabular-nums text-on-surface-variant">
                  {bodyFillDone}/{bodyFillTotal}
                </span>
                <span className="min-w-0 truncate text-[11px] text-outline" title={String(bodyFillState?.current || '')}>
                  {bodyFillState?.current || ''}
                </span>
              </div>
            ) : (
              <span className="min-w-0 flex-1 truncate text-[11px] text-outline" title={String(bodyFillState?.message || '')}>
                {bodyFillState?.message || ''}
              </span>
            )}
            {/* 一键入口按当前标签切换：点开「待填写」出填写、点开「待审核」出复核，同一个位置同一套样式。
                任务执行中在任何筛选下都要能看到进度，所以运行态按钮不受此限制。 */}
            {tagFilter === 'template_ready' || bodyFillRunning ? (
              <Button
                type="button"
                onClick={handleBodyFillAll}
                disabled={Boolean(busyAction) || bodyFillRunning || !bodyFillCounts.pending}
                title={
                  bodyFillRunning
                    ? '一键填写任务执行中'
                    : `填写当前筛选出的 ${filteredItems.length} 个目录项（含正文与附表），产物统一进入待审核`
                }
                size="sm"
                variant="primary"
              >
                {bodyFillRunning
                  ? `填写中 ${bodyFillDone}/${bodyFillTotal}`
                  : `一键填写${bodyFillCounts.pending ? `（${bodyFillCounts.pending}）` : ''}`}
              </Button>
            ) : tagFilter === 'template_review' && reviewQueue.length ? (
              <Button
                type="button"
                onClick={handleBatchReviewPass}
                disabled={Boolean(busyAction) || !batchReviewables.length}
                title={
                  flaggedReviewCount
                    ? `复核通过 ${batchReviewables.length} 条，其中 ${flaggedReviewCount} 条质量待复核（未填字段或验收未达标）`
                    : `复核通过 ${batchReviewables.length} 条，质量均已达标`
                }
                size="sm"
                variant="primary"
              >
                批量复核通过（{batchReviewables.length}）
              </Button>
            ) : bodyFillCounts.failed ? (
              // 走到这里只剩「有失败但没筛选」一种：失败的项停在「待填写」里，给出去处。
              <span className="shrink-0 text-[11px] text-outline">点开「待填写」标签重试失败项</span>
            ) : null}
          </div>
        </div>
      ) : null}

      <DataCard className="!p-0 overflow-hidden">
        <div className="business-section-head flex items-center border-b border-surface-container-high px-4 py-3">
          <h3 className="text-base font-headline font-bold text-on-surface">技术目录</h3>
        </div>

        {!isCompleted ? (
          <div className="h-[340px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">fact_check</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">等待生成缺口计划</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              点击“识别缺口”后会按已确认目录、限定素材库、技术标 Wiki、投标机型和解析空副表生成第一步识别结果。
            </p>
            <Button
              type="button"
              onClick={handleRunDetection}
              disabled={Boolean(busyAction)}
              className="mt-5"
              variant="primary"
            >
              {busyAction === 'detect' ? '识别中...' : '识别缺口'}
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 p-3 xl:h-[clamp(34rem,calc(100dvh-15rem),56rem)] xl:min-h-[32rem] xl:overflow-hidden xl:grid-cols-[460px_minmax(0,1fr)] 2xl:grid-cols-[520px_minmax(0,1fr)]">
            <div className="flex min-h-0 flex-col overflow-hidden">
              <div className="h-12 shrink-0 px-2 py-3">
                <div className="flex items-center gap-2 text-xs font-semibold text-on-surface">
                  <span>目录项 · {filteredItems.length}/{items.length}</span>
                  {tagFilter ? (
                    <button
                      type="button"
                      onClick={() => setTagFilter('')}
                      title="取消筛选"
                      className="inline-flex items-center gap-0.5 rounded bg-surface-container-high px-1.5 py-0.5 text-[11px] font-semibold text-on-surface-variant hover:bg-surface-dim"
                    >
                      {TECHNICAL_GAP_TAG_CONFIG[tagFilter]?.label}
                      <span className="material-symbols-outlined text-[13px]">close</span>
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="max-h-[44dvh] min-h-0 flex-1 overflow-auto xl:max-h-none">
                <div>
                  {/* 可折叠目录树（产品裁决 2026-08-04）：默认只展开一级章，第一波先定章级；
                      被冻结的子级灰显、可点开查看、操作禁用；列表行纯展示，
                      忽略操作在右侧详情面板（2026-08-04 v6 调整）。 */}
                  {treeRows.map(({ item, key, depth, hasChildren, expanded }) => {
                    const active = effectiveSelectedId === item.id
                    const tag = technicalGapTagOf(item, items)
                    const frozen = tag === 'parent_covered'
                    const ignored = tag === 'title_only'
                    // 上一轮填写失败：标红边框 + hover 出原因，不新增标签（标签已有 7 个）
                    const fillError = technicalGapFillError(item)
                    return (
                      <div
                        key={item.id}
                        onClick={() => handleSelectTocItem(item.id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') handleSelectTocItem(item.id)
                        }}
                        title={fillError ? `上次填写失败：${fillError}` : undefined}
                        style={depth ? { marginLeft: `${depth * 16}px` } : undefined}
                        className={`business-toc-item mb-2 block h-auto cursor-pointer rounded-md border px-3 py-3 text-left transition-colors ${
                          active
                            ? 'border-primary bg-primary-fixed shadow-sm'
                            : fillError
                              ? 'border-error bg-error-container/20 hover:bg-error-container/30'
                              : frozen || ignored
                                ? 'border-surface-container-high bg-surface-container-low opacity-60 hover:opacity-80'
                                : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'
                        }`}
                        data-active={active ? 'true' : 'false'}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex min-w-0 items-start gap-1">
                            {hasChildren && !tagFilter ? (
                              <button
                                type="button"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  toggleTocKeyExpanded(key)
                                }}
                                aria-label={expanded ? `收起 ${item.number || item.title}` : `展开 ${item.number || item.title}`}
                                className="mt-0.5 -ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline transition-transform hover:bg-surface-container-high hover:text-on-surface"
                              >
                                <span className={`material-symbols-outlined text-[16px] transition-transform ${expanded ? 'rotate-90' : ''}`}>chevron_right</span>
                              </button>
                            ) : (
                              <span className="w-4 shrink-0" />
                            )}
                            <div className="min-w-0">
                              <div className={`text-[11px] font-medium ${frozen || ignored ? 'text-outline/70' : 'text-outline'}`}>{item.number || item.section || '-'}</div>
                              <div className={`mt-1 line-clamp-2 text-sm font-semibold leading-snug ${frozen || ignored ? 'text-on-surface-variant' : 'text-on-surface'}`}>{item.title}</div>
                            </div>
                          </div>
                          <div className="flex shrink-0 flex-col items-end gap-1">
                            <TechnicalTocActionBadge item={item} items={items} />
                            <TechnicalGapQualityBadge item={item} />
                          </div>
                        </div>
                      </div>
                    )
                  })}
                  {!treeRows.length ? (
                    <div className="px-5 py-10 text-center text-sm text-outline">
                      当前筛选下暂无目录项。
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="min-h-0 overflow-hidden rounded-md border border-surface-container-high bg-surface-container-lowest">
              {selected ? (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="shrink-0 border-b border-surface-container-high bg-surface-container-lowest px-5 py-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-outline">{selected.number || selected.section || '-'}</span>
                        <TechnicalTocActionBadge item={selected} items={items} />
                        {/* 待审核项在标题旁直接亮出质检结论（验收通过/待复核，复盘口径），
                            复用 resultSummaryForItem，不用点开对比弹窗才知道这条填得怎么样。 */}
                        {selectedTag === 'template_review' ? (() => {
                          const summary = resultSummaryForItem(selected, items)
                          if (!summary) return null
                          return (
                            <Badge shape="square" size="xs" variant={summary.tone === 'fill' ? 'warn' : 'done'}>
                              {summary.label}
                            </Badge>
                          )
                        })() : null}
                      </div>
                      <div className="mt-1.5 flex items-center justify-between gap-3">
                        <h3 className="min-w-0 truncate text-lg font-headline font-bold leading-snug text-on-surface">{selected.title}</h3>
                        <div className="flex shrink-0 items-center gap-2">
                          <TechnicalGapActionControls
                            item={selected}
                            items={items}
                            busy={Boolean(busyAction)}
                            onConfirmReady={handleConfirmGapReady}
                            onReviewPass={handleReviewPassAiFill}
                            onRefill={handleRefillAiFill}
                            onTitleOnly={handleSetTitleOnly}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                  <TechnicalGapQualityNotice item={selected} />

                  <div className="min-h-0 flex-1 overflow-y-auto bg-surface-container-low">
                    <div className="space-y-4 p-4">
                      {/* 已选中素材 / 本章合并清单（产品裁决 2026-07-21 交互重构）：
                          - 默认只展示后端定案（文件名精确命中）或父级覆盖的素材；启发式候选一律待在备选池。
                          - 解析空副表常驻本区，带 预览 + AI填写；点「选择」选用的素材进入合并清单。
                          - 已选区内：待填写素材 预览 + AI填写，不用填写的素材只有 预览。 */}
                      {defaultSelections.length || topBlankEntries.length || mergeArtifacts.length ? (
                        <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs font-semibold text-on-surface">
                              {mergeArtifacts.length ? '本章合并清单' : '已选中素材'}
                            </div>
                            {!mergeArtifacts.length && defaultSelections.length > 1 ? (
                              <span className="text-[10px] text-outline">
                                多机型 · 按此顺序铺开 {defaultSelections.length} 份
                              </span>
                            ) : null}
                          </div>
                          {!mergeArtifacts.length && defaultSelections.length ? (
                            <div className="mt-2 space-y-2">
                              {/* 定案/父级覆盖素材已在已选区：不再提供「选择」，待填写时才有 AI填写。
                                  多机型时每个机型一张卡，顺序即 planner 按机型明细给出的顺序。 */}
                              {defaultSelections.map((selection, index) => (
                                <MaterialCandidateCard
                                  key={String(selection.material?.id || selection.material?.materialId || index)}
                                  material={selection.material}
                                  isSelected
                                  coverageLabel={selection.inherited
                                    ? `父级覆盖 · ${selection.sourceItem?.number || selection.sourceItem?.title || '父章节'}`
                                    : (defaultSelections.length > 1 ? `第 ${index + 1} 份` : '')}
                                  busy={Boolean(busyAction)}
                                  selecting={false}
                                  onPreview={handlePreviewMaterial}
                                  onSelect={null}
                                  {...cardAiFillProps(selection.material)}
                                />
                              ))}
                            </div>
                          ) : null}
                          {/* 合并清单：每条产物带来源标签与直达预览。
                              「确认可合并」二次确认已移除（产品意见 2026-07-17：填写完成直接进入选中状态）。
                              2026-08-02：每个目录项只定案一份素材，取消合并顺序编号与说明。 */}
                          {mergeArtifacts.length ? (
                            <div className="mt-2 space-y-1.5">
                              {mergeArtifacts.map((artifact, index) => {
                                const key = artifact.id || `${artifact.fileName || ''}-${index}`
                                if (artifact.source === 'ai_fill') {
                                  const canCompare = canCompareAiFillArtifact(artifact)
                                  return (
                                    <div key={key} className="rounded-md border border-primary/25 bg-primary-fixed/35 px-3 py-3">
                                      <div className="flex items-center justify-between gap-3">
                                        <div className="flex min-w-0 items-center gap-3">
                                          <span className="material-symbols-outlined flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary text-[19px] text-on-primary">
                                            auto_awesome
                                          </span>
                                          <div className="min-w-0">
                                            <div className="flex items-center gap-2">
                                              <span className="text-xs font-semibold text-primary">AI 填写结果</span>
                                              <Badge size="xs" variant="done">已生成</Badge>
                                            </div>
                                            <div className="mt-1 truncate text-xs font-medium text-on-surface" title={artifact.fileName || ''}>
                                              {artifact.fileName || artifact.title || artifact.id || '-'}
                                            </div>
                                          </div>
                                        </div>
                                        <Button
                                          type="button"
                                          onClick={() => handlePreviewMergeArtifact(artifact)}
                                          disabled={Boolean(busyAction)}
                                          icon={canCompare ? 'compare' : 'visibility'}
                                          size="sm"
                                          variant="primary"
                                        >
                                          {canCompare ? '对比预览' : '预览结果'}
                                        </Button>
                                      </div>
                                    </div>
                                  )
                                }

                                return (
                                  <div key={key} className="flex items-center justify-between gap-2 rounded-md bg-surface-container-low px-3 py-2">
                                    <div className="flex min-w-0 items-center gap-2 text-xs">
                                      <span className="truncate font-medium text-on-surface" title={artifact.fileName || ''}>
                                        {artifact.fileName || artifact.title || artifact.id || '-'}
                                      </span>
                                      <Badge size="xs" variant="done">
                                        {artifactSourceLabels[artifact.source] || '产物'}
                                      </Badge>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-2">
                                      <Button
                                        type="button"
                                        onClick={() => handlePreviewMergeArtifact(artifact)}
                                        disabled={Boolean(busyAction)}
                                        size="sm"
                                        variant="quiet"
                                      >
                                        预览
                                      </Button>
                                      {(() => {
                                        // 选用的「待填写-」模板在清单里保留 AI填写；其余产物只有预览。
                                        const task = fillTaskForMergeArtifact(artifact)
                                        if (!task) return null
                                        const completed = String(task?.status || '') === 'completed'
                                        return (
                                          <Button
                                            type="button"
                                            onClick={() => startAiFill(task)}
                                            disabled={Boolean(busyAction) || bodyFillRunning}
                                            title={bodyFillRunning ? '一键填写进行中，暂不可单条填写' : completed ? '已完成，可再次发起 AI 填写' : ''}
                                            size="sm"
                                            variant="secondary"
                                          >
                                            {aiFillBusy ? 'AI填写中...' : completed ? '已AI填写' : 'AI填写'}
                                          </Button>
                                        )
                                      })()}
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          ) : null}
                          {/* 解析空副表常驻已选区：预览 + AI填写（填写完成后仍可再次发起）。 */}
                          {topBlankEntries.length ? (
                            <div className="mt-2 space-y-2">
                              {topBlankEntries.map((entry) => (
                                <MaterialCandidateCard
                                  key={entry.key || entry.task?.id}
                                  material={entry.material}
                                  isSelected
                                  busy={Boolean(busyAction)}
                                  selecting={false}
                                  onPreview={() => handlePreviewBlankFor(entry.blank)}
                                  onSelect={null}
                                  fillable
                                  onAiFill={() => startAiFill(entry.task)}
                                  aiFillBusy={aiFillBusy}
                                  aiFillCompleted={String(entry.task?.status || '') === 'completed'}
                                  aiFillDisabled={bodyFillRunning}
                                  aiFillDisabledReason="一键填写进行中，暂不可单条填写"
                                />
                              ))}
                            </div>
                          ) : null}
                          {selectedPlaceholderLabels.total ? (
                            <div className="mt-3">
                              <div className="text-[11px] font-semibold text-on-surface">识别到的待填字段</div>
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                {selectedPlaceholderLabels.visible.map((label) => (
                                  <span key={label} className="rounded bg-surface-container-low px-2 py-0.5 text-[11px] text-on-surface-variant">
                                    {label}
                                  </span>
                                ))}
                                {selectedPlaceholderLabels.overflow ? (
                                  <span className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] text-outline">
                                    +{selectedPlaceholderLabels.overflow}
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                        </section>
                      ) : null}

                      {/* 定案项（含 0.99 精确命中）的备选区默认收起，保留「更换素材」入口
                          （产品裁决 2026-08-04：99 分不展示备选，但撤换通道必须留）。 */}
                      {!frozenSelected && settledSelected && backupEntries.length && !materialSwapOpen ? (
                        <div className="flex justify-end">
                          <Button
                            type="button"
                            onClick={() => setMaterialSwapOpen(true)}
                            disabled={Boolean(busyAction)}
                            size="sm"
                            variant="quiet"
                          >
                            更换素材（{backupEntries.length} 个备选）
                          </Button>
                        </div>
                      ) : null}
                      {/* 备选素材：待填写素材与参考素材平级的统一候选池（已剔除选中项，无候选则整块不渲染）；
                          被冻结（由父章覆盖/仅保留标题）的子节不展示备选，避免重复匹配和重复拼接。 */}
                      {!frozenSelected && !defaultSelection?.inherited && backupEntries.length
                        && (!settledSelected || materialSwapOpen) ? (
                        <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs font-semibold text-on-surface">备选素材</div>
                            <div className="flex items-center gap-2">
                              {selectedSourceRouting ? (
                                <span className="rounded bg-tertiary-fixed px-2 py-0.5 text-[10px] font-semibold text-on-tertiary-fixed">
                                  规则规定
                                </span>
                              ) : null}
                              <button
                                type="button"
                                onClick={() => {
                                  setMultiPickOpen((prev) => !prev)
                                  setMultiPickKeys([])
                                }}
                                className={`rounded px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                                  multiPickOpen
                                    ? 'bg-primary text-on-primary'
                                    : 'bg-surface-container-high text-on-surface-variant hover:text-primary'
                                }`}
                                title="一个目录项可以铺开多份素材，例如多机型各一份"
                              >
                                {multiPickOpen ? '退出多选' : '多选'}
                              </button>
                            </div>
                          </div>
                          {multiPickOpen ? (
                            <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-[11px] leading-relaxed text-on-surface-variant">
                              勾选顺序即正文里的铺开顺序，可在下方调整。
                            </div>
                          ) : null}
                          {selectedSourceRoutingSummary ? (
                            <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-[11px] leading-relaxed text-on-surface-variant">
                              {selectedSourceRoutingSummary}
                            </div>
                          ) : null}
                          <div className="mt-2 space-y-2">
                            {/* 备选池统一只有 预览 + 选择（产品裁决 2026-07-21）：AI填写 在选用后才出现。 */}
                            {backupEntries.map((wrapper) => {
                              const wrapperMaterial = wrapper.kind === 'blank' ? wrapper.entry.material : wrapper.material
                              const pickIndex = multiPickKeys.indexOf(wrapper.key)
                              return (
                                <MaterialCandidateCard
                                  key={wrapper.key}
                                  material={wrapperMaterial}
                                  isSelected={false}
                                  busy={Boolean(busyAction)}
                                  selecting={busyAction === `select-material:${selected.id}:${wrapper.key}`}
                                  onPreview={wrapper.kind === 'blank' ? () => handlePreviewMaterial(wrapperMaterial) : handlePreviewMaterial}
                                  onSelect={multiPickOpen ? null : handleSelectMaterial}
                                  fillable={wrapper.kind === 'blank' ? true : materialFillable(wrapperMaterial)}
                                  coverageLabel={
                                    wrapper.kind === 'blank' || multiPickOpen
                                      ? ''
                                      : (matchedMaterialIds.has(wrapper.key) ? '系统预选' : '')
                                  }
                                  onCardClick={multiPickOpen ? () => toggleMultiPick(wrapper.key) : null}
                                  leading={multiPickOpen ? (
                                    <label
                                      className="flex shrink-0 items-center gap-1 pt-0.5"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={pickIndex >= 0}
                                        onChange={() => toggleMultiPick(wrapper.key)}
                                        className="h-4 w-4 shrink-0 accent-primary"
                                        aria-label={`勾选 ${wrapperMaterial?.name || wrapper.key}`}
                                      />
                                      {pickIndex >= 0 ? (
                                        <span className="rounded bg-primary px-1.5 py-0.5 text-[10px] font-semibold text-on-primary">
                                          {pickIndex + 1}
                                        </span>
                                      ) : null}
                                    </label>
                                  ) : null}
                                />
                              )
                            })}
                          </div>
                          {multiPickOpen && multiPickKeys.length ? (
                            <div className="mt-3 rounded-md border border-surface-container-high bg-surface-container-low p-2">
                              <div className="mb-1.5 text-[11px] font-semibold text-on-surface">
                                将按此顺序铺开（{multiPickKeys.length} 份）
                              </div>
                              <ol className="space-y-1">
                                {multiPickKeys.map((key, index) => (
                                  <li key={key} className="flex items-center gap-2 text-[11px] text-on-surface-variant">
                                    <span className="w-4 shrink-0 text-right font-semibold text-primary">{index + 1}</span>
                                    <span className="min-w-0 flex-1 truncate">{multiPickMaterialName(key)}</span>
                                    <button
                                      type="button"
                                      disabled={index === 0}
                                      onClick={() => moveMultiPick(index, -1)}
                                      className="shrink-0 rounded px-1 text-outline hover:text-primary disabled:opacity-30"
                                      aria-label="上移"
                                    >
                                      <span className="material-symbols-outlined text-[16px]">arrow_upward</span>
                                    </button>
                                    <button
                                      type="button"
                                      disabled={index === multiPickKeys.length - 1}
                                      onClick={() => moveMultiPick(index, 1)}
                                      className="shrink-0 rounded px-1 text-outline hover:text-primary disabled:opacity-30"
                                      aria-label="下移"
                                    >
                                      <span className="material-symbols-outlined text-[16px]">arrow_downward</span>
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => toggleMultiPick(key)}
                                      className="shrink-0 rounded px-1 text-outline hover:text-error"
                                      aria-label="移除"
                                    >
                                      <span className="material-symbols-outlined text-[16px]">close</span>
                                    </button>
                                  </li>
                                ))}
                              </ol>
                              <div className="mt-2 flex justify-end">
                                <Button
                                  size="sm"
                                  variant="primary"
                                  disabled={Boolean(busyAction)}
                                  onClick={async () => {
                                    const materials = multiPickKeys.map(multiPickMaterialOf).filter(Boolean)
                                    const result = await handleSelectMaterials(materials)
                                    if (result) {
                                      setMultiPickKeys([])
                                      setMultiPickOpen(false)
                                    }
                                  }}
                                >
                                  {busyAction === `select-material:${selected.id}:multi`
                                    ? '选用中...'
                                    : `选用这 ${multiPickKeys.length} 份`}
                                </Button>
                              </div>
                            </div>
                          ) : null}
                        </section>
                      ) : null}

                      {/* 统一兜底入口：搜索限定素材库或直接上传素材，选定即定案（行为② 2026-08-04）。
                          冻结（父章覆盖/仅留标题）的目录项只读，不渲染兜底入口；
                          虚线边框降视觉层级——它是兜底，不与已选/备选主区抢眼。 */}
                      {frozenSelected ? null : (
                      <section className="rounded-lg border border-dashed border-surface-container-high bg-surface-container-low/50 p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-xs font-semibold text-on-surface">搜索 / 上传素材</div>
                            <div className="mt-1 text-[11px] text-outline">
                              搜索只在当前项目、客户和通用素材边界内进行；上传的文件会直接选用为本目录项的匹配素材。
                            </div>
                          </div>
                          <label className={`inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container ${busyAction ? 'pointer-events-none opacity-50' : ''}`}>
                            <span className="material-symbols-outlined text-[16px]">upload_file</span>
                            {busyAction === `upload:${selected.id}` ? '上传中...' : '上传素材'}
                            <input
                              type="file"
                              accept=".docx"
                              className="hidden"
                              disabled={Boolean(busyAction)}
                              onChange={handleUploadGapMaterial}
                            />
                          </label>
                        </div>
                        <div className="mt-3 flex gap-2">
                          <input
                            value={materialKeyword}
                            onChange={(event) => setMaterialKeyword(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter') handleSearchMaterials()
                            }}
                            placeholder="搜索素材名称"
                            className="min-w-0 flex-1 h-9 px-3 rounded-md border border-surface-container-high bg-surface text-sm text-on-surface"
                          />
                          <button
                            onClick={handleSearchMaterials}
                            disabled={materialLoading}
                            className="h-9 px-3 bg-surface-container-high text-on-surface-variant text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {materialLoading ? '查询中...' : '查询'}
                          </button>
                        </div>
                        <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
                          {materialSearch.items.length ? materialSearch.items.map((item) => {
                            const materialId = String(item?.id || item?.materialId || '').trim()
                            return (
                              <MaterialCandidateCard
                                key={item.id}
                                material={item}
                                isSelected={selectedMaterialIdSet.has(materialId)}
                                busy={Boolean(busyAction) || !materialId}
                                selecting={busyAction === `select-material:${selected.id}:${materialId}`}
                                onPreview={handlePreviewMaterial}
                                onSelect={handleSelectMaterial}
                                fillable={materialFillable(item)}
                              />
                            )
                          }) : (
                            <p className="text-xs text-outline">
                              {materialLoading ? '正在查询素材...' : '输入关键词后查询限定素材库。'}
                            </p>
                          )}
                        </div>
                      </section>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-outline">选择一个目录项查看处理详情</div>
              )}
            </div>

          </div>
        )}
      </DataCard>
      {factModalOpen ? (
        <FactMaintenanceModal
          open
          factTable={factTable}
          fields={factFields}
          busy={['facts-confirm', 'facts-material-sources', 'facts-curate'].includes(busyAction)}
          specsImported={factSpecsMeta.imported}
          specsFileName={factSpecsMeta.fileName}
          materialPaths={factMaterialPaths}
          materialScopes={factMaterialScopes}
          curateReport={factCurateReport}
          curating={busyAction === 'facts-curate' || factCurateRunning}
          curatePhase={factCurateRunning ? String(factCurateState?.phase || '') : ''}
          curateMessage={factCurateRunning ? String(factCurateState?.message || '') : ''}
          updatingScope={busyAction === 'facts-material-sources'}
          onClose={() => setFactModalOpen(false)}
          onConfirm={handleConfirmFactTable}
          onFieldChange={handleFactFieldChange}
          onAddField={handleAddFactField}
          onGoToRules={() => navigate('/workspace/tech/materials/rules')}
          onSaveMaterialPaths={handleSaveMaterialPaths}
          onCurate={handleCurateFacts}
        />
      ) : null}
      <TechnicalGenerationProgressModal
        open={(generationModalOpen || generationRunning) && !generationModalDismissed}
        status={generationStatus}
        onClose={() => {
          setGenerationModalDismissed(true)
          setGenerationModalOpen(false)
        }}
      />
      <AiFillReferenceModal
        open={Boolean(aiFillModalTask)}
        blankTitle={aiFillModalTask?.blankSource?.title || aiFillModalTask?.blankSource?.id || ''}
        sourceRoutingSummary={selectedSourceRoutingSummary}
        tenderDocumentState={aiFillTenderDocumentState}
        candidates={selectedReferenceCandidates}
        referenceIds={aiFillModalTask ? aiFillReferenceIdsFor(aiFillModalTask) : []}
        busy={Boolean(busyAction)}
        onToggle={(materialId) => handleToggleAiFillReference(aiFillModalTask, materialId)}
        onPreview={handlePreviewMaterial}
        onUpload={handleAiFillUpload}
        uploadBusy={aiFillUploadBusy}
        confirmBlockReason={bodyFillRunning ? '一键填写进行中，暂不可单条填写' : ''}
        onConfirm={() => {
          const task = aiFillModalTask
          setAiFillModalTask(null)
          setAiFillUploadedCandidates([])
          handleAiFill(task)
        }}
        onClose={() => {
          setAiFillModalTask(null)
          setAiFillUploadedCandidates([])
        }}
      />
      <TechnicalPreviewModal
        open={previewOpen}
        sectionTitle={selected?.title || ''}
        selectedPreviewChoice={selectedPreviewChoice}
        comparison={previewComparison}
        previewLoading={previewLoading}
        previewSession={previewSession}
        previewError={previewError}
        referencePreviewLoading={referencePreviewLoading}
        referencePreviewSession={referencePreviewSession}
        referencePreviewError={referencePreviewError}
        onClose={() => setPreviewOpen(false)}
        reviewQueue={reviewQueue}
        reviewCurrentId={effectiveSelectedId}
        onReviewStep={handleReviewStep}
        onReviewPass={selected ? handleReviewPassInModal : null}
        reviewBusy={Boolean(busyAction)}
      />
    </div>
  )
}
