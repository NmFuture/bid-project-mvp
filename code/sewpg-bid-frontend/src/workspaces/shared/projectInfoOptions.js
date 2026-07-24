export const STATIC_CUSTOMER_OPTIONS = [
  '华润',
  '中电建',
  '中能建',
  '中煤',
  '京能',
  '中节能',
  '协合',
  '华能',
  '中国绿发',
  '中广核',
  '中核',
  '中航',
  '国家电投',
  '国家能源',
  '中石油',
  '中海油',
  '中石化',
  '华电',
  '大唐',
  '国投电力',
  '三峡',
  '其他',
]

export const STATIC_TURBINE_MODEL_OPTIONS = [
  'EW5.0-202',
  'EW5.6-202',
  'EW5.0-220',
  'EW6.25-202',
  'EW6.7-202',
  'EW6.25-220',
  'EW6.25-220中压',
  'EW6.7-220',
  'EW7.5-202下置',
  'EW7.5-220上置',
  'EW7.5-220下置',
  'EW7.7-230上置',
  'EW7.7-230下置',
  'EW8.35-220上置',
  'EW8.35-220下置',
  'EW8.5-220上置',
  'EW8.5-220下置',
  'EW8.5-230上置',
  'EW8.5-230下置',
  'EW10.0-220上置',
  'EW10.0-220下置',
  'EW10.0-230上置',
  'EW10.0-230下置',
  'EW11.0-230上置',
  'EW8.5-208',
  'EW8.0-230',
  'EW8.5-230',
  'EW9.0-230',
  'EW11.0-252',
  'EW12.0-252',
  'EW12.6-252',
  'EW13.0-252',
  'EW16.0-252',
  'EW16.0-252漂浮式',
  'EW16.0-252低频',
  'EW16.6-252',
  'EW16.7-252',
  'EW18.0-260',
  'EW12.0-270',
  'EW12.5-270',
  'EW12.6-270',
  'EW13.0-270',
  'EW13.6-270',
  'EW14.0-270',
  'EW16.0-270',
  'EW16.2-270',
  'EW12.5-272',
  'EW25.0-310',
]

export const STATIC_FOUNDATION_TYPE_OPTIONS = [
  '钢塔',
  '混塔',
  '单桩',
  '导管架',
  '多桩承台',
]

const normalizeOptionText = (value) => String(value || '').trim()

const normalizeStringOptions = (items = []) => {
  const seen = new Set()
  return (Array.isArray(items) ? items : [])
    .map((item) => normalizeOptionText(typeof item === 'string' ? item : item?.name || item?.label || item?.model))
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

export const normalizeProjectInfoOptions = (payload = {}) => ({
  customers: normalizeStringOptions(payload.customers).length
    ? normalizeStringOptions(payload.customers)
    : STATIC_CUSTOMER_OPTIONS,
  turbineModels: normalizeStringOptions(payload.turbineModels).length
    ? normalizeStringOptions(payload.turbineModels)
    : STATIC_TURBINE_MODEL_OPTIONS,
  source: payload.source || 'static',
  updatedAt: payload.updatedAt || '',
})

export const STATIC_PROJECT_INFO_OPTIONS = normalizeProjectInfoOptions({
  customers: STATIC_CUSTOMER_OPTIONS,
  turbineModels: STATIC_TURBINE_MODEL_OPTIONS,
  source: 'static',
})

export const loadProjectInfoOptions = async (api, options = {}) => {
  const useRemote = Boolean(options.useRemote)
  if (!useRemote) return STATIC_PROJECT_INFO_OPTIONS
  if (!api?.get) return STATIC_PROJECT_INFO_OPTIONS
  try {
    const payload = await api.get()
    if (String(payload?.source || '').endsWith('static-placeholder')) return STATIC_PROJECT_INFO_OPTIONS
    return normalizeProjectInfoOptions(payload)
  } catch {
    return STATIC_PROJECT_INFO_OPTIONS
  }
}

// "其他" 兜底选项：客户与风机机型下拉都需要在派生候选末尾追加一个手动输入入口。
export const OTHER_OPTION_LABEL = '其他'

const appendOtherOption = (items = []) => {
  const list = normalizeStringOptions(items).filter((item) => item !== OTHER_OPTION_LABEL)
  return [...list, OTHER_OPTION_LABEL]
}

// 从技术标三级目录 JSON 索引派生「客户」候选：取 tier==='customer'（客户定制）下
// 各 3 级目录的 customerName（回退 name），末尾追加「其他」。
// 见 doc/anbc_doc/20260618-技术标三级目录JSON索引-下游使用Handoff.md
export const deriveCustomerOptionsFromIndex = (indexPayload = {}) => {
  const tiers = Array.isArray(indexPayload?.tiers) ? indexPayload.tiers : []
  const customerTier = tiers.find((tier) => tier?.tier === 'customer')
  const names = (customerTier?.folders || []).map((folder) => folder?.customerName || folder?.name)
  return appendOtherOption(names)
}

// 从 JSON 索引派生「风机机型」候选：取 tier==='standard'（标准文件）下各 3 级目录的
// 目录名（即机型号），末尾追加「其他」。
export const deriveTurbineModelOptionsFromIndex = (indexPayload = {}) => {
  const tiers = Array.isArray(indexPayload?.tiers) ? indexPayload.tiers : []
  const standardTier = tiers.find((tier) => tier?.tier === 'standard')
  const names = (standardTier?.folders || []).map((folder) => folder?.name)
  return appendOtherOption(names)
}
