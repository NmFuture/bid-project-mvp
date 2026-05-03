export const asArray = (value) => (Array.isArray(value) ? value : [])

export const asObjectArray = (value) => asArray(value).filter((item) => item && typeof item === 'object')

export const uniqueStrings = (items) => {
  const seen = new Set()
  return asArray(items)
    .map((item) => String(item || '').trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

export const defaultAiFillReferenceMaterialIds = (selected, selectedMaterialIds = []) => {
  const manualIds = uniqueStrings(selectedMaterialIds)
  if (manualIds.length) return manualIds

  const matchedIds = uniqueStrings(
    asObjectArray(selected?.matchedMaterials).map((item) => item.id),
  )
  if (matchedIds.length) return matchedIds

  return uniqueStrings(
    asObjectArray(selected?.appendixTasks)
      .flatMap((task) => asObjectArray(task?.recommendedMaterials).slice(0, 1))
      .map((item) => item.id),
  )
}

export const defaultAiFillParseFieldIds = (selected, task) => uniqueStrings([
  task?.blankSource?.id,
  ...asObjectArray(selected?.appendixTasks)
    .filter((appendixTask) => {
      const blankId = String(task?.blankSource?.id || '')
      return !blankId || String(appendixTask?.id || '') === blankId
    })
    .flatMap((appendixTask) => asObjectArray(appendixTask?.availableParseFields).map((field) => field.id)),
])
