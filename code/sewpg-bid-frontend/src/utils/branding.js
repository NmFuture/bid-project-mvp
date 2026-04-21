const OPENCODE_PATTERN = /opencode/gi

export const brandFutureCode = (value) => {
  if (value === null || value === undefined) return ''
  return String(value).replace(OPENCODE_PATTERN, 'futurecode')
}

export const brandFutureCodeOrFallback = (value, fallback = '-') => {
  const branded = brandFutureCode(value).trim()
  return branded || fallback
}
