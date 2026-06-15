const RISK_LEVEL_LABELS = {
  high: '高风险',
  medium: '中风险',
  low: '低风险',
}

export const businessRiskLevelLabel = (value = '') => {
  const key = String(value ?? '').trim()
  if (!key) return '未识别'
  return RISK_LEVEL_LABELS[key] || key
}
