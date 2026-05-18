import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { businessGapsAPI, generateAPI, stagesAPI } from '../api'
import { PageLoading, PageError } from '../components/states/PageState'
import PageHeader from '../components/shared/PageHeader'
import DataCard from '../components/shared/DataCard'
import OnlyOfficeEmbed from '../components/shared/OnlyOfficeEmbed'
import ProjectStageProgress from '../components/shared/ProjectStageProgress'
import StageBreadcrumb from '../components/shared/StageBreadcrumb'
import { projectRoute, useWorkspaceSlug } from '../utils/workspace'

const statusLabels = {
  idle: '未生成',
  ready: '已就绪',
  needs_input: '待补料/待填写',
  review_required: '待复核',
  filling: '处理中',
  resolved: '已解决',
  ignored: '已忽略',
}

const decisionLabels = {
  ready: '可使用',
  fill_required: '需生成/填写',
  material_required: '需补材料',
  ai_draft_required: '需AI起草',
  review_required: '需复核',
}

const moduleLabels = {
  base_documents_guarantees: '01-基础响应文书与担保文件',
  structured_response_tables: '02-报价与结构化响应表',
  qualification_compliance_certificates: '03-主体资格、合规信用与专题证书',
  enterprise_finance_supply: '04-企业能力、财务与供货保障',
  performance_cooperation_support: '05-业绩、合作与专项支撑',
  commitments_and_notes: '06-承诺函与其他说明',
}

