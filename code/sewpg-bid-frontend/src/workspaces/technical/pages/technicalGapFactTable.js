// 项目事实表维护弹窗的纯展示/归一逻辑（从 TechnicalGapRecognition.jsx 抽出），
// 不依赖 React，可用 node --test 直接验证。

// 表级与字段级都有 confirmed，含义不同（表：全部了结 / 字段：有值可用），分成两张表
export const factTableStatusLabels = {
  empty: '待生成',
  draft: '待补齐',
  confirmed: '已填满',
}

// 字段级三态（产品裁决 2026-08-10：取消人工确认闸门，有值即可用）
export const factFieldStatusLabels = {
  confirmed: '可用',
  unextracted: '待填写',
  not_applicable: '不适用',
}

// 历史状态归一：extracted/pending_confirmation/conflict/candidate 都是「有值但没人看过」，
// missing/missing_source 都是「没值」，后端已收敛成三态，这里兜住尚未重建的旧项目状态。
export const LEGACY_FACT_FIELD_STATUS = {
  extracted: 'confirmed',
  pending_confirmation: 'confirmed',
  conflict: 'confirmed',
  candidate: 'confirmed',
  missing: 'unextracted',
  missing_source: 'unextracted',
}

export const normalizeFactFieldStatus = (status) => {
  const value = String(status || 'unextracted')
  return LEGACY_FACT_FIELD_STATUS[value] || value
}

// 字段状态配色（统计 chip 与列表状态下拉共用）：confirmed 绿 / unextracted 浅琥珀 / not_applicable 灰
export const factFieldStatusTone = (status) => {
  switch (normalizeFactFieldStatus(status)) {
    case 'confirmed':
      return 'bg-secondary-container text-on-secondary-container'
    case 'unextracted':
      return 'bg-amber-50 text-amber-800'
    default:
      return 'bg-surface-container-high text-on-surface-variant'
  }
}

// 统计条 chip 的展示顺序
export const factStatusChipOrder = ['confirmed', 'unextracted', 'not_applicable']

export const hasFactSpecSeq = (field) =>
  field?.specSeq !== null && field?.specSeq !== undefined && String(field.specSeq) !== ''

// 清单进度分段，口径与后端 summary 的 spec*Count 一致：
// confirmed=有值可用；unfilled=没值待人工填；notApplicable=人工标了不适用，不计待办
export const factSpecSegment = (field) => {
  if (normalizeFactFieldStatus(field?.status) === 'not_applicable') return 'notApplicable'
  return String(field?.value || '').trim() ? 'confirmed' : 'unfilled'
}

// 来源素材路径展示（产品反馈 2026-08-03：事实表只保留 字段/确认值/来源路径 三列）：
// 优先素材完整路径，其次解析来源文件，退回 目录/文件名 或素材名。
export const factRefPath = (ref) => {
  const direct = String(ref?.path || ref?.sourceFile || '').trim()
  if (direct) return direct
  const folder = String(ref?.folderPath || '').trim().replace(/\/+$/, '')
  const name = String(ref?.name || '').trim()
  if (folder && name) return `${folder}/${name}`
  return name || String(ref?.title || '').trim()
}

// 来源列只展示文件名降噪，完整路径放 tooltip（产品反馈 2026-08-03）
export const factRefFileName = (path) => String(path || '').split('/').filter(Boolean).pop() || String(path || '')

// 固定三段最小宽度，避免原生 table 自动布局把“事实值”挤成竖条。
export const factRowGridStyle = {
  gridTemplateColumns: 'minmax(180px, 0.75fr) minmax(320px, 1.25fr) minmax(300px, 1.5fr)',
}

export const normalizeMaterialTreePath = (value) => String(value || '').replace(/^\/+|\/+$/g, '')
export const normalizeMaterialTreeNodes = (nodes = []) =>
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
export const collectDefaultExpandedTreePaths = (nodes = [], depth = 0, result = new Set()) => {
  nodes.forEach((node) => {
    if (node.children.length) {
      if (depth < 2) result.add(node.path)
      collectDefaultExpandedTreePaths(node.children, depth + 1, result)
    }
  })
  return result
}
