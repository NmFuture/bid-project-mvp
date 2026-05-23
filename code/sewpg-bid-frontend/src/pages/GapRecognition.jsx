import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { gapsAPI, materialsAPI, outlineAPI, parseAPI, projectsAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import Button from '../components/ui/Button'
import Toolbar from '../components/ui/Toolbar'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'
import {
  asArray,
  asObjectArray,
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
  latestResolvedArtifact,
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
    className={`business-metric h-[58px] rounded-md border px-3 text-left transition-colors ${
      active
        ? 'border-primary bg-primary text-on-primary'
        : 'border-surface-container-high bg-surface-container-lowest text-on-surface hover:bg-surface-container-low'
    }`}
  >
    <div className={`text-[11px] ${active ? 'text-on-primary/80' : 'text-outline'}`}>{label}</div>
    <div className="mt-1 text-xl font-headline font-bold">{value}</div>
  </button>
)

const factStatusLabels = {
  empty: '待生成',
  draft: '待确认',
  confirmed: '已确认',
  candidate: '候选',
  missing: '待补充',
  conflict: '冲突',
}

const FactMaintenanceModal = ({
  open,
  factTable,
  fields,
  busy,
  onClose,
  onBuild,
  onConfirm,
  onFieldChange,
  onAddField,
}) => {
  if (!open) return null
  const summary = factTable?.summary || {}
  const status = factTable?.status || 'empty'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-headline font-bold text-on-surface">项目事实表维护</h3>
              <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${status === 'confirmed' ? 'bg-secondary-container text-on-secondary-container' : 'bg-tertiary-fixed text-on-tertiary-fixed'}`}>
                {factStatusLabels[status] || status}
              </span>
            </div>
            <p className="mt-1 text-xs text-on-surface-variant">
              字段：{summary.totalCount || fields.length || 0} · 已确认：{summary.confirmedCount || 0} · 待补充：{summary.missingCount || 0} · 冲突：{summary.conflictCount || 0}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onBuild}
              disabled={busy}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-surface-container-high px-3 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px]">sync</span>
              {fields.length ? '刷新事实' : '生成事实表'}
            </button>
            <button
              type="button"
              onClick={onAddField}
              disabled={busy}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-surface-container-high px-3 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px]">add</span>
              新增字段
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={busy || !fields.length}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px]">fact_check</span>
              确认并用于填写
            </button>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim"
              aria-label="关闭"
            >
              <span className="material-symbols-outlined text-[18px]">close</span>
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-4">
          {fields.length ? (
            <div className="overflow-hidden rounded-md border border-surface-container-high">
              <table className="w-full min-w-[880px] border-collapse bg-surface-container-lowest text-sm">
                <thead className="bg-surface-container-low text-left text-xs text-outline">
                  <tr>
                    <th className="w-36 px-3 py-2 font-semibold">字段</th>
                    <th className="w-64 px-3 py-2 font-semibold">确认值</th>
                    <th className="w-24 px-3 py-2 font-semibold">状态</th>
                    <th className="w-28 px-3 py-2 font-semibold">置信度</th>
                    <th className="px-3 py-2 font-semibold">来源素材/依据</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-high">
                  {fields.map((field, index) => {
                    const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
                    const statusTone = field.status === 'confirmed'
                      ? 'bg-secondary-container text-on-secondary-container'
                      : field.status === 'missing'
                        ? 'bg-tertiary-fixed text-on-tertiary-fixed'
                        : field.status === 'conflict'
                          ? 'bg-error/10 text-error'
                          : 'bg-surface-container-high text-on-surface-variant'
                    const refs = asObjectArray(field.sourceRefs).slice(0, 2)
                    return (
                      <tr key={field.id || `${field.label}-${index}`} className="align-top">
                        <td className="px-3 py-2">
                          {isManualField ? (
                            <input
                              value={field.label || ''}
                              onChange={(event) => onFieldChange(index, 'label', event.target.value)}
                              placeholder="字段名称"
                              className="h-9 w-full rounded-md border border-surface-container-high bg-surface px-2 text-sm font-semibold text-on-surface"
                            />
                          ) : (
                            <div className="font-semibold text-on-surface">{field.label}</div>
                          )}
                          <div className="mt-1 text-[11px] text-outline">{field.category || '项目事实'}</div>
                        </td>
                        <td className="px-3 py-2">
                          <input
                            value={field.value || ''}
                            onChange={(event) => onFieldChange(index, 'value', event.target.value)}
                            className={`h-9 w-full rounded-md border px-2 text-sm text-on-surface ${
                              field.status === 'missing'
                                ? 'border-tertiary bg-tertiary-fixed/40'
                                : 'border-surface-container-high bg-surface'
                            }`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <span className={`inline-flex rounded-md px-2 py-1 text-[11px] font-semibold ${statusTone}`}>
                            {factStatusLabels[field.status] || field.status || '-'}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-xs text-on-surface-variant">
                          {field.confidence ? `${Math.round(Number(field.confidence) * 100)}%` : '-'}
                        </td>
                        <td className="px-3 py-2 text-xs text-on-surface-variant">
                          {refs.length ? refs.map((ref) => (
                            <div key={`${ref.type || ''}-${ref.field || ref.title || ''}`} className="mb-1 truncate" title={[ref.title, ref.field, ref.gapId].filter(Boolean).join(' · ')}>
                              {[ref.title, ref.field, ref.gapId].filter(Boolean).join(' · ')}
                            </div>
                          )) : '-'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex min-h-[260px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest text-center">
              <div>
                <span className="material-symbols-outlined text-4xl text-primary">fact_check</span>
                <p className="mt-3 text-sm text-on-surface-variant">还没有项目事实表，先从项目基础信息、目录缺口、素材和解析字段生成候选事实。</p>
                <button
                  type="button"
                  onClick={onAddField}
                  disabled={busy}
                  className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]">add</span>
                  新增字段
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function GapRecognition({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
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
  const [factModalOpen, setFactModalOpen] = useState(false)
  const [factTable, setFactTable] = useState(null)
  const [factFields, setFactFields] = useState([])

  const loadData = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setLoading(true)
      setError('')
    }
    try {
      const [payload, scopePayload, factsPayload] = await Promise.all([
        gapsAPI.detectionStatus(id),
        projectsAPI.materialsPath(id),
        gapsAPI.facts(id),
      ])
      const items = normalizeItems(payload)
      setData(payload)
      setMaterialScope(scopePayload)
      const nextFacts = factsPayload?.schemaVersion ? factsPayload : payload?.projectFactTable
      setFactTable(nextFacts || null)
      setFactFields(asObjectArray(nextFacts?.fields))
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
  const visiblePreviewChoices = useMemo(() => {
    const choices = [...selectedPreviewChoices]
    if (manualPreviewActive && !choices.some((choice) => choice.key === manualPreviewActive.key)) {
      choices.push(manualPreviewActive)
    }
    return choices
  }, [manualPreviewActive, selectedPreviewChoices])
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
      selectedMaterialMatch?.material,
      ...asObjectArray(selected?.matchedMaterials),
      ...selectedCandidateMaterials,
      ...selectedAppendixTasks.flatMap((task) => asObjectArray(task?.recommendedMaterials)),
    ].filter(Boolean)
    return candidates.filter((item) => {
      const key = String(item?.id || item?.materialId || item?.name || '').trim()
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    }).slice(0, 10)
  })()
  const selectedAiFillReferenceIds = useMemo(
    () => defaultAiFillReferenceMaterialIds(selected),
    [selected],
  )
  const selectedAiFillParseFieldIds = useMemo(
    () => defaultAiFillParseFieldIds(selected, selectedFillTask),
    [selected, selectedFillTask],
  )
  const selectedResolvedArtifact = latestResolvedArtifact(selected)
  const selectedAiFillCompleted = Boolean(
    selectedResolvedArtifact?.source === 'ai_fill'
    || selectedFillTask?.status === 'completed',
  )
  const aiFillActionKey = selected ? `ai-fill:${selected.id}` : 'ai-fill'
  const aiFillBusy = busyAction === aiFillActionKey
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
  const selectedCurrentArtifactPath = selectedResolvedArtifact?.path || selectedBlankPath || selectedMaterialMatch?.material?.path || ''
  const summaryCards = useMemo(() => {
    return [
      ['all', '全部', items.length],
      ['ready', '可直接合并', summary[decisionSummaryKeys.ready] ?? items.filter((item) => decisionOf(item) === 'ready').length],
      ['fill_required', '需填写空表/Word', summary[decisionSummaryKeys.fill_required] ?? items.filter((item) => decisionOf(item) === 'fill_required').length],
      ['material_required', '缺素材', summary[decisionSummaryKeys.material_required] ?? items.filter((item) => decisionOf(item) === 'material_required').length],
      ['review_required', '需人工复核', summary[decisionSummaryKeys.review_required] ?? items.filter((item) => decisionOf(item) === 'review_required').length],
    ]
  }, [items, summary])
  const factConfirmed = factTable?.status === 'confirmed'
  const fillablePendingCount = useMemo(() => items.filter((item) => (
    decisionOf(item) === 'fill_required'
    && asObjectArray(item?.fillTasks).some((task) => task?.status !== 'completed')
  )).length, [items])

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
    () => gapsAPI.runDetection(id),
    (payload) => payload?.message || '缺口识别完成',
  )

  const loadFactTable = async ({ build = false } = {}) => {
    if (busyAction) return null
    setBusyAction(build ? 'facts-build' : 'facts-load')
    try {
      const payload = build ? await gapsAPI.buildFacts(id) : await gapsAPI.facts(id)
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      return payload
    } catch (e) {
      showToast?.(e?.message || '项目事实表加载失败', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

  const ensureFactTableReady = async () => {
    if (factTable?.status === 'confirmed') return true
    if (busyAction) return false

    setBusyAction('facts-auto')
    try {
      const currentFields = factFields.length
        ? factFields
        : asObjectArray((await gapsAPI.buildFacts(id))?.fields)
      const fieldsToSave = currentFields.filter((field) => String(field.label || field.value || '').trim())
      const payload = await gapsAPI.saveFacts(id, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
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
    setFactFields((current) => current.map((field, idx) => (
      idx === index
        ? {
            ...field,
            [key]: value,
            status: String(key === 'value' ? value : field.value || '').trim()
              ? (field.status === 'confirmed' ? 'confirmed' : 'candidate')
              : 'missing',
          }
        : field
    )))
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
        status: 'missing',
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
      const payload = await gapsAPI.saveFacts(id, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      showToast?.('项目事实表已确认，可以开始 AI 填写')
      return payload
    } catch (e) {
      showToast?.(e?.message || '项目事实表确认失败', 'error')
      return null
    } finally {
      setBusyAction('')
    }
  }

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
    const materialId = String(material?.id || material?.materialId || '').trim()
    if (!selected || !materialId) return
    const existing = selectedPreviewChoices.find((choice) => (
      choice.kind === 'material' && String(choice.material?.id || choice.material?.materialId || '') === materialId
    ))
    if (existing) {
      setPreviewChoiceKey(existing.key)
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
  }

  const handleAiFillAll = async () => {
    if (!factConfirmed && !(await ensureFactTableReady())) {
      return null
    }
    const payload = await runAction(
      'ai-fill-all',
      () => gapsAPI.aiFillAll(id, { operator: '当前用户' }),
      (result) => `一键填写完成：通过 ${result?.summary?.passed || 0} 项，待复核 ${result?.summary?.needsReview || 0} 项`,
    )
    if (payload) {
      setPreviewChoiceKey('')
      setPreviewSession(null)
      setPreviewError('')
      setManualPreviewChoice(null)
    }
    return payload
  }

  const handleAiFill = async () => {
    if (!selected || !selectedFillTask) return null
    if (!factConfirmed && !(await ensureFactTableReady())) {
      return null
    }
    const referenceIds = selectedAiFillReferenceIds
    const referenceMaterials = selectedReferenceCandidates.filter((material) => (
      referenceIds.includes(String(material?.id || material?.materialId || '').trim())
    ))
    const payload = await runAction(
      aiFillActionKey,
      () => gapsAPI.aiFill(id, selected.id, {
        fillTaskId: selectedFillTask.id,
        referenceMaterialIds: referenceIds,
        referenceMaterials,
        parseFieldIds: selectedAiFillParseFieldIds,
        operator: '当前用户',
      }),
      (result) => (result?.artifact?.fileName ? `AI填写完成：${result.artifact.fileName}` : 'AI填写完成'),
    )
    if (payload) {
      setPreviewChoiceKey('')
      setPreviewSession(null)
      setPreviewError('')
      setManualPreviewChoice(null)
    }
    return payload
  }

  const handleAdvanceToS4 = async () => {
    if (busyAction) return
    setBusyAction('advance-s4')
    try {
      await outlineAPI.confirm(id)
      await stagesAPI.update(id, 3, { status: 'completed', allowUnconfirmedTechnicalGap: true })
      showToast?.(isCompleted ? '素材匹配已确认，已进入标书生成。' : '已跳过素材匹配，进入标书生成。')
      navigate(projectRoute(id, '/generate', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入标书生成失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  if (loading) return <PageLoading title="正在加载素材匹配..." />
  if (error) return <PageError title="素材匹配加载失败" description={error} onRetry={loadData} />

  return (
    <div className="stage-page business-ui-shell flex flex-col gap-6 animate-fade-in w-full max-w-none">
      <StageBreadcrumb currentLabel="素材匹配" />
      <ProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actionsClassName="stage-header-actions"
        actions={(
          <Toolbar>
            <Button
              type="button"
              onClick={handleAiFillAll}
              disabled={Boolean(busyAction) || !isCompleted || !fillablePendingCount}
              size="stage"
              variant="primary"
            >
              {busyAction === 'ai-fill-all' ? '一键填写中...' : `一键AI填写${fillablePendingCount ? `(${fillablePendingCount})` : ''}`}
            </Button>
            <Button
              type="button"
              onClick={() => loadData()}
              size="stage"
              variant="quiet"
            >
              刷新
            </Button>
            <Button
              type="button"
              onClick={handleRunDetection}
              disabled={Boolean(busyAction)}
              size="stage"
              variant="primary"
            >
              {busyAction === 'detect' ? '识别中...' : isCompleted ? '重新识别缺口' : '识别缺口'}
            </Button>
            <Button
              type="button"
              onClick={handleAdvanceToS4}
              disabled={Boolean(busyAction)}
              title={isCompleted ? '进入标书生成；未确认的技术缺口会在生成和共创阶段继续提示' : '技术标已允许跳过素材匹配直接进入标书生成'}
              size="stage"
              variant="success"
            >
              {busyAction === 'advance-s4' ? '进入中...' : '进入标书生成'}
            </Button>
          </Toolbar>
        )}
      />

      {isCompleted ? (
        <div className="grid auto-rows-max gap-2 sm:grid-cols-2 lg:grid-cols-5">
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

      <DataCard className="!p-0 overflow-hidden business-panel">
        <div className="business-section-head border-b border-surface-container-high px-4 py-3">
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
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="text-xs font-semibold text-on-surface">待填写对象</div>
                                <div className="mt-1 truncate text-[11px] text-outline" title={selectedBlankSource?.title || ''}>
                                  {selectedBlankSource?.title || '待填写空表/Word'}
                                </div>
                              </div>
                              <span className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ${
                                aiFillBusy
                                  ? 'bg-primary/10 text-primary'
                                  : selectedAiFillCompleted
                                    ? 'bg-secondary-container text-on-secondary-container'
                                    : factConfirmed
                                      ? 'bg-tertiary-fixed text-on-tertiary-fixed'
                                      : 'bg-error/10 text-error'
                              }`}>
                                <span className="material-symbols-outlined text-[15px]">
                                  {selectedAiFillCompleted ? 'task_alt' : aiFillBusy ? 'pending' : factConfirmed ? 'edit_document' : 'rule_settings'}
                                </span>
                                {aiFillBusy ? 'AI填写中' : selectedAiFillCompleted ? 'AI已填写' : '等待AI填写'}
                              </span>
                            </div>
                            <div className="mt-3 grid grid-cols-1 gap-2">
                              <MiniFact label="执行 Skill" value={selectedFillTask?.skill || 'bid-tech-table-filler'} />
                              <MiniFact label="空白来源" value={selectedBlankSource?.sourceFile || selectedBlankSource?.folderPath || selectedBlankSource?.id || '-'} />
                            </div>
                            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-container-low px-3 py-2">
                              <div className="min-w-0 text-xs">
                                <div className="font-semibold text-on-surface">
                                  {selectedAiFillCompleted ? '已生成填写结果' : '待执行 AI 填写'}
                                </div>
                                <div className="mt-1 truncate text-outline" title={selectedResolvedArtifact?.fileName || selectedBlankPath || ''}>
                                  {selectedResolvedArtifact?.fileName || selectedBlankPath || '尚未生成填写产物'}
                                </div>
                              </div>
                              <button
                                type="button"
                                onClick={handleAiFill}
                                disabled={Boolean(busyAction) || !selectedFillTask}
                                className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                <span className="material-symbols-outlined text-[16px]">auto_fix_high</span>
                                {aiFillBusy ? 'AI填写中...' : selectedAiFillCompleted ? '重新AI填写' : 'AI填写'}
                              </button>
                            </div>
                            {selectedResolvedArtifact?.qualityReport ? (
                              <div className="mt-3 grid grid-cols-3 gap-2">
                                <MiniFact label="覆盖率" value={`${Math.round(Number(selectedResolvedArtifact.qualityReport.coverageRate || 0) * 100)}%`} />
                                <MiniFact label="正确率" value={`${Math.round(Number(selectedResolvedArtifact.qualityReport.correctnessRate || 0) * 100)}%`} />
                                <MiniFact label="完整率" value={`${Math.round(Number(selectedResolvedArtifact.qualityReport.completenessRate || 0) * 100)}%`} />
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
                            {selectedReferenceCandidates.length ? (
                              <div className="mt-3 space-y-2">
                                <div className="text-[11px] font-semibold text-on-surface">填写来源素材</div>
                                {selectedReferenceCandidates.map((material) => (
                                  <button
                                    key={material.id || material.materialId || material.name}
                                    type="button"
                                    onClick={() => handlePreviewMaterial(material)}
                                    className="block w-full rounded-md bg-surface-container-low px-3 py-2 text-left text-xs hover:bg-surface-container-high"
                                    title={material.path || material.folderPath || material.id}
                                  >
                                    <span className="flex items-start justify-between gap-2">
                                      <span className="min-w-0 font-medium text-on-surface">{material.name || material.cleanedFileName || material.id}</span>
                                      {selectedAiFillReferenceIds.includes(String(material.id || material.materialId || '').trim()) ? (
                                        <span className="shrink-0 rounded bg-secondary-container px-1.5 py-0.5 text-[10px] font-semibold text-on-secondary-container">
                                          用于AI
                                        </span>
                                      ) : null}
                                    </span>
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
                              <div className="mt-1 break-all font-medium text-on-surface">{selectedCurrentArtifactPath || '-'}</div>
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
                          {visiblePreviewChoices.length > 1 ? (
                            visiblePreviewChoices.map((choice) => {
                              const active = selectedPreviewChoice?.key === choice.key
                              return (
                                <button
                                  key={choice.key}
                                  type="button"
                                  onClick={() => setPreviewChoiceKey(choice.key)}
                                  className={`inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-colors ${
                                    active
                                      ? 'bg-primary text-on-primary'
                                      : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim'
                                  }`}
                                >
                                  <span className="material-symbols-outlined text-[15px]">{previewKindIcons[choice.kind] || 'description'}</span>
                                  {choice.label}
                                </button>
                              )
                            })
                          ) : selectedPreviewChoice ? (
                            <span className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 text-xs font-semibold text-on-primary">
                              <span className="material-symbols-outlined text-[15px]">{previewKindIcons[selectedPreviewChoice.kind] || 'description'}</span>
                              {selectedPreviewChoice.label}
                            </span>
                          ) : null}
                        </div>
                      </div>

                      <div className="min-h-0 flex-1 p-4">
                        {previewLoading ? (
                          <div className="flex h-full min-h-[480px] items-center justify-center rounded-md border border-surface-container-high bg-surface-container-lowest px-6 text-center">
                            <div>
                              <span className="material-symbols-outlined text-4xl text-primary">hourglass_empty</span>
                              <p className="mt-3 text-sm text-on-surface-variant">正在加载预览...</p>
                            </div>
                          </div>
                        ) : previewSession?.onlyoffice ? (
                          <OnlyOfficeEmbed
                            session={previewSession.onlyoffice}
                            mode="view"
                            className="h-full min-h-[480px] w-full rounded-md border border-surface-container-high bg-white"
                            onReady={() => setPreviewError('')}
                            onError={(message) => setPreviewError(message || 'OnlyOffice 预览加载失败')}
                          />
                        ) : (
                          <div className="flex h-full min-h-[480px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
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
      <FactMaintenanceModal
        open={factModalOpen}
        factTable={factTable}
        fields={factFields}
        busy={['facts-build', 'facts-load', 'facts-confirm'].includes(busyAction)}
        onClose={() => setFactModalOpen(false)}
        onBuild={() => loadFactTable({ build: true })}
        onConfirm={handleConfirmFactTable}
        onFieldChange={handleFactFieldChange}
        onAddField={handleAddFactField}
      />
    </div>
  )
}
