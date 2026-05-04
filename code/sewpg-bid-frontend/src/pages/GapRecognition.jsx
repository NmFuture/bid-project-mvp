import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { gapsAPI, materialsAPI, parseAPI, projectsAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import {
  asArray,
  asObjectArray,
  matchedMaterialForItem,
  previewChoicesForItem,
  primaryBlankSource,
  resultSummaryForItem,
  uniqueStrings,
} from './gapRecognitionHelpers'

const formatDateTime = (value) => {
  if (!value) return '未执行'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未执行'
  return date.toLocaleString('zh-CN', { hour12: false })
}

const statusConfig = {
  matched: { label: '已匹配', tone: 'bg-secondary-container text-on-secondary-container', icon: 'check_circle' },
  structural: { label: '结构章节', tone: 'bg-surface-container-high text-on-surface-variant', icon: 'account_tree' },
  missing: { label: '缺素材', tone: 'bg-error/10 text-error', icon: 'error' },
  needs_input: { label: '需处理', tone: 'bg-tertiary-fixed text-on-tertiary-fixed', icon: 'edit_note' },
  filling: { label: '处理中', tone: 'bg-primary/10 text-primary', icon: 'pending' },
  resolved: { label: '已解决', tone: 'bg-secondary-container text-on-secondary-container', icon: 'task_alt' },
  ignored: { label: '已忽略', tone: 'bg-surface-container-high text-on-surface-variant', icon: 'do_not_disturb_on' },
}

const decisionConfig = {
  ready: {
    label: '可直接合并',
    shortLabel: '合并',
    tone: 'bg-secondary-container text-on-secondary-container',
    icon: 'library_add_check',
  },
  fill_required: {
    label: '需填写空表/Word',
    shortLabel: '填写',
    tone: 'bg-tertiary-fixed text-on-tertiary-fixed',
    icon: 'edit_document',
  },
  material_required: {
    label: '缺素材',
    shortLabel: '补料',
    tone: 'bg-error/10 text-error',
    icon: 'upload_file',
  },
  review_required: {
    label: '需人工复核',
    shortLabel: '复核',
    tone: 'bg-primary/10 text-primary',
    icon: 'rule_settings',
  },
}

const decisionSummaryKeys = {
  ready: 'readyCount',
  fill_required: 'fillRequiredCount',
  material_required: 'materialRequiredCount',
  review_required: 'reviewRequiredCount',
}

const usageLabels = {
  chapter_master: '整章合并',
  covered_by_parent: '父章覆盖',
  section_merge: '章节合并',
  table_source: '空表填写参考',
  appendix_fill: '副表填写',
  section_fill: 'Word 填写',
  structural: '结构章节',
  both: '合并与填写',
}

const turbineStatusLabels = {
  matched: '机型匹配',
  generic: '通用素材',
  conflict: '机型冲突',
  unknown: '未命中素材',
}

const previewKindLabels = {
  material: '素材预览',
  appendix: '未填写预览',
  blankMaterial: '未填写预览',
  artifact: '结果预览',
}

const previewKindIcons = {
  material: 'description',
  appendix: 'table_view',
  blankMaterial: 'description',
  artifact: 'task',
}

const resultToneClasses = {
  resolved: 'bg-secondary-container text-on-secondary-container',
  material: 'bg-secondary-container text-on-secondary-container',
  fill: 'bg-tertiary-fixed text-on-tertiary-fixed',
  missing: 'bg-error/10 text-error',
  none: 'bg-surface-container-high text-on-surface-variant',
}

const fallbackDocumentRoot = (projectId) => `/data/documents/${projectId}/technical-workspace/s4_gap_workdir`

const compactList = (items, limit = 4) => {
  const list = uniqueStrings(items)
  return {
    visible: list.slice(0, limit),
    overflow: Math.max(0, list.length - limit),
    total: list.length,
  }
}

const decisionOf = (item) => {
  const decision = String(item?.decision || '').trim()
  return decisionConfig[decision] ? decision : ''
}

const configForItem = (item) => {
  const decision = decisionOf(item)
  return decision ? decisionConfig[decision] : (statusConfig[item?.status] || statusConfig.missing)
}

const labelForUsage = (usage) => usageLabels[usage] || usage || '未指定'

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

const MiniFact = ({ label, value }) => (
  <div className="rounded-md bg-surface-container-low px-3 py-2">
    <div className="text-[11px] text-outline">{label}</div>
    <div className="mt-1 truncate text-xs font-semibold text-on-surface" title={String(value || '')}>
      {value || '-'}
    </div>
  </div>
)

const SmallStat = ({ label, value, active, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`h-[58px] rounded-md border px-3 text-left transition-colors ${
      active
        ? 'border-primary bg-primary text-on-primary'
        : 'border-surface-container-high bg-surface-container-lowest text-on-surface hover:bg-surface-container-low'
    }`}
  >
    <div className={`text-[11px] ${active ? 'text-on-primary/80' : 'text-outline'}`}>{label}</div>
    <div className="mt-1 text-xl font-headline font-bold">{value}</div>
  </button>
)

export default function GapRecognition({ showToast }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [materialKeyword, setMaterialKeyword] = useState('')
  const [materialSearch, setMaterialSearch] = useState({ items: [], total: 0 })
  const [materialLoading, setMaterialLoading] = useState(false)
  const [materialScope, setMaterialScope] = useState(null)
  const [decisionFilter, setDecisionFilter] = useState('all')
  const [previewChoiceKey, setPreviewChoiceKey] = useState('')
  const [previewSession, setPreviewSession] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [manualPreviewChoice, setManualPreviewChoice] = useState(null)

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const [payload, scopePayload] = await Promise.all([
        gapsAPI.detectionStatus(id),
        projectsAPI.materialsPath(id),
      ])
      const items = normalizeItems(payload)
      setData(payload)
      setMaterialScope(scopePayload)
      setSelectedId((prev) => (items.some((item) => item.id === prev) ? prev : items[0]?.id || ''))
    } catch (e) {
      if (!silent) setError(e?.message || '缺口识别与处理加载失败')
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

  const items = useMemo(() => normalizeItems(data), [data])
  const filteredItems = useMemo(
    () => (decisionFilter === 'all' ? items : items.filter((item) => decisionOf(item) === decisionFilter)),
    [decisionFilter, items],
  )
  const effectiveSelectedId = filteredItems.some((item) => item.id === selectedId)
    ? selectedId
    : (filteredItems[0]?.id || '')
  const selected = useMemo(
    () => filteredItems.find((item) => item.id === effectiveSelectedId) || null,
    [effectiveSelectedId, filteredItems],
  )
  const summary = useMemo(() => data?.gapPlan?.summary || data?.summary || {}, [data])
  const sampleVersion = data?.gapPlan?.sampleVersion || data?.sampleVersion || ''
  const isCompleted = data?.status === 'completed'
  const readableScopes = useMemo(
    () => (Array.isArray(materialScope?.readableScopes) ? materialScope.readableScopes : []),
    [materialScope],
  )
  const scopePaths = useMemo(
    () => readableScopes.map((scope) => String(scope?.path || '')).filter(Boolean),
    [readableScopes],
  )
  const scopeSummary = materialScope?.summary || scopePaths.join('；')
  const projectTurbineModel = data?.gapPlan?.projectTurbineModel || data?.projectTurbineModel || materialScope?.turbineModel || null
  const turbineModelLabel = projectTurbineModel?.model
    ? [
        projectTurbineModel.model,
        projectTurbineModel.platform,
        projectTurbineModel.ratedPowerKw ? `${projectTurbineModel.ratedPowerKw}kW` : '',
        projectTurbineModel.rotorDiameterM ? `叶轮${projectTurbineModel.rotorDiameterM}m` : '',
      ].filter(Boolean).join(' / ')
    : ''
  const selectedConfig = selected ? configForItem(selected) : null
  const selectedDecision = decisionOf(selected)
  const selectedMaterialScope = selected?.materialScope || {}
  const selectedTurbineCheck = selected?.turbineCheck || {}
  const selectedAppendixTasks = asArray(selected?.appendixTasks)
  const selectedCandidateMaterials = asObjectArray(selected?.candidateMaterials)
  const selectedMaterialMatch = matchedMaterialForItem(selected, items)
  const selectedBlankSource = primaryBlankSource(selected)
  const selectedResultSummary = resultSummaryForItem(selected, items)
  const selectedPreviewChoices = useMemo(
    () => previewChoicesForItem(selected, items),
    [items, selected],
  )
  const manualPreviewActive = manualPreviewChoice
    && manualPreviewChoice.itemId === selected?.id
    && manualPreviewChoice.key === previewChoiceKey
    ? manualPreviewChoice
    : null
  const effectivePreviewChoiceKey = manualPreviewActive
    ? manualPreviewActive.key
    : selectedPreviewChoices.some((choice) => choice.key === previewChoiceKey)
    ? previewChoiceKey
    : (selectedPreviewChoices[0]?.key || '')
  const selectedPreviewChoice = manualPreviewActive
    || selectedPreviewChoices.find((choice) => choice.key === effectivePreviewChoiceKey)
    || null
  const selectedUsages = compactList([
    selected?.usage,
    ...asObjectArray(selected?.matchedMaterials).map((item) => item.usage),
    ...selectedCandidateMaterials.map((item) => item.usage),
    ...selectedAppendixTasks.flatMap((task) => asObjectArray(task?.recommendedMaterials).map((item) => item.usage)),
  ], 4)
  const selectedAllowedPaths = compactList(selectedMaterialScope.allowedPaths)
  const selectedEvidenceRefs = asArray(selected?.evidenceRefs).slice(0, 6)
  const selectedFillTasks = asObjectArray(selected?.fillTasks)
  const selectedFillTask = selectedFillTasks[0] || null
  const selectedReferenceCandidates = (() => {
    const seen = new Set()
    const candidates = [
      ...selectedCandidateMaterials,
      ...selectedAppendixTasks.flatMap((task) => asObjectArray(task?.recommendedMaterials)),
    ]
    return candidates.filter((item) => {
      const key = String(item?.id || item?.name || '').trim()
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    }).slice(0, 8)
  })()
  const selectedPlaceholderLabels = compactList([
    ...asArray(selectedBlankSource?.placeholderLabels),
    ...selectedCandidateMaterials.flatMap((item) => asArray(item?.placeholderLabels)),
  ], 10)
  const selectedBlankPath = selectedBlankSource?.docxPath || selectedBlankSource?.workspacePath || selectedBlankSource?.path || ''
  const gapWorkRoot = fallbackDocumentRoot(id)
  const selectedSourceMaterialId = [
    selectedBlankSource?.materialId,
    selectedBlankSource?.id,
    selectedMaterialMatch?.material?.id,
  ].map((value) => String(value || '')).find((value) => value.startsWith('RAW-')) || ''
  const selectedSourceObjectLabel = selectedSourceMaterialId
    ? `bid-materials/cleaned/${selectedSourceMaterialId}/...`
    : (selectedBlankPath || selectedMaterialMatch?.material?.path || selectedMaterialMatch?.material?.folderPath || '-')
  const selectedWorkDir = selectedDecision === 'fill_required'
    ? `${gapWorkRoot}/ai_fill/${selected?.id || '<gapId>'}`
    : selectedDecision === 'material_required'
      ? `${gapWorkRoot}/manual_upload/${selected?.id || '<gapId>'}`
      : gapWorkRoot
  const summaryCards = useMemo(() => {
    return [
      ['all', '全部', items.length],
      ['ready', '可直接合并', summary[decisionSummaryKeys.ready] ?? items.filter((item) => decisionOf(item) === 'ready').length],
      ['fill_required', '需填写空表/Word', summary[decisionSummaryKeys.fill_required] ?? items.filter((item) => decisionOf(item) === 'fill_required').length],
      ['material_required', '缺素材', summary[decisionSummaryKeys.material_required] ?? items.filter((item) => decisionOf(item) === 'material_required').length],
      ['review_required', '需人工复核', summary[decisionSummaryKeys.review_required] ?? items.filter((item) => decisionOf(item) === 'review_required').length],
    ]
  }, [items, summary])

  useEffect(() => {
    let cancelled = false
    const loadPreview = async () => {
      setPreviewSession(null)
      setPreviewError('')

      if (!selectedPreviewChoice) return

      if (selectedPreviewChoice.kind === 'artifact') {
        setPreviewSession({
          onlyoffice: selectedPreviewChoice.artifact?.onlyoffice,
          fileName: selectedPreviewChoice.title,
          source: 'artifact',
        })
        return
      }

      setPreviewLoading(true)
      try {
        const payload = selectedPreviewChoice.kind === 'appendix'
          ? await parseAPI.appendixPreview(id, selectedPreviewChoice.blankSource.id)
          : await materialsAPI.raw.previewCleanedFile(selectedPreviewChoice.material.id)
        if (!cancelled) {
          setPreviewSession(payload)
        }
      } catch (e) {
        if (!cancelled) {
          setPreviewError(e?.message || '预览加载失败')
        }
      } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    }

    loadPreview()
    return () => {
      cancelled = true
    }
  }, [id, selectedPreviewChoice])

  const updatePayload = (payload) => {
    const next = payload?.payload || payload
    setData(next)
    const nextItems = normalizeItems(next)
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
    () => gapsAPI.runDetection(id),
    (payload) => payload?.message || '缺口识别完成',
  )

  const handleSearchMaterials = async () => {
    setMaterialLoading(true)
    try {
      const targetPaths = scopePaths.length ? scopePaths : ['']
      const payloads = await Promise.all(targetPaths.map((folderPath) => materialsAPI.raw.files({
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

  const handlePreviewMaterial = (material) => {
    if (!selected || !material?.id) return
    const existing = selectedPreviewChoices.find((choice) => (
      choice.kind === 'material' && choice.material?.id === material.id
    ))
    if (existing) {
      setPreviewChoiceKey(existing.key)
      return
    }
    const choice = {
      key: `material:${material.id}:manual`,
      kind: 'material',
      label: '参考素材',
      title: material.name || material.cleanedFileName || material.id,
      subtitle: material.folderPath || material.path || '',
      material,
      itemId: selected.id,
    }
    setManualPreviewChoice(choice)
    setPreviewChoiceKey(choice.key)
  }

  if (loading) return <PageLoading title="正在加载 S3 缺口处理..." />
  if (error) return <PageError title="S3 缺口处理加载失败" description={error} onRetry={loadData} />

  return (
    <div className="stage-page flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb currentLabel="S3 缺口处理" />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <>
            <button
              onClick={() => loadData()}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors"
            >
              刷新
            </button>
            <button
              onClick={handleRunDetection}
              disabled={Boolean(busyAction)}
              className="px-4 py-2.5 bg-primary text-on-primary text-sm font-medium rounded-lg hover:bg-primary-container transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busyAction === 'detect' ? '识别中...' : isCompleted ? '重新识别缺口' : '识别缺口'}
            </button>
          </>
        )}
      />

      <DataCard className="!p-0 overflow-hidden">
        <div className="border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-start 2xl:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-on-surface">缺口识别结果</h3>
                <span className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ${isCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                  <span className="material-symbols-outlined text-[15px]">{isCompleted ? 'check_circle' : 'pending'}</span>
                  {isCompleted ? '已识别' : '待识别'}
                </span>
              </div>
              <p className="mt-1 text-xs text-on-surface-variant">
                识别时间：{formatDateTime(data?.recognizedAt)} · 目录项：{summary.totalTocItems ?? items.length}
              </p>
              {turbineModelLabel || scopeSummary || sampleVersion ? (
                <p className="mt-1 truncate text-xs text-outline" title={[turbineModelLabel, scopeSummary, sampleVersion].filter(Boolean).join(' · ')}>
                  {[
                    turbineModelLabel ? `投标机型：${turbineModelLabel}` : '',
                    scopeSummary ? `素材边界：${scopeSummary}` : '',
                    sampleVersion ? `样例版本：${sampleVersion}` : '',
                  ].filter(Boolean).join(' · ')}
                </p>
              ) : null}
            </div>

            {isCompleted ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5 2xl:w-[42rem]">
                {summaryCards.map(([key, label, value]) => (
                  <SmallStat
                    key={key}
                    label={label}
                    value={value}
                    active={decisionFilter === key}
                    onClick={() => setDecisionFilter(key)}
                  />
                ))}
              </div>
            ) : null}
          </div>
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
          </div>
        ) : (
          <div className="grid h-[min(850px,calc(100vh-205px))] min-h-[650px] min-w-[72rem] grid-cols-[repeat(3,minmax(0,1fr))] overflow-x-auto">
            <div className="border-r border-surface-container-high min-h-0 flex flex-col">
              <div className="h-12 shrink-0 border-b border-surface-container-high bg-surface-container-lowest px-4 py-3">
                <div className="text-xs font-semibold text-on-surface">
                  目录项 · {filteredItems.length}/{items.length}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
                <div className="divide-y divide-surface-container-high">
                  {filteredItems.map((item) => {
                    const cfg = configForItem(item)
                    const result = resultSummaryForItem(item, items)
                    const active = effectiveSelectedId === item.id
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          setSelectedId(item.id)
                          setPreviewChoiceKey('')
                          setPreviewSession(null)
                          setPreviewError('')
                          setManualPreviewChoice(null)
                        }}
                        className={`block w-full px-4 py-3 text-left transition-colors hover:bg-surface-container-low/70 ${active ? 'bg-primary/5 shadow-[inset_3px_0_0_var(--md-sys-color-primary)]' : 'bg-transparent'}`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[11px] font-medium text-outline">{item.number || item.section || '-'}</div>
                            <div className="mt-1 line-clamp-2 text-sm font-semibold leading-snug text-on-surface">{item.title}</div>
                          </div>
                          <span className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold ${cfg.tone}`}>
                            <span className="material-symbols-outlined text-[14px]">{cfg.icon}</span>
                            {cfg.shortLabel || cfg.label}
                          </span>
                        </div>
                        <div className="mt-2 flex items-center gap-2 text-xs">
                          <span className={`min-w-0 truncate rounded-md px-2 py-1 ${resultToneClasses[result.tone] || resultToneClasses.none}`} title={result.label}>
                            {result.label}
                          </span>
                        </div>
                        {item.gapReason ? (
                          <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-on-surface-variant">{item.gapReason}</p>
                        ) : null}
                      </button>
                    )
                  })}
                  {!filteredItems.length ? (
                    <div className="px-5 py-10 text-center text-sm text-outline">
                      当前筛选下暂无目录项。
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="min-h-0 overflow-hidden border-r border-surface-container-high bg-surface-container-lowest">
              {selected ? (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="shrink-0 border-b border-surface-container-high bg-surface-container-lowest px-5 py-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-outline">{selected.number || selected.section || '-'}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <h3 className="text-lg font-headline font-bold leading-snug text-on-surface">{selected.title}</h3>
                          {selectedConfig ? (
                            <span className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ${selectedConfig.tone}`}>
                              <span className="material-symbols-outlined text-[16px]">{selectedConfig.icon}</span>
                              {selectedConfig.label}
                            </span>
                          ) : null}
                          <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${resultToneClasses[selectedResultSummary.tone] || resultToneClasses.none}`}>
                            {selectedResultSummary.label}
                          </span>
                        </div>
                        <p className="mt-2 max-w-4xl text-sm leading-relaxed text-on-surface-variant">
                          {selected.gapReason || selected.reason || '当前目录项已纳入缺口处理计划。'}
                        </p>
                      </div>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
                      <MiniFact
                        label="用途"
                        value={selectedUsages.visible.length ? selectedUsages.visible.map(labelForUsage).join('；') : labelForUsage(selected.usage)}
                      />
                      <MiniFact
                        label="读取边界"
                        value={selectedAllowedPaths.visible.length ? selectedAllowedPaths.visible.join('；') : scopeSummary}
                      />
                      <MiniFact
                        label="机型判断"
                        value={turbineStatusLabels[selectedTurbineCheck.status] || selectedTurbineCheck.status || '未判断'}
                      />
                      <MiniFact
                        label="当前预览"
                        value={selectedPreviewChoice ? previewKindLabels[selectedPreviewChoice.kind] : '暂无'}
                      />
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 overflow-y-auto bg-surface-container-low">
                    <div className="space-y-4 p-4">
                        {selectedMaterialMatch?.material ? (
                          <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                            <div className="flex items-start gap-2">
                              <div className="text-xs font-semibold text-on-surface">
                                {selectedMaterialMatch.inherited ? '父章覆盖素材' : '最终匹配素材'}
                              </div>
                            </div>
                            <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-xs">
                              <div className="font-medium text-on-surface">{selectedMaterialMatch.material.name || selectedMaterialMatch.material.id}</div>
                              <div className="mt-1 break-all text-outline">{selectedMaterialMatch.material.path || selectedMaterialMatch.material.folderPath || '-'}</div>
                              <div className="mt-1 text-outline">
                                {selectedMaterialMatch.material.materialTier || '素材'} · {labelForUsage(selectedMaterialMatch.material.usage)}
                              </div>
                            </div>
                          </section>
                        ) : null}

                        {selectedDecision === 'fill_required' ? (
                          <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                            <div>
                              <div className="text-xs font-semibold text-on-surface">待填写对象</div>
                              <div className="mt-1 text-[11px] text-outline">
                                {selectedBlankSource?.title || '待填写空表/Word'}
                              </div>
                            </div>
                            <div className="mt-3 grid grid-cols-1 gap-2">
                              <MiniFact label="后续处理" value={selectedFillTask?.skill || 'bid-tech-table-filler'} />
                              <MiniFact label="空表来源" value={selectedBlankSource?.sourceFile || selectedBlankSource?.folderPath || selectedBlankSource?.id || '-'} />
                            </div>
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
                            {selectedReferenceCandidates.length ? (
                              <div className="mt-3 space-y-2">
                                <div className="text-[11px] font-semibold text-on-surface">自动候选参考素材</div>
                                {selectedReferenceCandidates.map((material) => (
                                  <button
                                    key={material.id || material.name}
                                    type="button"
                                    onClick={() => handlePreviewMaterial(material)}
                                    className="block w-full rounded-md bg-surface-container-low px-3 py-2 text-left text-xs hover:bg-surface-container-high"
                                    title={material.path || material.folderPath || material.id}
                                  >
                                    <span className="block font-medium text-on-surface">{material.name || material.id}</span>
                                    <span className="mt-1 block truncate text-outline">{material.folderPath || material.path || material.id}</span>
                                  </button>
                                ))}
                              </div>
                            ) : null}
                          </section>
                        ) : null}

                        {selectedDecision === 'material_required' || selectedDecision === 'review_required' ? (
                          <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                            <div>
                              <div className="text-xs font-semibold text-on-surface">
                                {selectedDecision === 'material_required' ? '素材库查询' : '复核素材查询'}
                              </div>
                              <div className="mt-1 text-[11px] text-outline">只在当前项目、客户和通用素材边界内查询。</div>
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
                            {scopeSummary ? (
                              <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-[11px] text-outline">
                                {scopeSummary}{turbineModelLabel ? `；${turbineModelLabel}` : ''}
                              </div>
                            ) : null}
                            <div className="mt-3 max-h-48 space-y-2 overflow-y-auto">
                              {materialSearch.items.length ? materialSearch.items.map((item) => {
                                return (
                                  <div key={item.id} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                                    <button
                                      type="button"
                                      onClick={() => handlePreviewMaterial(item)}
                                      className="min-w-0 flex-1 text-left"
                                    >
                                      <span className="block font-medium text-on-surface">{item.name}</span>
                                      <span className="mt-1 block break-all text-outline">
                                        {item.id} · {item.hasCleanedWord ? '清洗稿' : '原始 Word'} · {item.folderPath || '-'}
                                      </span>
                                    </button>
                                  </div>
                                )
                              }) : (
                                <p className="text-xs text-outline">
                                  {materialLoading ? '正在查询素材...' : '输入关键词后查询限定素材库。'}
                                </p>
                              )}
                            </div>
                          </section>
                        ) : null}

                        <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                          <div className="text-xs font-semibold text-on-surface">存储位置</div>
                          <div className="mt-2 space-y-2 text-xs">
                            <div className="rounded-md bg-surface-container-low px-3 py-2">
                              <div className="text-[11px] text-outline">来源对象</div>
                              <div className="mt-1 break-all font-medium text-on-surface">{selectedSourceObjectLabel}</div>
                            </div>
                            <div className="rounded-md bg-surface-container-low px-3 py-2">
                              <div className="text-[11px] text-outline">项目工作区</div>
                              <div className="mt-1 break-all font-medium text-on-surface">{selectedWorkDir}</div>
                            </div>
                            <div className="rounded-md bg-surface-container-low px-3 py-2">
                              <div className="text-[11px] text-outline">当前产物</div>
                              <div className="mt-1 break-all font-medium text-on-surface">{selectedBlankPath || selectedMaterialMatch?.material?.path || '-'}</div>
                            </div>
                          </div>
                        </section>

                        {selectedEvidenceRefs.length ? (
                          <details className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                            <summary className="cursor-pointer text-xs font-semibold text-on-surface marker:text-outline">识别依据</summary>
                            <div className="mt-3 space-y-2">
                              {selectedEvidenceRefs.map((ref, index) => (
                                <div key={`${ref.id || ref.title || ref.name}-${index}`} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                                  <div className="font-medium text-on-surface">{ref.title || ref.name || ref.id || '依据'}</div>
                                  <div className="mt-1 break-all text-outline">
                                    {[ref.type, ref.number, ref.folderPath, ref.id].filter(Boolean).join(' · ') || '-'}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : null}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-outline">选择一个目录项查看处理详情</div>
              )}
            </div>

            <section className="flex min-h-0 flex-col bg-white">
              {selected ? (
                <>
                      <div className="flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
                        <div className="min-w-0">
                          <h4 className="truncate text-base font-semibold text-on-surface">
                            {selectedPreviewChoice?.title || 'Office 预览'}
                          </h4>
                          <p className="mt-1 truncate text-xs text-outline" title={selectedPreviewChoice?.subtitle || ''}>
                            {selectedPreviewChoice
                              ? `${previewKindLabels[selectedPreviewChoice.kind] || '预览'} · ${selectedPreviewChoice.subtitle || '-'}`
                              : '选择左侧目录项后显示最终匹配结果。'}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {selectedPreviewChoice ? (
                            <span className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 text-xs font-semibold text-on-primary">
                              <span className="material-symbols-outlined text-[15px]">{previewKindIcons[selectedPreviewChoice.kind] || 'description'}</span>
                              {selectedPreviewChoice.label}
                            </span>
                          ) : null}
                        </div>
                      </div>

                      <div className="min-h-0 flex-1 p-4">
                        {previewLoading ? (
                          <div className="flex h-full min-h-[420px] items-center justify-center rounded-md border border-surface-container-high bg-surface-container-lowest px-6 text-center">
                            <div>
                              <span className="material-symbols-outlined text-4xl text-primary">hourglass_empty</span>
                              <p className="mt-3 text-sm text-on-surface-variant">正在加载预览...</p>
                            </div>
                          </div>
                        ) : previewSession?.onlyoffice ? (
                          <OnlyOfficeEmbed
                            session={previewSession.onlyoffice}
                            mode="view"
                            className="h-full min-h-[420px] w-full rounded-md border border-surface-container-high bg-white"
                            onReady={() => setPreviewError('')}
                            onError={(message) => setPreviewError(message || 'OnlyOffice 预览加载失败')}
                          />
                        ) : (
                          <div className="flex h-full min-h-[420px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
                            <p className="max-w-md text-sm text-on-surface-variant">
                              {previewError || (selectedPreviewChoice ? '当前对象暂时无法预览，请检查素材是否已清洗为 Word。' : '当前目录项还没有可预览的素材、空表或处理产物。')}
                            </p>
                          </div>
                        )}
                      </div>
                </>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-outline">选择一个目录项查看处理详情</div>
              )}
            </section>
          </div>
        )}
      </DataCard>
    </div>
  )
}
