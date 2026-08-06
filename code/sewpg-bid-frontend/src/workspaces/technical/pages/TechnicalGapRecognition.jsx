import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { technicalGapsAPI, technicalGenerateAPI, technicalMaterialsAPI, technicalParseAPI, technicalProjectsAPI, technicalStagesAPI } from '../../../api'
import { PageLoading, PageError } from '../../../components/states/PageState'
import PageHeader from '../../../components/shared/PageHeader'
import DataCard from '../../../components/shared/DataCard'
import OnlyOfficeEmbed from '../../../components/shared/OnlyOfficeEmbed'
import TechnicalGenerationProgressModal from '../components/TechnicalGenerationProgressModal'
import TechnicalProjectStageProgress from '../components/TechnicalProjectStageProgress'
import Badge from '../../../components/ui/Badge'
import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
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
  isStructuralItem,
  latestResolvedArtifact,
  matchedMaterialForItem,
  previewChoicesForItem,
  primaryBlankSource,
  TECHNICAL_GAP_READY_SCORE,
  TECHNICAL_GAP_TAG_CONFIG,
  technicalAppendixSourceMatrixUploadMessage,
  TECHNICAL_WORD_FILL_SKILL,
  technicalBodyFillCounts,
  technicalGapDescendants,
  technicalGapFillError,
  technicalGapTagOf,
  technicalMatchScore,
  tenderDocumentStateForAiFill,
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

// 合并清单条目的来源标签。
const artifactSourceLabels = {
  material_library: '选用素材',
  manual_upload: '人工上传',
  ai_fill: 'AI填写',
}

// 目录列表里的标签：三字工作态 / 四字旁路态（命名 v6，产品裁决 2026-08-04），hover 出提示。
// 结构章（planner 判定的纯骨架章，如「标前概述」）天生等同忽略：显示同款「仅留标题」，
// tip 注明来源，消除"第1章为什么没标签还放开了子级"的困惑（产品反馈 2026-08-04）。
function TechnicalTocActionBadge({ item, items }) {
  const tag = technicalGapTagOf(item, items)
  let config = TECHNICAL_GAP_TAG_CONFIG[tag]
  let tip = config?.tip
  if (!config && isStructuralItem(item) && technicalGapDescendants(item, items).length) {
    config = TECHNICAL_GAP_TAG_CONFIG.title_only
    tip = '未找到整章素材，内容由下级承接'
  }
  // 其余无标签项（空骨架叶子）保持无提示（产品意见 2026-07-17：删除「空章节」等冗余提示）。
  if (!config) return null
  return (
    <Badge className="business-toc-status-badge" shape="square" size="xs" variant={config.variant} title={tip}>
      {config.label}
    </Badge>
  )
}

