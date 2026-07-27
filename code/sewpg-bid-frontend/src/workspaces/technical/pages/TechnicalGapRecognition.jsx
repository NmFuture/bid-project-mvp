import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  appendixTaskForFillTask,
  defaultAiFillParseFieldIds,
  defaultAiFillReferenceMaterialIds,
  isFillTemplateMaterial,
  latestResolvedArtifact,
  matchedMaterialForItem,
  previewChoicesForItem,
  primaryBlankSource,
  TECHNICAL_GAP_READY_SCORE,
  TECHNICAL_GAP_TAG_CONFIG,
  technicalGenerationPresentation,
  technicalGapParentCoverageState,
  technicalGapTagOf,
  technicalMatchScore,
  uniqueStrings,
} from './technicalGapRecognitionHelpers'

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

const materialTierLabels = {
  standard: '通用素材',
  customer: '客户素材',
  project: '项目素材',
}

// 合并清单条目的来源标签：resolvedArtifacts 的先后顺序即正文合并顺序。
const artifactSourceLabels = {
  material_library: '选用素材',
  manual_upload: '人工上传',
  ai_fill: 'AI填写',
}

// 目录列表里的标签：纯展示，不带任何操作（产品反馈 2026-07-21：「确认」散落在左侧
// 每一行太乱，只在右侧详情面板标题旁对当前选中项放一个「确认」）。
function TechnicalTocActionBadge({ item, items }) {
  const tag = technicalGapTagOf(item, items)
  const config = TECHNICAL_GAP_TAG_CONFIG[tag]
  // 结构项/空章节无标签（v2 裁决 + 产品意见 2026-07-17：删除「空章节」等冗余提示）。
  if (!config) return null
  return (
    <Badge className="business-toc-status-badge" shape="square" size="xs" variant={config.variant}>
      {config.label}
    </Badge>
  )
}

// 就绪确认控件（产品反馈 2026-07-21）：只在右侧详情面板标题旁对当前选中目录项渲染，
// 且只有一个可点击控件——不再是「标签 + 按钮」两个元素。
// UI 统一性（产品反馈）：已就绪的目录项也保留这个按钮，展示成「已点击过」的样式，
// 不因为是文件名精确命中自动就绪就把控件藏起来。
// 按钮在「确认」与「已就绪（可再点撤销）」间切换，是变「已就绪」的唯一人工入口；
// 对自动就绪（非人工确认）的项点撤销只是把 humanConfirmed 显式落为 false，不影响其
// 已就绪的展示（因为分数命中不依赖这个标记），所以视觉上不会有变化，属预期行为。
function TechnicalGapReadyControl({ item, items, busy, onConfirmReady }) {
  const tag = technicalGapTagOf(item, items)
  const config = TECHNICAL_GAP_TAG_CONFIG[tag]
  if (!config) return null
  const confirmed = tag === 'ready'
  return (
    <Button
      type="button"
      onClick={() => onConfirmReady(item, !confirmed)}
      disabled={busy}
      title={confirmed ? '已就绪状态，点击撤销人工确认' : '人工确认本章已就绪'}
      size="sm"
      variant={confirmed ? 'secondary' : 'primary'}
    >
      {confirmed ? '已就绪' : '确认'}
    </Button>
  )
}

// 「父章节覆盖」控件（产品需求 2026-07-27）：放在「确认」左边，只对有下级目录的节点渲染。
// 作用是把本节点选定的素材铺给它下面的所有小节——评审时人一眼能看出「这一章就是这份
// 素材写的」，不用逐个小节再选一遍。本节点自己没选素材时禁用（覆盖源不能是空的）。
// 已设置后按钮切成撤销态，与「确认/已就绪」的交互一致。
function TechnicalGapParentCoverageControl({ item, items, busy, onSetParentCoverage }) {
  const state = technicalGapParentCoverageState(item, items)
  if (!state.descendantCount) return null
  const disabled = busy || (!state.applied && !state.canApply)
  const title = state.applied
    ? `已把 ${state.coveredCount} 个下级目录设为父章节覆盖，点击撤销`
    : state.hasMaterial
      ? `把下面 ${state.descendantCount} 个目录项设为由本章素材覆盖`
      : '本章还没有选用素材，选好素材后才能设置父章节覆盖'
  return (
    <Button
      type="button"
      onClick={() => onSetParentCoverage(item, !state.applied)}
      disabled={disabled}
      title={title}
      size="sm"
      variant="secondary"
    >
      {state.applied ? `已覆盖下级 ${state.coveredCount}` : '父章节覆盖'}
    </Button>
  )
}

