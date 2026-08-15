// 技术标/商务标解析结果表格共用的纯展示逻辑。

export const PROJECT_BASIC_FIELDS = [
  ['projectName', '项目名称'],
  ['tenderNo', '招标编号'],
  ['projectUnit', '项目单位'],
  ['tenderer', '招标人'],
  ['tenderAgency', '招标代理机构'],
  ['bidDeadline', '递交截止时间'],
]

export const displayValue = (value, emptyText = '-') => {
  if (Array.isArray(value)) {
    const text = value.map((item) => String(item || '').trim()).filter(Boolean).join('，')
    return text || emptyText
  }
  const text = String(value ?? '').trim()
  return text || emptyText
}

export const sourceValue = (row = {}) => displayValue(
  [row.sourceFile, row.section, row.evidenceLocation].filter(Boolean),
)

export const formatBidDeadline = (value, emptyText = '-') => {
  const text = String(value ?? '').trim()
  if (!text) return emptyText

  const normalized = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2})?)?$/)
  if (normalized) {
    const [, year, month, day, hour, minute] = normalized
    return hour ? `${year}-${month}-${day} ${hour}:${minute}` : `${year}-${month}-${day}`
  }

  const chinese = text.match(/(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?(?:\s*(\d{1,2})\s*(?:时|:)\s*(\d{1,2})?\s*分?)?/)
  if (chinese) {
    const [, year, month, day, hour, minute] = chinese
    const datePart = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
    return hour ? `${datePart} ${hour.padStart(2, '0')}:${String(minute || '0').padStart(2, '0')}` : datePart
  }

  return text
}

// 技术标：按原始值是否为空判断「未识别」。
export const resolveTechnicalProjectBasicValue = (key, field = {}) => {
  const found = Boolean(String(field?.value || '').trim())
  return { text: found ? displayValue(field.value) : '未识别', found }
}

// 商务标：截止时间先归一化格式，再按展示文案判断「未识别」。
export const resolveBusinessProjectBasicValue = (key, field = {}) => {
  const text = key === 'bidDeadline'
    ? formatBidDeadline(field?.value, '未识别')
    : displayValue(field?.value, '未识别')
  return { text, found: text !== '未识别' }
}
