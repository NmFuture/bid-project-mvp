import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { gapsAPI, generateAPI, materialsAPI, projectsAPI, reviewAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'
import {
  asArray,
  asObjectArray,
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
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
    label: '需填写空表',
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

const decisionFilterOptions = [
  { key: 'all', label: '全部' },
  { key: 'ready', label: '可直接合并' },
  { key: 'fill_required', label: '需填写空表' },
  { key: 'material_required', label: '缺素材' },
  { key: 'review_required', label: '需人工复核' },
]

const decisionSummaryKeys = {
  ready: 'readyCount',
  fill_required: 'fillRequiredCount',
  material_required: 'materialRequiredCount',
  review_required: 'reviewRequiredCount',
}

const nextActionLabels = {
  s4_merge_material: '合并进标书',
  ai_fill_appendix: '调用填写 Skill',
  select_reference_material: '选择参考素材',
  select_material: '选择已有素材',
  confirm_material_usage: '确认素材用法',
  replace_material: '替换素材',
  manual_upload: '上传补充资料',
  ignore: '人工忽略',
}

const usageLabels = {
  chapter_master: '整章合并',
  covered_by_parent: '父章覆盖',
  section_merge: '章节合并',
  table_source: '空表填写参考',
  appendix_fill: '副表填写',
  structural: '结构章节',
  both: '合并与填写',
}

const turbineStatusLabels = {
  matched: '机型匹配',
  generic: '通用素材',
  conflict: '机型冲突',
  unknown: '未命中素材',
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

const configForItem = (item) => {
  const decision = decisionOf(item)
  return decision ? decisionConfig[decision] : (statusConfig[item?.status] || statusConfig.missing)
}

const labelForAction = (action) => nextActionLabels[action] || action

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

const readFileAsDataUrl = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(String(reader.result || ''))
  reader.onerror = () => reject(reader.error || new Error('文件读取失败'))
  reader.readAsDataURL(file)
})

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
  const [selectedMaterialIds, setSelectedMaterialIds] = useState([])
  const [materialScope, setMaterialScope] = useState(null)
  const [decisionFilter, setDecisionFilter] = useState('all')
  const fileInputRef = useRef(null)

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
  const selectedMaterialItems = useMemo(
    () => materialSearch.items.filter((item) => selectedMaterialIds.includes(item.id)),
    [materialSearch.items, selectedMaterialIds],
  )
  const summary = useMemo(() => data?.gapPlan?.summary || data?.summary || {}, [data])
  const integrity = useMemo(() => data?.gapPlan?.integrity || data?.integrity || {}, [data])
  const sampleVersion = data?.gapPlan?.sampleVersion || data?.sampleVersion || ''
  const isCompleted = data?.status === 'completed'
  const canGenerate = isCompleted && (integrity?.status === 'passed' || Number(summary?.blockingCount || 0) === 0)
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
  const selectedFillTasks = asArray(selected?.fillTasks)
  const selectedCandidateMaterials = asObjectArray(selected?.candidateMaterials)
  const selectedUsages = compactList([
    selected?.usage,
    ...asObjectArray(selected?.matchedMaterials).map((item) => item.usage),
    ...selectedCandidateMaterials.map((item) => item.usage),
    ...selectedAppendixTasks.flatMap((task) => asObjectArray(task?.recommendedMaterials).map((item) => item.usage)),
  ], 4)
  const selectedAllowedPaths = compactList(selectedMaterialScope.allowedPaths)
  const selectedMatchedPaths = compactList(selectedMaterialScope.actualMatchedPaths)
  const selectedNextActions = compactList(selected?.nextActions, 6)
  const selectedEvidenceRefs = asArray(selected?.evidenceRefs).slice(0, 6)
  const summaryCards = useMemo(() => {
    const fillTaskCount = items.reduce((total, item) => total + asArray(item.fillTasks).length, 0)
    return [
      ['ready', '可直接合并', summary[decisionSummaryKeys.ready] ?? items.filter((item) => decisionOf(item) === 'ready').length],
      ['fill_required', '需填写空表', summary[decisionSummaryKeys.fill_required] ?? items.filter((item) => decisionOf(item) === 'fill_required').length],
      ['material_required', '缺素材', summary[decisionSummaryKeys.material_required] ?? items.filter((item) => decisionOf(item) === 'material_required').length],
      ['review_required', '需人工复核', summary[decisionSummaryKeys.review_required] ?? items.filter((item) => decisionOf(item) === 'review_required').length],
      ['fill_tasks', 'AI 填写任务', summary.fillableTaskCount ?? fillTaskCount],
    ]
  }, [items, summary])

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
    } catch (e) {
      showToast?.(e?.message || '操作失败，请稍后重试', 'error')
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
      setSelectedMaterialIds((prev) => prev.filter((id) => items.some((item) => item.id === id)))
    } catch (e) {
      showToast?.(e?.message || '查询素材失败', 'error')
    } finally {
      setMaterialLoading(false)
    }
  }

  const toggleMaterial = (materialId) => {
    setSelectedMaterialIds((prev) => (
      prev.includes(materialId)
        ? prev.filter((item) => item !== materialId)
        : [...prev, materialId]
    ))
  }

  const handleSelectMaterials = () => {
    if (!selected || !selectedMaterialItems.length) {
      showToast?.('请先选择素材。', 'error')
      return
    }
    return runAction(
      `select-${selected.id}`,
      () => gapsAPI.selectMaterial(id, selected.id, {
        materials: selectedMaterialItems.map((item) => ({
          id: item.id,
          name: item.name,
          folderPath: item.folderPath,
          materialTier: item.materialTier,
                        cleanedFileName: item.cleanedFileName,
                        turbineModel: item.turbineModel,
                        turbineModelLabel: item.turbineModelLabel,
                      })),
      }),
      () => '已选择已有素材并挂回缺口计划。',
    )
  }

  const handleAiFill = () => {
    if (!selected?.fillTasks?.length) {
      showToast?.('当前目录项没有可执行的 AI 填写任务。', 'error')
      return
    }
    const task = selected.fillTasks[0]
    return runAction(
      `ai-${selected.id}`,
      () => gapsAPI.aiFill(id, selected.id, {
        fillTaskId: task.id,
        referenceMaterialIds: defaultAiFillReferenceMaterialIds(selected, selectedMaterialIds),
        parseFieldIds: defaultAiFillParseFieldIds(selected, task),
      }),
      () => 'AI 填写完成，产物已挂回缺口计划。',
    )
  }

  const handleIgnore = () => {
    if (!selected) return
    return runAction(
      `ignore-${selected.id}`,
      () => gapsAPI.updateMissing(id, selected.id, { status: 'skipped', reason: '人工确认本项目不适用或无需补充。' }),
      () => '已记录人工忽略原因。',
    )
  }

  const handleUploadPicked = async (event) => {
    const files = Array.from(event.target.files || [])
    if (event.target) event.target.value = ''
    if (!selected || !files.length) return
    if (busyAction) return
    setBusyAction(`upload-${selected.id}`)
    try {
      const payload = await gapsAPI.upload(id, selected.id, {
        bidType: '技术标',
        files: await Promise.all(files.map(async (file) => ({
          name: file.name,
          type: file.type || 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
          size: Number(file.size || 0),
          data: await readFileAsDataUrl(file),
        }))),
      })
      updatePayload(payload)
      showToast?.('客户资料已上传并挂回缺口计划。')
    } catch (e) {
      showToast?.(e?.message || '上传客户资料失败', 'error')
    } finally {
      setBusyAction('')
    }
  }

  const handleRecheck = () => runAction(
    'recheck',
    async () => {
      await gapsAPI.recheck(id)
      return gapsAPI.detectionStatus(id)
    },
    () => '缺口完整性校验完成。',
  )

  const handleSubmitAndGenerate = () => runAction(
    'generate',
    async () => {
      await gapsAPI.submitReview(id)
      await reviewAPI.prepareParse(id)
      await reviewAPI.confirm(id)
      await stagesAPI.update(id, 3, { status: 'completed' })
      const started = await generateAPI.run(id)
      navigate(projectRoute(id, '/generate', workspaceSlug))
      return started
    },
    (payload) => payload?.message || '已通过缺口校验并开始生成标书。',
  )

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
            <button
              onClick={handleRecheck}
              disabled={!isCompleted || Boolean(busyAction)}
              className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busyAction === 'recheck' ? '检查中...' : '重新检查缺口'}
            </button>
            <button
              onClick={handleSubmitAndGenerate}
              disabled={!canGenerate || Boolean(busyAction)}
              title={!canGenerate ? '全部缺口解决后可生成标书' : ''}
              className="px-4 py-2.5 bg-secondary text-on-secondary text-sm font-medium rounded-lg hover:bg-secondary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busyAction === 'generate' ? '提交中...' : '生成标书'}
            </button>
          </>
        )}
      />

      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
        {summaryCards.map(([key, label, value]) => {
          const cfg = decisionConfig[key] || {
            icon: 'edit_note',
            tone: 'bg-surface-container-high text-on-surface-variant',
          }
          return (
            <DataCard key={key} className="!p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-on-surface-variant">{label}</div>
                <span className={`inline-flex h-8 w-8 items-center justify-center rounded-md ${cfg.tone}`}>
                  <span className="material-symbols-outlined text-[18px]">{cfg.icon}</span>
                </span>
              </div>
              <div className="mt-2 text-2xl font-headline font-bold text-on-surface">{value}</div>
            </DataCard>
          )
        })}
      </div>

      <DataCard className="!p-0 overflow-hidden">
        <div className="px-6 py-4 border-b border-surface-container-high flex flex-col lg:flex-row lg:items-center justify-between gap-3 bg-surface-container-low">
          <div>
            <h3 className="text-sm font-semibold text-on-surface">匹配/缺口处理计划</h3>
            <p className="text-xs text-on-surface-variant mt-1">
              识别时间：{formatDateTime(data?.recognizedAt)} · 校验状态：{integrity?.status === 'passed' ? '已通过' : '未通过或待检查'} · 目录项：{summary.totalTocItems ?? items.length}
            </p>
            {turbineModelLabel ? (
              <p className="text-xs text-on-surface-variant mt-1">投标机型：{turbineModelLabel}</p>
            ) : null}
            {scopeSummary ? (
              <p className="text-xs text-on-surface-variant mt-1">素材边界：{scopeSummary}</p>
            ) : null}
            {sampleVersion ? (
              <p className="text-xs text-outline mt-1">样例版本：{sampleVersion}</p>
            ) : null}
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${isCompleted ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
            {isCompleted ? '计划已生成' : '待识别'}
          </span>
        </div>

        {!isCompleted ? (
          <div className="h-[340px] px-6 py-8 flex flex-col items-center justify-center text-center">
            <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center mb-4">
              <span className="material-symbols-outlined text-primary text-3xl">fact_check</span>
            </div>
            <h4 className="text-lg font-headline font-bold text-on-surface mb-2">等待生成缺口计划</h4>
            <p className="text-sm text-on-surface-variant max-w-xl leading-relaxed">
              点击“识别缺口”后会调用缺口识别 Skill，按已确认目录、素材库 Wiki、真实素材和解析结果生成处理计划。
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-12 xl:h-[min(760px,calc(100vh-260px))] xl:min-h-[560px]">
            <div className="xl:col-span-7 border-r border-surface-container-high min-h-0 flex flex-col">
              <div className="px-5 py-3 border-b border-surface-container-high bg-surface-container-lowest shrink-0">
                <div className="flex flex-wrap gap-2">
                  {decisionFilterOptions.map((option) => {
                    const active = decisionFilter === option.key
                    const count = option.key === 'all'
                      ? items.length
                      : (summary[decisionSummaryKeys[option.key]] ?? items.filter((item) => decisionOf(item) === option.key).length)
                    return (
                      <button
                        key={option.key}
                        type="button"
                        onClick={() => setDecisionFilter(option.key)}
                        className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-xs font-semibold transition-colors ${
                          active
                            ? 'bg-primary text-on-primary'
                            : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim'
                        }`}
                      >
                        <span>{option.label}</span>
                        <span className={active ? 'text-on-primary/80' : 'text-outline'}>{count}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10">
                    <tr className="bg-surface-container-low border-b border-surface-container-high">
                      <th className="px-5 py-3 text-left font-semibold text-on-surface">目录项</th>
                      <th className="px-5 py-3 text-left font-semibold text-on-surface">判断</th>
                      <th className="px-5 py-3 text-left font-semibold text-on-surface">素材/副表</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredItems.map((item) => {
                      const cfg = configForItem(item)
                      const decision = decisionOf(item)
                      const appendixCount = asArray(item.appendixTasks).length
                      const fillTaskCount = asArray(item.fillTasks).length
                      const matchedMaterials = asArray(item.matchedMaterials)
                      const candidateCount = asArray(item.candidateMaterials).length
                      return (
                        <tr
                          key={item.id}
                          onClick={() => {
                            setSelectedId(item.id)
                            setSelectedMaterialIds([])
                          }}
                          className={`border-b border-surface-container-high cursor-pointer hover:bg-surface-container-low/60 ${effectiveSelectedId === item.id ? 'bg-primary/5' : ''}`}
                        >
                          <td className="px-5 py-3 min-w-[280px]">
                            <div className="text-xs text-outline">{item.number || item.section || '-'}</div>
                            <div className="font-medium text-on-surface mt-1">{item.title}</div>
                            {item.gapReason ? <div className="text-xs text-on-surface-variant mt-1">{item.gapReason}</div> : null}
                          </td>
                          <td className="px-5 py-3 min-w-[120px]">
                            <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-semibold ${cfg.tone}`}>
                              <span className="material-symbols-outlined text-[16px]">{cfg.icon}</span>
                              {cfg.label}
                            </span>
                            {decision ? (
                              <div className="mt-1 text-[11px] text-outline">原状态：{(statusConfig[item.status] || statusConfig.missing).label}</div>
                            ) : null}
                          </td>
                          <td className="px-5 py-3 text-on-surface-variant min-w-[240px]">
                            <div>{matchedMaterials.length ? '1 份最终素材' : item.coveredByParent ? '父章覆盖' : '无最终素材'}</div>
                            <div>{candidateCount} 份候选/参考素材</div>
                            <div>{appendixCount} 个空副表</div>
                            <div>{fillTaskCount} 个 AI 填写任务</div>
                            <div>{asArray(item.resolvedArtifacts).length} 个解决产物</div>
                          </td>
                        </tr>
                      )
                    })}
                    {!filteredItems.length ? (
                      <tr>
                        <td colSpan={3} className="px-5 py-10 text-center text-sm text-outline">
                          当前筛选下暂无目录项。
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="xl:col-span-5 p-5 bg-surface-container-lowest min-h-0 overflow-y-auto">
              {selected ? (
                <div className="flex flex-col gap-5">
                  <div>
                    <div className="text-xs text-outline">{selected.number || selected.section || '-'}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <h3 className="text-xl font-headline font-bold text-on-surface">{selected.title}</h3>
                      {selectedConfig ? (
                        <span className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ${selectedConfig.tone}`}>
                          <span className="material-symbols-outlined text-[16px]">{selectedConfig.icon}</span>
                          {selectedConfig.label}
                        </span>
                      ) : null}
                    </div>
                    <p className="text-sm text-on-surface-variant mt-2">{selected.gapReason || selected.reason || '当前目录项已纳入缺口处理计划。'}</p>
                  </div>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">缺口判断</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                      <div className="rounded-md bg-surface-container-low px-3 py-2">
                        <div className="text-outline">业务分类</div>
                        <div className="mt-1 font-medium text-on-surface">
                          {selectedDecision ? decisionConfig[selectedDecision].label : (statusConfig[selected.status] || statusConfig.missing).label}
                        </div>
                      </div>
                      <div className="rounded-md bg-surface-container-low px-3 py-2">
                        <div className="text-outline">用途</div>
                        <div className="mt-1 font-medium text-on-surface">
                          {selectedUsages.visible.length
                            ? selectedUsages.visible.map(labelForUsage).join('；')
                            : labelForUsage(selected.usage)}
                        </div>
                      </div>
                    </div>
                    {selected.coverageRole || selected.coveredByParent ? (
                      <div className="mt-3 rounded-md bg-surface-container-low px-3 py-2 text-xs">
                        <div className="font-medium text-on-surface">
                          {selected.coverageRole === 'chapter_master' ? '整章素材' : '父章覆盖'}
                        </div>
                        <div className="mt-1 text-outline">
                          {selected.coverageRole === 'chapter_master'
                            ? '该目录项作为整章 Word 合并，子节不再单独匹配素材。'
                            : `由父章节 ${selected.coveredByParent || '-'} 覆盖，当前子节不单独生成缺口。`}
                        </div>
                      </div>
                    ) : null}
                    {selectedNextActions.visible.length ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {selectedNextActions.visible.map((action) => (
                          <span key={action} className="rounded-md bg-surface-container-high px-2 py-1 text-[11px] font-medium text-on-surface-variant">
                            {labelForAction(action)}
                          </span>
                        ))}
                        {selectedNextActions.overflow ? (
                          <span className="rounded-md bg-surface-container-high px-2 py-1 text-[11px] text-outline">
                            +{selectedNextActions.overflow}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">素材边界与机型判断</h4>
                    <div className="space-y-3 text-xs">
                      <div>
                        <div className="font-medium text-on-surface mb-1">允许读取范围</div>
                        {selectedAllowedPaths.visible.length ? (
                          <div className="space-y-1">
                            {selectedAllowedPaths.visible.map((path) => (
                              <div key={path} className="rounded-md bg-surface-container-low px-3 py-2 text-outline break-all">{path}</div>
                            ))}
                            {selectedAllowedPaths.overflow ? <div className="text-outline">还有 {selectedAllowedPaths.overflow} 个范围</div> : null}
                          </div>
                        ) : (
                          <div className="text-outline">暂无范围信息。</div>
                        )}
                      </div>
                      <div>
                        <div className="font-medium text-on-surface mb-1">实际命中范围</div>
                        {selectedMatchedPaths.visible.length ? (
                          <div className="space-y-1">
                            {selectedMatchedPaths.visible.map((path) => (
                              <div key={path} className="rounded-md bg-surface-container-low px-3 py-2 text-outline break-all">{path}</div>
                            ))}
                            {selectedMatchedPaths.overflow ? <div className="text-outline">还有 {selectedMatchedPaths.overflow} 个范围</div> : null}
                          </div>
                        ) : (
                          <div className="text-outline">当前目录项未命中可用素材。</div>
                        )}
                      </div>
                      <div className="rounded-md bg-surface-container-low px-3 py-2">
                        <div className="font-medium text-on-surface">
                          {turbineStatusLabels[selectedTurbineCheck.status] || selectedTurbineCheck.status || '未判断'}
                        </div>
                        <div className="mt-1 text-outline">{selectedTurbineCheck.reason || '暂无机型判断说明。'}</div>
                      </div>
                    </div>
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">最终匹配素材</h4>
                    {asObjectArray(selected.matchedMaterials).length ? (
                      <div className="space-y-2">
                        {asObjectArray(selected.matchedMaterials).map((item, index) => (
                          <div key={`${item.id || item.path}-${index}`} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{item.name || item.id || item.path || '素材'}</div>
                            <div className="text-outline break-all mt-1">{item.path || item.docx || item.matchReason || '-'}</div>
                            <div className="text-outline mt-1">
                              {item.materialScope || item.materialTier || '素材'} · {labelForUsage(item.usage)} · {item.turbineFit || '机型未标记'}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">{selected.coveredByParent ? '当前子节由父章整章素材覆盖。' : '暂无最终匹配素材。'}</p>}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">候选/参考素材</h4>
                    {selectedCandidateMaterials.length ? (
                      <div className="space-y-2">
                        {selectedCandidateMaterials.slice(0, 8).map((item, index) => (
                          <div key={`${item.id || item.path}-${index}`} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{item.name || item.id || item.path || '素材'}</div>
                            <div className="text-outline break-all mt-1">{item.path || item.folderPath || item.matchReason || '-'}</div>
                            <div className="text-outline mt-1">
                              {item.materialScope || item.materialTier || '素材'} · {labelForUsage(item.usage)} · {item.turbineFit || '机型未标记'}
                            </div>
                          </div>
                        ))}
                        {selectedCandidateMaterials.length > 8 ? (
                          <div className="text-xs text-outline">还有 {selectedCandidateMaterials.length - 8} 份候选/参考素材</div>
                        ) : null}
                      </div>
                    ) : <p className="text-xs text-outline">暂无候选或参考素材。</p>}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h4 className="text-sm font-semibold text-on-surface">选择已有素材</h4>
                      <button
                        onClick={handleSelectMaterials}
                        disabled={!selectedMaterialItems.length || Boolean(busyAction)}
                        className="h-8 px-3 bg-secondary text-on-secondary text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busyAction === `select-${selected.id}` ? '挂回中...' : '挂回缺口'}
                      </button>
                    </div>
                    <div className="flex gap-2">
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
                      <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-xs text-outline">
                        当前读取范围：{scopeSummary}{turbineModelLabel ? `；机型筛选：${turbineModelLabel}` : ''}
                      </div>
                    ) : null}
                    <div className="mt-3 space-y-2 max-h-44 overflow-y-auto">
                      {materialSearch.items.length ? materialSearch.items.map((item) => {
                        const checked = selectedMaterialIds.includes(item.id)
                        return (
                          <label key={item.id} className="flex items-start gap-2 rounded-md bg-surface-container-low px-3 py-2 text-xs cursor-pointer">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleMaterial(item.id)}
                              className="mt-0.5"
                            />
                            <span className="min-w-0">
                              <span className="block font-medium text-on-surface">{item.name}</span>
                              <span className="block text-outline break-all mt-1">
                                {item.id} · {item.hasCleanedWord ? '清洗稿' : '原始 Word'} · {item.folderPath || '-'}
                              </span>
                            </span>
                          </label>
                        )
                      }) : (
                        <p className="text-xs text-outline">
                          {materialLoading ? '正在查询素材...' : '输入关键词后查询素材库，可作为缺口解决产物或 AI 填写参考。'}
                        </p>
                      )}
                    </div>
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <div className="flex items-center justify-between gap-2 mb-3">
                      <h4 className="text-sm font-semibold text-on-surface">AI 填写任务</h4>
                      <button
                        onClick={handleAiFill}
                        disabled={!selected.fillTasks?.length || Boolean(busyAction)}
                        className="h-8 px-3 bg-primary text-on-primary text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busyAction === `ai-${selected.id}` ? '填写中...' : '调用 Skill 填写'}
                      </button>
                    </div>
                    {selectedAppendixTasks.length ? (
                      <div className="mb-3 rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                        <div className="mb-2 text-xs font-semibold text-on-surface">解析生成的空副表/Word</div>
                        <div className="space-y-2">
                          {selectedAppendixTasks.map((task) => {
                            const recommended = asObjectArray(task.recommendedMaterials).slice(0, 3)
                            return (
                              <div key={task.id || task.title} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                                <div className="font-medium text-on-surface">{task.title || task.id || '空副表'}</div>
                                <div className="text-outline mt-1">
                                  {task.sourceFile || '招标文件'} · 行数：{task.rowCount ?? 0} · 字段：{asArray(task.availableParseFields).length}
                                </div>
                                {task.workspacePath ? <div className="text-outline break-all mt-1">{task.workspacePath}</div> : null}
                                {recommended.length ? (
                                  <div className="mt-2 flex flex-wrap gap-1.5">
                                    {recommended.map((material) => (
                                      <span key={material.id || material.name} className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] text-on-surface-variant">
                                        {material.name || material.id}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ) : null}
                    {selectedFillTasks.length ? (
                      <div className="space-y-2">
                        {selectedFillTasks.map((task) => (
                          <div key={task.id} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{task.title || task.id}</div>
                            <div className="text-outline mt-1">Skill：{task.skill} · 状态：{task.status || 'pending'}</div>
                            {task.blankSource?.title ? <div className="text-outline mt-1">空表：{task.blankSource.title}</div> : null}
                            {asArray(task.requiredReferences).length ? (
                              <div className="text-outline mt-1">参考：{asArray(task.requiredReferences).join('、')}</div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">当前目录项不需要 AI 填写。</p>}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <h4 className="text-sm font-semibold text-on-surface">客户资料上传</h4>
                        <p className="text-xs text-outline mt-1">上传后会作为项目补料产物挂回当前目录项。</p>
                      </div>
                      <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={Boolean(busyAction)}
                        className="h-8 px-3 bg-surface-container-high text-on-surface-variant text-xs font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busyAction === `upload-${selected.id}` ? '上传中...' : '上传资料'}
                      </button>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="hidden"
                      multiple
                      onChange={handleUploadPicked}
                    />
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">处理产物</h4>
                    {(selected.resolvedArtifacts || []).length ? (
                      <div className="space-y-2">
                        {selected.resolvedArtifacts.map((artifact) => (
                          <div key={artifact.id} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">{artifact.fileName || artifact.title || artifact.id}</div>
                            <div className="text-outline mt-1">来源：{artifact.source || '-'} · Skill：{artifact.skill || '-'}</div>
                            {artifact.fillReport ? (
                              <div className="mt-2 grid grid-cols-2 gap-2">
                                <div className="rounded bg-surface-container-high px-2 py-1">
                                  <div className="text-outline">已填字段</div>
                                  <div className="font-semibold text-on-surface">{artifact.fillReport.filledFieldCount ?? 0}</div>
                                </div>
                                <div className="rounded bg-surface-container-high px-2 py-1">
                                  <div className="text-outline">未填字段</div>
                                  <div className="font-semibold text-on-surface">{artifact.fillReport.unfilledFieldCount ?? asArray(artifact.unfilledFields).length}</div>
                                </div>
                              </div>
                            ) : null}
                            {asObjectArray(artifact.referenceMaterials).length ? (
                              <div className="mt-2">
                                <div className="text-outline mb-1">使用素材</div>
                                <div className="flex flex-wrap gap-1.5">
                                  {asObjectArray(artifact.referenceMaterials).slice(0, 4).map((material) => (
                                    <span key={material.id || material.name} className="rounded bg-surface-container-high px-2 py-0.5 text-[11px] text-on-surface-variant">
                                      {material.name || material.id}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                            {asArray(artifact.unfilledFields).length ? (
                              <div className="mt-2">
                                <div className="text-outline mb-1">待人工复核</div>
                                <div className="space-y-1">
                                  {asArray(artifact.unfilledFields).slice(0, 4).map((field) => (
                                    <div key={field} className="rounded bg-error/10 px-2 py-1 text-error">{field}</div>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                            {artifact.onlyoffice?.fileUrl ? (
                              <a className="inline-flex mt-2 text-primary font-semibold" href={artifact.onlyoffice.fileUrl} target="_blank" rel="noreferrer">
                                OnlyOffice 预览
                              </a>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">暂无处理产物。</p>}
                  </section>

                  <section className="rounded-lg border border-surface-container-high p-4">
                    <h4 className="text-sm font-semibold text-on-surface mb-3">识别依据</h4>
                    {selectedEvidenceRefs.length ? (
                      <div className="space-y-2">
                        {selectedEvidenceRefs.map((ref, index) => (
                          <div key={`${ref.id || ref.title || ref.name}-${index}`} className="rounded-md bg-surface-container-low px-3 py-2 text-xs">
                            <div className="font-medium text-on-surface">
                              {ref.title || ref.name || ref.id || '依据'}
                            </div>
                            <div className="text-outline break-all mt-1">
                              {[ref.type, ref.number, ref.folderPath, ref.id].filter(Boolean).join(' · ') || '-'}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : <p className="text-xs text-outline">暂无识别依据。</p>}
                  </section>

                  <div className="flex justify-end">
                    <button
                      onClick={handleIgnore}
                      disabled={Boolean(busyAction)}
                      className="px-4 py-2.5 bg-surface-container-high text-on-surface-variant text-sm font-medium rounded-lg hover:bg-surface-dim transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      人工忽略
                    </button>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-sm text-outline">选择一个目录项查看处理详情</div>
              )}
            </div>
          </div>
        )}
      </DataCard>
    </div>
  )
}
