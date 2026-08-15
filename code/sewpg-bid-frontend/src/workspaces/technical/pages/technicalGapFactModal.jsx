import { Fragment, useState } from 'react'
import { technicalMaterialsAPI } from '../../../api'
import Button from '../../../components/ui/Button'
import IconButton from '../../../components/ui/IconButton'
import Toolbar from '../../../components/ui/Toolbar'
import { asObjectArray, materialTierLabels, uniqueStrings } from './technicalGapRecognitionHelpers'
import {
  collectDefaultExpandedTreePaths,
  factFieldStatusLabels,
  factFieldStatusTone,
  factRefFileName,
  factRefPath,
  factRowGridStyle,
  factSpecSegment,
  factStatusChipOrder,
  factTableStatusLabels,
  hasFactSpecSeq,
  normalizeFactFieldStatus,
  normalizeMaterialTreeNodes,
} from './technicalGapFactTable'

// 项目事实表维护弹窗（从 TechnicalGapRecognition.jsx 抽出，纯 props 驱动）：
// 字段列表编辑、状态/清单进度筛选、参考目录范围设置、刷新并 AI 填充入口。
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
  onGoToRules,
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
  const specSegments = { confirmed: 0, unfilled: 0, notApplicable: 0 }
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

  // 多机型项目按机型分段成块显示（后端已把这些行按 turbineGroup 排到表首）。
  // 单机型只有一组，不分块，表现与改动前一致。
  const turbineGroupCount = new Set(
    fields.map((field) => Number(field.turbineGroup) || 0).filter(Boolean),
  ).size
  // 连续同组的行归成一段：机型段渲染成带边框的小块，其余段平铺
  const factRowSections = []
  visibleRows.forEach((row) => {
    const group = turbineGroupCount > 1 ? Number(row.field.turbineGroup) || 0 : 0
    const last = factRowSections[factRowSections.length - 1]
    if (last && last.group === group) {
      last.rows.push(row)
      return
    }
    factRowSections.push({
      group,
      // 组内各行的机型名相同，取第一行的即可
      modelLabel: String(row.field.turbineModelLabel || '').trim(),
      rows: [row],
    })
  })
  // 机型块标题右侧的摘要：台数与基础形式已在块内成行，这里只做一眼可辨的概览
  const factGroupSummary = (rows) => {
    const valueOf = (suffix) =>
      String(rows.find(({ field }) => String(field.label || '').endsWith(suffix))?.field.value || '').trim()
    const count = valueOf('台数')
    const foundation = valueOf('基础形式')
    return [count ? `${count} 台` : '', foundation].filter(Boolean).join(' · ')
  }

  // index 是 factFields 里的原始下标，onFieldChange 按它回写，分段渲染不能改
  const renderFactRow = ({ field, index }) => {
    const isManualField = asObjectArray(field.sourceRefs).some((ref) => ref.type === 'manualFact')
    const isEmptyStatus = normalizeFactFieldStatus(field.status) === 'unextracted'
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
                <span className="shrink-0 rounded bg-tertiary-fixed px-1.5 py-0.5 text-[10px] font-semibold text-on-tertiary-fixed" title={field.notes || '清单标记：该字段口径建议人工核一遍'}>
                  核口径
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
  }

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-2 sm:p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div role="dialog" aria-modal="true" aria-labelledby="technical-fact-modal-title" className="flex h-[calc(100dvh-1rem)] max-h-[860px] w-full max-w-[1180px] flex-col overflow-hidden overscroll-contain rounded-lg bg-surface shadow-[0_12px_28px_rgba(13,33,55,0.14)] sm:h-[calc(100dvh-2rem)]">
        <div className="flex flex-col gap-3 border-b border-surface-container-high bg-surface-container-low px-3 py-3.5 sm:px-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id="technical-fact-modal-title" className="text-lg font-headline font-bold text-on-surface">项目事实表维护</h3>
              <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${status === 'confirmed' ? 'bg-secondary-container text-on-secondary-container' : 'bg-tertiary-fixed text-on-tertiary-fixed'}`}>
                {factTableStatusLabels[status] || status}
              </span>
            </div>
            <Toolbar className="w-full sm:w-auto">
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
              const label = factFieldStatusLabels[statusKey] || statusKey
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
                title={`清单字段共 ${specTotal} 个：可用 ${specSegments.confirmed} · 待填写 ${specSegments.unfilled} · 不适用 ${specSegments.notApplicable}`}
              >
                <span className="text-xs text-on-surface-variant">清单进度</span>
                <div className="flex h-2 w-32 overflow-hidden rounded-full bg-surface-container-high">
                  {[
                    ['confirmed', 'bg-secondary', specSegments.confirmed],
                    ['unfilled', 'bg-amber-300', specSegments.unfilled],
                    ['notApplicable', 'bg-surface-container-highest', specSegments.notApplicable],
                  ].map(([segmentKey, barClass, count]) =>
                    count ? (
                      <span key={segmentKey} className={barClass} style={{ width: `${(count / specTotal) * 100}%` }} />
                    ) : null
                  )}
                </div>
                <span className="text-xs font-semibold tabular-nums text-on-surface">
                  {specSegments.confirmed}/{specTotal} 可用
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
            <Button
              type="button"
              onClick={onGoToRules}
              disabled={busy}
              icon="open_in_new"
              size="xs"
              variant="quiet"
              title="事实表清单已迁至素材库 · 规则页统一维护"
            >
              去规则页维护
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
                    <div>
                      {factRowSections.map((section) => {
                        const summary = section.group ? factGroupSummary(section.rows) : ''
                        const rows = (
                          <div className="divide-y divide-surface-container-high" role="rowgroup">
                            {section.rows.map(renderFactRow)}
                          </div>
                        )
                        if (!section.group) {
                          return (
                            <Fragment key={`fact-section-shared-${section.rows[0].index}`}>
                              {turbineGroupCount > 1 ? (
                                <div className="flex items-center gap-1.5 border-y border-surface-container-high bg-surface-container-low px-4 py-2 text-xs font-semibold text-on-surface-variant">
                                  <span className="material-symbols-outlined text-[15px] text-outline">public</span>
                                  全场共用
                                </div>
                              ) : null}
                              {rows}
                            </Fragment>
                          )
                        }
                        return (
                          <div key={`fact-section-turbine-${section.group}`} className="px-3 pb-1 pt-3">
                            <div className="overflow-hidden rounded-lg border border-primary/30 shadow-sm">
                              <div className="flex items-center gap-2 border-b border-primary/20 bg-primary/[0.08] px-3 py-2">
                                <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-bold leading-none text-on-primary">
                                  {section.group}
                                </span>
                                <span className="truncate text-sm font-semibold text-on-surface" title={section.modelLabel}>
                                  {section.modelLabel || `机型${section.group}`}
                                </span>
                                {summary ? (
                                  <span className="ml-auto shrink-0 rounded-md bg-surface px-2 py-0.5 text-[11px] font-medium text-on-surface-variant">
                                    {summary}
                                  </span>
                                ) : null}
                              </div>
                              {rows}
                            </div>
                          </div>
                        )
                      })}
                      {!visibleRows.length ? (
                        <div className="px-4 py-10 text-center text-xs text-outline">
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
                      事实表「{specsFileName || '已上传'}」尚未生成字段，请到素材库 · 规则页重新上传后重试。
                    </p>
                    <button
                      type="button"
                      onClick={onGoToRules}
                      disabled={busy}
                      className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                    >
                      <span className="material-symbols-outlined text-[16px]">open_in_new</span>
                      前往规则页
                    </button>
                  </>
                ) : (
                  <>
                    <p className="mt-3 text-sm text-on-surface-variant">
                      还没有项目事实表。请先到素材库 · 规则页上传事实表清单 Excel，系统会从表中提取要填写的字段，再匹配项目素材。
                    </p>
                    <button
                      type="button"
                      onClick={onGoToRules}
                      disabled={busy}
                      className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-semibold text-on-primary hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50"
                    >
                      <span className="material-symbols-outlined text-[16px]">open_in_new</span>
                      前往规则页上传
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

export default FactMaintenanceModal
