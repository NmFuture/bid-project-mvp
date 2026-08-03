export const OPEN_SOURCE_FONT_OPTIONS = {
  zh: [
    { value: 'Noto Sans CJK SC', label: '等线风格（Noto Sans CJK SC）' },
    { value: 'Noto Serif CJK SC', label: '宋体风格（Noto Serif CJK SC）' },
  ],
  en: [
    { value: 'Liberation Serif', label: 'Times 风格（Liberation Serif）' },
    { value: 'Liberation Sans', label: 'Arial 风格（Liberation Sans）' },
  ],
}

const LEGACY_FONT_ALIASES = {
  等线: 'Noto Sans CJK SC',
  '等线 Light': 'Noto Sans CJK SC',
  微软雅黑: 'Noto Sans CJK SC',
  黑体: 'Noto Sans CJK SC',
  宋体: 'Noto Serif CJK SC',
  SimSun: 'Noto Serif CJK SC',
  NSimSun: 'Noto Serif CJK SC',
  'Times New Roman': 'Liberation Serif',
  Arial: 'Liberation Sans',
}

export const normalizeFontStyleOverrides = (overrides = {}) => Object.fromEntries(
  Object.entries(overrides).map(([key, value]) => [
    key,
    key.endsWith('Font') && typeof value === 'string' ? (LEGACY_FONT_ALIASES[value] || value) : value,
  ]),
)
