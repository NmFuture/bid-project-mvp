export const createTurbineModelRow = (data = {}) => ({
  id: String(data.id || `turbine-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
  model: String(data.model || data.turbineModel || data.name || '').trim(),
  turbineCount: String(data.turbineCount || data.count || '').trim(),
  foundationType: String(data.foundationType || data.foundation || '').trim(),
  source: String(data.source || 'static-options'),
})

export const normalizeTurbineModelRows = (project = null) => {
  const rawRows = Array.isArray(project?.turbineModels) ? project.turbineModels : []
  const rows = rawRows.map(createTurbineModelRow).filter((row) => row.model || row.turbineCount || row.foundationType)
  if (rows.length) return rows
  const primary = project?.turbineModel || project?.selectedTurbineModel
  const model = typeof primary === 'string'
    ? primary
    : primary?.model || primary?.turbineModel || primary?.name || ''
  if (!model) return [createTurbineModelRow()]
  return [createTurbineModelRow({
    model,
    turbineCount: primary?.turbineCount || '',
    foundationType: primary?.foundationType || '',
    source: primary?.source || 'legacy',
  })]
}

export const cleanTurbineModelRows = (rows = []) =>
  rows
    .map(createTurbineModelRow)
    .map((row) => ({
      model: row.model,
      turbineCount: row.turbineCount,
      foundationType: row.foundationType,
      source: row.source || 'static-options',
    }))
    .filter((row) => row.model || row.turbineCount || row.foundationType)

export const isPositiveIntegerText = (value) => /^[1-9]\d*$/.test(String(value || '').trim())

export const buildPrimaryTurbineModel = (rows = []) => {
  const first = cleanTurbineModelRows(rows).find((row) => row.model)
  if (!first) return {}
  return {
    model: first.model,
    turbineCount: first.turbineCount,
    foundationType: first.foundationType,
    source: first.source || 'static-options',
  }
}

export const mergeOptionValues = (options = [], values = []) => {
  const seen = new Set()
  return [...options, ...values]
    .map((item) => String(item || '').trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}
