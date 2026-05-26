import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalGapsAPI, technicalGenerateAPI, technicalMaterialsAPI, technicalParseAPI, technicalProjectsAPI, technicalStagesAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import DataCard from '../../../components/shared/DataCard'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
import Toolbar from '../../../components/ui/Toolbar'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'
import {
  asArray,
  asObjectArray,
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
  latestResolvedArtifact,
  matchedMaterialForItem,
  previewChoicesForItem,
  primaryBlankSource,
  uniqueStrings,
} from './technicalGapRecognitionHelpers'

const decisionConfig = {
  ready: true,
  fill_required: true,
  material_required: true,
  review_required: true,
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

const taskActionLabels = {
  fixed_material: '固定素材',
  manual_select: '人工指定',
  manual_upload: '人工补料',
  ignored: '忽略',
  ai_table_fill: 'AI填表',
}

const taskActionVariant = (mode) => {
  if (mode === 'ignored') return 'pending'
  if (mode === 'ai_table_fill') return 'info'
  if (mode === 'manual_upload') return 'error'
  if (mode === 'manual_select') return 'warn'
  return 'done'
}

const isStructuralItem = (item) => (
  String(item?.status || '') === 'structural'
    || String(item?.usage || '') === 'structural'
    || asArray(item?.usages).includes('structural')
)

const technicalActionMode = (item) => {
  if (!item || isStructuralItem(item)) return ''
  const decision = decisionOf(item)
  if (decision === 'fill_required') return 'ai_table_fill'
  if (decision === 'material_required') return 'manual_upload'
  if (decision === 'review_required') return 'manual_select'
  if (decision === 'ready') return 'fixed_material'
  if (String(item.status || '') === 'ignored') return 'ignored'
  if (String(item.status || '') === 'resolved' || String(item.status || '') === 'matched') return 'fixed_material'
  return 'manual_upload'
}

function TechnicalTocActionBadge({ item }) {
  const mode = technicalActionMode(item)
  if (!mode) {
    return <Badge className="business-toc-status-badge" shape="square" size="xs" variant="pending">空章节</Badge>
  }
  return (
    <Badge className="business-toc-status-badge" shape="square" size="xs" variant={taskActionVariant(mode)}>
      {taskActionLabels[mode]}
    </Badge>
  )
}

function StatCard({ label, value }) {
  return (
    <div className="business-metric rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex min-h-7 items-center justify-between gap-3">
        <div className="min-w-0 truncate text-xs font-semibold text-on-surface-variant">{label}</div>
        <div className="shrink-0 text-lg font-headline font-bold tabular-nums text-primary">{value || 0}</div>
      </div>
    </div>
  )
}

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
              保存
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

function TechnicalGenerationProgressModal({
  open,
  status,
  progress,
  onClose,
}) {
  if (!open) return null
  const running = status?.status === 'running'
  const completed = status?.status === 'completed'
  const failed = status?.status === 'failed'
  const title = running ? '正在生成技术标正文' : completed ? '技术标正文已生成' : failed ? '技术标正文生成失败' : '技术标正文生成'
  const summary = status?.summary || (running ? '系统正在根据当前素材匹配结果生成正文。' : completed ? '可继续进入共创导出。' : failed ? '请检查任务状态后重新生成。' : '准备生成技术标正文。')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="w-full max-w-xl rounded-lg bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">{title}</h3>
            <p className="mt-1 text-sm text-on-surface-variant">{summary}</p>
          </div>
          {!running ? <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" /> : null}
        </div>
        <div className="space-y-4 p-5">
          <div className="flex items-center gap-3">
            <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-container-high">
              <div
                className={`h-full transition-all duration-700 ${failed ? 'bg-error' : 'bg-primary'}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-12 text-right text-xs font-semibold text-outline">{progress}%</span>
          </div>
          {completed ? (
            <div className="rounded-md border border-secondary/20 bg-secondary-container/40 px-3 py-2 text-sm text-on-secondary-container">
              技术标正文已生成。可返回本页继续调整素材匹配并重新生成，或进入共创导出。
            </div>
          ) : null}
          {failed ? (
            <div className="rounded-md border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
              {status?.error || '生成失败，请稍后重试。'}
            </div>
          ) : null}
        </div>
        <div className="flex justify-end border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <Button type="button" onClick={onClose} disabled={running} variant={completed ? 'primary' : 'quiet'}>
            {running ? '生成中...' : '关闭'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function TechnicalPreviewModal({
  open,
  selectedPreviewChoice,
  visiblePreviewChoices,
  previewLoading,
  previewSession,
  previewError,
  onSelectPreviewChoice,
  onClose,
}) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4 py-6">
      <section className="flex max-h-[92vh] w-full max-w-7xl flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex min-h-[58px] flex-wrap items-center justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-4 py-3">
          <div className="min-w-0">
            <h4 className="truncate text-base font-semibold text-on-surface">
              {selectedPreviewChoice?.title || '素材预览'}
            </h4>
            <p className="mt-1 truncate text-xs text-outline" title={selectedPreviewChoice?.subtitle || ''}>
              {selectedPreviewChoice
                ? `${previewKindLabels[selectedPreviewChoice.kind] || '预览'} · ${selectedPreviewChoice.subtitle || '-'}`
                : '当前目录项还没有可预览的素材、空表或处理产物。'}
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
                    onClick={() => onSelectPreviewChoice(choice.key)}
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
            <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
          </div>
        </div>

        <div className="min-h-0 flex-1 p-4">
          {previewLoading ? (
            <div className="flex h-[min(76vh,760px)] min-h-[520px] items-center justify-center rounded-md border border-surface-container-high bg-surface-container-lowest px-6 text-center">
              <div>
                <span className="material-symbols-outlined text-4xl text-primary">hourglass_empty</span>
                <p className="mt-3 text-sm text-on-surface-variant">正在加载预览...</p>
              </div>
            </div>
          ) : previewSession?.onlyoffice ? (
            <OnlyOfficeEmbed
              session={previewSession.onlyoffice}
              mode="view"
              className="h-[min(76vh,760px)] min-h-[520px] w-full rounded-md border border-surface-container-high bg-white"
              onError={() => {}}
            />
          ) : (
            <div className="flex h-[min(76vh,760px)] min-h-[520px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
              <p className="max-w-md text-sm text-on-surface-variant">
                {previewError || (selectedPreviewChoice ? '当前对象暂时无法预览，请检查素材是否已清洗为 Word。' : '当前目录项还没有可预览的素材、空表或处理产物。')}
              </p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

export default function TechnicalGapRecognition({ showToast }) {
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
  const [previewChoiceKey, setPreviewChoiceKey] = useState('')
  const [previewSession, setPreviewSession] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [manualPreviewChoice, setManualPreviewChoice] = useState(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [factModalOpen, setFactModalOpen] = useState(false)
  const [factTable, setFactTable] = useState(null)
  const [factFields, setFactFields] = useState([])
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationModalOpen, setGenerationModalOpen] = useState(false)

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
  const filteredItems = items
  const effectiveSelectedId = filteredItems.some((item) => item.id === selectedId)
    ? selectedId
    : (filteredItems[0]?.id || '')
  const selected = useMemo(
    () => filteredItems.find((item) => item.id === effectiveSelectedId) || null,
    [effectiveSelectedId, filteredItems],
  )
  const summary = useMemo(() => data?.gapPlan?.summary || data?.summary || {}, [data])
  const isCompleted = data?.status === 'completed'
  const readableScopes = useMemo(
    () => (Array.isArray(materialScope?.readableScopes) ? materialScope.readableScopes : []),
    [materialScope],
  )
  const scopePaths = useMemo(
    () => readableScopes.map((scope) => String(scope?.path || '')).filter(Boolean),
    [readableScopes],
  )
  const projectTurbineModel = data?.gapPlan?.projectTurbineModel || data?.projectTurbineModel || materialScope?.turbineModel || null
  const selectedDecision = decisionOf(selected)
  const selectedActionMode = technicalActionMode(selected)
  const selectedAppendixTasks = asArray(selected?.appendixTasks)
  const selectedCandidateMaterials = asObjectArray(selected?.candidateMaterials)
  const selectedMaterialMatch = matchedMaterialForItem(selected, items)
  const selectedBlankSource = primaryBlankSource(selected)
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
  const actionCounts = useMemo(() => ({
    fixed_material: items.filter((item) => technicalActionMode(item) === 'fixed_material').length,
    ai_table_fill: items.filter((item) => technicalActionMode(item) === 'ai_table_fill').length,
    manual_upload: items.filter((item) => technicalActionMode(item) === 'manual_upload').length,
    manual_select: items.filter((item) => technicalActionMode(item) === 'manual_select').length,
  }), [items])
  const factConfirmed = factTable?.status === 'confirmed'
  const hasTechnicalGapPlan = data?.status === 'completed' && Boolean(data?.gapPlan || items.length)
  const generationRunning = generationStatus?.status === 'running'
  const generationCompleted = generationStatus?.status === 'completed'
  const generationProgress = Math.max(0, Math.min(100, Number(generationStatus?.percentage) || 0))

  useEffect(() => {
    let cancelled = false
    const loadPreview = async () => {
      setPreviewSession(null)
      setPreviewError('')

      if (!previewOpen || !selectedPreviewChoice) return

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
          ? await technicalParseAPI.appendixPreview(id, selectedPreviewChoice.blankSource.id)
          : await technicalMaterialsAPI.raw.previewCleanedFile(selectedPreviewChoice.material.id)
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
  }, [id, previewOpen, selectedPreviewChoice])

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

  const loadFactTable = async ({ build = false } = {}) => {
    if (busyAction) return null
    setBusyAction(build ? 'facts-build' : 'facts-load')
    try {
      const payload = build ? await technicalGapsAPI.buildFacts(id) : await technicalGapsAPI.facts(id)
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
      const payload = await technicalGapsAPI.saveFacts(id, { fields: fieldsToSave, confirm: true, operator: '当前用户' })
      setFactTable(payload)
      setFactFields(asObjectArray(payload?.fields))
      setData((current) => current ? { ...current, projectFactTable: payload } : current)
      showToast?.('项目事实表已保存，可以开始 AI 填写')
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
      () => technicalGapsAPI.aiFill(id, selected.id, {
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

  useEffect(() => {
    if (!generationRunning) return undefined
    const timer = window.setInterval(() => {
      loadGenerationStatus()
    }, 1200)
    return () => window.clearInterval(timer)
  }, [generationRunning, loadGenerationStatus])

  const runTechnicalAssembly = async () => {
    if (busyAction) return
    if (!hasTechnicalGapPlan) {
      showToast?.('素材匹配完成后可生成技术标正文。', 'error')
      return
    }
    setBusyAction('technical-generate')
    setGenerationModalOpen(true)
    try {
      const payload = await technicalGenerateAPI.run(id)
      setGenerationStatus(payload)
      loadGenerationStatus()
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

  if (loading) return <PageLoading title="正在加载素材匹配..." />
  if (error) return <PageError title="素材匹配加载失败" description={error} onRetry={loadData} />

  return (
    <div className="business-ui-shell flex flex-col gap-6">
      <TechnicalProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actions={(
          <Toolbar>
            <Button
              type="button"
              onClick={() => setFactModalOpen(true)}
              disabled={Boolean(busyAction) || data?.status !== 'completed'}
              size="stage"
              variant={factConfirmed ? 'secondary' : 'quiet'}
            >
              {factConfirmed ? '项目事实表已确认' : '维护项目事实表'}
            </Button>
            <Button
              type="button"
              onClick={runTechnicalAssembly}
              disabled={Boolean(busyAction) || !hasTechnicalGapPlan || generationRunning}
              title={!hasTechnicalGapPlan ? '素材匹配完成后可生成正文' : '允许带未确认项生成正文，生成结果会保留复核提示'}
              size="stage"
              variant="primary"
            >
              {generationRunning ? '生成中...' : generationCompleted ? '重新生成正文' : '生成技术标正文'}
            </Button>
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

      {isCompleted ? (
        <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.56fr)]">
          <div className="grid auto-rows-max gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="目录节点" value={summary.totalTocItems ?? items.length} />
            <StatCard label="处理任务" value={items.length} />
            <StatCard label="待处理" value={(actionCounts.manual_upload || 0) + (actionCounts.manual_select || 0)} />
            <StatCard label="已就绪" value={actionCounts.fixed_material || 0} />
          </div>
          <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="flex min-h-7 items-center gap-2">
              <div className="shrink-0 text-xs font-semibold text-on-surface-variant">处理方式统计</div>
              <div className="grid min-w-0 flex-1 grid-cols-4 gap-1.5 text-center">
                {[
                  ['fixed_material', '固定素材'],
                  ['ai_table_fill', 'AI填表'],
                  ['manual_upload', '人工补充'],
                  ['manual_select', '人工指定'],
                ].map(([key, label]) => (
                  <div key={key} className="flex min-h-7 items-center justify-center gap-1 rounded-md bg-surface-container-low px-2 py-0.5">
                    <span className="text-[11px] text-on-surface-variant">{label}</span>
                    <span className="text-sm font-headline font-bold tabular-nums text-primary">{actionCounts[key] || 0}</span>
                  </div>
                ))}
              </div>
            </div>
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
          <div className="grid min-h-[720px] gap-4 p-3 xl:grid-cols-[460px_minmax(0,1fr)] 2xl:grid-cols-[520px_minmax(0,1fr)]">
            <div className="min-h-0 flex flex-col overflow-hidden">
              <div className="h-12 shrink-0 px-2 py-3">
                <div className="text-xs font-semibold text-on-surface">
                  目录项 · {filteredItems.length}/{items.length}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
                <div>
                  {filteredItems.map((item) => {
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
                          setPreviewOpen(false)
                        }}
                        className={`business-toc-item mb-2 block h-auto w-full rounded-md border px-3 py-3 text-left transition-colors ${active ? 'border-primary bg-primary-fixed shadow-sm' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}
                        data-active={active ? 'true' : 'false'}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[11px] font-medium text-outline">{item.number || item.section || '-'}</div>
                            <div className="mt-1 line-clamp-2 text-sm font-semibold leading-snug text-on-surface">{item.title}</div>
                          </div>
                          <TechnicalTocActionBadge item={item} />
                        </div>
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

            <div className="min-h-0 overflow-hidden rounded-md border border-surface-container-high bg-surface-container-lowest">
              {selected ? (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="shrink-0 border-b border-surface-container-high bg-surface-container-lowest px-5 py-4">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0">
                        <div className="text-xs font-medium text-outline">{selected.number || selected.section || '-'}</div>
                        <h3 className="mt-1 text-lg font-headline font-bold leading-snug text-on-surface">{selected.title}</h3>
                      </div>
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 overflow-y-auto bg-surface-container-low">
                    <div className="space-y-4 p-4">
                      {!selectedActionMode ? (
                        <div className="business-dropzone rounded-md border border-dashed border-surface-container-high p-8 text-center">
                          <span className="material-symbols-outlined text-4xl text-outline">inventory_2</span>
                          <h3 className="mt-3 text-base font-headline font-bold text-on-surface">当前章节暂无系统任务</h3>
                          <p className="mt-2 text-sm text-on-surface-variant">结构性目录项不需要单独匹配素材。</p>
                        </div>
                      ) : (
                        <>
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

                        </>
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
      <TechnicalGenerationProgressModal
        open={generationModalOpen || generationRunning}
        status={generationStatus}
        progress={generationProgress}
        onClose={() => setGenerationModalOpen(false)}
      />
      <TechnicalPreviewModal
        open={previewOpen}
        selectedPreviewChoice={selectedPreviewChoice}
        visiblePreviewChoices={visiblePreviewChoices}
        previewLoading={previewLoading}
        previewSession={previewSession}
        previewError={previewError}
        onSelectPreviewChoice={(key) => setPreviewChoiceKey(key)}
        onClose={() => setPreviewOpen(false)}
      />
    </div>
  )
}
