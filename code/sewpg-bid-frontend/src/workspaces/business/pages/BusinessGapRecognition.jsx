import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { businessGapsAPI, businessGenerateAPI, businessStagesAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import DataCard from '../../../components/shared/DataCard'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import BusinessProjectStageProgress from '../components/BusinessProjectStageProgress'
import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import FileButton from '../../../components/ui/FileButton'
import IconButton from '../../../components/ui/IconButton'
import Toolbar from '../../../components/ui/Toolbar'
import { projectRoute, useWorkspaceSlug } from '../../../utils/workspace'

const statusLabels = {
  idle: '未生成',
  ready: '已就绪',
  needs_input: '待补料/待填写',
  review_required: '待复核',
  filling: '处理中',
  resolved: '已解决',
  ignored: '已忽略',
}

const taskActionLabels = {
  fixed_material: '固定素材',
  manual_select: '人工指定',
  manual_upload: '人工补料',
  ignored: '忽略',
  ai_table_fill: 'AI填表',
}

const statusVariant = (status) => {
  if (status === 'ready' || status === 'resolved') return 'done'
  if (status === 'needs_input') return 'error'
  if (status === 'review_required') return 'warn'
  if (status === 'filling') return 'running'
  return 'pending'
}

const asArray = (value) => Array.isArray(value) ? value : []

const factStatusLabels = {
  empty: '未生成',
  draft: '待确认',
  confirmed: '已确认',
  candidate: '候选',
  missing: '待补充',
  conflict: '冲突',
}

const usageModeLabels = {
  attach_whole: '整件挂载',
  extract_fields: '抽字段',
  extract_image: '摘图/扫描件',
  fill_table: '填表',
  fill_template: '填模板',
  embed_scan: '嵌入扫描件',
  extract_and_summarize: '提取总结',
  generate_draft: 'AI起草',
  manual_upload: '人工上传来源',
  reference_only: '仅参考',
}

const sourceModeLabels = {
  uploaded_in_business_s3: '人工上传补料',
  selected_from_business_material_library: '已选素材快照',
  generated_by_business_s3_ai_draft: 'AI填表产物',
  generated_by_business_table_fill: 'AI填表产物',
  generated_by_s1_business_parser: '解析生成承诺函',
  parsed_from_tender_attachment_template: '解析附件模板',
  parsed_business_scoring: '解析商务评分',
  project_uploaded_bid_template: '项目上传投标模板',
  system_default_bid_template: '系统默认商务模板',
  selected_from_bid_template: '已选投标模板',
}

const SUPPLEMENT_ACCEPT = '.doc,.docx,.pdf,.xls,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff'
const MAX_VISIBLE_CANDIDATES = 4

const BUSINESS_MATERIAL_KIND_LABELS = {
  fixed: '固定素材',
  other: '其他',
}

const looksLikeTemplateAsset = (item) => {
  if (!item) return false
  const usage = item.wikiUsageMode || item.materialUsage || ''
  const mode = item.assemblyMode || ''
  const sourceMode = item.sourceMode || ''
  const artifactType = item.artifactType || ''
  const name = `${item.fileName || ''} ${item.materialName || item.name || ''} ${item.folderPath || item.path || ''}`
  return mode === 'template_fill_docx'
    || usage === 'fill_template'
    || sourceMode === 'parsed_from_tender_attachment_template'
    || artifactType === 'parse_appendix_template'
    || (/\.docx?$/i.test(name) && /模板|格式|底稿|投标函|授权|廉洁|承诺|声明|说明|履约/.test(name))
}

const PROJECT_FACT_SOURCE_KEY = '__project_fact_table__'

const isProjectFactSource = (item) => item?.kind === 'project_fact_table' || item?.id === PROJECT_FACT_SOURCE_KEY

const materialPreviewKey = (item) => isProjectFactSource(item) ? PROJECT_FACT_SOURCE_KEY : (item?.materialId || item?.id || '')

const materialPreviewTitle = (item) =>
  item?.materialName || item?.name || item?.fileName || item?.evidenceSegmentTitle || item?.id || item?.materialId || '候选素材'

const candidateMaterialKey = (material) =>
  material?.materialId || material?.id || material?.path || material?.folderPath || material?.materialName || material?.evidenceSegmentId || material?.wikiCardId || ''

const pickerItemKey = (tab, item) => {
  if (tab === 'templates') return item?.templateId || item?.filePath || item?.id || ''
  if (tab === 'segments') return item?.evidenceSegmentId || item?.id || ''
  return item?.materialId || item?.id || ''
}

const materialSelectionPayload = (item, tab) => {
  if (!item) return null
  if (isProjectFactSource(item)) return null
  if (tab === 'segments') {
    return {
      id: item.id || item.materialId,
      materialId: item.materialId || item.id,
      materialName: item.materialName,
      folderPath: item.folderPath,
      materialTier: item.materialTier,
      businessMaterialKind: item.businessMaterialKind,
      businessMaterialKindLabel: item.businessMaterialKindLabel,
      cleanedFileName: item.cleanedFileName,
      evidenceSegmentId: item.evidenceSegmentId,
      evidenceSegmentTitle: item.evidenceSegmentTitle,
      evidenceSegmentType: item.evidenceSegmentType,
      evidenceSourcePages: item.evidenceSourcePages,
      evidenceSummary: item.evidenceSummary,
      wikiCardId: item.wikiCardId,
      wikiUsageMode: item.wikiUsageMode,
      wikiEvidence: item.wikiEvidence,
    }
  }
  return {
    id: item.id || item.materialId,
    materialId: item.materialId || item.id,
    materialName: item.materialName,
    folderPath: item.folderPath,
    materialTier: item.materialTier,
    businessMaterialKind: item.businessMaterialKind,
    businessMaterialKindLabel: item.businessMaterialKindLabel,
    cleanedFileName: item.cleanedFileName,
    evidenceSegments: item.evidenceSegments,
    wikiCardId: item.wikiCardId,
    wikiUsageMode: item.wikiUsageMode,
    wikiEvidence: item.wikiEvidence,
  }
}

const evidenceSegmentFromCandidate = (material) => {
  if (!material?.evidenceSegmentId) return null
  return {
    segmentId: material.evidenceSegmentId,
    evidenceSegmentId: material.evidenceSegmentId,
    title: material.evidenceSegmentTitle || '',
    evidenceSegmentTitle: material.evidenceSegmentTitle || '',
    sourcePages: material.evidenceSourcePages || material.wikiEvidence?.sourcePages || '',
    evidenceSourcePages: material.evidenceSourcePages || material.wikiEvidence?.sourcePages || '',
    summary: material.evidenceSummary || material.wikiEvidence?.summary || '',
    evidenceSummary: material.evidenceSummary || material.wikiEvidence?.summary || '',
    wikiCardId: material.wikiCardId || '',
    wikiUsageMode: material.wikiUsageMode || '',
    materialId: material.materialId || '',
    materialName: material.materialName || '',
    folderPath: material.folderPath || material.path || '',
    wikiEvidence: material.wikiEvidence || {},
  }
}

const numericMatchScore = (material) => {
  const raw = material?.score ?? material?.matchScore ?? material?.similarity ?? material?.confidence ?? 0
  const value = Number(raw)
  if (!Number.isFinite(value)) return 0
  return value > 1 ? value / 100 : value
}

const mergeCandidateMaterials = (materials) => {
  const grouped = new Map()
  asArray(materials).forEach((material) => {
    if (!material) return
    const key = candidateMaterialKey(material)
    if (!key) return
    const current = grouped.get(key)
    const segment = evidenceSegmentFromCandidate(material)
    if (!current) {
      const evidenceSegments = [...asArray(material.evidenceSegments)]
      if (segment && !evidenceSegments.some((item) => (item.evidenceSegmentId || item.segmentId) === segment.evidenceSegmentId)) {
        evidenceSegments.push(segment)
      }
      grouped.set(key, { ...material, evidenceSegments })
      return
    }
    if (numericMatchScore(material) > numericMatchScore(current)) current.score = material.score
    if (material.reason && !String(current.reason || '').includes(material.reason)) {
      current.reason = [current.reason, material.reason].filter(Boolean).join(' + ')
    }
    ;['cleanStatus', 'cleanedFileName', 'folderPath', 'path', 'wikiCardId', 'wikiUsageMode', 'validityStatus', 'expiryDate', 'businessMaterialKind', 'businessMaterialKindLabel'].forEach((field) => {
      if (!current[field] && material[field]) current[field] = material[field]
    })
    if (!current.wikiEvidence && material.wikiEvidence) current.wikiEvidence = material.wikiEvidence
    const evidenceSegments = current.evidenceSegments || []
    asArray(material.evidenceSegments).forEach((item) => {
      const segmentId = item?.evidenceSegmentId || item?.segmentId
      if (segmentId && !evidenceSegments.some((existing) => (existing.evidenceSegmentId || existing.segmentId) === segmentId)) {
        evidenceSegments.push(item)
      }
    })
    if (segment && !evidenceSegments.some((item) => (item.evidenceSegmentId || item.segmentId) === segment.evidenceSegmentId)) {
      evidenceSegments.push(segment)
    }
    current.evidenceSegments = evidenceSegments
  })
  return Array.from(grouped.values()).sort((a, b) => numericMatchScore(b) - numericMatchScore(a))
}

const topCandidateMaterials = (materials) => mergeCandidateMaterials(materials).slice(0, MAX_VISIBLE_CANDIDATES)

const businessMaterialKindLabel = (material) => {
  const rawLabel = String(material?.businessMaterialKindLabel || '').trim()
  if (rawLabel === 'fixed' || rawLabel.includes('固定')) return '固定素材'
  if (rawLabel === 'other' || rawLabel.includes('其他')) return '其他'
  const kind = String(material?.businessMaterialKind || material?.materialKind || '').trim().toLowerCase()
  if (kind === 'fixed' || kind === '固定' || kind === '固定素材' || material?.isFixedMaterial === true) return '固定素材'
  if (kind === 'other' || kind === '其他') return '其他'
  return ''
}

const tableFillTargetKey = (item) =>
  item?.artifactId || item?.templateId || item?.materialId || item?.id || item?.filePath || item?.path || item?.fileName || ''

const tableFillTargetTitle = (item) =>
  item?.templateName || item?.fileName || item?.materialName || item?.name || item?.title || item?.templateId || item?.artifactId || '待填表'

const isProjectUploadedBidTemplate = (item) =>
  ['project_uploaded_bid_template', 'system_default_bid_template', 'selected_from_bid_template'].includes(String(item?.sourceMode || ''))

const looksLikeTableFillTarget = (item) => {
  if (!item) return false
  if (isProjectUploadedBidTemplate(item)) return false
  const name = `${item.fileName || ''} ${item.templateName || ''} ${item.materialName || ''} ${item.name || ''} ${item.title || ''} ${item.filePath || ''} ${item.path || ''} ${item.folderPath || ''}`
  const usage = item.materialUsage || item.wikiUsageMode || ''
  const mode = item.assemblyMode || ''
  const artifactType = item.artifactType || ''
  if (artifactType === 'business_table_fill' || item.sourceMode === 'generated_by_business_table_fill') return false
  return looksLikeTemplateAsset(item)
    || mode === 'table_fill_from_material'
    || ['fill_table', 'fill_template'].includes(usage)
    || /表|报价|分项|偏差|规格|清单|附件|模板|格式|报价函|投标函/.test(name)
}

const tableFillTargetCandidates = (task) => {
  const entries = [
    ...asArray(task?.templateCandidates).filter((item) => !isProjectUploadedBidTemplate(item)),
    ...asArray(task?.candidateMaterials),
    ...asArray(task?.resolvedArtifacts),
  ]
  const grouped = new Map()
  entries.forEach((item) => {
    if (!looksLikeTableFillTarget(item)) return
    const key = tableFillTargetKey(item)
    if (!key || grouped.has(key)) return
    grouped.set(key, item)
  })
  return Array.from(grouped.values())
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

function tocLevelStyles(levelValue) {
  const level = Math.max(1, Number(levelValue) || 1)
  if (level === 1) {
    return {
      itemClass: 'py-2.5 bg-surface-container-low',
      titleClass: 'text-sm font-bold text-on-surface',
      titleStyle: { fontWeight: 700 },
    }
  }
  if (level === 2) {
    return {
      itemClass: 'py-2',
      titleClass: 'text-[13px] font-semibold text-on-surface',
      titleStyle: { fontWeight: 600 },
    }
  }
  return {
    itemClass: 'py-1.5',
    titleClass: 'text-xs font-medium text-on-surface-variant',
    titleStyle: { fontWeight: 500 },
  }
}

function TaskStatusBadge({ status }) {
  return (
    <Badge className="business-toc-status-badge" shape="square" size="xs" variant={statusVariant(status)}>
      {statusLabels[status] || status || '待处理'}
    </Badge>
  )
}

function taskActionMode(task) {
  const explicit = String(task?.handlingMode || task?.businessHandlingMode || '').trim()
  if (explicit === 'ignored' || String(task?.status || '') === 'ignored') return 'ignored'
  const artifacts = asArray(task?.resolvedArtifacts)
  if (artifacts.some((artifact) => (
    artifact?.artifactType === 'business_table_fill'
    || artifact?.sourceMode === 'generated_by_business_table_fill'
  ))) {
    return 'ai_table_fill'
  }
  if (explicit && taskActionLabels[explicit]) return explicit
  const latest = artifacts[artifacts.length - 1] || null
  const sourceMode = String(latest?.sourceMode || '')
  const artifactType = String(latest?.artifactType || '')
  if (artifactType === 'business_table_fill' || sourceMode === 'generated_by_business_table_fill') return 'ai_table_fill'
  if (sourceMode === 'uploaded_in_business_s3') return 'manual_upload'
  if (sourceMode === 'selected_from_business_material_library') {
    return String(latest?.businessMaterialKind || '') === 'fixed' ? 'fixed_material' : 'manual_select'
  }
  return ''
}

function taskActionVariant(mode) {
  if (mode === 'ignored') return 'pending'
  if (mode === 'ai_table_fill') return 'info'
  return 'done'
}

function TocActionBadges({ tasks }) {
  const list = asArray(tasks)
  if (!list.length) return <Badge className="business-toc-status-badge" shape="square" size="xs" variant="pending">空章节</Badge>

  const modeCounts = list.reduce((counts, task) => {
    const mode = taskActionMode(task)
    if (mode) counts[mode] = (counts[mode] || 0) + 1
    return counts
  }, {})
  const entries = Object.entries(modeCounts).filter(([, count]) => count > 0)
  if (!entries.length) {
    const counts = taskCounts(list)
    return <TaskStatusBadge status={counts.pending ? 'review_required' : 'ready'} />
  }

  return (
    <div className="flex max-w-[180px] flex-wrap justify-end gap-1">
      {entries.map(([mode, count]) => (
        <Badge key={mode} className="business-toc-status-badge" shape="square" size="xs" variant={taskActionVariant(mode)}>
          {taskActionLabels[mode]}{count > 1 ? ` ${count}` : ''}
        </Badge>
      ))}
    </div>
  )
}

function taskCounts(tasks) {
  const list = asArray(tasks)
  return {
    ready: list.filter((task) => ['ready', 'resolved', 'ignored'].includes(task.status)).length,
    pending: list.filter((task) => ['needs_input', 'review_required', 'filling'].includes(task.status)).length,
    candidates: list.reduce((total, task) => total + asArray(task.candidateMaterials).length, 0),
    artifacts: list.reduce((total, task) => total + asArray(task.resolvedArtifacts).length, 0),
  }
}

function FactMaintenanceModal({
  open,
  factTable,
  fields,
  busy,
  onClose,
  onConfirm,
  onFieldChange,
}) {
  if (!open) return null
  const summary = factTable?.summary || {}
  const status = factTable?.status || 'empty'
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-headline font-bold text-on-surface">商务标项目事实表维护</h3>
              <Badge shape="square" variant={status === 'confirmed' ? 'done' : 'warn'}>
                {factStatusLabels[status] || status}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-on-surface-variant">
              字段：{summary.totalCount || fields.length || 0} · 已确认：{summary.confirmedCount || 0} · 待补充：{summary.missingCount || 0} · 冲突：{summary.conflictCount || 0}
            </p>
          </div>
          <Toolbar>
            <Button
              type="button"
              onClick={onConfirm}
              disabled={busy || !fields.length}
              size="sm"
              variant="primary"
            >
              保存
            </Button>
            <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
          </Toolbar>
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
                    <th className="px-3 py-2 font-semibold">来源依据</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-high">
                  {fields.map((field, index) => {
                    const fieldVariant = field.status === 'confirmed'
                      ? 'done'
                      : field.status === 'missing'
                        ? 'warn'
                        : field.status === 'conflict'
                          ? 'error'
                          : 'pending'
                    const refs = asArray(field.sourceRefs).slice(0, 2)
                    return (
                      <tr key={field.id || `${field.label}-${index}`} className="align-top">
                        <td className="px-3 py-2">
                          <div className="font-semibold text-on-surface">{field.label}</div>
                          <div className="mt-1 text-[11px] text-outline">{field.category || '项目事实'}</div>
                        </td>
                        <td className="px-3 py-2">
                          <input
                            value={field.value || ''}
                            onChange={(event) => onFieldChange(index, 'value', event.target.value)}
                            className={`h-9 w-full rounded-md border px-2 text-sm text-on-surface ${field.status === 'missing' ? 'border-tertiary bg-tertiary-fixed/40' : 'border-surface-container-high bg-surface'}`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Badge shape="square" size="xs" variant={fieldVariant}>
                            {factStatusLabels[field.status] || field.status || '-'}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-xs text-on-surface-variant">
                          {field.confidence ? `${Math.round(Number(field.confidence) * 100)}%` : '-'}
                        </td>
                        <td className="px-3 py-2 text-xs text-on-surface-variant">
                          {refs.length ? refs.map((ref) => (
                            <div key={`${ref.type || ''}-${ref.field || ref.title || ''}`} className="mb-1 truncate" title={[ref.title, ref.field, ref.taskId].filter(Boolean).join(' · ')}>
                              {[ref.title, ref.field, ref.taskId].filter(Boolean).join(' · ')}
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
                <p className="mt-3 text-sm text-on-surface-variant">还没有商务标项目事实表，先从解析字段、商务任务和素材库生成候选事实。</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function BusinessGenerationProgressModal({
  open,
  status,
  progress,
  onClose,
}) {
  if (!open) return null
  const running = status?.status === 'running'
  const completed = status?.status === 'completed'
  const failed = status?.status === 'failed'
  const title = running ? '正在生成商务标正文' : completed ? '商务标正文已生成' : failed ? '商务标正文生成失败' : '商务标正文生成'
  const summary = status?.summary || (running ? '系统正在根据当前素材匹配结果生成正文。' : completed ? '可继续进入 S4 共创导出。' : failed ? '请检查任务状态后重新生成。' : '准备生成商务标正文。')
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
              商务标正文已生成。可返回本页继续调整素材匹配并重新生成，或进入 S4 共创导出。
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

function BusinessGapPlanProgressModal({
  open,
  running,
  error,
  onClose,
}) {
  if (!open) return null
  const failed = Boolean(error)
  const title = failed ? '素材匹配失败' : running ? '正在执行素材匹配' : '素材匹配已完成'
  const progress = failed ? 100 : running ? 68 : 100
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="w-full max-w-xl rounded-lg bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">{title}</h3>
          </div>
          {!running ? <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" /> : null}
        </div>
        <div className="space-y-4 p-5">
          <div className="flex items-center gap-3">
            <div className="h-3 flex-1 overflow-hidden rounded-full bg-surface-container-high">
              <div
                className={`h-full ${failed ? 'bg-error' : 'bg-primary'}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="w-12 text-right text-xs font-semibold text-outline">{progress}%</span>
          </div>
          {failed ? (
            <div className="rounded-md border border-error/25 bg-error/10 px-3 py-2 text-sm text-error">
              {error}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function BusinessMaterialPreviewDrawer({
  open,
  loading,
  payload,
  source,
  onClose,
  onOpenOffice,
}) {
  const [fullscreen, setFullscreen] = useState(false)
  useEffect(() => {
    if (!fullscreen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [fullscreen])
  if (!open) return null
  const title = payload?.materialName || materialPreviewTitle(source)
  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/30">
      <div className={`flex h-full w-full flex-col overflow-hidden bg-surface shadow-2xl ${fullscreen ? 'max-w-none' : 'max-w-5xl'}`}>
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-lg font-headline font-bold text-on-surface">{title}</h3>
              {payload?.previewMode && (
                <Badge shape="square" variant="info">
                  {payload.previewMode === 'native' ? '原件预览' : payload.previewMode === 'onlyoffice' ? '原件 OnlyOffice' : '下载核对'}
                </Badge>
              )}
            </div>
            <p className="mt-1 truncate text-xs text-on-surface-variant">{payload?.folderPath || source?.folderPath || '商务标素材库候选材料'}</p>
          </div>
          <IconButton
            aria-label={fullscreen ? '退出全屏' : '全屏查看'}
            icon={fullscreen ? 'close_fullscreen' : 'open_in_full'}
            onClick={() => setFullscreen((value) => !value)}
            variant="quiet"
          />
        </div>

        <div className="min-h-0 flex-1 overflow-hidden p-3">
          {loading ? (
            <div className="flex h-full flex-col gap-3">
              <div className="h-16 animate-pulse rounded-md bg-surface-container-low" />
              <div className="min-h-0 flex-1 animate-pulse rounded-md bg-surface-container-low" />
            </div>
          ) : !payload ? (
            <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">暂无预览数据。</div>
          ) : (
            <div className="h-full space-y-4">
              {payload.previewMode === 'native' && payload.renderer === 'image' && payload.browserFileUrl ? (
                <div className="h-full rounded-lg border border-surface-container-high bg-surface-container-lowest p-3">
                  <img src={payload.browserFileUrl} alt={title} className="h-full w-full object-contain" />
                </div>
              ) : payload.previewMode === 'native' && payload.renderer === 'pdf' && payload.browserFileUrl ? (
                <div className="h-full overflow-hidden rounded-lg border border-surface-container-high bg-surface-container-lowest">
                  <iframe title={title} src={payload.browserFileUrl} className="h-full w-full" />
                </div>
              ) : payload.previewMode === 'onlyoffice' && payload.onlyoffice ? (
                <div className="h-full overflow-hidden rounded-lg border border-surface-container-high bg-surface-container-lowest">
                  <OnlyOfficeEmbed
                    session={payload.onlyoffice}
                    mode="view"
                    className="h-full w-full bg-white"
                  />
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">
                  当前文件类型暂不支持内嵌预览，可打开原件核对。
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-container-high bg-surface-container-low px-5 py-3">
          <div />
          <Toolbar>
            {payload?.browserFileUrl && (
              <Button as="a" className="h-9" href={payload.browserFileUrl} target="_blank" rel="noreferrer" variant="quiet">
                打开原件
              </Button>
            )}
            {payload?.officeAvailable && payload?.previewMode !== 'onlyoffice' && (
              <Button
                type="button"
                onClick={onOpenOffice}
                disabled={loading}
                variant="secondary"
              >
                OnlyOffice 原件预览
              </Button>
            )}
            <Button type="button" onClick={onClose} variant="primary">
              关闭
            </Button>
          </Toolbar>
        </div>
      </div>
    </div>
  )
}

function BusinessMaterialPickerModal({
  open,
  task,
  payload,
  loading,
  keyword,
  activeTab,
  selectedKeys,
  onKeywordChange,
  onTabChange,
  onToggleKey,
  onClose,
  onConfirm,
  onPreview,
}) {
  if (!open || !task) return null
  const templates = asArray(payload?.templates)
  const materials = asArray(payload?.items)
  const selectedList = activeTab === 'templates' ? templates : materials
  const normalizedSelectedKeys = asArray(selectedKeys)
  const selectedItems = selectedList.filter((item) => normalizedSelectedKeys.includes(pickerItemKey(activeTab, item)))
  const selectedItem = selectedItems[0] || null
  const multiSelect = activeTab !== 'templates'
  const selectedCount = multiSelect ? selectedItems.length : (selectedItem ? 1 : 0)
  const selectAllVisible = () => {
    if (!multiSelect) return
    const visibleKeys = selectedList.map((item) => pickerItemKey(activeTab, item)).filter(Boolean)
    const allSelected = visibleKeys.length > 0 && visibleKeys.every((key) => normalizedSelectedKeys.includes(key))
    onToggleKey(allSelected ? [] : visibleKeys, { replace: true })
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">人工指定素材库材料/模板</h3>
          </div>
          <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
        </div>

        <div className="border-b border-surface-container-high p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[260px] flex-1">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-lg text-outline">search</span>
              <input
                value={keyword}
                onChange={(event) => onKeywordChange(event.target.value)}
                className="h-10 w-full rounded-md border border-surface-container-high bg-surface-container-lowest pl-10 pr-3 text-sm text-on-surface"
                placeholder="搜索模板、素材名称、清洗稿、路径、关键词..."
              />
            </div>
            <Toolbar className="rounded-md border border-surface-container-high bg-surface-container-lowest p-1" justify="start">
              <Button
                type="button"
                onClick={() => onTabChange('templates')}
                size="sm"
                variant={activeTab === 'templates' ? 'primary' : 'ghost'}
              >
                模板 {templates.length}
              </Button>
              <Button
                type="button"
                onClick={() => onTabChange('materials')}
                size="sm"
                variant={activeTab === 'materials' ? 'primary' : 'ghost'}
              >
                素材/清洗稿 {materials.length}
              </Button>
            </Toolbar>
            {multiSelect && !!selectedList.length && (
              <Button
                type="button"
                onClick={selectAllVisible}
                size="sm"
                variant="quiet"
              >
                {selectedList.every((item) => normalizedSelectedKeys.includes(pickerItemKey(activeTab, item))) ? '取消本页全选' : '选择本页全部'}
              </Button>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-4">
          {loading ? (
            <div className="space-y-2">
              <div className="h-14 animate-pulse rounded-md bg-surface-container-low" />
              <div className="h-14 animate-pulse rounded-md bg-surface-container-low" />
              <div className="h-14 animate-pulse rounded-md bg-surface-container-low" />
            </div>
          ) : activeTab === 'templates' ? (
            templates.length ? (
              <div className="space-y-2">
                {templates.map((template) => {
                  const key = template.templateId || template.filePath || template.id
                  return (
                    <label key={key} className={`block cursor-pointer rounded-md border p-3 transition-colors ${normalizedSelectedKeys.includes(key) ? 'border-primary bg-primary/5' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}>
                      <div className="flex items-start gap-3">
                        <input
                          type="radio"
                          name="business-template-select"
                          checked={normalizedSelectedKeys.includes(key)}
                          onChange={() => onToggleKey(key, { replace: true })}
                          className="mt-1 h-4 w-4"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="font-semibold text-on-surface">{template.templateName || template.fileName}</div>
                          <div className="mt-1 truncate text-xs text-outline">{template.sourceLabel || sourceModeLabels[template.sourceMode] || template.sourceMode || '投标模板'} · {template.filePath || '-'}</div>
                          {template.reason && <div className="mt-1 line-clamp-2 text-xs text-on-surface-variant">{template.reason}</div>}
                        </div>
                      </div>
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">暂无可选模板。请确认 S1/S2 已上传模板，或系统设置中已配置商务标默认模板。</div>
            )
          ) : materials.length ? (
            <div className="space-y-2">
              {materials.map((material) => {
                const key = material.materialId || material.id
                const evidenceSegments = asArray(material.evidenceSegments)
                return (
                  <label key={key} className={`block cursor-pointer rounded-md border p-3 transition-colors ${normalizedSelectedKeys.includes(key) ? 'border-primary bg-primary/5' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}>
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={normalizedSelectedKeys.includes(key)}
                        onChange={() => onToggleKey(key)}
                        className="mt-1 h-4 w-4"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="font-semibold text-on-surface">{material.materialName}</div>
                            <div className="mt-1 truncate text-xs text-outline">{material.folderPath}</div>
                          </div>
                          {materialPreviewKey(material) && (
                            <Button
                              type="button"
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                onPreview?.(material)
                              }}
                              size="xs"
                              variant="quiet"
                            >
                              预览
                            </Button>
                          )}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-on-surface-variant">
                          <span>层级：{material.materialTier || '-'}</span>
                          <span>清洗：{material.cleanStatus || '-'}</span>
                          <span>依据：{material.segmentCount || 0}</span>
                          {material.turbineModelLabel && <span>机型：{material.turbineModelLabel}</span>}
                        </div>
                        {!!evidenceSegments.length && (
                          <div className="mt-2 rounded bg-primary/5 px-2 py-1 text-[11px] text-on-surface-variant">
                            推荐依据：{evidenceSegments.slice(0, 2).map((segment) => segment.evidenceSegmentTitle || segment.materialName || segment.evidenceSegmentId).filter(Boolean).join('；')}
                            {evidenceSegments.length > 2 ? `；另有 ${evidenceSegments.length - 2} 个` : ''}
                          </div>
                        )}
                      </div>
                    </div>
                  </label>
                )
              })}
            </div>
          ) : (
            <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">暂无匹配素材。</div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="text-xs text-on-surface-variant">
            {payload?.summary ? `可选模板 ${payload.summary.templateCount || 0} 个 · 可选素材/清洗稿 ${payload.summary.materialCount || 0} 个` : '从当前商务标可读范围加载'}
            {selectedCount ? ` · 已选 ${selectedCount} 个` : ''}
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" onClick={onClose} variant="quiet">取消</Button>
            <Button
              type="button"
              onClick={() => onConfirm(multiSelect ? selectedItems : selectedItem, activeTab)}
              disabled={!selectedCount || loading}
              variant="primary"
            >
              {activeTab === 'templates' ? '指定为当前任务模板' : `指定 ${selectedCount || ''} 个素材`}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function BusinessTableFillModal({
  open,
  task,
  payload,
  loading,
  busy,
  keyword,
  targetKey,
  sourceKeys,
  onKeywordChange,
  onTargetChange,
  onToggleSource,
  onPreview,
  onClose,
  onConfirm,
}) {
  if (!open || !task) return null
  const targets = tableFillTargetCandidates(task)
  const factSource = {
    id: PROJECT_FACT_SOURCE_KEY,
    kind: 'project_fact_table',
    materialId: PROJECT_FACT_SOURCE_KEY,
    materialName: '项目事实表',
    folderPath: '商务标项目事实表',
    materialTier: 'project',
    cleanStatus: 'confirmed',
    segmentCount: 1,
  }
  const materials = [factSource, ...asArray(payload?.items)]
  const normalizedSourceKeys = asArray(sourceKeys)
  const selectedTarget = targets.find((item) => tableFillTargetKey(item) === targetKey) || null
  const selectedSources = materials.filter((item) => normalizedSourceKeys.includes(materialPreviewKey(item)))
  const toggleVisibleSources = () => {
    const visibleKeys = materials.map((item) => materialPreviewKey(item)).filter((key) => key && key !== PROJECT_FACT_SOURCE_KEY)
    const allSelected = visibleKeys.length > 0 && visibleKeys.every((key) => normalizedSourceKeys.includes(key))
    onToggleSource(allSelected ? [PROJECT_FACT_SOURCE_KEY] : [PROJECT_FACT_SOURCE_KEY, ...visibleKeys], { replace: true })
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">AI填表</h3>
          </div>
          <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
        </div>

        <div className="border-b border-surface-container-high p-4">
          <div className="relative">
            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-lg text-outline">search</span>
            <input
              value={keyword}
              onChange={(event) => onKeywordChange(event.target.value)}
              className="h-10 w-full rounded-md border border-surface-container-high bg-surface-container-lowest pl-10 pr-3 text-sm text-on-surface"
              placeholder="搜索右侧素材库文件、清洗稿、路径、关键词..."
            />
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.2fr)]">
          <div className="min-h-0 overflow-auto border-b border-surface-container-high p-4 lg:border-b-0 lg:border-r">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h4 className="text-sm font-semibold text-on-surface">待填表</h4>
              <Badge size="xs" variant={targets.length ? 'pending' : 'warn'}>{targets.length} 个</Badge>
            </div>
            {targets.length ? (
              <div className="space-y-2">
                {targets.map((target) => {
                  const key = tableFillTargetKey(target)
                  const checked = targetKey === key
                  return (
                    <label key={key} className={`block cursor-pointer rounded-md border p-3 transition-colors ${checked ? 'border-primary bg-primary/5' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}>
                      <div className="flex items-start gap-3">
                        <input
                          type="radio"
                          name="business-table-fill-target"
                          checked={checked}
                          onChange={() => onTargetChange(key)}
                          className="mt-1 h-4 w-4"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="line-clamp-2 text-sm font-semibold text-on-surface">{tableFillTargetTitle(target)}</div>
                          <div className="mt-1 truncate text-xs text-outline">
                            {sourceModeLabels[target.sourceMode] || target.sourceLabel || target.sourceMode || '模板/附件'} · {target.filePath || target.path || target.templateId || target.artifactId || '-'}
                          </div>
                          {(target.reason || target.evidenceSummary) && (
                            <div className="mt-1 line-clamp-2 text-xs text-on-surface-variant">{target.reason || target.evidenceSummary}</div>
                          )}
                        </div>
                      </div>
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">
                当前任务还没有可填表模板或附件。可先在候选素材中选择表格、人工指定素材库表格，或上传补充表格。
              </div>
            )}
          </div>

          <div className="min-h-0 overflow-auto p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-on-surface">数据来源素材</h4>
                <Badge size="xs" variant="pending">{materials.length} 个</Badge>
              </div>
              {materials.length > 1 && (
                <Button type="button" onClick={toggleVisibleSources} size="sm" variant="quiet">
                  {materials.filter((item) => !isProjectFactSource(item)).every((item) => normalizedSourceKeys.includes(materialPreviewKey(item))) ? '取消本页全选' : '选择本页全部'}
                </Button>
              )}
            </div>
            {loading ? (
              <div className="space-y-2">
                <div className="h-16 animate-pulse rounded-md bg-surface-container-low" />
                <div className="h-16 animate-pulse rounded-md bg-surface-container-low" />
                <div className="h-16 animate-pulse rounded-md bg-surface-container-low" />
              </div>
            ) : materials.length ? (
              <div className="space-y-2">
                {materials.map((material) => {
                  const key = materialPreviewKey(material)
                  const checked = normalizedSourceKeys.includes(key)
                  const evidenceSegments = asArray(material.evidenceSegments)
                  const projectFact = isProjectFactSource(material)
                  return (
                    <label key={key} className={`block cursor-pointer rounded-md border p-3 transition-colors ${checked ? 'border-primary bg-primary/5' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}>
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={projectFact}
                          onChange={() => onToggleSource(key)}
                          className="mt-1 h-4 w-4"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <div className="line-clamp-2 text-sm font-semibold text-on-surface">{material.materialName || material.name || material.fileName || key}</div>
                                {projectFact && <Badge size="xs" variant="done">默认数据源</Badge>}
                                {businessMaterialKindLabel(material) && <Badge size="xs" variant={businessMaterialKindLabel(material) === '固定素材' ? 'done' : 'pending'}>{businessMaterialKindLabel(material)}</Badge>}
                              </div>
                              <div className="mt-1 truncate text-xs text-outline">{material.folderPath || material.path || '-'}</div>
                            </div>
                            {materialPreviewKey(material) && !projectFact && (
                              <Button
                                type="button"
                                onClick={(event) => {
                                  event.preventDefault()
                                  event.stopPropagation()
                                  onPreview?.(material)
                                }}
                                size="xs"
                                variant="quiet"
                              >
                                预览
                              </Button>
                            )}
                          </div>
                          {!projectFact && <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-on-surface-variant">
                            <span>层级：{material.materialTier || '-'}</span>
                            <span>清洗：{material.cleanStatus || '-'}</span>
                            <span>依据：{material.segmentCount || evidenceSegments.length || 0}</span>
                            {material.turbineModelLabel && <span>机型：{material.turbineModelLabel}</span>}
                          </div>}
                          {!!evidenceSegments.length && (
                            <div className="mt-2 rounded bg-primary/5 px-2 py-1 text-[11px] text-on-surface-variant">
                              依据：{evidenceSegments.slice(0, 2).map((segment) => segment.evidenceSegmentTitle || segment.materialName || segment.evidenceSegmentId).filter(Boolean).join('；')}
                              {evidenceSegments.length > 2 ? `；另有 ${evidenceSegments.length - 2} 个` : ''}
                            </div>
                          )}
                        </div>
                      </div>
                    </label>
                  )
                })}
              </div>
            ) : (
              <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">暂无匹配素材。</div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="text-xs text-on-surface-variant">
            {payload?.summary ? `可选素材 ${payload.summary.materialCount || 0} 个` : '从当前商务标素材库加载'}
            {selectedTarget ? ` · 待填表：${tableFillTargetTitle(selectedTarget)}` : ''}
            {selectedSources.length ? ` · 数据来源 ${selectedSources.length} 个` : ' · 默认包含项目事实表'}
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" onClick={onClose} disabled={busy} variant="quiet">取消</Button>
            <Button
              type="button"
              onClick={() => onConfirm(selectedTarget, selectedSources)}
              disabled={busy || loading || !selectedTarget}
              variant="primary"
            >
              {busy ? '填表中...' : '开始AI填表'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function BusinessGapRecognition({ showToast }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const workspaceSlug = useWorkspaceSlug()
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [selectedTocId, setSelectedTocId] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [actionLoading, setActionLoading] = useState('')
  const [factModalOpen, setFactModalOpen] = useState(false)
  const [factTable, setFactTable] = useState(null)
  const [factFields, setFactFields] = useState([])
  const [materialPickerOpen, setMaterialPickerOpen] = useState(false)
  const [materialPickerTaskId, setMaterialPickerTaskId] = useState('')
  const [materialPickerPayload, setMaterialPickerPayload] = useState(null)
  const [materialPickerLoading, setMaterialPickerLoading] = useState(false)
  const [materialPickerKeyword, setMaterialPickerKeyword] = useState('')
  const [materialPickerTab, setMaterialPickerTab] = useState('materials')
  const [materialPickerSelectedKeys, setMaterialPickerSelectedKeys] = useState([])
  const [materialPreviewOpen, setMaterialPreviewOpen] = useState(false)
  const [materialPreviewLoading, setMaterialPreviewLoading] = useState(false)
  const [materialPreviewPayload, setMaterialPreviewPayload] = useState(null)
  const [materialPreviewSource, setMaterialPreviewSource] = useState(null)
  const [tableFillOpen, setTableFillOpen] = useState(false)
  const [tableFillTaskId, setTableFillTaskId] = useState('')
  const [tableFillPayload, setTableFillPayload] = useState(null)
  const [tableFillLoading, setTableFillLoading] = useState(false)
  const [tableFillKeyword, setTableFillKeyword] = useState('')
  const [tableFillTargetKeyValue, setTableFillTargetKeyValue] = useState('')
  const [tableFillSourceKeys, setTableFillSourceKeys] = useState([])
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationModalOpen, setGenerationModalOpen] = useState(false)
  const [gapPlanModalOpen, setGapPlanModalOpen] = useState(false)
  const [gapPlanError, setGapPlanError] = useState('')
  const selectedTocIdRef = useRef('')
  const autoFactBuildRef = useRef(false)
  const autoPlanRunRef = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [data, factsPayload] = await Promise.all([
        businessGapsAPI.list(id),
        businessGapsAPI.facts(id),
      ])
      setPayload(data)
      const nextFacts = factsPayload?.schemaVersion ? factsPayload : null
      setFactTable(nextFacts)
      setFactFields(asArray(nextFacts?.fields))
      const refs = asArray(data?.tocRefs)
      if (refs.length) {
        setSelectedTocId((current) => current || selectedTocIdRef.current || refs[0].nodeId)
      }
    } catch (e) {
      setError(e?.message || '商务标缺口计划加载失败。')
    } finally {
      setLoading(false)
    }
  }, [id])

  const loadGenerationStatus = useCallback(async () => {
    try {
      const data = await businessGenerateAPI.status(id)
      setGenerationStatus(data)
      return data
    } catch {
      return null
    }
  }, [id])

  useEffect(() => {
    const timer = setTimeout(() => {
      load()
      loadGenerationStatus()
    }, 0)
    return () => clearTimeout(timer)
  }, [load, loadGenerationStatus])

  useEffect(() => {
    selectedTocIdRef.current = selectedTocId
  }, [selectedTocId])

  const plan = useMemo(() => payload?.plan || payload?.businessGapPlan || {}, [payload?.businessGapPlan, payload?.plan])
  const tocRefs = useMemo(() => asArray(payload?.tocRefs || plan?.tocRefs), [payload, plan])
  const tasks = useMemo(() => asArray(payload?.tasks || plan?.tasks), [payload, plan])
  const taskById = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks])
  const selectedToc = tocRefs.find((ref) => ref.nodeId === selectedTocId) || tocRefs[0]
  const tocTaskIds = asArray(selectedToc?.taskIds)
  const visibleTasks = tocTaskIds.map((taskId) => taskById.get(taskId)).filter(Boolean)
  const selectedTask = taskById.get(selectedTaskId) || visibleTasks[0] || null
  const materialPickerTask = taskById.get(materialPickerTaskId) || selectedTask
  const tableFillTask = taskById.get(tableFillTaskId) || selectedTask
  const summary = payload?.summary || plan?.summary || {}
  const hasBusinessGapPlan = payload?.status === 'completed' && plan?.schemaVersion === 'bid-business-gap-plan-v1'
  const factConfirmed = factTable?.status === 'confirmed'
  const generationRunning = generationStatus?.status === 'running'
  const generationCompleted = generationStatus?.status === 'completed'
  const generationProgress = Math.max(0, Math.min(100, Number(generationStatus?.percentage) || 0))
  const actionCounts = useMemo(() => {
    const initial = {
      fixed_material: 0,
      manual_select: 0,
      manual_upload: 0,
      ignored: 0,
      ai_table_fill: 0,
      pending: 0,
    }
    tasks.forEach((task) => {
      const mode = taskActionMode(task)
      if (mode && initial[mode] !== undefined) initial[mode] += 1
      else initial.pending += 1
    })
    return initial
  }, [tasks])

  useEffect(() => {
    if (!generationRunning) return undefined
    const timer = window.setInterval(() => {
      loadGenerationStatus()
    }, 1200)
    return () => window.clearInterval(timer)
  }, [generationRunning, loadGenerationStatus])

  const runPlan = useCallback(async () => {
    setRunning(true)
    setError('')
    setGapPlanError('')
    setGapPlanModalOpen(true)
    try {
      const data = await businessGapsAPI.run(id)
      setPayload(data)
      const refs = asArray(data?.tocRefs || data?.plan?.tocRefs)
      if (refs.length) setSelectedTocId(refs[0].nodeId)
      showToast?.(data?.message || '商务标缺口计划已生成')
    } catch (e) {
      const message = e?.message || '商务标缺口计划生成失败。'
      setError(message)
      setGapPlanError(message)
      showToast?.(message, 'error')
    } finally {
      setRunning(false)
    }
  }, [id, showToast])

  const runBusinessAssembly = async () => {
    if (actionLoading) return
    if (!hasBusinessGapPlan) {
      showToast?.('素材匹配完成后可生成商务标正文。', 'error')
      return
    }
    setActionLoading('business-generate')
    setGenerationModalOpen(true)
    try {
      const data = await businessGenerateAPI.run(id)
      setGenerationStatus(data)
      loadGenerationStatus()
      showToast?.(data?.message || '已开始生成商务标正文。')
    } catch (e) {
      setGenerationModalOpen(false)
      showToast?.(e?.message || '生成商务标正文失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const advanceToBusinessS4 = async () => {
    if (actionLoading) return
    if (!generationCompleted) {
      showToast?.('请先完成商务标正文生成，再进入 S4 共创导出。', 'error')
      return
    }
    setActionLoading('advance-business-s4')
    try {
      await businessStagesAPI.update(id, 4, { status: 'completed', allowUnconfirmedBusinessGap: true })
      showToast?.('已进入 S4 共创导出。')
      navigate(projectRoute(id, '/editor', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入 S4 共创导出失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const mergePlanPayload = (data) => {
    setPayload((current) => ({
      ...(current || {}),
      plan: data.plan || current?.plan,
      businessGapPlan: data.plan || current?.businessGapPlan,
      tocRefs: data.plan?.tocRefs || current?.tocRefs,
      tasks: data.plan?.tasks || current?.tasks,
      summary: data.summary || data.plan?.summary || current?.summary,
      integrity: data.integrity || current?.integrity,
    }))
  }

  const selectMaterials = async (task, materials) => {
    const selectedMaterials = asArray(materials).filter(Boolean)
    if (!task || !selectedMaterials.length) return
    const materialKey = selectedMaterials.map((material) => material.evidenceSegmentId || material.wikiCardId || material.materialId || material.materialName).filter(Boolean).join(',')
    setActionLoading(`select:${materialKey}`)
    try {
      const preferredHandlingMode = selectedMaterials.map((material) => material.handlingMode).find(Boolean)
      const data = await businessGapsAPI.selectMaterial(id, task.id, {
        materials: selectedMaterials,
        handlingMode: preferredHandlingMode,
      })
      mergePlanPayload(data)
      showToast?.(`已选择 ${selectedMaterials.length} 个素材并快照到商务 S3 工作区`)
    } catch (e) {
      showToast?.(e?.message || '选择素材失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const selectTemplate = async (task, template) => {
    if (!task || !template) return
    const templateKey = template.templateId || template.filePath || template.templateName || template.fileName
    setActionLoading(`select-template:${templateKey}`)
    try {
      const data = await businessGapsAPI.selectTemplate(id, task.id, { template })
      mergePlanPayload(data)
      showToast?.(data?.message || '已选择模板并快照到商务 S3 工作区')
    } catch (e) {
      showToast?.(e?.message || '选择模板失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const openMaterialPreview = async (material, mode = 'quick') => {
    const materialId = materialPreviewKey(material)
    if (!materialId) {
      showToast?.('该候选素材缺少素材 ID，暂不能预览。', 'error')
      return
    }
    setMaterialPreviewOpen(true)
    setMaterialPreviewLoading(true)
    setMaterialPreviewSource(material)
    if (mode === 'quick') setMaterialPreviewPayload(null)
    try {
      const data = await businessGapsAPI.previewMaterial(id, materialId, { mode })
      setMaterialPreviewPayload(data)
    } catch (e) {
      showToast?.(e?.message || '候选素材预览失败', 'error')
      if (mode === 'quick') setMaterialPreviewOpen(false)
    } finally {
      setMaterialPreviewLoading(false)
    }
  }

  const closeMaterialPreview = () => {
    setMaterialPreviewOpen(false)
    setMaterialPreviewPayload(null)
    setMaterialPreviewSource(null)
    setMaterialPreviewLoading(false)
  }

  const loadTableFillMaterials = useCallback(async (keyword = '') => {
    setTableFillLoading(true)
    try {
      const data = await businessGapsAPI.selectableMaterials(id, { keyword: keyword.trim() })
      setTableFillPayload(data)
    } catch (e) {
      showToast?.(e?.message || 'AI填表数据来源加载失败', 'error')
      setTableFillPayload({ items: [], summary: {} })
    } finally {
      setTableFillLoading(false)
    }
  }, [id, showToast])

  const loadSelectableMaterials = useCallback(async (keyword = '') => {
    setMaterialPickerLoading(true)
    try {
      const data = await businessGapsAPI.selectableMaterials(id, { keyword: keyword.trim() })
      setMaterialPickerPayload(data)
      const preferredTab = asArray(data?.templates).length ? 'templates' : 'materials'
      setMaterialPickerTab((current) => current || preferredTab)
      setMaterialPickerSelectedKeys([])
    } catch (e) {
      showToast?.(e?.message || '商务素材库可选材料加载失败', 'error')
      setMaterialPickerPayload({ templates: [], items: [] })
    } finally {
      setMaterialPickerLoading(false)
    }
  }, [id, showToast])

  const openMaterialPicker = async (task) => {
    if (!task) return
    setMaterialPickerTaskId(task.id)
    setMaterialPickerOpen(true)
    setMaterialPickerKeyword('')
    setMaterialPickerSelectedKeys([])
    setMaterialPickerTab('materials')
    await loadSelectableMaterials('')
  }

  const openTableFillModal = async (task) => {
    if (!task) return
    const targets = tableFillTargetCandidates(task)
    setTableFillTaskId(task.id)
    setTableFillOpen(true)
    setTableFillKeyword('')
    setTableFillTargetKeyValue(targets[0] ? tableFillTargetKey(targets[0]) : '')
    setTableFillSourceKeys([PROJECT_FACT_SOURCE_KEY])
    await loadTableFillMaterials('')
  }

  const toggleMaterialPickerKey = (value, options = {}) => {
    const keys = Array.isArray(value) ? value.filter(Boolean) : [value].filter(Boolean)
    if (options.replace) {
      setMaterialPickerSelectedKeys(keys)
      return
    }
    const key = keys[0]
    if (!key) return
    setMaterialPickerSelectedKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  }

  const selectCandidateMaterial = async (task, material) => {
    const selectedMaterial = materialSelectionPayload(material, 'materials')
    if (!selectedMaterial) return
    await selectMaterials(task, [{ ...selectedMaterial, handlingMode: businessMaterialKindLabel(material) === '固定素材' ? 'fixed_material' : 'manual_select' }])
  }

  const ignoreTask = async (task) => {
    if (!task || actionLoading) return
    setActionLoading(`ignore:${task.id}`)
    try {
      const data = await businessGapsAPI.updateTask(id, task.id, {
        status: 'ignored',
        decision: 'ready',
        handlingMode: 'ignored',
        notes: '人工忽略',
      })
      mergePlanPayload(data)
      showToast?.('已忽略该任务')
    } catch (e) {
      showToast?.(e?.message || '忽略任务失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const confirmMaterialPicker = async (selection, tab) => {
    const task = materialPickerTask
    const selectedItems = asArray(selection).filter(Boolean)
    if (!task || !selectedItems.length) return
    if (tab === 'templates') {
      setMaterialPickerOpen(false)
      await selectTemplate(task, selectedItems[0])
      return
    }
    const materials = selectedItems.map((item) => materialSelectionPayload(item, tab)).filter(Boolean)
    setMaterialPickerOpen(false)
    await selectMaterials(task, materials)
  }

  const changeMaterialPickerKeyword = (value) => {
    setMaterialPickerKeyword(value)
  }

  const changeTableFillKeyword = (value) => {
    setTableFillKeyword(value)
  }

  const toggleTableFillSourceKey = (value, options = {}) => {
    const keys = Array.isArray(value) ? value.filter(Boolean) : [value].filter(Boolean)
    if (options.replace) {
      setTableFillSourceKeys(keys)
      return
    }
    const key = keys[0]
    if (!key) return
    setTableFillSourceKeys((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  }

  const confirmTableFill = async (target, sourceMaterials) => {
    const task = tableFillTask
    if (!task || !target) return
    setActionLoading(`table-fill:${task.id}`)
    try {
      const materials = asArray(sourceMaterials)
        .filter((item) => !isProjectFactSource(item))
        .map((item) => materialSelectionPayload(item, 'materials'))
        .filter(Boolean)
      const data = await businessGapsAPI.tableFill(id, task.id, {
        target,
        sourceMaterials: materials,
        handlingMode: 'ai_table_fill',
        operator: '当前用户',
      })
      mergePlanPayload(data)
      if (data?.projectFactTable?.schemaVersion) {
        setFactTable(data.projectFactTable)
        setFactFields(asArray(data.projectFactTable.fields))
      }
      setTableFillOpen(false)
      showToast?.(data?.message || 'AI填表产物已生成')
    } catch (e) {
      showToast?.(e?.message || 'AI填表失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  useEffect(() => {
    if (!materialPickerOpen) return undefined
    const timer = setTimeout(() => {
      loadSelectableMaterials(materialPickerKeyword)
    }, 300)
    return () => clearTimeout(timer)
  }, [loadSelectableMaterials, materialPickerKeyword, materialPickerOpen])

  useEffect(() => {
    if (!tableFillOpen) return undefined
    const timer = setTimeout(() => {
      loadTableFillMaterials(tableFillKeyword)
    }, 300)
    return () => clearTimeout(timer)
  }, [loadTableFillMaterials, tableFillKeyword, tableFillOpen])

  const createManualTaskForSelectedToc = async (files) => {
    if (!selectedToc) throw new Error('请先选择一个目录章节。')
    const firstFileName = files?.[0]?.name || ''
    const data = await businessGapsAPI.createManualTask(id, selectedToc.nodeId, {
      title: firstFileName ? `${selectedToc.title}补充材料` : `${selectedToc.title || '本章节'}补充材料`,
      requirement: `操作人在 S3 针对目录章节「${selectedToc.title || selectedToc.nodeId}」手动上传补充材料。`,
    })
    mergePlanPayload(data)
    setSelectedTaskId(data.task?.id || '')
    return data.task
  }

  const uploadSupplementForTask = async (event, task = selectedTask) => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (!files.length) return
    setActionLoading('upload')
    try {
      const targetTask = task || await createManualTaskForSelectedToc(files)
      if (!targetTask) throw new Error('未能创建补料任务。')
      const emptyFile = files.find((file) => !file.size)
      if (emptyFile) throw new Error(`文件内容为空：${emptyFile.name}`)
      const formData = new FormData()
      files.forEach((file) => formData.append('files', file))
      formData.append('operator', '当前用户')
      const data = await businessGapsAPI.uploadFiles(id, targetTask.id, { formData })
      mergePlanPayload(data)
      showToast?.(`已上传 ${files.length} 份补充材料`)
    } catch (e) {
      showToast?.(e?.message || '上传补料失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const loadFactTable = async ({ build = false } = {}) => {
    if (actionLoading) return null
    setActionLoading(build ? 'facts-build' : 'facts-load')
    try {
      const data = build ? await businessGapsAPI.buildFacts(id) : await businessGapsAPI.facts(id)
      setFactTable(data)
      setFactFields(asArray(data?.fields))
      showToast?.(build ? '商务标项目事实表已生成' : '商务标项目事实表已刷新')
      return data
    } catch (e) {
      showToast?.(e?.message || '商务标项目事实表加载失败', 'error')
      return null
    } finally {
      setActionLoading('')
    }
  }

  const openFactModal = async () => {
    setFactModalOpen(true)
    if (!factTable?.schemaVersion || !asArray(factTable?.fields).length) {
      await loadFactTable({ build: true })
    }
  }

  const changeFactField = (index, key, value) => {
    setFactFields((current) => current.map((field, idx) => (
      idx === index ? { ...field, [key]: value, status: value ? (field.status === 'confirmed' ? 'confirmed' : 'candidate') : 'missing' } : field
    )))
  }

  const confirmFactTable = async () => {
    if (actionLoading || !factFields.length) return null
    setActionLoading('facts-confirm')
    try {
      const data = await businessGapsAPI.saveFacts(id, { fields: factFields, confirm: true, operator: '当前用户' })
      setFactTable(data)
      setFactFields(asArray(data?.fields))
      showToast?.('商务标项目事实表已保存，可用于后续填写')
      return data
    } catch (e) {
      showToast?.(e?.message || '商务标项目事实表保存失败', 'error')
      return null
    } finally {
      setActionLoading('')
    }
  }

  useEffect(() => {
    if (loading || payload?.status !== 'completed' || autoFactBuildRef.current) return
    if (factTable?.schemaVersion && asArray(factTable?.fields).length) return
    autoFactBuildRef.current = true
    let cancelled = false
    const build = async () => {
      try {
        const data = await businessGapsAPI.buildFacts(id)
        if (cancelled) return
        setFactTable(data)
        setFactFields(asArray(data?.fields))
      } catch (e) {
        if (!cancelled) {
          showToast?.(e?.message || '商务标项目事实表自动生成失败', 'error')
        }
      }
    }
    build()
    return () => {
      cancelled = true
    }
  }, [factTable?.schemaVersion, factTable?.fields, id, loading, payload?.status, showToast])

  useEffect(() => {
    if (loading || autoPlanRunRef.current || running || payload?.status === 'completed') return
    autoPlanRunRef.current = true
    runPlan()
  }, [loading, payload?.status, running, runPlan])

  if (loading) return <PageLoading title="正在加载商务标素材匹配" description="正在读取商务目录、解析产物和素材推荐。" />
  if (error && !payload) return <PageError title="加载失败" description={error} onRetry={load} />

  return (
    <div className="business-ui-shell flex flex-col gap-6">
      <BusinessProjectStageProgress projectId={id} showToast={showToast} />
      <PageHeader
        actions={(
          <Toolbar>
            <Button
              type="button"
              onClick={openFactModal}
              disabled={running || !!actionLoading || payload?.status !== 'completed'}
              size="stage"
              variant={factConfirmed ? 'secondary' : 'quiet'}
            >
              {factConfirmed ? '项目事实表已确认' : '维护项目事实表'}
            </Button>
            <Button
              type="button"
              onClick={runBusinessAssembly}
              disabled={running || !!actionLoading || !hasBusinessGapPlan || generationRunning}
              title={!hasBusinessGapPlan ? '素材匹配完成后可生成正文' : '允许带未确认项生成正文，生成结果会保留复核提示'}
              size="stage"
              variant="primary"
            >
              {generationRunning ? '生成中...' : generationCompleted ? '重新生成正文' : '生成商务标正文'}
            </Button>
            <Button
              type="button"
              onClick={advanceToBusinessS4}
              disabled={running || !!actionLoading || !generationCompleted}
              size="stage"
              variant="success"
            >
              {actionLoading === 'advance-business-s4' ? '进入中...' : '进入共创导出'}
            </Button>
          </Toolbar>
        )}
      />

      {error && (
        <div className="rounded-lg border border-error/20 bg-error/10 px-4 py-3 text-sm text-error">{error}</div>
      )}

      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.56fr)]">
        <div className="grid auto-rows-max gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="目录节点" value={summary.tocRefCount || tocRefs.length} />
          <StatCard label="响应件任务" value={summary.taskCount || tasks.length} />
          <StatCard label="待处理" value={(summary.needsInputCount || 0) + (summary.reviewRequiredCount || 0)} />
          <StatCard label="已就绪" value={summary.readyCount || 0} />
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

      {payload?.status === 'completed' ? (
        <div className="grid min-h-[720px] gap-4 xl:grid-cols-[460px_minmax(0,1fr)] 2xl:grid-cols-[520px_minmax(0,1fr)]">
          <DataCard className="!p-0 overflow-hidden">
            <div className="business-section-head flex items-center border-b border-surface-container-high px-4 py-3">
              <h3 className="text-base font-headline font-bold text-on-surface">商务目录</h3>
            </div>
            <div className="max-h-[720px] overflow-auto p-3">
              {tocRefs.map((ref) => {
                const refTasks = asArray(ref.taskIds).map((taskId) => taskById.get(taskId)).filter(Boolean)
                const isSelected = selectedToc?.nodeId === ref.nodeId
                const level = Math.max(1, Number(ref.level) || 1)
                const levelStyles = tocLevelStyles(level)
                return (
                  <Button
                    key={ref.nodeId}
                    type="button"
                    onClick={() => {
                      setSelectedTocId(ref.nodeId)
                      setSelectedTaskId('')
                    }}
                    className={`business-toc-item mb-2 h-auto w-full items-start justify-start border px-3 text-left ${levelStyles.itemClass} ${isSelected ? 'border-primary bg-primary-fixed shadow-sm' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}
                    data-active={isSelected ? 'true' : 'false'}
                    data-level={level}
                    style={{ paddingLeft: `${12 + Math.max(0, level - 1) * 14}px` }}
                    variant="ghost"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 items-start">
                        <div className={`line-clamp-2 leading-snug ${levelStyles.titleClass}`} style={levelStyles.titleStyle}>{ref.number ? `${ref.number} ` : ''}{ref.title}</div>
                      </div>
                      <TocActionBadges tasks={refTasks} />
                    </div>
                  </Button>
                )
              })}
            </div>
          </DataCard>

          <DataCard className="!p-0 overflow-hidden">
            <div className="business-section-head flex items-center border-b border-surface-container-high px-4 py-3">
              <h3 className="text-base font-headline font-bold text-on-surface">
                {selectedToc ? `${selectedToc.number ? `${selectedToc.number} ` : ''}${selectedToc.title}` : '请选择目录章节'}
              </h3>
            </div>
            {!selectedToc ? (
              <div className="p-8 text-sm text-on-surface-variant">请选择左侧商务目录章节。</div>
            ) : (
              <div className="max-h-[720px] overflow-auto p-4">
                {!visibleTasks.length ? (
                  <div className="business-dropzone rounded-md border border-dashed border-surface-container-high p-8 text-center">
                    <span className="material-symbols-outlined text-4xl text-outline">inventory_2</span>
                    <h3 className="mt-3 text-base font-headline font-bold text-on-surface">当前章节暂无系统任务</h3>
                    <FileButton
                      accept={SUPPLEMENT_ACCEPT}
                      className="mt-4"
                      disabled={!!actionLoading}
                      icon="add"
                      multiple
                      onChange={(event) => uploadSupplementForTask(event, null)}
                      variant="primary"
                    >
                      {actionLoading === 'upload' ? '上传中...' : '新增任务并上传补料'}
                    </FileButton>
                  </div>
                ) : visibleTasks.map((task) => {
                  const resolvedArtifacts = asArray(task.resolvedArtifacts)
                  const selectedMaterialIds = new Set(
                    resolvedArtifacts
                      .filter((artifact) => artifact?.sourceMode === 'selected_from_business_material_library')
                      .map((artifact) => artifact.materialId)
                      .filter(Boolean),
                  )
                  const materialCandidates = topCandidateMaterials(task.candidateMaterials).sort((a, b) => {
                    const aSelected = selectedMaterialIds.has(a.materialId || a.id)
                    const bSelected = selectedMaterialIds.has(b.materialId || b.id)
                    if (aSelected !== bSelected) return aSelected ? -1 : 1
                    return numericMatchScore(b) - numericMatchScore(a)
                  })
                  return (
                  <section
                    key={task.id}
                    className="mb-4"
                    data-active={selectedTask?.id === task.id ? 'true' : 'false'}
                    onMouseEnter={() => setSelectedTaskId(task.id)}
                  >
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" onClick={() => openMaterialPicker(task)} disabled={!!actionLoading} size="sm" variant="primary">
                        人工指定素材库材料
                      </Button>
                      <FileButton accept={SUPPLEMENT_ACCEPT} disabled={!!actionLoading} icon="" multiple onChange={(event) => uploadSupplementForTask(event, task)} size="sm" variant="primary">
                        {actionLoading === 'upload' ? '上传中...' : '人工上传补充'}
                      </FileButton>
                      <Button type="button" disabled={!!actionLoading} onClick={() => openTableFillModal(task)} size="sm" variant="primary">
                        {actionLoading === `table-fill:${task.id}` ? '填表中...' : 'AI填表'}
                      </Button>
                      <Button type="button" disabled={!!actionLoading} onClick={() => ignoreTask(task)} size="sm" variant="quiet">
                        {actionLoading === `ignore:${task.id}` ? '处理中...' : '忽略'}
                      </Button>
                    </div>

                    <div className="mt-4 grid gap-3">
                      <div className="rounded-md border border-surface-container-high bg-surface p-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <h4 className="text-sm font-semibold text-on-surface">候选素材</h4>
                          </div>
                        </div>
                        {!materialCandidates.length ? (
                          <p className="mt-2 text-sm text-on-surface-variant">暂无候选素材。可上传补料，或后续更新 Wiki 映射/素材清洗稿。</p>
                        ) : materialCandidates.map((material) => {
                          const evidence = material.wikiEvidence || {}
                          const evidenceSegments = asArray(material.evidenceSegments)
                          const primarySegment = evidenceSegments[0] || {}
                          const segmentTitle = primarySegment.evidenceSegmentTitle || primarySegment.title || material.evidenceSegmentTitle || evidence.segmentTitle || ''
                          const sourcePages = primarySegment.evidenceSourcePages || primarySegment.sourcePages || material.evidenceSourcePages || evidence.sourcePages || ''
                          const evidenceSummary = primarySegment.evidenceSummary || primarySegment.summary || material.evidenceSummary || evidence.summary || ''
                          const materialKey = candidateMaterialKey(material)
                          const isSelectedCandidate = selectedMaterialIds.has(material.materialId || material.id)
                          const kindLabel = businessMaterialKindLabel(material)
                          const matchScore = Math.round(numericMatchScore(material) * 100)
                          return (
                            <div
                              key={materialKey}
                              className={`mt-2 rounded-md border px-3 py-2 ${
                                isSelectedCandidate
                                  ? 'border-secondary bg-secondary-container/50'
                                  : 'border-surface-container-high bg-surface-container-lowest'
                              }`}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0 flex-1">
                                  <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <div className="truncate text-sm font-semibold text-on-surface">{material.materialName || material.materialId}</div>
                                      {isSelectedCandidate && <Badge size="xs" variant="done">已选择素材</Badge>}
                                      {kindLabel && <Badge size="xs" variant={kindLabel === '固定素材' ? 'done' : 'pending'}>{kindLabel}</Badge>}
                                    </div>
                                    <div className="mt-1 text-xs text-outline">匹配度 {matchScore}% · {material.reason}</div>
                                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-on-surface-variant">
                                      {material.cleanStatus && <span>清洗：{material.cleanStatus}</span>}
                                      {material.cleanedFileName && <span>清洗稿可用</span>}
                                    </div>
                                    {segmentTitle && (
                                      <div className="mt-1 rounded bg-primary/5 px-2 py-1 text-[11px] text-on-surface-variant">
                                        Wiki依据：<span className="font-semibold text-primary">{segmentTitle}</span>
                                        {sourcePages ? ` · ${sourcePages}` : ''}
                                        {evidenceSegments.length > 1 ? ` · 另有 ${evidenceSegments.length - 1} 条依据` : ''}
                                      </div>
                                    )}
                                    {evidenceSummary && <div className="mt-1 line-clamp-2 text-[11px] text-on-surface-variant">{evidenceSummary}</div>}
                                    {material.wikiCardId && (
                                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-primary">
                                        <Badge size="xs" variant="info">Wiki</Badge>
                                        <span>{material.wikiCardId} · {usageModeLabels[material.wikiUsageMode] || material.wikiUsageMode || '未标注用法'}</span>
                                      </div>
                                    )}
                                    {evidence.validityStatus && <div className="mt-1 text-[11px] text-outline">有效期状态：{evidence.validityStatus}{evidence.expiryDate ? ` · ${evidence.expiryDate}` : ''}</div>}
                                    {material.folderPath && <div className="mt-1 truncate text-[11px] text-outline">{material.folderPath}</div>}
                                  </div>
                                </div>
                                <div className="flex shrink-0 flex-col gap-2">
                                  {materialPreviewKey(material) && (
                                    <Button
                                      type="button"
                                      onClick={() => openMaterialPreview(material)}
                                      disabled={!!actionLoading}
                                      size="sm"
                                      variant="quiet"
                                    >
                                      预览
                                    </Button>
                                  )}
                                  <Button
                                    type="button"
                                    onClick={() => selectCandidateMaterial(task, material)}
                                    disabled={!!actionLoading}
                                    size="sm"
                                    variant={isSelectedCandidate ? 'secondary' : 'primary'}
                                  >
                                    {actionLoading === `select:${materialKey}` ? '选择中...' : isSelectedCandidate ? '已选择' : '选择'}
                                  </Button>
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>

                  </section>
                  )
                })}
              </div>
            )}
          </DataCard>
        </div>
      ) : null}
      <FactMaintenanceModal
        open={factModalOpen}
        factTable={factTable}
        fields={factFields}
        busy={['facts-build', 'facts-load', 'facts-confirm'].includes(actionLoading)}
        onClose={() => setFactModalOpen(false)}
        onConfirm={confirmFactTable}
        onFieldChange={changeFactField}
      />
      <BusinessMaterialPickerModal
        open={materialPickerOpen}
        task={materialPickerTask}
        payload={materialPickerPayload}
        loading={materialPickerLoading}
        keyword={materialPickerKeyword}
        activeTab={materialPickerTab}
        selectedKeys={materialPickerSelectedKeys}
        onKeywordChange={changeMaterialPickerKeyword}
        onTabChange={(tab) => {
          setMaterialPickerTab(tab)
          setMaterialPickerSelectedKeys([])
        }}
        onToggleKey={toggleMaterialPickerKey}
        onClose={() => setMaterialPickerOpen(false)}
        onConfirm={confirmMaterialPicker}
        onPreview={openMaterialPreview}
      />
      <BusinessTableFillModal
        open={tableFillOpen}
        task={tableFillTask}
        payload={tableFillPayload}
        loading={tableFillLoading}
        busy={actionLoading === `table-fill:${tableFillTask?.id}`}
        keyword={tableFillKeyword}
        targetKey={tableFillTargetKeyValue}
        sourceKeys={tableFillSourceKeys}
        onKeywordChange={changeTableFillKeyword}
        onTargetChange={setTableFillTargetKeyValue}
        onToggleSource={toggleTableFillSourceKey}
        onClose={() => setTableFillOpen(false)}
        onConfirm={confirmTableFill}
        onPreview={openMaterialPreview}
      />
      <BusinessGenerationProgressModal
        open={generationModalOpen || generationRunning}
        status={generationStatus}
        progress={generationProgress}
        onClose={() => setGenerationModalOpen(false)}
      />
      <BusinessGapPlanProgressModal
        open={gapPlanModalOpen}
        running={running}
        error={gapPlanError}
        onClose={() => setGapPlanModalOpen(false)}
      />
      {materialPreviewOpen ? (
        <BusinessMaterialPreviewDrawer
          open={materialPreviewOpen}
          loading={materialPreviewLoading}
          payload={materialPreviewPayload}
          source={materialPreviewSource}
          onClose={closeMaterialPreview}
          onOpenOffice={() => openMaterialPreview(materialPreviewSource, 'office')}
        />
      ) : null}
    </div>
  )
}
