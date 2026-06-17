export const TECHNICAL_INTERPRETATION_DISPLAY_GROUPS = [
  '设备选型适配',
  '供货范围界定',
  '设计与制造标准',
  '施工与验收规范',
  '技术资料交付',
  '全生命周期质保',
  '涉网性能合规',
  'CMS / 一次调频 / 国产化 / 二次安防等',
]

export const TECHNICAL_INTERPRETATION_GROUP_ALIASES = {
  设备选型适配: '设备选型适配',
  供货范围界定: '供货范围界定',
  设计与制造标准: '设计与制造标准',
  施工与验收规范: '施工与验收规范',
  技术资料交付: '技术资料交付',
  投标技术资料要求: '技术资料交付',
  资格与资质要求: '技术资料交付',
  全生命周期质保: '全生命周期质保',
  涉网性能合规: '涉网性能合规',
  中央监控与远程监测系统: 'CMS / 一次调频 / 国产化 / 二次安防等',
  CMS振动监测系统: 'CMS / 一次调频 / 国产化 / 二次安防等',
  一次调频与惯量响应系统: 'CMS / 一次调频 / 国产化 / 二次安防等',
  国产自主可控软硬件: 'CMS / 一次调频 / 国产化 / 二次安防等',
  二次安防系统: 'CMS / 一次调频 / 国产化 / 二次安防等',
}

export const technicalInterpretationDisplayGroup = (item = {}) =>
  item.displayGroup
    || TECHNICAL_INTERPRETATION_GROUP_ALIASES[item.primaryCategory]
    || item.primaryCategory
    || '其他'

export const technicalInterpretationStatusLabel = (status = '') => {
  if (status === 'found') return '已找到'
  if (status === 'partial') return '部分找到'
  if (status === 'needs_spec') return '需补充核对'
  if (status === 'missing') return '未找到'
  return '待解析'
}

export const technicalInterpretationEvidenceSummary = (item = {}) => {
  const refs = Array.isArray(item.evidenceRefs) ? item.evidenceRefs : []
  if (item.evidenceSummary) return item.evidenceSummary
  if (!refs.length) {
    return item.status === 'needs_spec' && item.neededSourceName
      ? `需补充/核对：${item.neededSourceName}`
      : '-'
  }
  return refs
    .map((ref) => [ref.sourceFile, ref.section, ref.evidenceLocation].filter(Boolean).join(' / '))
    .filter(Boolean)
    .slice(0, 2)
    .join('；') || '-'
}

export const groupTechnicalInterpretationItems = (items = []) => {
  const grouped = new Map()
  for (const groupName of TECHNICAL_INTERPRETATION_DISPLAY_GROUPS) {
    grouped.set(groupName, [])
  }
  items.forEach((item) => {
    const groupName = technicalInterpretationDisplayGroup(item)
    if (!grouped.has(groupName)) grouped.set(groupName, [])
    grouped.get(groupName).push(item)
  })
  return Array.from(grouped.entries())
    .filter(([, groupItems]) => groupItems.length)
    .map(([groupName, groupItems]) => ({
      groupName,
      items: groupItems,
      counts: groupItems.reduce((acc, item) => {
        const status = item.status || 'pending'
        acc[status] = (acc[status] || 0) + 1
        return acc
      }, {}),
    }))
}