// 素材卡（产品裁决 2026-07-21 交互重构）：候选池/搜索结果里的素材一律只有 预览 + 选择；
// 点「选择」进入上方已选区后，待填写素材（命名纪律「待填写-」前缀或填写任务空白模板）
// 才出现 AI填写，不用填写的已选素材只有 预览——AI填写 按钮仅在传入 onAiFill 时渲染。
// leading 用于前置控件（如 AI 参考素材勾选框）。系统召回、来源推荐、搜索结果共用此卡片。
// coverageLabel：父级覆盖等场景的说明标签，只加标签不改变卡片基础结构（产品意见 2026-07-17）。
// onSelect 为空时不渲染「选择」按钮（如解析空表、AI 参考素材弹窗）；
// onCardClick 使整卡可点（AI 弹窗里点卡即勾选参考素材），卡内按钮均阻断冒泡。
function MaterialCandidateCard({
  material,
  isSelected,
  busy,
  selecting,
  onPreview,
  onSelect,
  fillable,
  onAiFill,
  aiFillBusy,
  aiFillCompleted,
  leading,
  coverageLabel,
  onCardClick,
}) {
  const name = material.name || material.cleanedFileName || material.id || material.materialId
  const path = material.folderPath || material.path || material.id
  // 新口径 matchScore 已是 0~1（启发式封顶 0.98，0.99=文件名精确命中）；Math.min 仅为存量旧版无界分兜底。
  const matchPercent = Math.min(100, Math.round(technicalMatchScore(material) * 100))
  const tierLabel = materialTierLabels[String(material.materialTier || '')] || ''
  const isFillable = fillable ?? isFillTemplateMaterial(material)
  // 展示极简口径（产品裁决）：文件名 + 匹配度 + 路径，不展示召回原因/清洗状态/证据片段。
  return (
    <div
      onClick={onCardClick || undefined}
      className={`rounded-md border px-3 py-2 text-xs ${
        isSelected ? 'border-secondary bg-secondary-container/50' : 'border-surface-container-high bg-surface-container-lowest'
      }${onCardClick ? ' cursor-pointer hover:border-primary/40' : ''}`}
    >
      <div className="flex items-start justify-between gap-3">
        {leading || null}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-on-surface">{name}</span>
            {isSelected ? <Badge size="xs" variant="done">已选中素材</Badge> : null}
            {coverageLabel ? <Badge size="xs" variant="pending">{coverageLabel}</Badge> : null}
            {isFillable ? <Badge size="xs" variant="info">待填写</Badge> : null}
            {tierLabel ? <Badge size="xs" variant="pending">{tierLabel}</Badge> : null}
          </div>
          {matchPercent > 0 ? (
            <div className="mt-1 text-[11px]">
              {/* <50% 为弱关联召回的低置信候选（如纯同义词蹭分），弱化显示防误导。 */}
              <span className={`font-semibold ${matchPercent < 50 ? 'text-outline' : 'text-primary'}`}>
                匹配度 {matchPercent}%{matchPercent < 50 ? '（低置信）' : ''}
              </span>
            </div>
          ) : null}
          <span className="mt-1 block truncate text-[11px] text-outline" title={path}>{path}</span>
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          <Button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onPreview(material)
            }}
            disabled={busy}
            size="sm"
            variant="quiet"
          >
            预览
          </Button>
          {onSelect ? (
            <Button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onSelect(material)
              }}
              disabled={busy}
              size="sm"
              variant={isSelected ? 'secondary' : 'primary'}
            >
              {selecting ? '选择中...' : isSelected ? '已选中' : '选择'}
            </Button>
          ) : null}
          {isFillable && onAiFill ? (
            <Button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onAiFill(material)
              }}
              disabled={busy}
              title={aiFillCompleted ? '已完成，可再次发起 AI 填写' : ''}
              size="sm"
              variant="secondary"
            >
              {aiFillBusy ? 'AI填写中...' : aiFillCompleted ? (
                <>
                  <span className="material-symbols-outlined align-[-3px] text-[14px] text-secondary">check_circle</span>
                  已AI填写
                </>
              ) : 'AI填写'}
            </Button>
          ) : null}
        </div>
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

