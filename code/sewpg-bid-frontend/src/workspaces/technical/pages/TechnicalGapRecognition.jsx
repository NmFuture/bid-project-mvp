import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalGapsAPI, technicalOutlineAPI, technicalProjectsAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import DataCard from '../../../components/shared/DataCard'
import TechnicalGenerationProgressModal from '../components/TechnicalGenerationProgressModal'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
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
import { useGapPreviewSession } from './useGapPreviewSession'
import { useBackgroundTaskPolling } from './useBackgroundTaskPolling'
import { useFactTableMaintenance } from './useFactTableMaintenance'
import { useAiFillFlow } from './useAiFillFlow'
import { useMaterialSelection } from './useMaterialSelection'
import { useGapReviewQueue } from './useGapReviewQueue'
import { useTechnicalGeneration } from './useTechnicalGeneration'
import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import Toolbar from '../../../components/ui/Toolbar'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import {
  asArray,
  asObjectArray,
  aiFillComparisonPair,
  appendixTaskForFillTask,
  buildTocTreeRows,
  compactList,
  currentResolvedArtifacts,
  isFillTemplateMaterial,
  latestResolvedArtifact,
  matchedMaterialForItem,
  normalizeItems,
  primaryBlankSource,
  resultSummaryForItem,
  sourceRoutingForAppendixTasks,
  sourceRoutingText,
  TECHNICAL_GAP_TAG_CONFIG,
  technicalBodyFillCounts,
  technicalGapFillError,
  technicalGapProgressCounts,
  technicalGapTagBucketOf,
  technicalGapTagOf,
  tenderDocumentStateForAiFill,
} from './technicalGapRecognitionHelpers'

// 合并清单条目的来源标签。
const artifactSourceLabels = {
  material_library: '选用素材',
  manual_upload: '人工上传',
  ai_fill: 'AI填写',
}