// 右侧详情面板标题旁的操作控件（产品裁决 2026-08-04 v6）：
// - 「忽略/取消忽略」：有下级且未被冻结的节点都有——红色「待补充」的章、无标签骨架章同样适用；
//   列表行保持纯展示（回归 2026-07-21 裁决），忽略操作只在这里。
// - 「确认」：只对有系统预选素材（matchedMaterials 非空）的待确认项渲染——空确认不产生定案
//   （产品反馈 2026-08-04）；备选/搜索里的素材走「选择」即定案。
// - 已定案（待填写/已就绪）：展示定案态，可点撤销回落；
// - 待审核：「重新AI填写」+「复核通过」。
function TechnicalGapActionControls({ item, items, busy, onConfirmReady, onReviewPass, onRefill, onTitleOnly }) {
  const tag = technicalGapTagOf(item, items)
  if (tag === 'parent_covered') return null
  const ignored = tag === 'title_only'
  // 结构章天生骨架，无自身匹配可忽略；忽略按钮只给「有自身匹配的带下级节点」。
  const hasChildren = !isStructuralItem(item) && technicalGapDescendants(item, items).length > 0
  const ignoreButton = hasChildren ? (
    <Button
      type="button"
      onClick={() => onTitleOnly(item, !ignored)}
      disabled={busy}
      title={ignored ? '取消忽略：本级恢复匹配素材，子级重新冻结' : '忽略本级：仅保留标题，下级各自匹配素材'}
      size="sm"
      variant="quiet"
    >
      {ignored ? '取消忽略' : '忽略本级'}
    </Button>
  ) : null
  if (ignored) return ignoreButton
  if (tag === 'template_review') {
    return (
      <>
        {ignoreButton}
        <Button
          type="button"
          onClick={() => onRefill(item)}
          disabled={busy}
          title="复核不通过时重新发起 AI 填写"
          size="sm"
          variant="secondary"
        >
          重新AI填写
        </Button>
        <Button
          type="button"
          onClick={() => onReviewPass(item)}
          disabled={busy}
          title="确认 AI 填写结果无误，本条定案"
          size="sm"
          variant="primary"
        >
          复核通过
        </Button>
      </>
    )
  }
  const settled = tag === 'material_ready' || tag === 'template_ready'
  const confirmable = tag === 'needs_choice' && asObjectArray(item?.matchedMaterials).length > 0
  // 上一轮填写失败的项停在「待填写」，这里给出原地重填入口（一键批量里失败的也走这条）
  const fillError = technicalGapFillError(item)
  return (
    <>
      {ignoreButton}
      {fillError ? (
        <Button
          type="button"
          onClick={() => onRefill(item)}
          disabled={busy}
          title={`上次填写失败：${fillError}`}
          size="sm"
          variant="secondary"
        >
          重新填写
        </Button>
      ) : null}
      {settled || confirmable ? (
        <Button
          type="button"
          onClick={() => onConfirmReady(item, !settled)}
          disabled={busy}
          title={settled ? '已定案，点击撤销（回落到待确认）' : '确认使用系统预选的素材'}
          size="sm"
          variant={settled ? 'secondary' : 'primary'}
        >
          {settled ? '已定案' : '确认'}
        </Button>
      ) : null}
    </>
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
  // 匹配度做成色块徽标（≥99 绿 = 精确命中 / ≥50 琥珀 / <50 灰 = 低置信），按钮横排收紧卡片高度。
  return (
    <div
      onClick={onCardClick || undefined}
      className={`rounded-lg border px-3 py-2.5 text-xs transition-all ${
        isSelected ? 'border-secondary bg-secondary-container/40' : 'border-surface-container-high bg-surface-container-lowest hover:border-primary/30 hover:shadow-sm'
      }${onCardClick ? ' cursor-pointer' : ''}`}
    >
      <div className="flex items-center justify-between gap-3">
        {leading || null}
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold text-on-surface" title={name}>{name}</span>
            {matchPercent > 0 ? (
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold tabular-nums ${
                  matchPercent >= 99
                    ? 'bg-secondary-container text-on-secondary-container'
                    : matchPercent >= 50
                      ? 'bg-amber-100 text-amber-800'
                      : 'bg-surface-container-high text-outline'
                }`}
              >
                {matchPercent}%{matchPercent < 50 ? ' 低置信' : ''}
              </span>
            ) : null}
            {isSelected ? <Badge size="xs" variant="done">已选中</Badge> : null}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-1.5">
            {coverageLabel ? <Badge size="xs" variant="pending">{coverageLabel}</Badge> : null}
            {isFillable ? <Badge size="xs" variant="info">待填写</Badge> : null}
            {tierLabel ? <span className="shrink-0 text-[10px] text-outline">{tierLabel}</span> : null}
            <span className="min-w-0 truncate text-[11px] text-outline" title={path}>{path}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
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
  // 表级状态
  empty: '待生成',
  draft: '待确认',
  confirmed: '已确认',
  // 字段级七态（事实表 v2）
  unextracted: '未提取',
  extracted: '已自动提取',
  pending_confirmation: '待人工确认',
  missing_source: '缺少来源',
  conflict: '存在冲突',
  not_applicable: '不适用',
  // v1 遗留（旧数据兼容展示）
  candidate: '候选',
  missing: '待补充',
}

// v1 遗留 missing 按 v2 missing_source 归一处理（统计、配色、筛选统一口径，不并列 option）
const normalizeFactFieldStatus = (status) => {
  const value = String(status || 'unextracted')
  return value === 'missing' ? 'missing_source' : value
}

// 字段状态配色（统计 chip 与列表状态下拉共用）：confirmed 绿 / extracted 蓝 / pending_confirmation 青 /
// missing_source 橙 / unextracted 浅琥珀 / conflict 红 / not_applicable 灰
const factFieldStatusTone = (status) => {
  switch (normalizeFactFieldStatus(status)) {
    case 'confirmed':
      return 'bg-secondary-container text-on-secondary-container'
    case 'extracted':
      return 'bg-primary-fixed text-on-primary-fixed-variant'
    case 'pending_confirmation':
      return 'bg-tertiary-fixed text-on-tertiary-fixed'
    case 'missing_source':
      return 'bg-orange-100 text-orange-900'
    case 'unextracted':
      return 'bg-amber-50 text-amber-800'
    case 'conflict':
      return 'bg-error/10 text-error'
    default:
      return 'bg-surface-container-high text-on-surface-variant'
  }
}

// 统计条七态 chip 的展示顺序
const factStatusChipOrder = [
  'confirmed',
  'pending_confirmation',
  'extracted',
  'unextracted',
  'missing_source',
  'conflict',
  'not_applicable',
]

const hasFactSpecSeq = (field) =>
  field?.specSeq !== null && field?.specSeq !== undefined && String(field.specSeq) !== ''

// 清单进度分段，口径与后端 summary 的 spec*Count 一致：
// confirmed=已确认；pending=待人工确认；unfilled=无值或未提取/缺来源；其余=已填未确认
const factSpecSegment = (field) => {
  const status = normalizeFactFieldStatus(field?.status)
  if (status === 'confirmed') return 'confirmed'
  if (status === 'pending_confirmation') return 'pending'
  if (!String(field?.value || '').trim() || status === 'unextracted' || status === 'missing_source') return 'unfilled'
  return 'filledUnconfirmed'
}

// 来源素材路径展示（产品反馈 2026-08-03：事实表只保留 字段/确认值/来源路径 三列）：
// 优先素材完整路径，其次解析来源文件，退回 目录/文件名 或素材名。
const factRefPath = (ref) => {
  const direct = String(ref?.path || ref?.sourceFile || '').trim()
  if (direct) return direct
  const folder = String(ref?.folderPath || '').trim().replace(/\/+$/, '')
  const name = String(ref?.name || '').trim()
  if (folder && name) return `${folder}/${name}`
  return name || String(ref?.title || '').trim()
}

// 来源列只展示文件名降噪，完整路径放 tooltip（产品反馈 2026-08-03）
const factRefFileName = (path) => String(path || '').split('/').filter(Boolean).pop() || String(path || '')

// 固定三段最小宽度，避免原生 table 自动布局把“事实值”挤成竖条。
const factRowGridStyle = {
  gridTemplateColumns: 'minmax(180px, 0.75fr) minmax(320px, 1.25fr) minmax(300px, 1.5fr)',
}

const normalizeMaterialTreePath = (value) => String(value || '').replace(/^\/+|\/+$/g, '')
const normalizeMaterialTreeNodes = (nodes = []) =>
  (Array.isArray(nodes) ? nodes : [])
    .map((node) => {
      const path = normalizeMaterialTreePath(node?.path || node?.name || '')
      return {
        path,
        name: String(node?.name || node?.title || path.split('/').pop() || '未命名目录'),
        fileCount: Number(node?.fileCount || 0),
        children: normalizeMaterialTreeNodes(node?.children || []),
      }
    })
    .filter((node) => node.path)
const collectDefaultExpandedTreePaths = (nodes = [], depth = 0, result = new Set()) => {
  nodes.forEach((node) => {
    if (node.children.length) {
      if (depth < 2) result.add(node.path)
      collectDefaultExpandedTreePaths(node.children, depth + 1, result)
    }
  })
  return result
}

const FactMaintenanceModal = ({
  open,
  factTable,
  fields,
  busy,
  specsImported,
  specsFileName,
  materialPaths,
  materialScopes,
  curateReport,
  curating,
  curatePhase,
  curateMessage,
  updatingScope,
  onClose,
  onConfirm,
  onFieldChange,
  onAddField,
  onUploadSpecs,
  onSaveMaterialPaths,
  onCurate,
}) => {
  const [selectedPaths, setSelectedPaths] = useState(() => uniqueStrings(materialPaths || []))
  const [pathsEditing, setPathsEditing] = useState(false)
  const [treeNodes, setTreeNodes] = useState([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeError, setTreeError] = useState('')
  const [expandedTreePaths, setExpandedTreePaths] = useState(() => new Set())
  // 统计条联动筛选：{ type: 'status' | 'spec', key, label }，null 表示全部
  const [factFilter, setFactFilter] = useState(null)
  const ignoredSuggestions = Array.isArray(curateReport?.ignored) ? curateReport.ignored : []
  if (!open) return null
  const status = factTable?.status || 'empty'

  // 默认素材范围：后端给出的三层（标准文件/客户定制/项目定制），与 AI 匹配填充的扫描口径一致。
  // 摘要只显示层名，完整路径与自定义参考目录放 title，避免长路径撑破工具条。
  const scopeList = Array.isArray(materialScopes) ? materialScopes.filter(Boolean) : []
  const scopeNames = scopeList.map((scope) => materialTierLabels[scope.tier] || String(scope.tier || '')).filter(Boolean)
  const scopeSummary = scopeNames.length ? scopeNames.join(' · ') : '项目素材'
  const scopeTitle = [
    ...scopeList.map((scope) => `${materialTierLabels[scope.tier] || scope.tier}：${scope.path || ''}`),
    ...(materialPaths || []).map((path) => `参考目录：${path}`),
  ].join('\n')

  // 统计口径：全部从本地 fields（factFields state）实时推导，与列表同一数据源，
  // 新增字段、本地改状态后立即反映，不再依赖后端 summary 快照
  const statusCounts = {}
  fields.forEach((field) => {
    const fieldStatus = normalizeFactFieldStatus(field.status)
    statusCounts[fieldStatus] = (statusCounts[fieldStatus] || 0) + 1
  })
  const specSegments = { confirmed: 0, pending: 0, unfilled: 0, filledUnconfirmed: 0 }
  const specTotal = fields.reduce((total, field) => {
    if (!hasFactSpecSeq(field)) return total
    specSegments[factSpecSegment(field)] += 1
    return total + 1
  }, 0)

  const toggleFactFilter = (filter) => {
    setFactFilter((current) => (current && current.type === filter.type && current.key === filter.key ? null : filter))
  }
  const matchesFactFilter = (field) => {
    if (!factFilter) return true
    if (factFilter.type === 'status') return normalizeFactFieldStatus(field.status) === factFilter.key
    return hasFactSpecSeq(field) && factSpecSegment(field) === factFilter.key
  }
  // 保留原始下标：onFieldChange 按 factFields 下标回写，筛选后不能重排
  const visibleRows = fields
    .map((field, index) => ({ field, index }))
    .filter(({ field }) => matchesFactFilter(field))

  const factFilterChipClass = (active, tone, count) =>
    `rounded-md px-2.5 py-1 text-xs font-semibold ${tone} ${
      active ? 'ring-2 ring-primary/70' : 'hover:brightness-95'
    } ${count ? '' : 'opacity-50'}`

  const enterPathsEditing = async () => {
    if (pathsEditing) {
      // 收起时丢弃未保存的勾选，回退到已保存的参考路径
      setSelectedPaths(uniqueStrings(materialPaths || []))
      setPathsEditing(false)
      return
    }
    setPathsEditing(true)
    if (treeNodes.length || treeLoading) return
    setTreeLoading(true)
    setTreeError('')
    try {
      const payload = await technicalMaterialsAPI.raw.tree()
      const nodes = normalizeMaterialTreeNodes(payload?.tree || payload?.items || payload?.nodes || [])
      setTreeNodes(nodes)
      setExpandedTreePaths(collectDefaultExpandedTreePaths(nodes))
    } catch (e) {
      setTreeError(e?.message || '素材目录树加载失败')
    } finally {
      setTreeLoading(false)
    }
  }

  const togglePathSelected = (path) => {
    setSelectedPaths((prev) => (prev.includes(path) ? prev.filter((item) => item !== path) : [...prev, path]))
  }

  const toggleTreeExpand = (path) => {
    setExpandedTreePaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const renderPathTreeNode = (node, depth = 0) => {
    const checked = selectedPaths.includes(node.path)
    const hasChildren = node.children.length > 0
    const expanded = expandedTreePaths.has(node.path)
    return (
      <div key={node.path}>
        <div
          className="flex items-center gap-1.5 rounded py-1 pr-1.5 text-xs hover:bg-surface-container-high/60"
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={() => toggleTreeExpand(node.path)}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-outline hover:bg-surface-container-high"
              aria-label={expanded ? `收起 ${node.name}` : `展开 ${node.name}`}
            >
              <span className="material-symbols-outlined text-[16px]">{expanded ? 'expand_more' : 'chevron_right'}</span>
            </button>
          ) : (
            <span className="h-5 w-5 shrink-0" aria-hidden="true" />
          )}
          <input
            type="checkbox"
            checked={checked}
            onChange={() => togglePathSelected(node.path)}
            className="h-4 w-4 shrink-0 accent-primary"
            aria-label={`选择参考目录 ${node.path}`}
          />
          <span className="min-w-0 flex-1 truncate text-on-surface" title={node.path}>{node.name}</span>
          {node.fileCount > 0 && (
            <span className="shrink-0 rounded bg-surface-container-high px-1.5 py-0.5 text-[10px] tabular-nums text-on-surface-variant">{node.fileCount}</span>
          )}
        </div>
        {hasChildren && expanded ? node.children.map((child) => renderPathTreeNode(child, depth + 1)) : null}
      </div>
    )
  }

  return (
    // 点弹窗外空白关闭（仅点遮罩本身生效，点弹窗内容不误关，产品反馈 2026-08-03）
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 py-6"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex h-[calc(100vh-64px)] max-h-[860px] w-full max-w-[1180px] flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex flex-col gap-3 border-b border-surface-container-high bg-surface-container-low px-5 py-3.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-headline font-bold text-on-surface">项目事实表维护</h3>
              <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${status === 'confirmed' ? 'bg-secondary-container text-on-secondary-container' : 'bg-tertiary-fixed text-on-tertiary-fixed'}`}>
                {factStatusLabels[status] || status}
              </span>
            </div>
            <Toolbar>
              <Button
                type="button"
                onClick={onCurate}
                disabled={busy || !fields.length}
                title="先按最新素材范围刷新事实表，再由 AI 匹配素材填充字段值，结果置为待人工确认（耗时较长）"
                size="md"
                variant="success"
              >
                {curating ? (curatePhase || '刷新填充中...') : '刷新并 AI 填充'}
              </Button>
              <Button type="button" onClick={onAddField} disabled={busy} icon="add" size="md" variant="secondary">
                新增字段
              </Button>
              <Button type="button" onClick={onConfirm} disabled={busy || !fields.length} icon="save" size="md" variant="primary">
                保存
              </Button>
              <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="ghost" />
            </Toolbar>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={() => setFactFilter(null)}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                factFilter
                  ? 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim'
                  : 'bg-primary/10 text-primary ring-1 ring-primary/40'
              }`}
            >
              全部：{fields.length}
            </button>
            {factStatusChipOrder.map((statusKey) => {
              const count = statusCounts[statusKey] || 0
              const active = factFilter?.type === 'status' && factFilter.key === statusKey
              const label = factStatusLabels[statusKey] || statusKey
              return (
                <button
                  key={statusKey}
                  type="button"
                  onClick={() => toggleFactFilter({ type: 'status', key: statusKey, label })}
                  title={`筛选「${label}」字段${active ? '（再次点击取消）' : ''}`}
                  className={factFilterChipClass(active, factFieldStatusTone(statusKey), count)}
                >
                  {label}：{count}
                </button>
              )
            })}
            {specTotal ? (
              <div
                className="ml-1 flex items-center gap-2 border-l border-surface-container-high pl-3"
                title={`清单字段共 ${specTotal} 个：已确认 ${specSegments.confirmed} · 待确认 ${specSegments.pending} · 未填 ${specSegments.unfilled} · 已填未确认 ${specSegments.filledUnconfirmed}`}
              >
                <span className="text-xs text-on-surface-variant">清单进度</span>
                <div className="flex h-2 w-32 overflow-hidden rounded-full bg-surface-container-high">
                  {[
                    ['confirmed', 'bg-secondary', specSegments.confirmed],
                    ['pending', 'bg-tertiary', specSegments.pending],
                    ['filledUnconfirmed', 'bg-primary-fixed-dim', specSegments.filledUnconfirmed],
                    ['unfilled', 'bg-amber-300', specSegments.unfilled],
                  ].map(([segmentKey, barClass, count]) =>
                    count ? (
                      <span key={segmentKey} className={barClass} style={{ width: `${(count / specTotal) * 100}%` }} />
                    ) : null
                  )}
                </div>
                <span className="text-xs font-semibold tabular-nums text-on-surface">
                  {specSegments.confirmed}/{specTotal} 已确认
                </span>
              </div>
            ) : null}
          </div>
        </div>

        {curating ? (
          <div className="flex items-center gap-2 border-b border-surface-container-high bg-tertiary-fixed/40 px-5 py-2.5 text-xs text-on-surface">
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-tertiary" />
            <span className="font-semibold">{curatePhase || '刷新填充中'}</span>
            <span className="min-w-0 truncate text-on-surface-variant">{curateMessage || ''}</span>
            <span className="ml-auto shrink-0 text-on-surface-variant">任务在后台执行，可关闭本窗口</span>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-container-high bg-surface-container-lowest px-5 py-2.5 text-xs text-on-surface-variant">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <span className="material-symbols-outlined shrink-0 text-[16px] text-outline">description</span>
              <span className="truncate" title={specsFileName || ''}>
                {specsImported ? (specsFileName || '事实表已上传') : '尚未上传事实表'}
              </span>
            </span>
            <Button type="button" onClick={onUploadSpecs} disabled={busy} icon="upload_file" size="xs" variant="quiet">
              {specsImported ? '重新上传' : '上传事实表'}
            </Button>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <span className="material-symbols-outlined shrink-0 text-[16px] text-outline">folder_open</span>
              <span className="max-w-[22rem] truncate" title={scopeTitle}>
                {scopeSummary}
                {materialPaths?.length ? ` + ${materialPaths.length} 个参考目录` : ''}
              </span>
            </span>
            <Button
              type="button"
              onClick={enterPathsEditing}
              disabled={busy}
              icon={pathsEditing ? 'expand_less' : 'tune'}
              size="xs"
              variant="quiet"
            >
              {pathsEditing ? '收起' : '设置范围'}
            </Button>
          </div>
        </div>

        {pathsEditing ? (
          <div className="border-b border-surface-container-high bg-surface-container-lowest px-5 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-on-surface-variant">
                从素材目录树勾选额外参考目录（默认三层范围始终参与，无需勾选）
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    const saved = await onSaveMaterialPaths(selectedPaths)
                    if (saved) setPathsEditing(false)
                  }}
                  disabled={busy}
                  className="inline-flex h-7 items-center rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                >
                  {updatingScope ? '更新中...' : '保存'}
                </button>
                <button
                  type="button"
                  onClick={enterPathsEditing}
                  disabled={busy}
                  className="inline-flex h-7 items-center rounded-md bg-surface-container-high px-3 text-xs text-on-surface-variant hover:bg-surface-dim disabled:opacity-50"
                >
                  取消
                </button>
              </div>
            </div>
            {selectedPaths.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {selectedPaths.map((path) => (
                  <span
                    key={path}
                    className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary"
                    title={path}
                  >
                    <span className="max-w-[320px] truncate">{path}</span>
                    <button
                      type="button"
                      onClick={() => togglePathSelected(path)}
                      className="flex h-4 w-4 items-center justify-center rounded hover:bg-primary/15"
                      aria-label={`移除参考目录 ${path}`}
                    >
                      <span className="material-symbols-outlined text-[13px]">close</span>
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
            <div className="mt-2 max-h-56 overflow-y-auto rounded-md border border-surface-container-high bg-surface p-1.5">
              {treeLoading ? (
                <div className="flex h-24 items-center justify-center text-xs text-outline">正在加载素材目录树...</div>
              ) : treeError ? (
                <div className="flex h-24 items-center justify-center text-xs text-error">{treeError}</div>
              ) : treeNodes.length ? (
                treeNodes.map((node) => renderPathTreeNode(node, 0))
              ) : (
                <div className="flex h-24 items-center justify-center text-xs text-outline">素材目录树为空，请先在原始材料库中建立目录</div>
              )}
            </div>
          </div>
        ) : null}

        {ignoredSuggestions.length ? (
          <div className="border-b border-error/30 bg-error-container/35 px-5 py-3 text-xs text-on-error-container">
            <p className="font-semibold">有 {ignoredSuggestions.length} 条 AI 建议未能写入事实表</p>
            <ul className="mt-1 space-y-1">
              {ignoredSuggestions.slice(0, 5).map((item, index) => (
                <li key={`${typeof item === 'object' ? item?.fieldKey : item}-${index}`}>
                  {typeof item === 'object'
                    ? `${item?.fieldKey || '未知字段'}：${item?.reason || '未提供原因'}`
                    : String(item)}
                </li>
              ))}
            </ul>
            {ignoredSuggestions.length > 5 ? <p className="mt-1">另有 {ignoredSuggestions.length - 5} 条未展示</p> : null}
          </div>
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col p-4">
          {fields.length ? (
            <>
              <div className="mb-2 flex h-6 shrink-0 items-center gap-2 text-xs text-on-surface-variant" aria-live="polite">
                {factFilter ? (
                  <>
                    <span className="material-symbols-outlined text-[14px]">filter_alt</span>
                    <span>筛选中：{factFilter.label}（{visibleRows.length} 条）</span>
                    <button
                      type="button"
                      onClick={() => setFactFilter(null)}
                      className="inline-flex h-6 items-center gap-0.5 rounded-md bg-surface-container-high px-2 font-semibold text-on-surface-variant hover:bg-surface-dim"
                    >
                      <span className="material-symbols-outlined text-[13px]">close</span>
                      清除筛选
                    </button>
                  </>
                ) : null}
              </div>
              <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-surface-container-high bg-surface-container-lowest">
                <div className="h-full overflow-auto [scrollbar-gutter:stable]" role="table" aria-label="项目事实字段">
                  <div className="min-w-[840px]">
                    <div
                      className="sticky top-0 z-10 grid items-center border-b border-surface-container-high bg-surface-container-low text-xs font-semibold text-outline"
                      style={factRowGridStyle}
                      role="row"
                    >
                      <div className="px-4 py-2.5" role="columnheader">字段</div>
                      <div className="px-4 py-2.5" role="columnheader">事实值</div>
                      <div className="px-4 py-2.5" role="columnheader">来源素材</div>
                    </div>
                    <div className="divide-y divide-surface-container-high" role="rowgroup">
                      {visibleRows.map(({ field, index }) => {
                      const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
                      const normalizedStatus = normalizeFactFieldStatus(field.status)
                      const isEmptyStatus = ['missing_source', 'unextracted'].includes(normalizedStatus)
                      const fieldNames = new Set([field.label, field.reviewLabel].map((value) => String(value || '').trim()).filter(Boolean))
                      const allRefPaths = uniqueStrings(asObjectArray(field.sourceRefs).map(factRefPath))
                        .filter((refPath) => !fieldNames.has(factRefFileName(refPath)))
                      const refPaths = allRefPaths.slice(0, 2)
                      const hiddenRefCount = Math.max(0, allRefPaths.length - refPaths.length)
                      return (
                        <div
                          key={field.id || `${field.label}-${index}`}
                          className="grid min-h-[60px] items-center transition-colors hover:bg-surface-container-low/60"
                          style={factRowGridStyle}
                          role="row"
                        >
                          <div className="min-w-0 px-4 py-3" role="cell">
                            {isManualField ? (
                              <input
                                value={field.label || ''}
                                onChange={(event) => onFieldChange(index, 'label', event.target.value)}
                                placeholder="字段名称"
                                className="h-9 w-full rounded-md border border-surface-container-high bg-surface px-3 text-sm font-semibold text-on-surface outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                              />
                            ) : (
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate font-semibold text-on-surface" title={field.label}>{field.label}</span>
                                {field.needsConfirmation ? (
                                  <span className="shrink-0 rounded bg-tertiary-fixed px-1.5 py-0.5 text-[10px] font-semibold text-on-tertiary-fixed" title={field.notes || '清单标记：该字段口径需人工确认'}>
                                    待确认口径
                                  </span>
                                ) : null}
                              </div>
                            )}
                          </div>
                          <div className="px-4 py-3" role="cell">
                            <input
                              value={field.value || ''}
                              onChange={(event) => onFieldChange(index, 'value', event.target.value)}
                              placeholder="待填写"
                              aria-label={`${field.label || '字段'}的事实值`}
                              className={`h-9 w-full rounded-md border px-3 text-sm text-on-surface outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 ${
                                isEmptyStatus
                                  ? 'border-tertiary bg-tertiary-fixed/35'
                                  : 'border-surface-container-high bg-surface'
                              }`}
                            />
                          </div>
                          <div className="min-w-0 px-4 py-3 text-xs text-on-surface-variant" role="cell">
                            {refPaths.length ? (
                              <div className="space-y-1">
                                {refPaths.map((refPath) => (
                                  <div key={refPath} className="flex min-w-0 items-center gap-1.5" title={refPath}>
                                    <span className="material-symbols-outlined shrink-0 text-[15px] text-outline">description</span>
                                    <span className="truncate">{factRefFileName(refPath)}</span>
                                  </div>
                                ))}
                                {hiddenRefCount ? (
                                  <div className="pl-[21px] text-[11px] text-outline">另有 {hiddenRefCount} 份素材</div>
                                ) : null}
                              </div>
                            ) : (
                              <span className="text-outline">暂无匹配素材</span>
                            )}
                          </div>
                        </div>
                      )
                      })}
                      {!visibleRows.length ? (
                        <div className="px-4 py-10 text-center text-xs text-outline" role="row">
                          没有符合「{factFilter?.label}」筛选条件的字段
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex min-h-[260px] flex-1 items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest text-center">
              <div>
                <span className="material-symbols-outlined text-4xl text-primary">upload_file</span>
                {specsImported ? (
                  <>
                    <p className="mt-3 text-sm text-on-surface-variant">
                      事实表「{specsFileName || '已上传'}」尚未生成字段，请重新上传后重试。
                    </p>
                    <button
                      type="button"
                      onClick={onUploadSpecs}
                      disabled={busy}
                      className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                    >
                      <span className="material-symbols-outlined text-[16px]">upload_file</span>
                      重新上传
                    </button>
                  </>
                ) : (
                  <>
                    <p className="mt-3 text-sm text-on-surface-variant">
                      还没有项目事实表。请先上传本项目的事实表 Excel，系统会从表中提取要填写的字段，再匹配项目素材。
                    </p>
                    <button
                      type="button"
                      onClick={onUploadSpecs}
                      disabled={busy}
                      className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                    >
                      <span className="material-symbols-outlined text-[16px]">upload_file</span>
                      上传事实表
                    </button>
                  </>
                )}
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
  tenderDocumentState,
  candidates,
  referenceIds,
  busy,
  onToggle,
  onPreview,
  onConfirm,
  onClose,
  onUpload,
  uploadBusy,
}) {
  if (!open) return null
  const usesTenderDocument = Boolean(tenderDocumentState?.required)
  const missingTenderDocument = Boolean(tenderDocumentState?.missingSource)
  const tenderDocumentNames = asArray(tenderDocumentState?.documentNames)
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
          {usesTenderDocument ? (
            <div className={`mt-2 rounded-md px-3 py-2 text-[11px] leading-relaxed ${missingTenderDocument ? 'bg-error-container text-on-error-container' : 'bg-primary-container/45 text-on-primary-container'}`}>
              <div className="font-semibold">使用项目招标文件全文</div>
              <div className="mt-0.5">
                {missingTenderDocument
                  ? '项目当前没有可读取的招标文件，请先在技术标解析中补充或替换招标文件并重新解析。'
                  : tenderDocumentNames.length
                    ? `${tenderDocumentNames.join('、')}（共 ${tenderDocumentState.documentCount} 份）`
                    : '执行时将读取解析阶段上传的完整招标文件及其全文、表格解析结果。'}
              </div>
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
                {usesTenderDocument && !missingTenderDocument
                  ? '本次无需额外选择素材，AI 将读取项目招标文件全文进行填写。'
                  : '暂无推荐素材，可先在目录项底部搜索或上传素材后再发起 AI 填写。'}
              </div>
            )}
          </div>
          {onUpload ? (
            <div className="mt-3 rounded-md border border-dashed border-surface-container-high bg-surface-container-low/50 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-on-surface">上传补充素材</div>
                  <div className="mt-0.5 text-[11px] text-outline">
                    自动匹配不准时可手动补料：上传的文件会存入项目素材库，并自动勾选为本次 AI 填写的参考素材。
                  </div>
                </div>
                <label className={`inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container ${busy || uploadBusy ? 'pointer-events-none opacity-50' : ''}`}>
                  <span className="material-symbols-outlined text-[16px]">upload_file</span>
                  {uploadBusy ? '上传中...' : '上传素材'}
                  <input
                    type="file"
                    multiple
                    accept=".docx,.xlsx,.xls,.pdf"
                    className="hidden"
                    disabled={busy || uploadBusy}
                    onChange={(event) => {
                      const files = event.target.files
                      event.target.value = ''
                      if (files?.length) onUpload(files)
                    }}
                  />
                </label>
              </div>
            </div>
          ) : null}
        </div>
        <div className="flex items-center justify-between border-t border-surface-container-high bg-surface-container-low px-5 py-4">
          <div className="flex flex-wrap gap-1.5">
            <span className="rounded bg-secondary-container px-2 py-0.5 text-[10px] font-semibold text-on-secondary-container">
              已选 {referenceIds.length} 份参考素材
            </span>
            {usesTenderDocument && !missingTenderDocument ? (
              <span className="rounded bg-primary-container px-2 py-0.5 text-[10px] font-semibold text-on-primary-container">
                招标文件 {tenderDocumentState.documentCount || '全部'} 份
              </span>
            ) : null}
          </div>
          <div className="flex gap-2">
            <Button type="button" onClick={onClose} disabled={busy} variant="quiet">取消</Button>
            <Button type="button" onClick={onConfirm} disabled={busy || missingTenderDocument} variant="primary">
              {busy ? '处理中...' : missingTenderDocument ? '缺少招标文件' : '开始 AI 填写'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}


function PreviewDocumentPane({
  eyebrow,
  title,
  icon,
  loading,
  session,
  error,
}) {
  return (
    <section className="flex min-h-[560px] min-w-0 flex-col overflow-hidden rounded-md border border-surface-container-high bg-surface-container-lowest">
      <div className="flex min-h-[64px] shrink-0 items-center gap-3 border-b border-surface-container-high px-4 py-3">
        <span className="material-symbols-outlined flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary-fixed text-[20px] text-primary">
          {icon}
        </span>
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-primary">{eyebrow}</div>
          <h4 className="mt-0.5 truncate text-sm font-semibold text-on-surface" title={title}>{title}</h4>
        </div>
      </div>
      <div className="min-h-0 flex-1 bg-surface-container-low p-2">
        {loading ? (
          <div className="flex h-full min-h-[480px] items-center justify-center rounded-md bg-surface-container-lowest px-6 text-center">
            <div>
              <span className="material-symbols-outlined text-3xl text-primary">hourglass_empty</span>
              <p className="mt-2 text-sm text-on-surface-variant">正在加载预览...</p>
            </div>
          </div>
        ) : session?.onlyoffice ? (
          <OnlyOfficeEmbed
            session={session.onlyoffice}
            mode="view"
            className="h-full min-h-[480px] w-full rounded-md border border-surface-container-high bg-white"
            onError={() => {}}
          />
        ) : (
          <div className="flex h-full min-h-[480px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
            <p className="max-w-md text-sm text-on-surface-variant">
              {error || '当前文档暂时无法预览，请检查素材是否已清洗为 Word。'}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

function TechnicalPreviewModal({
  open,
  sectionTitle,
  selectedPreviewChoice,
  comparison,
  previewLoading,
  previewSession,
  previewError,
  referencePreviewLoading,
  referencePreviewSession,
  referencePreviewError,
  onClose,
  reviewQueue,
  reviewCurrentId,
  onReviewStep,
  onReviewPass,
  reviewBusy,
}) {
  if (!open) return null
  const comparing = Boolean(comparison)
  // 待审核队列：一键填完是一批产物，在弹窗里连着审，不用退出去逐条点目录
  const queue = asObjectArray(reviewQueue)
  const queueIndex = queue.findIndex((item) => item?.id === reviewCurrentId)
  const showQueue = comparing && queue.length > 1

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-3 py-4">
      <section className="flex h-[min(94vh,980px)] w-[min(96vw,1800px)] flex-col overflow-hidden rounded-lg bg-surface shadow-2xl">
        <div className="flex min-h-[68px] shrink-0 items-center justify-between gap-4 border-b border-surface-container-high bg-surface px-5 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-on-surface">
              {comparing ? 'AI 填写结果对比' : (selectedPreviewChoice?.title || '文档预览')}
            </h3>
            <p className="mt-1 truncate text-xs text-outline" title={sectionTitle || selectedPreviewChoice?.subtitle || ''}>
              {comparing
                ? (sectionTitle || '对照填写前参考稿与 AI 填写结果')
                : `${previewKindLabels[selectedPreviewChoice?.kind] || '预览'} · ${selectedPreviewChoice?.subtitle || '-'}`}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {showQueue ? (
              <div className="flex items-center gap-1 rounded-md bg-surface-container-low px-1 py-0.5">
                <IconButton
                  aria-label="上一条待审核"
                  icon="chevron_left"
                  onClick={() => onReviewStep?.(-1)}
                  disabled={reviewBusy}
                  variant="quiet"
                />
                <span className="min-w-12 text-center text-[11px] tabular-nums text-on-surface-variant">
                  {queueIndex >= 0 ? queueIndex + 1 : '-'}/{queue.length}
                </span>
                <IconButton
                  aria-label="下一条待审核"
                  icon="chevron_right"
                  onClick={() => onReviewStep?.(1)}
                  disabled={reviewBusy}
                  variant="quiet"
                />
              </div>
            ) : null}
            {comparing && onReviewPass ? (
              <Button
                type="button"
                onClick={onReviewPass}
                disabled={reviewBusy}
                title="确认本条 AI 填写结果无误，定案后自动看下一条"
                size="sm"
                variant="primary"
              >
                复核通过
              </Button>
            ) : null}
            <IconButton aria-label="关闭" icon="close" onClick={onClose} variant="quiet" />
          </div>
        </div>

        <div className={`min-h-0 flex-1 overflow-auto bg-surface-container-low p-3 ${comparing ? 'grid gap-3 lg:grid-cols-2' : ''}`}>
          {comparing ? (
            <>
              <PreviewDocumentPane
                eyebrow="填写前 · 参考稿"
                title={comparison.reference.title || '待填写文档'}
                icon={previewKindIcons[comparison.reference.kind] || 'description'}
                loading={referencePreviewLoading}
                session={referencePreviewSession}
                error={referencePreviewError}
              />
              <PreviewDocumentPane
                eyebrow="填写后 · AI 结果"
                title={comparison.result.title || 'AI 填写结果'}
                icon="auto_awesome"
                loading={previewLoading}
                session={previewSession}
                error={previewError}
              />
            </>
          ) : selectedPreviewChoice ? (
            <PreviewDocumentPane
              eyebrow={previewKindLabels[selectedPreviewChoice.kind] || '文档预览'}
              title={selectedPreviewChoice.title || '文档预览'}
              icon={previewKindIcons[selectedPreviewChoice.kind] || 'description'}
              loading={previewLoading}
              session={previewSession}
              error={previewError}
            />
          ) : (
            <div className="flex h-full min-h-[520px] items-center justify-center rounded-md border border-dashed border-surface-container-high bg-surface-container-lowest px-6 text-center">
              <p className="max-w-md text-sm text-on-surface-variant">当前目录项还没有可预览的素材、空表或处理产物。</p>
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
  // 目录树展开态（key = 归一化目录号）；「忽略」父级时自动展开其子级。
  const [expandedTocKeys, setExpandedTocKeys] = useState(() => new Set())
  // 定案项的备选区默认收起，「更换素材」临时展开；切换目录项时复位。
  const [materialSwapOpen, setMaterialSwapOpen] = useState(false)
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
  const [referencePreviewSession, setReferencePreviewSession] = useState(null)
  const [referencePreviewLoading, setReferencePreviewLoading] = useState(false)
  const [referencePreviewError, setReferencePreviewError] = useState('')
  const [manualPreviewChoice, setManualPreviewChoice] = useState(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [factModalOpen, setFactModalOpen] = useState(false)
  const [factTable, setFactTable] = useState(null)
  const [factFields, setFactFields] = useState([])
  const [factCurateReport, setFactCurateReport] = useState(null)
  const [generationStatus, setGenerationStatus] = useState(null)
  const [generationModalOpen, setGenerationModalOpen] = useState(false)
  const [aiFillReferenceSelections, setAiFillReferenceSelections] = useState({})
  // AI 填写弹窗：点素材卡上的 AI填写 打开，选参考素材后执行；null=关闭。
  const [aiFillModalTask, setAiFillModalTask] = useState(null)
  // AI 填写弹窗内手动上传的补充素材：入项目素材库后注入候选列表并默认勾选，
  // 关闭弹窗时清空，避免串到下一个附表任务。
  const [aiFillUploadedCandidates, setAiFillUploadedCandidates] = useState([])
  const [aiFillUploadBusy, setAiFillUploadBusy] = useState(false)
  // 事实表：用户按项目上传 Excel（7 列清单），上传后后端解析字段清单作为事实表字段骨架；
  // 未上传的项目不出字段，仅引导上传。factMaterialPaths 是用户自定义的参考资料目录。
  const [factSpecsMeta, setFactSpecsMeta] = useState({ imported: false, fileName: '' })
  const [sourceMatrixMeta, setSourceMatrixMeta] = useState({ imported: false, fileName: '' })
  const [factMaterialPaths, setFactMaterialPaths] = useState([])
  // 默认生效的素材范围（标准文件/客户定制/项目定制三层），由后端按项目身份给出
  const [factMaterialScopes, setFactMaterialScopes] = useState([])
  // AI 匹配填充任务状态：执行在后台 worker，弹窗关闭/页面刷新都不影响，靠轮询恢复
  const [factCurateState, setFactCurateState] = useState(null)
  const factCurateNotifiedRef = useRef('')
  const factCurateRunning = ['queued', 'running'].includes(String(factCurateState?.status || ''))
  // 正文一键填写任务状态：同样跑在后台 worker，进度靠轮询恢复，关页面不影响
  const [bodyFillState, setBodyFillState] = useState(null)
  const bodyFillNotifiedRef = useRef('')
  const bodyFillRunning = ['queued', 'running'].includes(String(bodyFillState?.status || ''))
  const bodyFillDone = Number(bodyFillState?.done || 0)
  const bodyFillTotal = Number(bodyFillState?.total || 0)
  const fillRuleInputRef = useRef(null)
  const sourceMatrixInputRef = useRef(null)

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
        imported: Boolean(matrixMeta?.path),
        fileName: String(matrixMeta?.fileName || ''),
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
  const filteredItems = useMemo(() => (
    tagFilter ? items.filter((item) => technicalGapTagOf(item, items) === tagFilter) : items
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
  const summary = useMemo(() => data?.gapPlan?.summary || data?.summary || {}, [data])
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
  const previewComparison = useMemo(
    () => aiFillComparisonPair(visiblePreviewChoices, selectedPreviewChoice),
    [selectedPreviewChoice, visiblePreviewChoices],
  )
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
  const matchedTopMaterialId = String(asObjectArray(selected?.matchedMaterials)[0]?.id || '').trim()
  const topBlankEntries = fillBlankEntries.filter((entry) => {
    if (!entry.isMaterialBlank) return true
    if (!settledSelected) return false
    return !matchedTopMaterialId || entry.key !== matchedTopMaterialId
  })
  const poolBlankEntries = fillBlankEntries.filter((entry) => entry.isMaterialBlank && !settledSelected)
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
    const deduped = wrappers.filter((wrapper) => {
      if (!wrapper.key || seen.has(wrapper.key)) return false
      seen.add(wrapper.key)
      return true
    })
    // 系统预选置顶（产品裁决 2026-08-04）：无论展示分高低，第一张卡永远是系统预选的那份。
    const preselectedId = String(asObjectArray(selected?.matchedMaterials)[0]?.id || '').trim()
    if (!preselectedId) return deduped
    const pinned = deduped.filter((wrapper) => wrapper.key === preselectedId)
    return pinned.length
      ? [...pinned, ...deduped.filter((wrapper) => wrapper.key !== preselectedId)]
      : deduped
  })()
  const selectedPlaceholderLabels = compactList([
    ...asArray(selectedBlankSource?.placeholderLabels),
    ...selectedCandidateMaterials.flatMap((item) => asArray(item?.placeholderLabels)),
  ], 10)
  // 目录标签统计（v6 五工作态口径）：父章覆盖/仅留标题是旁路态不计入。
  const tagCounts = useMemo(() => {
    const counts = {
      manual_supplement: 0,
      needs_choice: 0,
      template_ready: 0,
      template_review: 0,
      material_ready: 0,
    }
    items.forEach((item) => {
      const tag = technicalGapTagOf(item, items)
      if (tag in counts) counts[tag] += 1
    })
    return counts
  }, [items])
  // 正文填写汇总：不区分单条填还是一键填，也不区分本轮还是历史
  const bodyFillCounts = useMemo(() => technicalBodyFillCounts(items), [items])
  const factConfirmed = factTable?.status === 'confirmed'
  const hasTechnicalGapPlan = data?.status === 'completed' && Boolean(data?.gapPlan || items.length)
  const generationRunning = generationStatus?.status === 'running'
  const generationCompleted = generationStatus?.status === 'completed'
  const generationProgress = Math.max(0, Math.min(100, Number(generationStatus?.percentage) || 0))

  useEffect(() => {
    let cancelled = false
    const sessionForChoice = async (choice) => {
      if (choice.kind === 'artifact') {
        return {
          onlyoffice: choice.artifact?.onlyoffice,
          fileName: choice.title,
          source: 'artifact',
        }
      }
      return choice.kind === 'appendix'
        ? technicalParseAPI.appendixPreview(id, choice.blankSource.id)
        : technicalMaterialsAPI.raw.previewCleanedFile(choice.material.id)
    }

    const loadSelectedPreview = async () => {
      setPreviewLoading(true)
      try {
        const payload = await sessionForChoice(selectedPreviewChoice)
        if (!cancelled) setPreviewSession(payload)
      } catch (e) {
        if (!cancelled) setPreviewError(e?.message || '预览加载失败')
      } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    }

    const loadReferencePreview = async () => {
      if (!previewComparison?.reference) return
      setReferencePreviewLoading(true)
      try {
        const payload = await sessionForChoice(previewComparison.reference)
        if (!cancelled) setReferencePreviewSession(payload)
      } catch (e) {
        if (!cancelled) setReferencePreviewError(e?.message || '参考稿预览加载失败')
      } finally {
        if (!cancelled) setReferencePreviewLoading(false)
      }
    }

    const loadPreviews = async () => {
      setPreviewSession(null)
      setPreviewLoading(false)
      setPreviewError('')
      setReferencePreviewSession(null)
      setReferencePreviewLoading(false)
      setReferencePreviewError('')
      if (!previewOpen || !selectedPreviewChoice) return
      await Promise.all([loadSelectedPreview(), loadReferencePreview()])
    }

    loadPreviews()
    return () => {
      cancelled = true
    }
  }, [id, previewComparison, previewOpen, selectedPreviewChoice])

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
    // 未上传事实表的项目不出字段：打开事实表弹窗引导上传，不再静默自动生成事实表
    if (!factSpecsMeta.imported && !factFields.length) {
      showToast?.('请先上传本项目的事实表 Excel，系统才能提取要填写的字段', 'error')
      setFactModalOpen(true)
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
        status: String(key === 'value' ? value : field.value || '').trim()
          ? (field.status === 'confirmed' ? 'confirmed' : 'extracted')
          : 'unextracted',
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
    setPreviewChoiceKey('')
    setPreviewSession(null)
    setPreviewError('')
    setManualPreviewChoice(null)
    setPreviewOpen(false)
    setAiFillModalTask(null)
    setMaterialSwapOpen(false)
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

  // 批量复核通过：只收「无未填字段」的产物。有黄标的必须逐条看过再放行——
  // 一键放过带 [待人工补充] 的产物，前面所有宁空勿错的努力就白费了。
  const batchReviewables = useMemo(
    () => reviewQueue.filter((item) => !Number(item?.qualityReport?.unfilledPlaceholderCount || 0)
      && !asArray(item?.reviewNotes).length),
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
    const timer = window.setInterval(() => {
      loadGenerationStatus()
    }, 1200)
    return () => window.clearInterval(timer)
  }, [generationRunning, loadGenerationStatus])

  // AI 匹配填充轮询：任务在后台 worker 执行，这里只负责取进度；终态时把结果一次性落到界面。
  // 完成通知按 jobId+finishedAt 去重，避免收尾那一拍重复弹 toast。
  useEffect(() => {
    if (!factCurateRunning) return undefined
    const timer = window.setInterval(async () => {
      try {
        const payload = await technicalGapsAPI.curateFactsStatus(id)
        const state = payload?.factCurateState || null
        setFactCurateState(state)
        const status = String(state?.status || '')
        if (status !== 'succeeded' && status !== 'failed') return
        const notifyKey = `${state?.jobId || ''}:${state?.finishedAt || ''}`
        if (factCurateNotifiedRef.current === notifyKey) return
        factCurateNotifiedRef.current = notifyKey
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
      } catch {
        // 轮询失败不打断任务，下个周期继续取
      }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [factCurateRunning, id, showToast])

  // 正文一键填写轮询：与 AI 匹配填充同一套范式，终态按 jobId+finishedAt 去重通知，
  // 完成后拉一次最新数据把产物、标签、审核队列一起刷新。
  useEffect(() => {
    if (!bodyFillRunning) return undefined
    const timer = window.setInterval(async () => {
      try {
        const payload = await technicalGapsAPI.bodyFillStatus(id)
        const state = payload?.bodyFillState || null
        setBodyFillState(state)
        const status = String(state?.status || '')
        if (!['succeeded', 'partial', 'failed'].includes(status)) return
        const notifyKey = `${state?.jobId || ''}:${state?.finishedAt || ''}`
        if (bodyFillNotifiedRef.current === notifyKey) return
        bodyFillNotifiedRef.current = notifyKey
        await loadData({ silent: true })
        showToast?.(state?.message || '正文填写完成', status === 'failed' ? 'error' : undefined)
      } catch {
        // 轮询失败不打断任务，下个周期继续取
      }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [bodyFillRunning, id, loadData, showToast])

  // 一键填写：范围取当前标签筛选后的可见目录项（没筛选就是全部待填写正文）。
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
      bodyFillNotifiedRef.current = ''
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

  const handleFactSpecsUpload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/\.xlsx$/i.test(file.name)) {
      showToast?.('事实表仅支持 .xlsx 文件', 'error')
      return
    }
    if (busyAction) return
    if (factFields.length && !window.confirm('重新上传会按新清单重建事实表；不再属于清单且未受保留规则保护的字段可能被移除。是否继续？')) {
      return
    }
    setBusyAction('fact-specs-upload')
    let specsUploaded = false
    try {
      const formData = new FormData()
      formData.append('file', file)
      const payload = await technicalGapsAPI.uploadFactSpecs(id, formData)
      setFactSpecsMeta({ imported: true, fileName: payload?.fileName || file.name })
      specsUploaded = true
      // 上传成功后立即按新清单重建事实表字段
      const table = await technicalGapsAPI.buildFacts(id)
      setFactTable(table)
      setFactFields(asObjectArray(table?.fields))
      setFactCurateReport(null)
      setData((current) => (current ? { ...current, projectFactTable: table } : current))
      setFactModalOpen(true)
      // 重建完直接接上 AI 填充，人不用再点一次「刷新并 AI 填充」。
      // 提交后立即返回，进度沿用 factCurateState 轮询，关页面不影响后台任务。
      const specTotal = payload?.specTotal ?? 0
      try {
        const curatePayload = await technicalGapsAPI.curateFacts(id, {})
        setFactCurateState(curatePayload?.factCurateState || null)
        showToast?.(`事实表已解析 ${specTotal} 个字段，正在 AI 填充`)
      } catch (curateError) {
        showToast?.(
          `事实表已解析 ${specTotal} 个字段，但 AI 填充未启动：${curateError?.message || '请手动点击「刷新并 AI 填充」'}`,
          'error',
        )
      }
    } catch (e) {
      showToast?.(
        specsUploaded
          ? `事实表清单已上传，但自动更新失败：${e?.message || '请重新上传后重试'}`
          : (e?.message || '事实表上传失败'),
        'error',
      )
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

  const handleSourceMatrixUpload = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/\.xlsx$/i.test(file.name)) {
      showToast?.('附表填写规则仅支持 .xlsx 文件', 'error')
      return
    }
    if (busyAction) return
    if (sourceMatrixMeta.imported && !window.confirm('重新上传会以新文件完整覆盖当前附表填写规则；新文件未包含的旧规则及其推荐素材会被清除。是否继续？')) {
      return
    }
    setBusyAction('source-matrix-upload')
    try {
      const formData = new FormData()
      formData.append('file', file)
      const payload = await technicalGapsAPI.uploadAppendixSourceMatrix(id, formData)
      setSourceMatrixMeta({ imported: true, fileName: payload?.fileName || file.name })
      showToast?.(technicalAppendixSourceMatrixUploadMessage(payload))
      await loadData({ silent: true })
    } catch (e) {
      showToast?.(e?.message || '附表填写规则上传失败', 'error')
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
            <input
              ref={fillRuleInputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={handleFactSpecsUpload}
            />
            <input
              ref={sourceMatrixInputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={handleSourceMatrixUpload}
            />
            <Button
              type="button"
              onClick={() => sourceMatrixInputRef.current?.click()}
              disabled={Boolean(busyAction) || data?.status !== 'completed'}
              title={sourceMatrixMeta.imported ? `已上传：${sourceMatrixMeta.fileName || '已上传'}，点击可重新上传` : '上传附表填写规则 Excel（客户×附表→素材来源），缺口识别时确定每张附表的取值来源'}
              size="stage"
              variant={sourceMatrixMeta.imported ? 'secondary' : 'quiet'}
            >
              {busyAction === 'source-matrix-upload' ? '上传中...' : sourceMatrixMeta.imported ? '附表填写规则（已上传）' : '附表填写规则'}
            </Button>
            <Button
              type="button"
              onClick={() => setFactModalOpen(true)}
              disabled={Boolean(busyAction) || data?.status !== 'completed'}
              title={factSpecsMeta.imported ? `事实表清单：${factSpecsMeta.fileName}` : '尚未上传事实表，打开后按引导上传'}
              size="stage"
              variant={factConfirmed ? 'secondary' : 'quiet'}
            >
              {busyAction === 'fact-specs-upload' ? '上传中...' : factConfirmed ? '项目事实表已确认' : '项目事实表'}
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
              <span className="text-xs font-semibold text-on-surface-variant">目录节点</span>
              <span className="text-lg font-headline font-bold tabular-nums text-primary">{summary.totalTocItems ?? items.length}</span>
            </div>
            <div className="grid min-w-0 flex-1 grid-cols-3 gap-1.5 text-center sm:grid-cols-5">
              {['manual_supplement', 'needs_choice', 'template_ready', 'template_review', 'material_ready'].map((key) => {
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

      {/* 正文填写条：汇总 + 一键入口 + 进度。单条填和一键填共用同一份计数；
          附表不在这里，由另一条线负责。任务跑在后台 worker，关页面不影响。 */}
      {isCompleted ? (
        <div className="business-panel rounded-md border border-surface-container-high bg-surface-container-lowest px-3 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
          <div className="flex min-h-8 flex-wrap items-center gap-3">
            <span className="shrink-0 text-xs font-semibold text-on-surface-variant">正文填写</span>
            <div className="flex shrink-0 items-center gap-3 border-r border-surface-container-high pr-3 text-xs">
              <span className="text-on-surface-variant">待填写 <b className="text-sm font-headline tabular-nums text-primary">{bodyFillCounts.pending}</b></span>
              <span className="text-on-surface-variant">已填写 <b className="text-sm font-headline tabular-nums text-primary">{bodyFillCounts.filled}</b></span>
              <span className={bodyFillCounts.failed ? 'text-error' : 'text-on-surface-variant'}>
                失败 <b className="text-sm font-headline tabular-nums">{bodyFillCounts.failed}</b>
              </span>
            </div>
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
            {/* 一键入口只在点开「待填写」后出现：作用域天然限定，与「待审核」下的批量复核对称。
                任务执行中在任何筛选下都要能看到进度，所以运行态按钮不受此限制。 */}
            {tagFilter === 'template_ready' || bodyFillRunning ? (
              <Button
                type="button"
                onClick={handleBodyFillAll}
                disabled={Boolean(busyAction) || bodyFillRunning || !bodyFillCounts.pending}
                title={
                  bodyFillRunning
                    ? '正文填写任务执行中'
                    : `填写当前筛选出的 ${filteredItems.length} 个目录项，产物统一进入待审核`
                }
                size="sm"
                variant="primary"
              >
                {bodyFillRunning
                  ? `填写中 ${bodyFillDone}/${bodyFillTotal}`
                  : `一键填写${bodyFillCounts.pending ? `（${bodyFillCounts.pending}）` : ''}`}
              </Button>
            ) : (
              <span className="shrink-0 text-[11px] text-outline">点开「待填写」标签发起一键填写</span>
            )}
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
                  {/* 批量复核只在点开「待审核」后出现：作用域天然限定，也不会误点。
                      带未填字段的产物不纳入，必须逐条看过——一键放过黄标就前功尽弃了。 */}
                  {tagFilter === 'template_review' && reviewQueue.length ? (
                    <Button
                      type="button"
                      onClick={handleBatchReviewPass}
                      disabled={Boolean(busyAction) || !batchReviewables.length}
                      title={
                        batchReviewables.length < reviewQueue.length
                          ? `其中 ${reviewQueue.length - batchReviewables.length} 条有未填字段，需逐条复核`
                          : '全部产物无未填字段，可批量定案'
                      }
                      size="sm"
                      variant="secondary"
                      className="ml-auto"
                    >
                      批量复核通过（{batchReviewables.length}）
                    </Button>
                  ) : null}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
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
                          <TechnicalTocActionBadge item={item} items={items} />
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
                                coverageLabel={wrapper.key && wrapper.key === String(asObjectArray(selected?.matchedMaterials)[0]?.id || '').trim() ? '系统预选' : ''}
                              />
                            )))}
                          </div>
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
          busy={['facts-confirm', 'fact-specs-upload', 'facts-material-sources', 'facts-curate'].includes(busyAction)}
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
          onUploadSpecs={() => fillRuleInputRef.current?.click()}
          onSaveMaterialPaths={handleSaveMaterialPaths}
          onCurate={handleCurateFacts}
        />
      ) : null}
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
        tenderDocumentState={aiFillTenderDocumentState}
        candidates={selectedReferenceCandidates}
        referenceIds={aiFillModalTask ? aiFillReferenceIdsFor(aiFillModalTask) : []}
        busy={Boolean(busyAction)}
        onToggle={(materialId) => handleToggleAiFillReference(aiFillModalTask, materialId)}
        onPreview={handlePreviewMaterial}
        onUpload={handleAiFillUpload}
        uploadBusy={aiFillUploadBusy}
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