// AI 填写参考素材选择弹窗（产品裁决：点素材卡上的 AI填写 → 弹窗选参考素材 → 执行）。
// 弹窗内出现哪些素材的规则后续由匹配规则定义，当前沿用本目录项的推荐/召回候选池。
// 单一职责（产品意见 2026-07-17）：弹窗只做「挑 AI 参考素材」一件事——卡上不出现
// 「选择（选用为章节素材）」按钮，整卡点击即勾选/取消，避免「勾选」与「选择」两个概念混淆。
function AiFillReferenceModal({
  open,
  blankTitle,
  sourceRoutingSummary,
  candidates,
  referenceIds,
  busy,
  onToggle,
  onPreview,
  onConfirm,
  onClose,
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6">
      <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-lg font-headline font-bold text-on-surface">AI 填写</h3>
            <p className="mt-1 truncate text-xs text-on-surface-variant" title={blankTitle}>
              待填写对象：{blankTitle || '待填写空表/Word'}
            </p>
          </div>
          <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="rounded-md border border-secondary/20 bg-secondary-container/30 px-3 py-2 text-[11px] text-on-secondary-container">
            勾选结果会锁定为本次 AI 填写的唯一素材范围，不会自动扩大到其他素材。
          </div>
          {sourceRoutingSummary ? (
            <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-[11px] leading-relaxed text-on-surface-variant">
              {sourceRoutingSummary}
            </div>
          ) : null}
          <div className="mt-3 space-y-2">
            {candidates.length ? candidates.map((material) => {
              const materialId = String(material.id || material.materialId || '').trim()
              const checked = referenceIds.includes(materialId)
              return (
                <MaterialCandidateCard
                  key={materialId || material.name}
                  material={material}
                  isSelected={false}
                  busy={busy || !materialId}
                  selecting={false}
                  onPreview={onPreview}
                  onSelect={null}
                  fillable={false}
                  onCardClick={materialId && !busy ? () => onToggle(materialId) : null}
                  leading={(
                    <label
                      className="flex shrink-0 items-center gap-1 pt-0.5"
                      title="勾选后作为本次 AI 填写的参考素材"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={busy || !materialId}
                        onChange={() => onToggle(materialId)}
                        className="h-4 w-4 shrink-0 accent-primary"
                        aria-label={`勾选 ${material.name || material.cleanedFileName || materialId} 用于 AI 填写`}
                      />
                      {checked ? (
                        <span className="rounded bg-secondary-container px-1.5 py-0.5 text-[10px] font-semibold text-on-secondary-container">
                          用于AI
                        </span>
                      ) : null}
                    </label>
                  )}
                />
              )
            }) : (
              <div className="rounded-md bg-surface-container-low px-3 py-2 text-[11px] text-outline">
                暂无推荐素材，可先在目录项底部搜索或上传素材后再发起 AI 填写。
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <span className="rounded bg-secondary-container px-2 py-0.5 text-[10px] font-semibold text-on-secondary-container">
            已选 {referenceIds.length} 份参考素材
          </span>
          <div className="flex gap-2">
            <Button type="button" onClick={onClose} disabled={busy} variant="quiet">取消</Button>
            <Button type="button" onClick={onConfirm} disabled={busy} variant="primary">
              {busy ? '处理中...' : '开始 AI 填写'}
            </Button>
          </div>
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
  const { warningCount, formatCleanFailed, formatCleanMessage } = technicalGenerationPresentation(status)

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
          {completed && warningCount > 0 ? (
            <div className="rounded-md border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm text-on-tertiary-fixed-variant">
              生成结果包含 {warningCount} 项提示，可继续进入共创处理。
            </div>
          ) : null}
          {completed && formatCleanFailed ? (
            <div className="rounded-md border border-tertiary/25 bg-tertiary-fixed/40 px-3 py-2 text-sm font-semibold text-on-tertiary-fixed-variant">
              {formatCleanMessage}
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
  // 目录标签筛选（产品意见 2026-07-17）：点顶部统计标签只看对应目录项，再点一次取消。
  const [tagFilter, setTagFilter] = useState('')
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
  const [aiFillReferenceSelections, setAiFillReferenceSelections] = useState({})
  // AI 填写弹窗：点素材卡上的 AI填写 打开，选参考素材后执行；null=关闭。
  const [aiFillModalTask, setAiFillModalTask] = useState(null)
  // 填表规则：上传 Excel 用于匹配 AI 填写规则；解析与匹配待后端接入，前端先记录文件。
  const [fillRuleFile, setFillRuleFile] = useState(null)
  const fillRuleInputRef = useRef(null)

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
  const filteredItems = useMemo(() => (
    tagFilter ? items.filter((item) => technicalGapTagOf(item, items) === tagFilter) : items
  ), [items, tagFilter])
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
  const selectedAppendixTask = appendixTaskForFillTask(selected, selectedFillTask)
  const activeAppendixTasks = selectedAppendixTask ? [selectedAppendixTask] : selectedAppendixTasks
  const selectedSourceRouting = sourceRoutingForAppendixTasks(activeAppendixTasks, selected)
  const selectedSourceRoutingSummary = sourceRoutingText(selectedSourceRouting)
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
    return candidates.filter((item) => {
      const key = String(item?.id || item?.materialId || item?.name || '').trim()
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    // 上限 20：兼顾「章节同名目录素材」拼装列表（可能 10+ 份，全部确定相关）与渲染开销。
    }).sort((a, b) => technicalMatchScore(b) - technicalMatchScore(a)).slice(0, 20)
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
  // 本章合并清单（产品意见 2026-07-17 方案A）：全部已选用素材/上传/AI 产物按选用先后
  // （即正文合并顺序）展示，替代只显示最新一条产物的旧结果行。
  const mergeArtifacts = asObjectArray(selected?.resolvedArtifacts)
  // 已选用素材 id 集合：选用产物 source=material_library，对齐商务标已选高亮。
  const selectedMaterialIdSet = new Set(
    asObjectArray(selected?.resolvedArtifacts)
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
  const cardAiFillProps = (material) => ({
    fillable: materialFillable(material),
    onAiFill: selectedFillTask ? () => setAiFillModalTask(selectedFillTask) : null,
    aiFillBusy,
    aiFillCompleted: selectedAiFillCompleted,
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
  const topBlankEntries = fillBlankEntries.filter((entry) => !entry.isMaterialBlank)
  const poolBlankEntries = fillBlankEntries.filter((entry) => entry.isMaterialBlank)
  const defaultSelection = (() => {
    if (!selectedMaterialMatch?.material) return null
    if (
      selectedMaterialMatch.inherited
      || technicalMatchScore(selectedMaterialMatch.material) >= TECHNICAL_GAP_READY_SCORE
    ) {
      return {
        kind: 'material',
        material: selectedMaterialMatch.material,
        inherited: selectedMaterialMatch.inherited,
        sourceItem: selectedMaterialMatch.sourceItem,
      }
    }
    return null
  })()
  const selectedCardMaterialId = defaultSelection
    ? String(defaultSelection.material?.id || defaultSelection.material?.materialId || '').trim()
    : ''
  // 备选素材 = 统一候选池剔除已选中项；解析空副表常驻已选区，不进备选池。
  const backupEntries = (() => {
    const seen = new Set()
    topBlankEntries.forEach((entry) => seen.add(entry.key))
    if (selectedCardMaterialId) seen.add(selectedCardMaterialId)
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
    return wrappers.filter((wrapper) => {
      if (!wrapper.key || seen.has(wrapper.key)) return false
      seen.add(wrapper.key)
      return true
    })
  })()
  const selectedPlaceholderLabels = compactList([
    ...asArray(selectedBlankSource?.placeholderLabels),
    ...selectedCandidateMaterials.flatMap((item) => asArray(item?.placeholderLabels)),
  ], 10)
  // 目录标签统计（v2 四标签口径）：标签由候选池 × 素材形态 × 人工操作派生，结构项不计入任务。
  const tagCounts = useMemo(() => {
    const counts = { needs_material: 0, needs_refine: 0, needs_fill: 0, ready: 0 }
    items.forEach((item) => {
      const tag = technicalGapTagOf(item, items)
      if (tag) counts[tag] += 1
    })
    return counts
  }, [items])
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
    setPreviewChoiceKey('')
    setPreviewSession(null)
    setPreviewError('')
    setManualPreviewChoice(null)
    setPreviewOpen(false)
    setAiFillModalTask(null)
  }

  // 目录节点「确认」/撤销：把目录项翻成「已就绪」的唯一人工入口（文件名精确命中除外），
  // 无前置条件，以人的判断为准（产品裁决 2026-07-21）。
  const handleConfirmGapReady = (item, confirmed) => runAction(
    `confirm-ready:${item.id}`,
    () => technicalGapsAPI.confirmReady(id, item.id, { confirmed, operator: '当前用户' }),
    (result) => result?.message || (confirmed ? '本章已确认就绪' : '已撤销就绪确认'),
  )

  // 人工设「父章节覆盖」：把本节点的素材铺给全部下级目录项，可撤销。
  // 已自行选过素材的下级由后端跳过，跳过数量在返回消息里说明。
  const handleSetParentCoverage = (item, covered) => runAction(
    `parent-coverage:${item.id}`,
    () => technicalGapsAPI.setParentCoverage(id, item.id, { covered, operator: '当前用户' }),
    (result) => result?.message || (covered ? '已设为父章节覆盖' : '已撤销父章节覆盖'),
  )

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

  // task 缺省为首个填写任务；多空表目录项（如 附表F.5 双任务）由各自素材卡传入对应任务。
  const handleAiFill = async (task = selectedFillTask) => {
    if (!selected || !task) return null
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
      setPreviewChoiceKey('')
      setPreviewSession(null)
      setPreviewError('')
      setManualPreviewChoice(null)
      // 产品意见 2026-07-17：用户主动发起 AI 填写即视为人工操作，产物直接进入选中/就绪状态，
      // 不再保留「确认可合并」二次确认；质检未通过的产物由前端自动确认补齐门禁。
      const artifact = payload?.artifact
      const artifactId = String(artifact?.id || '').trim()
      const autoConfirmNeeded = artifactId
        && String(artifact?.source || '') === 'ai_fill'
        && String(artifact?.qualityGate || '') !== 'human_confirmed'
        && String(artifact?.qualityReport?.status || '') !== 'passed'
      if (autoConfirmNeeded) {
        try {
          const confirmed = await technicalGapsAPI.confirmAiFillArtifact(id, selected.id, artifactId, { operator: '当前用户' })
          if (confirmed) updatePayload(confirmed)
        } catch {
          // 自动确认失败不阻塞：产物已生成，刷新后可重新发起 AI 填写。
        }
      }
      // 产品意见 2026-07-17（二）：填写完成直接弹出结果预览——当场检查，有问题立刻重新填写，
      // 弥补免二次确认后缺失的验收环节。
      if (artifactId) {
        setPreviewChoiceKey(`artifact:${artifactId}`)
        setPreviewOpen(true)
      }
    }
    return payload
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

  const handleFillRuleFile = (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      showToast?.('填表规则仅支持 Excel 文件（.xlsx / .xls）', 'error')
      return
    }
    setFillRuleFile({ name: file.name, size: file.size })
    showToast?.(`填表规则已接收：${file.name}（解析与 AI 填写规则匹配待后端接入）`)
  }

  if (loading) return <PageLoading title="正在加载素材匹配..." />
  if (error) return <PageError title="素材匹配加载失败" description={error} onRetry={loadData} />

  return (
    <div className="business-ui-shell flex flex-col gap-6">
      <TechnicalProjectStageProgress projectId={id} showToast={showToast} />

      <PageHeader
        actions={(
          <Toolbar>
            <input
              ref={fillRuleInputRef}
              type="file"
              accept=".xlsx,.xls"
              className="hidden"
              onChange={handleFillRuleFile}
            />
            <Button
              type="button"
              onClick={() => fillRuleInputRef.current?.click()}
              disabled={Boolean(busyAction) || data?.status !== 'completed'}
              title={fillRuleFile ? `已上传：${fillRuleFile.name}` : '上传 Excel 填表规则，用于匹配 AI 填写规则'}
              size="stage"
              variant={fillRuleFile ? 'secondary' : 'quiet'}
            >
              {fillRuleFile ? '填表规则（已上传）' : '填表规则'}
            </Button>
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

      {/* 单条统计栏（产品意见 2026-07-17）：处理任务/待处理/已就绪卡片与四标签统计冗余，
          仅保留目录节点总数 + 四标签明细（待处理 = 前三项之和，处理任务 = 四项之和）。 */}
      {isCompleted ? (
        <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex min-h-7 flex-wrap items-center gap-3">
            <div className="flex shrink-0 items-center gap-2 border-r border-surface-container-high pr-3">
              <span className="text-xs font-semibold text-on-surface-variant">目录节点</span>
              <span className="text-lg font-headline font-bold tabular-nums text-primary">{summary.totalTocItems ?? items.length}</span>
            </div>
            <div className="grid min-w-0 flex-1 grid-cols-2 gap-1.5 text-center sm:grid-cols-4">
              {['needs_material', 'needs_refine', 'needs_fill', 'ready'].map((key) => {
                const active = tagFilter === key
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setTagFilter(active ? '' : key)}
                    title={active ? '再点一次取消筛选' : `只看「${TECHNICAL_GAP_TAG_CONFIG[key].label}」目录项`}
                    className={`flex min-h-7 items-center justify-center gap-1 rounded-md px-2 py-0.5 transition-colors ${
                      active ? 'bg-primary-fixed ring-1 ring-primary' : 'bg-surface-container-low hover:bg-surface-container-high'
                    }`}
                  >
                    <span className="text-[11px] text-on-surface-variant">{TECHNICAL_GAP_TAG_CONFIG[key].label}</span>
                    <span className="text-sm font-headline font-bold tabular-nums text-primary">{tagCounts[key] || 0}</span>
                  </button>
                )
              })}
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
          <div className="grid h-[min(78vh,900px)] min-h-[520px] gap-4 overflow-hidden p-3 xl:grid-cols-[460px_minmax(0,1fr)] 2xl:grid-cols-[520px_minmax(0,1fr)]">
            <div className="min-h-0 flex flex-col overflow-hidden">
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
              <div className="min-h-0 flex-1 overflow-auto">
                <div>
                  {filteredItems.map((item) => {
                    const active = effectiveSelectedId === item.id
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => handleSelectTocItem(item.id)}
                        className={`business-toc-item mb-2 block h-auto w-full rounded-md border px-3 py-3 text-left transition-colors ${active ? 'border-primary bg-primary-fixed shadow-sm' : 'border-surface-container-high bg-surface-container-lowest hover:bg-surface-container-low'}`}
                        data-active={active ? 'true' : 'false'}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[11px] font-medium text-outline">{item.number || item.section || '-'}</div>
                            <div className="mt-1 line-clamp-2 text-sm font-semibold leading-snug text-on-surface">{item.title}</div>
                          </div>
                          <TechnicalTocActionBadge item={item} items={items} />
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
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-outline">{selected.number || selected.section || '-'}</div>
                      <div className="mt-1 flex items-center justify-between gap-3">
                        <h3 className="min-w-0 truncate text-lg font-headline font-bold leading-snug text-on-surface">{selected.title}</h3>
                        <div className="flex shrink-0 items-center gap-2">
                          <TechnicalGapParentCoverageControl
                            item={selected}
                            items={items}
                            busy={Boolean(busyAction)}
                            onSetParentCoverage={handleSetParentCoverage}
                          />
                          <TechnicalGapReadyControl
                            item={selected}
                            items={items}
                            busy={Boolean(busyAction)}
                            onConfirmReady={handleConfirmGapReady}
                          />
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 overflow-y-auto bg-surface-container-low">
                    <div className="space-y-4 p-4">
                      {/* 已选中素材 / 本章合并清单（产品裁决 2026-07-21 交互重构）：
                          - 默认只展示后端定案（文件名精确命中）或父级覆盖的素材；启发式候选一律待在备选池。
                          - 解析空副表常驻本区，带 预览 + AI填写；点「选择」选用的素材进入合并清单。
                          - 已选区内：待填写素材 预览 + AI填写，不用填写的素材只有 预览。 */}
                      {defaultSelection || topBlankEntries.length || mergeArtifacts.length ? (
                        <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs font-semibold text-on-surface">
                              {mergeArtifacts.length ? '本章合并清单' : '已选中素材'}
                            </div>
                            {mergeArtifacts.length ? (
                              <span className="text-[11px] text-outline">
                                正文将按以下顺序合并 {mergeArtifacts.length} 份
                              </span>
                            ) : null}
                          </div>
                          {!mergeArtifacts.length && defaultSelection ? (
                            <div className="mt-2">
                              {/* 定案/父级覆盖素材已在已选区：不再提供「选择」，待填写时才有 AI填写。 */}
                              <MaterialCandidateCard
                                material={defaultSelection.material}
                                isSelected
                                coverageLabel={defaultSelection.inherited
                                  ? `父级覆盖 · ${defaultSelection.sourceItem?.number || defaultSelection.sourceItem?.title || '父章节'}`
                                  : ''}
                                busy={Boolean(busyAction)}
                                selecting={false}
                                onPreview={handlePreviewMaterial}
                                onSelect={null}
                                {...cardAiFillProps(defaultSelection.material)}
                              />
                            </div>
                          ) : null}
                          {/* 合并清单：每条产物按合并顺序编号，带来源标签与直达预览。
                              「确认可合并」二次确认已移除（产品意见 2026-07-17：填写完成直接进入选中状态）。 */}
                          {mergeArtifacts.length ? (
                            <div className="mt-2 space-y-1.5">
                              {mergeArtifacts.map((artifact, index) => (
                                <div
                                  key={artifact.id || `${artifact.fileName || ''}-${index}`}
                                  className="flex items-center justify-between gap-2 rounded-md bg-surface-container-low px-3 py-2"
                                >
                                  <div className="flex min-w-0 items-center gap-2 text-xs">
                                    <span className="shrink-0 rounded bg-surface-container-high px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-on-surface-variant">
                                      {index + 1}
                                    </span>
                                    <span className="truncate font-medium text-on-surface" title={artifact.fileName || ''}>
                                      {artifact.fileName || artifact.title || artifact.id || '-'}
                                    </span>
                                    <Badge size="xs" variant={artifact.source === 'ai_fill' ? 'info' : 'done'}>
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
                                          onClick={() => setAiFillModalTask(task)}
                                          disabled={Boolean(busyAction)}
                                          title={completed ? '已完成，可再次发起 AI 填写' : ''}
                                          size="sm"
                                          variant="secondary"
                                        >
                                          {aiFillBusy ? 'AI填写中...' : completed ? '已AI填写' : 'AI填写'}
                                        </Button>
                                      )
                                    })()}
                                  </div>
                                </div>
                              ))}
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
                                  onAiFill={() => setAiFillModalTask(entry.task)}
                                  aiFillBusy={aiFillBusy}
                                  aiFillCompleted={String(entry.task?.status || '') === 'completed'}
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

                      {/* 备选素材：待填写素材与参考素材平级的统一候选池（已剔除选中项，无候选则整块不渲染）；
                          被父章覆盖的子节不再单独展示匹配，避免重复匹配和重复拼接。 */}
                      {!defaultSelection?.inherited && backupEntries.length ? (
                        <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="text-xs font-semibold text-on-surface">备选素材</div>
                            {selectedSourceRouting ? (
                              <span className="rounded bg-tertiary-fixed px-2 py-0.5 text-[10px] font-semibold text-on-tertiary-fixed">
                                规则规定
                              </span>
                            ) : null}
                          </div>
                          {selectedSourceRoutingSummary ? (
                            <div className="mt-2 rounded-md bg-surface-container-low px-3 py-2 text-[11px] leading-relaxed text-on-surface-variant">
                              {selectedSourceRoutingSummary}
                            </div>
                          ) : null}
                          <div className="mt-2 space-y-2">
                            {/* 备选池统一只有 预览 + 选择（产品裁决 2026-07-21）：AI填写 在选用后才出现。 */}
                            {backupEntries.map((wrapper) => (wrapper.kind === 'blank' ? (
                              <MaterialCandidateCard
                                key={wrapper.key}
                                material={wrapper.entry.material}
                                isSelected={false}
                                busy={Boolean(busyAction)}
                                selecting={busyAction === `select-material:${selected.id}:${wrapper.key}`}
                                onPreview={() => handlePreviewMaterial(wrapper.entry.material)}
                                onSelect={handleSelectMaterial}
                                fillable
                              />
                            ) : (
                              <MaterialCandidateCard
                                key={wrapper.key}
                                material={wrapper.material}
                                isSelected={false}
                                busy={Boolean(busyAction)}
                                selecting={busyAction === `select-material:${selected.id}:${wrapper.key}`}
                                onPreview={handlePreviewMaterial}
                                onSelect={handleSelectMaterial}
                                fillable={materialFillable(wrapper.material)}
                              />
                            )))}
                          </div>
                        </section>
                      ) : null}

                      {/* 统一兜底入口（产品裁决）：所有目录项底部都可搜索限定素材库、或直接上传素材；
                          上传成功即选用为本目录项的匹配素材（人工产物，终审直接就绪）。 */}
                      <section className="rounded-md border border-surface-container-high bg-surface-container-lowest p-3">
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
      <AiFillReferenceModal
        open={Boolean(aiFillModalTask)}
        blankTitle={aiFillModalTask?.blankSource?.title || aiFillModalTask?.blankSource?.id || ''}
        sourceRoutingSummary={selectedSourceRoutingSummary}
        candidates={selectedReferenceCandidates}
        referenceIds={aiFillModalTask ? aiFillReferenceIdsFor(aiFillModalTask) : []}
        busy={Boolean(busyAction)}
        onToggle={(materialId) => handleToggleAiFillReference(aiFillModalTask, materialId)}
        onPreview={handlePreviewMaterial}
        onConfirm={() => {
          const task = aiFillModalTask
          setAiFillModalTask(null)
          handleAiFill(task)
        }}
        onClose={() => setAiFillModalTask(null)}
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