const statusTone = (status) => {
  if (status === 'ready' || status === 'resolved') return 'bg-secondary-container text-on-secondary-container'
  if (status === 'needs_input') return 'bg-error/10 text-error'
  if (status === 'review_required') return 'bg-tertiary-fixed text-on-tertiary-fixed'
  return 'bg-surface-container-high text-on-surface-variant'
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

const assemblyModeLabels = {
  template_fill_docx: '模板填充',
  attach_whole_file: '整件挂载/嵌入',
  embed_scan_or_image: '整件挂载/嵌入',
  extract_and_summarize: '整件挂载/嵌入',
  ai_draft: 'AI 自主填写',
  manual_upload: '人工上传来源',
}

const assemblyModeDescriptions = {
  template_fill_docx: '用于投标函、授权书、廉洁承诺等模板类文件，系统会基于模板和项目事实表填充。',
  attach_whole_file: '用于证书、扫描件、图片或内容已经完整的 Word/PDF，按整件挂载或嵌入处理。',
  embed_scan_or_image: '用于证书、扫描件、图片或内容已经完整的 Word/PDF，按整件挂载或嵌入处理。',
  extract_and_summarize: '兼容旧数据：后续商务素材按最小单元拆分后，不再单独提供提取总结/转写选项，旧任务按整件挂载/嵌入处理。',
  ai_draft: '用于无明确素材时由系统根据目录任务和项目事实表自主生成说明性文字。',
  manual_upload: '兼容旧数据：人工上传是材料来源，不建议作为处理方式。',
}

const assemblyModeOptions = [
  'template_fill_docx',
  'attach_whole_file',
  'ai_draft',
]

const editableAssemblyMode = (mode) => {
  if (mode === 'embed_scan_or_image') return 'attach_whole_file'
  if (mode === 'extract_and_summarize' || mode === 'extract_segment' || mode === 'table_fill_from_material') return 'attach_whole_file'
  return mode || ''
}

const sourceModeLabels = {
  uploaded_in_business_s3: '人工上传补料',
  selected_from_business_material_library: '已选素材快照',
  generated_by_business_s3_ai_draft: 'AI起草稿',
  generated_by_s1_business_parser: '解析生成承诺函',
  parsed_from_tender_attachment_template: '解析附件模板',
  parsed_business_scoring: '解析商务评分',
  project_uploaded_bid_template: '项目上传投标模板',
  system_default_bid_template: '系统默认商务模板',
  selected_from_bid_template: '已选投标模板',
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

const materialPreviewKey = (item) => item?.materialId || item?.id || ''

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
  if (tab === 'segments') {
    return {
      id: item.id || item.materialId,
      materialId: item.materialId || item.id,
      materialName: item.materialName,
      folderPath: item.folderPath,
      materialTier: item.materialTier,
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
    if ((material.score || 0) > (current.score || 0)) current.score = material.score
    if (material.reason && !String(current.reason || '').includes(material.reason)) {
      current.reason = [current.reason, material.reason].filter(Boolean).join(' + ')
    }
    ;['cleanStatus', 'cleanedFileName', 'folderPath', 'path', 'wikiCardId', 'wikiUsageMode', 'validityStatus', 'expiryDate'].forEach((field) => {
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
  return Array.from(grouped.values()).sort((a, b) => (b.score || 0) - (a.score || 0))
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-lg border border-surface-container-high bg-surface-container-lowest px-4 py-3">
      <div className="text-xs text-outline">{label}</div>
      <div className="mt-1 text-2xl font-headline font-bold text-on-surface">{value || 0}</div>
    </div>
  )
}

function TaskStatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${statusTone(status)}`}>
      {statusLabels[status] || status || '待处理'}
    </span>
  )
}

function AssemblyModeButton({ mode, active, disabled, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md border px-3 py-2 text-left text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        active
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-surface-container-high bg-surface-container-lowest text-on-surface-variant hover:bg-surface-container-low'
      }`}
      title={assemblyModeDescriptions[mode] || ''}
    >
      <span className="block font-semibold">{assemblyModeLabels[mode] || mode}</span>
      <span className="mt-0.5 block line-clamp-2 text-[11px] opacity-80">{assemblyModeDescriptions[mode] || ''}</span>
    </button>
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
  onBuild,
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
              onClick={onConfirm}
              disabled={busy || !fields.length}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[16px]">fact_check</span>
              确认并用于商务标填写
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
                    <th className="px-3 py-2 font-semibold">来源依据</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-high">
                  {fields.map((field, index) => {
                    const tone = field.status === 'confirmed'
                      ? 'bg-secondary-container text-on-secondary-container'
                      : field.status === 'missing'
                        ? 'bg-tertiary-fixed text-on-tertiary-fixed'
                        : field.status === 'conflict'
                          ? 'bg-error/10 text-error'
                          : 'bg-surface-container-high text-on-surface-variant'
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
                          <span className={`inline-flex rounded-md px-2 py-1 text-[11px] font-semibold ${tone}`}>
                            {factStatusLabels[field.status] || field.status || '-'}
                          </span>
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

function BusinessMaterialPreviewDrawer({
  open,
  loading,
  payload,
  source,
  onClose,
  onOpenOffice,
}) {
  if (!open) return null
  const summary = payload?.quickSummary || {}
  const snippets = asArray(payload?.snippets)
  const title = payload?.materialName || materialPreviewTitle(source)
  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/30">
      <div className="flex h-full w-full max-w-4xl flex-col overflow-hidden bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-lg font-headline font-bold text-on-surface">{title}</h3>
              {payload?.previewMode && (
                <span className="rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold text-primary">
                  {payload.previewMode === 'native' ? '原件预览' : payload.previewMode === 'text' ? '清洗稿快照' : payload.previewMode === 'onlyoffice' ? '完整 Word' : '下载核对'}
                </span>
              )}
            </div>
            <p className="mt-1 truncate text-xs text-on-surface-variant">{payload?.folderPath || source?.folderPath || '商务标素材库候选材料'}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim"
            aria-label="关闭"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {loading ? (
            <div className="space-y-3">
              <div className="h-16 animate-pulse rounded-md bg-surface-container-low" />
              <div className="h-[420px] animate-pulse rounded-md bg-surface-container-low" />
            </div>
          ) : !payload ? (
            <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">暂无预览数据。</div>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-3 rounded-lg border border-surface-container-high bg-surface-container-lowest p-3 text-xs text-on-surface-variant sm:grid-cols-2">
                <div>文件：<span className="font-semibold text-on-surface">{payload.fileName || summary.name || '-'}</span></div>
                <div>类型：{payload.mimeType || '-'}</div>
                <div>层级：{payload.materialTier || summary.materialTier || '-'}</div>
                <div>清洗：{payload.cleanStatus || summary.cleanStatus || '-'}</div>
                {summary.turbineModelLabel && <div>机型：{summary.turbineModelLabel}</div>}
                {payload.cleanedFileName && <div className="truncate">清洗稿：{payload.cleanedFileName}</div>}
              </div>

              {payload.message && (
                <div className="rounded-md bg-primary/5 px-3 py-2 text-sm text-on-surface-variant">{payload.message}</div>
              )}

              {payload.previewMode === 'native' && payload.renderer === 'image' && payload.browserFileUrl ? (
                <div className="rounded-lg border border-surface-container-high bg-surface-container-lowest p-3">
                  <img src={payload.browserFileUrl} alt={title} className="max-h-[68vh] w-full object-contain" />
                </div>
              ) : payload.previewMode === 'native' && payload.renderer === 'pdf' && payload.browserFileUrl ? (
                <div className="h-[68vh] overflow-hidden rounded-lg border border-surface-container-high bg-surface-container-lowest">
                  <iframe title={title} src={payload.browserFileUrl} className="h-full w-full" />
                </div>
              ) : payload.previewMode === 'onlyoffice' && payload.onlyoffice ? (
                <div className="h-[68vh] overflow-hidden rounded-lg border border-surface-container-high bg-surface-container-lowest">
                  <OnlyOfficeEmbed
                    session={payload.onlyoffice}
                    mode="view"
                    className="h-full min-h-[68vh] w-full bg-white"
                  />
                </div>
              ) : snippets.length ? (
                <div className="rounded-lg border border-surface-container-high bg-surface-container-lowest p-4">
                  <div className="mb-3 text-sm font-semibold text-on-surface">清洗稿文本快照</div>
                  <div className="space-y-2">
                    {snippets.map((snippet, index) => (
                      <p key={`${index}-${snippet.slice(0, 16)}`} className="rounded bg-surface px-3 py-2 text-sm leading-6 text-on-surface-variant">{snippet}</p>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded-md border border-dashed border-surface-container-high p-8 text-center text-sm text-on-surface-variant">
                  当前文件类型暂不支持内嵌预览，可打开原件核对。
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="text-xs text-on-surface-variant">预览只用于核对候选材料，不会自动选择或修改缺口任务。</div>
          <div className="flex flex-wrap items-center gap-2">
            {payload?.browserFileUrl && (
              <a href={payload.browserFileUrl} target="_blank" rel="noreferrer" className="rounded-md bg-surface-container-high px-3 py-2 text-sm font-semibold text-on-surface-variant hover:bg-surface-dim">
                打开原件
              </a>
            )}
            {payload?.officeAvailable && payload?.previewMode !== 'onlyoffice' && (
              <button
                type="button"
                onClick={onOpenOffice}
                disabled={loading}
                className="rounded-md bg-secondary-container px-3 py-2 text-sm font-semibold text-on-secondary-container hover:bg-secondary-fixed disabled:opacity-50"
              >
                完整预览 Word
              </button>
            )}
            <button type="button" onClick={onClose} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container">
              关闭
            </button>
          </div>
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
            <p className="mt-1 text-xs text-on-surface-variant">
              当前任务：{task.title}。模板保持单选；素材/清洗稿支持多选，会一次性快照到当前商务 S3 任务。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-surface-container-high text-on-surface-variant hover:bg-surface-dim"
            aria-label="关闭"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
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
            <div className="inline-flex overflow-hidden rounded-md border border-surface-container-high bg-surface-container-lowest text-xs font-semibold">
              <button
                type="button"
                onClick={() => onTabChange('templates')}
                className={`px-3 py-2 ${activeTab === 'templates' ? 'bg-primary text-on-primary' : 'text-on-surface-variant hover:bg-surface-container-low'}`}
              >
                模板 {templates.length}
              </button>
              <button
                type="button"
                onClick={() => onTabChange('materials')}
                className={`px-3 py-2 ${activeTab === 'materials' ? 'bg-primary text-on-primary' : 'text-on-surface-variant hover:bg-surface-container-low'}`}
              >
                素材/清洗稿 {materials.length}
              </button>
            </div>
            {multiSelect && !!selectedList.length && (
              <button
                type="button"
                onClick={selectAllVisible}
                className="rounded-md bg-surface-container-high px-3 py-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim"
              >
                {selectedList.every((item) => normalizedSelectedKeys.includes(pickerItemKey(activeTab, item))) ? '取消本页全选' : '选择本页全部'}
              </button>
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
                            <button
                              type="button"
                              onClick={(event) => {
                                event.preventDefault()
                                event.stopPropagation()
                                onPreview?.(material)
                              }}
                              className="shrink-0 rounded-md bg-surface-container-high px-2 py-1 text-[11px] font-semibold text-on-surface-variant hover:bg-surface-dim"
                            >
                              预览
                            </button>
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
            <button type="button" onClick={onClose} className="rounded-md bg-surface-container-high px-4 py-2 text-sm font-semibold text-on-surface-variant hover:bg-surface-dim">取消</button>
            <button
              type="button"
              onClick={() => onConfirm(multiSelect ? selectedItems : selectedItem, activeTab)}
              disabled={!selectedCount || loading}
              className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
            >
              {activeTab === 'templates' ? '指定为当前任务模板' : `指定 ${selectedCount || ''} 个素材`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function BusinessGapRecognition({ showToast, project: initialProject }) {
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
  const [candidateSelectionByTask, setCandidateSelectionByTask] = useState({})
  const [materialPreviewOpen, setMaterialPreviewOpen] = useState(false)
  const [materialPreviewLoading, setMaterialPreviewLoading] = useState(false)
  const [materialPreviewPayload, setMaterialPreviewPayload] = useState(null)
  const [materialPreviewSource, setMaterialPreviewSource] = useState(null)
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationLoading, setGenerationLoading] = useState(false)
  const selectedTocIdRef = useRef('')

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
    setGenerationLoading(true)
    try {
      const data = await generateAPI.status(id)
      setGenerationStatus(data)
      return data
    } catch {
      return null
    } finally {
      setGenerationLoading(false)
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
  const selectedTocCounts = taskCounts(visibleTasks)
  const summary = payload?.summary || plan?.summary || {}
  const hasBusinessGapPlan = payload?.status === 'completed' && plan?.schemaVersion === 'bid-business-gap-plan-v1'
  const factConfirmed = factTable?.status === 'confirmed'
  const factSummary = factTable?.summary || {}
  const generationRunning = generationStatus?.status === 'running'
  const generationCompleted = generationStatus?.status === 'completed'
  const generationProgress = Math.max(0, Math.min(100, Number(generationStatus?.percentage) || 0))

  useEffect(() => {
    if (!generationRunning) return undefined
    const timer = window.setInterval(() => {
      loadGenerationStatus()
    }, 1200)
    return () => window.clearInterval(timer)
  }, [generationRunning, loadGenerationStatus])

  const runPlan = async () => {
    setRunning(true)
    setError('')
    try {
      const data = await businessGapsAPI.run(id)
      setPayload(data)
      const refs = asArray(data?.tocRefs || data?.plan?.tocRefs)
      if (refs.length) setSelectedTocId(refs[0].nodeId)
      showToast?.(data?.message || '商务标缺口计划已生成')
    } catch (e) {
      const message = e?.message || '商务标缺口计划生成失败。'
      setError(message)
      showToast?.(message, 'error')
    } finally {
      setRunning(false)
    }
  }

  const runBusinessAssembly = async () => {
    if (actionLoading) return
    if (!hasBusinessGapPlan) {
      showToast?.('请先点击“生成/更新商务缺口计划”，生成完成后再生成商务标正文。', 'error')
      return
    }
    setActionLoading('business-generate')
    try {
      const data = await generateAPI.run(id)
      setGenerationStatus(data)
      showToast?.(data?.message || '已开始生成商务标正文。')
    } catch (e) {
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
      await stagesAPI.update(id, 4, { status: 'completed', allowUnconfirmedBusinessGap: true })
      showToast?.('已进入 S4 共创导出。')
      navigate(projectRoute(id, '/editor', workspaceSlug))
    } catch (e) {
      showToast?.(e?.message || '进入 S4 共创导出失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const confirmArtifact = async (task, artifact) => {
    if (!task || !artifact) return
    try {
      const data = await businessGapsAPI.confirmArtifact(id, task.id, {
        artifactId: artifact.artifactId,
        confirmed: true,
      })
      setPayload((current) => ({
        ...(current || {}),
        plan: data.plan || current?.plan,
        businessGapPlan: data.plan || current?.businessGapPlan,
        tocRefs: data.plan?.tocRefs || current?.tocRefs,
        tasks: data.plan?.tasks || current?.tasks,
        summary: data.plan?.summary || current?.summary,
      }))
      showToast?.('产物已确认，可用于后续商务标生成')
    } catch (e) {
      showToast?.(e?.message || '确认失败', 'error')
    }
  }

  const syncArtifactToMaterial = async (task, artifact) => {
    if (!task || !artifact) return
    setActionLoading(`sync:${artifact.artifactId}`)
    try {
      const data = await businessGapsAPI.syncArtifactMaterial(id, task.id, {
        artifactId: artifact.artifactId,
      })
      mergePlanPayload(data)
      showToast?.(data?.message || '补料已同步到商务标项目素材库')
    } catch (e) {
      showToast?.(e?.message || '同步到素材库失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const removeArtifact = async (task, artifact) => {
    if (!task || !artifact) return
    const artifactId = artifact.artifactId || artifact.id
    if (!artifactId) return
    setActionLoading(`remove:${artifactId}`)
    try {
      const data = await businessGapsAPI.removeArtifact(id, task.id, artifactId)
      mergePlanPayload(data)
      showToast?.(data?.message || '已取消该补料')
    } catch (e) {
      showToast?.(e?.message || '取消补料失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const markTaskIgnored = async (task) => {
    if (!task) return
    try {
      const data = await businessGapsAPI.updateTask(id, task.id, { status: 'ignored', decision: 'review_required' })
      mergePlanPayload(data)
      showToast?.('任务已标记忽略')
    } catch (e) {
      showToast?.(e?.message || '保存失败', 'error')
    }
  }

  const updateTaskAssemblyMode = async (task, assemblyMode) => {
    if (!task || !assemblyMode || task.assemblyMode === assemblyMode) return
    setActionLoading(`assembly:${task.id}`)
    try {
      const data = await businessGapsAPI.updateTask(id, task.id, { assemblyMode })
      mergePlanPayload(data)
      showToast?.(`已更新拼装方式：${assemblyModeLabels[assemblyMode] || assemblyMode}`)
    } catch (e) {
      showToast?.(e?.message || '拼装方式更新失败', 'error')
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
      summary: data.plan?.summary || current?.summary,
      integrity: data.integrity || current?.integrity,
    }))
  }

  const selectMaterials = async (task, materials) => {
    const selectedMaterials = asArray(materials).filter(Boolean)
    if (!task || !selectedMaterials.length) return
    const materialKey = selectedMaterials.map((material) => material.evidenceSegmentId || material.wikiCardId || material.materialId || material.materialName).filter(Boolean).join(',')
    setActionLoading(`select:${materialKey}`)
    try {
      const data = await businessGapsAPI.selectMaterial(id, task.id, { materials: selectedMaterials })
      mergePlanPayload(data)
      setCandidateSelectionByTask((current) => ({ ...current, [task.id]: [] }))
      showToast?.(`已选择 ${selectedMaterials.length} 个素材并快照到商务 S3 工作区`)
    } catch (e) {
      showToast?.(e?.message || '选择素材失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

  const selectMaterial = async (task, material) => selectMaterials(task, [material])

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

  const setCandidateSelectionForTask = (taskId, keys) => {
    if (!taskId) return
    setCandidateSelectionByTask((current) => ({
      ...current,
      [taskId]: asArray(keys).filter(Boolean),
    }))
  }

  const toggleCandidateSelection = (taskId, key) => {
    if (!taskId || !key) return
    setCandidateSelectionByTask((current) => {
      const existing = asArray(current[taskId])
      return {
        ...current,
        [taskId]: existing.includes(key) ? existing.filter((item) => item !== key) : [...existing, key],
      }
    })
  }

  const selectCandidateMaterials = async (task, materials) => {
    const selectedMaterials = asArray(materials).map((material) => materialSelectionPayload(material, 'materials')).filter(Boolean)
    await selectMaterials(task, selectedMaterials)
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

  useEffect(() => {
    if (!materialPickerOpen) return undefined
    const timer = setTimeout(() => {
      loadSelectableMaterials(materialPickerKeyword)
    }, 300)
    return () => clearTimeout(timer)
  }, [loadSelectableMaterials, materialPickerKeyword, materialPickerOpen])

  const runAiDraft = async (task) => {
    if (!task) return
    setActionLoading(`ai-draft:${task.id}`)
    try {
      const data = await businessGapsAPI.aiDraft(id, task.id, { operator: '当前用户' })
      mergePlanPayload(data)
      if (data?.projectFactTable?.schemaVersion) {
        setFactTable(data.projectFactTable)
        setFactFields(asArray(data.projectFactTable.fields))
      }
      showToast?.(data?.message || '已生成 AI 起草稿')
    } catch (e) {
      showToast?.(e?.message || 'AI 起草失败', 'error')
    } finally {
      setActionLoading('')
    }
  }

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
      showToast?.('商务标项目事实表已确认，可用于后续 S4 填写')
      return data
    } catch (e) {
      showToast?.(e?.message || '商务标项目事实表确认失败', 'error')
      return null
    } finally {
      setActionLoading('')
    }
  }

  if (loading) return <PageLoading title="正在加载商务标素材匹配" description="正在读取商务目录、解析产物和素材推荐。" />
  if (error && !payload) return <PageError title="加载失败" description={error} onRetry={load} />

  return (
    <div className="flex flex-col gap-6">
      <ProjectStageProgress projectId={id} showToast={showToast} />
      <StageBreadcrumb currentLabel="S3 商务标素材匹配" />
      <PageHeader
        title="商务标 S3 素材匹配"
        description="按商务目录展示响应件任务，完成素材匹配、补料、AI 起草和商务标正文生成。缺口处理方式保持不变。"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={load}
              disabled={running || !!actionLoading}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-surface-container-high px-4 text-sm font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">refresh</span>
              刷新
            </button>
            <button
              type="button"
              onClick={openFactModal}
              disabled={running || !!actionLoading || payload?.status !== 'completed'}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-secondary-container px-4 text-sm font-semibold text-on-secondary-container hover:bg-secondary-fixed disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">fact_check</span>
              {factConfirmed ? '项目事实表已确认' : '维护项目事实表'}
            </button>
            <button
              type="button"
              onClick={runPlan}
              disabled={running}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">rule_settings</span>
              {running ? '生成中...' : '生成/更新商务缺口计划'}
            </button>
            <button
              type="button"
              onClick={runBusinessAssembly}
              disabled={running || !!actionLoading || !hasBusinessGapPlan || generationRunning}
              title={!hasBusinessGapPlan ? '生成商务缺口计划后可生成正文' : '允许带未确认项生成正文，生成结果会保留复核提示'}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-secondary px-4 text-sm font-semibold text-on-secondary hover:bg-secondary/90 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">draw</span>
              {generationRunning ? '生成中...' : generationCompleted ? '重新生成正文' : '生成商务标正文'}
            </button>
            <button
              type="button"
              onClick={advanceToBusinessS4}
              disabled={running || !!actionLoading || !generationCompleted}
              title={!generationCompleted ? '商务标正文生成完成后可进入 S4 共创导出' : ''}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-tertiary px-4 text-sm font-semibold text-on-tertiary hover:bg-tertiary/90 disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
              {actionLoading === 'advance-business-s4' ? '进入中...' : '进入 S4 共创导出'}
            </button>
          </div>
        )}
      />

      {error && (
        <div className="rounded-lg border border-error/20 bg-error/10 px-4 py-3 text-sm text-error">{error}</div>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="目录节点" value={summary.tocRefCount || tocRefs.length} />
        <StatCard label="响应件任务" value={summary.taskCount || tasks.length} />
        <StatCard label="待处理" value={(summary.needsInputCount || 0) + (summary.reviewRequiredCount || 0)} />
        <StatCard label="已就绪" value={summary.readyCount || 0} />
      </div>

      <DataCard title="商务标正文生成" subtitle="S3 已合并原生成标书阶段；素材匹配完成后可直接生成商务标正文，再进入 S4 共创导出。">
        <div className="flex flex-col gap-4 p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold text-on-surface">
                状态：{generationRunning ? '生成中' : generationCompleted ? '已生成' : generationStatus?.status === 'failed' ? '生成失败' : '未生成'}
              </div>
              <div className="mt-1 text-xs text-on-surface-variant">
                {generationStatus?.summary || (hasBusinessGapPlan ? '可基于当前商务素材匹配结果生成正文。' : '请先生成/更新商务缺口计划。')}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={loadGenerationStatus}
                disabled={generationLoading || generationRunning}
                className="rounded-md bg-surface-container-high px-4 py-2 text-sm font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
              >
                {generationLoading ? '刷新中...' : '刷新生成状态'}
              </button>
              <button
                type="button"
                onClick={runBusinessAssembly}
                disabled={running || !!actionLoading || !hasBusinessGapPlan || generationRunning}
                className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
              >
                {generationRunning ? '生成中...' : generationCompleted ? '重新生成正文' : '生成商务标正文'}
              </button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[#e8eef2]">
              <div className="h-full bg-primary transition-all duration-700" style={{ width: `${generationProgress}%` }} />
            </div>
            <span className="whitespace-nowrap text-xs text-outline">{generationProgress}%</span>
          </div>
          {generationCompleted && (
            <div className="rounded-md border border-secondary/20 bg-secondary-container/40 px-3 py-2 text-sm text-on-secondary-container">
              商务标正文已生成。可继续在本页调整素材匹配并重新生成，或进入 S4 共创导出进行在线编辑和下载。
            </div>
          )}
        </div>
      </DataCard>

      {payload?.status === 'completed' && (
        <DataCard title="商务标项目事实表" subtitle="供 S4 填写投标函、授权书、报价表、承诺书等项目字段使用。">
          <div className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="grid gap-2 text-sm text-on-surface-variant sm:grid-cols-4">
              <div>状态：<span className="font-semibold text-on-surface">{factStatusLabels[factTable?.status] || '未生成'}</span></div>
              <div>字段：<span className="font-semibold text-on-surface">{factSummary.totalCount || factFields.length || 0}</span></div>
              <div>已确认：<span className="font-semibold text-on-surface">{factSummary.confirmedCount || 0}</span></div>
              <div>待补充：<span className="font-semibold text-on-surface">{factSummary.missingCount || 0}</span></div>
            </div>
            <button
              type="button"
              onClick={openFactModal}
              disabled={!!actionLoading}
              className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
            >
              {factFields.length ? '查看/确认事实表' : '生成事实表'}
            </button>
          </div>
        </DataCard>
      )}

      {payload?.status !== 'completed' ? (
        <DataCard title="尚未生成商务缺口计划" subtitle="请先确认商务目录，再点击生成/更新商务缺口计划。">
          <div className="p-6 text-sm text-on-surface-variant">
            当前项目：{initialProject?.name || id}。生成后会在这里按商务目录展示投标函、承诺书、证书、表格和支撑材料任务。
          </div>
        </DataCard>
      ) : (
        <div className="grid min-h-[720px] gap-4 xl:grid-cols-[460px_minmax(0,1fr)] 2xl:grid-cols-[520px_minmax(0,1fr)]">
          <DataCard title="商务目录" subtitle="按投标文件目录逐项处理缺口，不再额外按模块分层。">
            <div className="max-h-[720px] overflow-auto p-3">
              {tocRefs.map((ref) => {
                const refTasks = asArray(ref.taskIds).map((taskId) => taskById.get(taskId)).filter(Boolean)
                const counts = taskCounts(refTasks)
                const isSelected = selectedToc?.nodeId === ref.nodeId
                return (
                  <button
                    key={ref.nodeId}
                    type="button"
                    onClick={() => {
                      setSelectedTocId(ref.nodeId)
                      setSelectedTaskId('')
                    }}
                    className={`mb-2 w-full rounded-lg border px-3 py-2 text-left transition-colors ${isSelected ? 'border-primary bg-primary/10 shadow-sm' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}
                    style={{ paddingLeft: `${12 + Math.max(0, (Number(ref.level) || 1) - 1) * 14}px` }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="line-clamp-2 text-sm font-semibold leading-snug text-on-surface">{ref.number ? `${ref.number} ` : ''}{ref.title}</div>
                        <div className="mt-1 text-xs text-outline">
                          {refTasks.length ? `任务 ${refTasks.length} · 待处理 ${counts.pending}` : '空章节，可手动补料'}
                        </div>
                      </div>
                      <TaskStatusBadge status={ref.status} />
                    </div>
                  </button>
                )
              })}
            </div>
          </DataCard>

          <DataCard
            title={selectedToc ? `${selectedToc.number ? `${selectedToc.number} ` : ''}${selectedToc.title}` : '请选择目录章节'}
            subtitle={selectedToc ? `本章节任务 ${visibleTasks.length} 个 · 候选素材 ${selectedTocCounts.candidates} 个 · 产物 ${selectedTocCounts.artifacts} 个` : '从左侧商务目录选择章节后处理。'}
          >
            {!selectedToc ? (
              <div className="p-8 text-sm text-on-surface-variant">请选择左侧商务目录章节。</div>
            ) : (
              <div className="max-h-[720px] overflow-auto p-4">
                {!visibleTasks.length ? (
                  <div className="rounded-xl border border-dashed border-surface-container-high bg-surface-container-lowest p-8 text-center">
                    <span className="material-symbols-outlined text-4xl text-outline">inventory_2</span>
                    <h3 className="mt-3 text-base font-headline font-bold text-on-surface">当前章节暂无系统任务</h3>
                    <p className="mt-2 text-sm text-on-surface-variant">这通常说明该目录是容器章节，或 planner 没有识别出明确缺口。可直接上传补充材料，系统会自动为该章节创建人工补料任务。上传后先作为本项目 S3 补料快照使用，需要点击“同步到项目素材库”才会进入项目素材库。</p>
                    <label className={`mt-4 inline-flex cursor-pointer items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container ${actionLoading ? 'pointer-events-none opacity-50' : ''}`}>
                      <span className="material-symbols-outlined text-[18px]">add</span>
                      {actionLoading === 'upload' ? '上传中...' : '新增任务并上传补料'}
                      <input
                        type="file"
                        multiple
                        className="hidden"
                        accept=".doc,.docx,.pdf,.xls,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
                        onChange={(event) => uploadSupplementForTask(event, null)}
                        disabled={!!actionLoading}
                      />
                    </label>
                  </div>
                ) : visibleTasks.map((task) => {
                  const fillPlan = task.fillPlan || {}
                  const rawAssemblyMode = task.assemblyMode || fillPlan.mode || ''
                  const assemblyMode = editableAssemblyMode(rawAssemblyMode)
                  const materialUsage = task.materialUsage || fillPlan.materialUsage || ''
	                  const resolvedArtifacts = asArray(task.resolvedArtifacts)
	                  const aiDraftArtifacts = resolvedArtifacts.filter((artifact) => artifact.sourceMode === 'generated_by_business_s3_ai_draft')
	                  const templateArtifacts = resolvedArtifacts.filter(looksLikeTemplateAsset)
	                  const materialCandidates = mergeCandidateMaterials(task.candidateMaterials)
                  const candidateSelectedKeys = asArray(candidateSelectionByTask[task.id])
                  const candidateSelectedMaterials = materialCandidates.filter((material) => candidateSelectedKeys.includes(candidateMaterialKey(material)))
                  const allCandidatesSelected = materialCandidates.length > 0
                    && materialCandidates.every((material) => candidateSelectedKeys.includes(candidateMaterialKey(material)))
                  return (
                  <section
                    key={task.id}
                    className={`mb-4 rounded-xl border bg-surface-container-lowest p-4 ${selectedTask?.id === task.id ? 'border-primary shadow-sm' : 'border-surface-container-high'}`}
                    onMouseEnter={() => setSelectedTaskId(task.id)}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-base font-headline font-bold text-on-surface">{task.title}</h3>
                          <TaskStatusBadge status={task.status} />
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs text-outline">
                          <span>{moduleLabels[task.moduleKey] || task.moduleKey}</span>
                          <span>·</span>
                          <span>{decisionLabels[task.decision] || task.decision}</span>
                          <span>·</span>
                          <span>{task.taskType}</span>
                        </div>
                      </div>
	                      <div className="flex flex-wrap gap-2">
		                        <button
		                          type="button"
		                          onClick={() => openMaterialPicker(task)}
		                          disabled={!!actionLoading}
		                          className="rounded-md bg-secondary-container px-3 py-1.5 text-xs font-semibold text-on-secondary-container hover:bg-secondary-fixed disabled:opacity-50"
		                        >
		                          指定素材库材料/模板
		                        </button>
		                        <button type="button" onClick={() => markTaskIgnored(task)} className="rounded-md bg-surface-container-high px-3 py-1.5 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim">标记忽略</button>
	                        <label className={`inline-flex cursor-pointer items-center gap-2 rounded-md bg-secondary-container px-3 py-1.5 text-xs font-semibold text-on-secondary-container hover:bg-secondary-fixed ${actionLoading ? 'pointer-events-none opacity-50' : ''}`}>
                          <span className="material-symbols-outlined text-[16px]">upload_file</span>
                          {actionLoading === 'upload' ? '上传中...' : '上传补料'}
                          <input
                            type="file"
                            multiple
                            className="hidden"
                            accept=".doc,.docx,.pdf,.xls,.xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
                            onChange={(event) => uploadSupplementForTask(event, task)}
                            disabled={!!actionLoading}
                          />
                        </label>
                      </div>
                    </div>

                    <div className="mt-4 rounded-lg border border-surface-container-high bg-surface p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h4 className="text-sm font-semibold text-on-surface">素材处理方式</h4>
                          <p className="mt-1 text-xs text-on-surface-variant">
                            {assemblyModeDescriptions[assemblyMode] || '请选择当前任务的材料处理方式。'}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2 text-[11px] text-outline">
                          <span>输出：{fillPlan.outputArtifactType || '待确定'}</span>
                          {materialUsage && <span>建议：{usageModeLabels[materialUsage] || materialUsage}</span>}
                        </div>
                      </div>
                      <div className="mt-3 grid gap-2 sm:grid-cols-2 2xl:grid-cols-4">
                        {assemblyModeOptions.map((mode) => (
                          <AssemblyModeButton
                            key={mode}
                            mode={mode}
                            active={assemblyMode === mode}
                            disabled={!!actionLoading}
                            onClick={() => updateTaskAssemblyMode(task, mode)}
                          />
                        ))}
                      </div>
	                      {assemblyMode === 'template_fill_docx' && !templateArtifacts.length && (
	                        <div className="mt-3 rounded-md border border-error/25 bg-error/5 px-3 py-2 text-xs text-error">
	                          当前未绑定可填充 Word 模板。请点击“指定素材库材料/模板”或“上传补料”绑定一份可填充 Word 模板；绑定并确认后任务才会变为已就绪。
	                        </div>
	                      )}
                      {assemblyMode === 'ai_draft' && (
                        <div className="mt-3 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-on-surface-variant">
                          {aiDraftArtifacts.length
                            ? `已生成 ${aiDraftArtifacts.length} 份 AI 填写结果，可在下方“AI填写结果”直接预览和确认。`
                            : '选择 AI 自主填写后，请点击“生成AI填写结果”，系统会基于目录任务和项目事实表生成 Word 草稿。'}
                        </div>
                      )}
                    </div>

                    <div className="mt-4 grid gap-3">
                      {assemblyMode === 'ai_draft' && (
                        <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <h4 className="text-sm font-semibold text-on-surface">AI填写结果</h4>
                              <p className="mt-1 text-xs text-outline">可在当前任务中直接生成、预览并确认 AI 填写稿。</p>
                            </div>
                            <button
                              type="button"
                              onClick={() => runAiDraft(task)}
                              disabled={!!actionLoading}
                              className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                            >
                              {actionLoading === `ai-draft:${task.id}` ? '生成中...' : aiDraftArtifacts.length ? '重新生成AI填写结果' : '生成AI填写结果'}
                            </button>
                          </div>
                          {!aiDraftArtifacts.length && (
                            <p className="mt-2 text-sm text-on-surface-variant">暂无 AI 填写结果。生成后会作为 Word 产物显示在下方，可确认后进入正文生成。</p>
                          )}
                        </div>
                      )}
	                      <div className="rounded-lg border border-surface-container-high bg-surface p-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <h4 className="text-sm font-semibold text-on-surface">候选素材</h4>
                            <p className="mt-1 text-xs text-outline">
                              {materialCandidates.length} 个候选
                              {candidateSelectedMaterials.length ? ` · 已勾选 ${candidateSelectedMaterials.length} 个` : ''}
                            </p>
                          </div>
                          {!!materialCandidates.length && (
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => setCandidateSelectionForTask(
                                  task.id,
                                  allCandidatesSelected ? [] : materialCandidates.map(candidateMaterialKey).filter(Boolean),
                                )}
                                disabled={!!actionLoading}
                                className="rounded-md bg-surface-container-high px-3 py-1.5 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
                              >
                                {allCandidatesSelected ? '取消全选' : '全选候选'}
                              </button>
                              <button
                                type="button"
                                onClick={() => selectCandidateMaterials(task, candidateSelectedMaterials)}
                                disabled={!!actionLoading || !candidateSelectedMaterials.length}
                                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                              >
                                {actionLoading === `select:${candidateSelectedMaterials.map(candidateMaterialKey).filter(Boolean).join(',')}` ? '选择中...' : `选择已勾选${candidateSelectedMaterials.length ? ` ${candidateSelectedMaterials.length}` : ''}`}
                              </button>
                            </div>
                          )}
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
                          const checked = candidateSelectedKeys.includes(materialKey)
                          return (
                            <div key={materialKey} className={`mt-2 rounded-md border px-3 py-2 ${checked ? 'border-primary bg-primary/5' : 'border-surface-container-high bg-surface-container-lowest'}`}>
                              <div className="flex items-start justify-between gap-3">
                                <div className="flex min-w-0 flex-1 items-start gap-3">
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleCandidateSelection(task.id, materialKey)}
                                    disabled={!!actionLoading}
                                    aria-label={`勾选候选素材 ${material.materialName || material.materialId || materialKey}`}
                                    className="mt-1 h-4 w-4 shrink-0"
                                  />
                                  <div className="min-w-0">
                                    <div className="truncate text-sm font-semibold text-on-surface">{material.materialName || material.materialId}</div>
                                    <div className="mt-1 text-xs text-outline">匹配度 {Math.round((material.score || 0) * 100)}% · {material.reason}</div>
                                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-on-surface-variant">
                                      {material.cleanStatus && <span>清洗：{material.cleanStatus}</span>}
                                      {material.cleanedFileName && <span>清洗稿：{material.cleanedFileName}</span>}
                                    </div>
                                    {segmentTitle && (
                                      <div className="mt-1 rounded bg-primary/5 px-2 py-1 text-[11px] text-on-surface-variant">
                                        Wiki依据：<span className="font-semibold text-primary">{segmentTitle}</span>
                                        {sourcePages ? ` · ${sourcePages}` : ''}
                                        {evidenceSegments.length > 1 ? ` · 另有 ${evidenceSegments.length - 1} 条依据` : ''}
                                      </div>
                                    )}
                                    {evidenceSummary && <div className="mt-1 line-clamp-2 text-[11px] text-on-surface-variant">{evidenceSummary}</div>}
                                    {material.wikiCardId && <div className="mt-1 text-[11px] text-primary">Wiki证据：{material.wikiCardId} · {usageModeLabels[material.wikiUsageMode] || material.wikiUsageMode || '未标注用法'}</div>}
                                    {evidence.validityStatus && <div className="mt-1 text-[11px] text-outline">有效期状态：{evidence.validityStatus}{evidence.expiryDate ? ` · ${evidence.expiryDate}` : ''}</div>}
                                    {material.folderPath && <div className="mt-1 truncate text-[11px] text-outline">{material.folderPath}</div>}
                                  </div>
                                </div>
                                <div className="flex shrink-0 flex-col gap-2">
                                  {materialPreviewKey(material) && (
                                    <button
                                      type="button"
                                      onClick={() => openMaterialPreview(material)}
                                      disabled={!!actionLoading}
                                      className="rounded-md bg-surface-container-high px-3 py-1.5 text-xs font-semibold text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
                                    >
                                      预览
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => selectMaterial(task, material)}
                                    disabled={!!actionLoading}
                                    className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                                  >
                                    {actionLoading === `select:${materialKey}` ? '选择中...' : '选择'}
                                  </button>
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    <div className="mt-3 rounded-lg border border-surface-container-high bg-surface p-3">
                      <h4 className="text-sm font-semibold text-on-surface">已生成/已上传产物</h4>
                      {!resolvedArtifacts.length ? (
                        <p className="mt-2 text-sm text-on-surface-variant">暂无产物。可直接上传补料，或从候选素材中选择。</p>
                      ) : resolvedArtifacts.map((artifact) => (
                        <div key={artifact.artifactId || artifact.fileName} className="mt-3 rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-on-surface">{artifact.fileName}</div>
	                              <div className="mt-1 text-xs text-outline">
	                                {sourceModeLabels[artifact.sourceMode] || artifact.sourceMode} · {artifact.confirmed ? '已确认' : '待确认'}
	                                {artifact.materialSyncStatus === 'synced_to_project_material' ? ` · 已入项目素材库：${artifact.materialId || artifact.materialName || ''}` : ''}
	                                {artifact.wikiSyncStatus === 'wiki_rebuild_required' ? ' · Wiki待更新' : ''}
	                              </div>
	                              {(artifact.evidenceSegmentTitle || artifact.evidenceSummary || artifact.wikiCardId) && (
	                                <div className="mt-2 rounded bg-primary/5 px-2 py-1 text-[11px] text-on-surface-variant">
	                                  {artifact.evidenceSegmentTitle ? `Wiki依据：${artifact.evidenceSegmentTitle}` : artifact.wikiCardId ? `Wiki证据：${artifact.wikiCardId}` : 'Wiki依据'}
	                                  {artifact.evidenceSourcePages ? ` · ${artifact.evidenceSourcePages}` : ''}
	                                  {artifact.evidenceSummary ? ` · ${artifact.evidenceSummary}` : ''}
	                                </div>
	                              )}
	                            </div>
                            <div className="flex shrink-0 flex-wrap justify-end gap-2">
                              {!artifact.confirmed && (
                                <button type="button" onClick={() => confirmArtifact(task, artifact)} className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container">
                                  确认可用
                                </button>
                              )}
                              {artifact.sourceMode === 'uploaded_in_business_s3' && artifact.materialSyncStatus !== 'synced_to_project_material' && (
                                <button
                                  type="button"
                                  onClick={() => syncArtifactToMaterial(task, artifact)}
                                  disabled={!!actionLoading}
                                  className="rounded-md bg-secondary-container px-3 py-1.5 text-xs font-semibold text-on-secondary-container hover:bg-secondary-fixed disabled:opacity-50"
                                >
                                  {actionLoading === `sync:${artifact.artifactId}` ? '同步中...' : '同步到项目素材库'}
                                </button>
                              )}
                              {['uploaded_in_business_s3', 'selected_from_business_material_library', 'project_uploaded_bid_template', 'system_default_bid_template', 'selected_from_bid_template'].includes(artifact.sourceMode) && artifact.materialSyncStatus !== 'synced_to_project_material' && (
                                <button
                                  type="button"
                                  onClick={() => removeArtifact(task, artifact)}
                                  disabled={!!actionLoading}
                                  className="rounded-md bg-error/10 px-3 py-1.5 text-xs font-semibold text-error hover:bg-error/15 disabled:opacity-50"
                                >
                                  {actionLoading === `remove:${artifact.artifactId}` ? '取消中...' : '取消'}
                                </button>
                              )}
                            </div>
                          </div>
                          {artifact.materialTargetPath && (
                            <div className="mt-2 rounded bg-surface-container-low px-2 py-1 text-[11px] text-outline">素材库路径：{artifact.materialTargetPath}</div>
                          )}
                          {artifact.onlyoffice ? (
                            <div className="mt-3 h-[320px] overflow-hidden rounded-md border border-surface-container-high">
                              <OnlyOfficeEmbed
                                session={artifact.onlyoffice}
                                mode="view"
                                className="h-full min-h-[320px] w-full bg-white"
                              />
                            </div>
                          ) : artifact.browserFileUrl ? (
                            <a className="mt-3 inline-flex text-sm font-semibold text-primary" href={artifact.browserFileUrl} target="_blank" rel="noreferrer">打开文件</a>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </section>
                  )
                })}
              </div>
            )}
          </DataCard>
        </div>
      )}
      <FactMaintenanceModal
        open={factModalOpen}
        factTable={factTable}
        fields={factFields}
        busy={['facts-build', 'facts-load', 'facts-confirm'].includes(actionLoading)}
        onClose={() => setFactModalOpen(false)}
        onBuild={() => loadFactTable({ build: true })}
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
      <BusinessMaterialPreviewDrawer
        open={materialPreviewOpen}
        loading={materialPreviewLoading}
        payload={materialPreviewPayload}
        source={materialPreviewSource}
        onClose={closeMaterialPreview}
        onOpenOffice={() => openMaterialPreview(materialPreviewSource, 'office')}
      />
    </div>
  )
}