// 后台任务终态口径：一键填写（正文+附表）有成功/部分成功/失败。
// 轮询的去重与通知逻辑见 useBackgroundTaskPolling / technicalGapTaskPolling。
const BODY_FILL_TERMINAL_STATUSES = ['succeeded', 'partial', 'failed']
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [materialScope, setMaterialScope] = useState(null)
  // 目录前置守卫（R11-B07-03）：未生成/未确认/空目录时阻断素材匹配页，null 表示未加载（不阻断）
  const [outlineGuard, setOutlineGuard] = useState(null)
  // 一键填写（正文+附表）任务状态：跑在后台 worker，进度靠轮询恢复，关页面不影响
  const [bodyFillState, setBodyFillState] = useState(null)
  const bodyFillRunning = ['queued', 'running'].includes(String(bodyFillState?.status || ''))
  const bodyFillDone = Number(bodyFillState?.done || 0)
  const bodyFillTotal = Number(bodyFillState?.total || 0)

  // 事实表维护族（事实表状态/字段编辑/保存定稿/AI 匹配填充与轮询）已收口到 useFactTableMaintenance
  const {
    factModalOpen,
    setFactModalOpen,
    factTable,
    setFactTable,
    factFields,
    setFactFields,
    factCurateReport,
    factSpecsMeta,
    setFactSpecsMeta,
    sourceMatrixMeta,
    setSourceMatrixMeta,
    factMaterialPaths,
    setFactMaterialPaths,
    factMaterialScopes,
    setFactMaterialScopes,
    factCurateState,
    setFactCurateState,
    factCurateRunning,
    factConfirmed,
    ensureFactTableReady,
    handleFactFieldChange,
    handleAddFactField,
    handleConfirmFactTable,
    handleSaveMaterialPaths,
    handleCurateFacts,
  } = useFactTableMaintenance({ projectId: id, setData, busyAction, setBusyAction, showToast, navigate })

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
  }, [
    id,
    setFactTable,
    setFactFields,
    setFactSpecsMeta,
    setFactMaterialPaths,
    setFactMaterialScopes,
    setFactCurateState,
    setSourceMatrixMeta,
  ])

  const items = useMemo(() => normalizeItems(data), [data])
  // 筛选按统计桶比对，与标签上的数字同源：点「已就绪」要能筛出归入该桶的仅留标题行。
  const filteredItems = useMemo(() => (
    tagFilter
      ? items.filter((item) => technicalGapTagBucketOf(technicalGapTagOf(item, items)) === tagFilter)
      : items
  ), [items, tagFilter])
  // 目录树（可折叠）：构建规则见 buildTocTreeRows；默认只展开一级章。
  const treeRows = useMemo(
    () => buildTocTreeRows({ items, filteredItems, tagFilter, expandedTocKeys }),
    [items, filteredItems, tagFilter, expandedTocKeys],
  )
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
  const hasTechnicalGapPlan = data?.status === 'completed' && Boolean(data?.gapPlan || items.length)

  // 正文生成族（状态加载/运行订阅/生成与晋级）已收口到 useTechnicalGeneration
  const {
    generationStatus,
    generationModalOpen,
    generationModalDismissed,
    generationRunning,
    generationCompleted,
    loadGenerationStatus,
    closeGenerationModal,
    runTechnicalAssembly,
    advanceToTechnicalEditor,
  } = useTechnicalGeneration({
    projectId: id,
    hasTechnicalGapPlan,
    busyAction,
    setBusyAction,
    showToast,
    navigate,
    workspaceSlug,
  })

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData()
      loadGenerationStatus()
    }, 0)
    return () => clearTimeout(timer)
  }, [loadData, loadGenerationStatus])

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

  // AI 填写流（参考素材弹窗/勾选态/补料上传/单条填写执行）已收口到 useAiFillFlow
  const {
    aiFillModalTask,
    setAiFillModalTask,
    aiFillUploadBusy,
    selectedReferenceCandidates,
    aiFillReferenceIdsFor,
    handleAiFill,
    startAiFill,
    handleRefillAiFill,
    handleToggleAiFillReference,
    handleAiFillUpload,
    closeAiFillModal,
  } = useAiFillFlow({
    projectId: id,
    selected,
    selectedFillTask,
    activeAppendixTasks,
    selectedSourceRouting,
    selectedMaterialMatch,
    selectedCandidateMaterials,
    bodyFillRunning,
    factConfirmed,
    ensureFactTableReady,
    runAction,
    aiFillActionKey,
    busyAction,
    tagFilter,
    setTagFilter,
    setSelectedId,
    resetPreviewChoice,
    setPreviewChoiceKey,
    setPreviewOpen,
    readableScopes,
    materialScope,
    showToast,
  })
  const aiFillTenderDocumentState = tenderDocumentStateForAiFill(
    appendixTaskForFillTask(selected, aiFillModalTask),
  )

  // 素材选择/上传族（备选池派生/多选铺开/限定库搜索/选用与上传）已收口到 useMaterialSelection
  const {
    materialKeyword,
    setMaterialKeyword,
    materialSearch,
    materialLoading,
    materialSwapOpen,
    setMaterialSwapOpen,
    multiPickOpen,
    setMultiPickOpen,
    multiPickKeys,
    setMultiPickKeys,
    materialFillable,
    matchedMaterialIds,
    topBlankEntries,
    defaultSelections,
    defaultSelection,
    backupEntries,
    multiPickMaterialName,
    toggleMultiPick,
    moveMultiPick,
    submitMultiPick,
    handleSearchMaterials,
    handleSelectMaterial,
    handleUploadGapMaterial,
    resetMaterialPick,
  } = useMaterialSelection({
    projectId: id,
    items,
    selected,
    settledSelected,
    selectedFillTasks,
    selectedReferenceCandidates,
    selectedMaterialIdSet,
    runAction,
    showToast,
    scopePaths,
    materialScope,
    data,
    projectTurbineModel,
  })

  // 素材卡统一交互：AI填写按钮统一打开参考素材选择弹窗（产品裁决：先选参考素材再执行）；
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

  // 复核队列族（待审核队列/逐条与批量复核/弹窗内顶位续审）已收口到 useGapReviewQueue
  const {
    reviewQueue,
    batchReviewables,
    flaggedReviewCount,
    handleReviewStep,
    handleReviewPassAiFill,
    handleReviewPassInModal,
    handleBatchReviewPass,
  } = useGapReviewQueue({
    projectId: id,
    items,
    selected,
    effectiveSelectedId,
    setSelectedId,
    runAction,
    busyAction,
    loadData,
    showToast,
    setPreviewChoiceKey,
    setPreviewSession,
    setPreviewError,
    setManualPreviewChoice,
    setPreviewOpen,
  })

  const handleRunDetection = () => runAction(
    'detect',
    () => technicalGapsAPI.runDetection(id),
    (payload) => payload?.message || '缺口识别完成',
  )

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

  const handleSelectTocItem = (itemId) => {
    setSelectedId(itemId)
    resetPreviewChoice()
    setPreviewOpen(false)
    setAiFillModalTask(null)
    resetMaterialPick()
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
                                  onClick={submitMultiPick}
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
        onClose={closeGenerationModal}
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
          closeAiFillModal()
          handleAiFill(task)
        }}
        onClose={closeAiFillModal}
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
