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

export const latestResolvedArtifact = (selected) => {
  const artifacts = asObjectArray(selected?.resolvedArtifacts)
  return artifacts.length ? artifacts[artifacts.length - 1] : null
}

export const matchedMaterialForItem = (selected, allItems = []) => {
  const directMaterial = asObjectArray(selected?.matchedMaterials)[0]
  if (directMaterial) {
    return {
      inherited: false,
      material: directMaterial,
      sourceItem: selected || null,
    }
  }

  const parentId = String(selected?.coveredByParent || '').trim()
  if (!parentId) return null

  const parentItem = asObjectArray(allItems).find((item) => String(item?.id || '') === parentId)
  const parentMaterial = asObjectArray(parentItem?.matchedMaterials)[0]
  if (!parentMaterial) return null

  return {
    inherited: true,
    material: parentMaterial,
    sourceItem: parentItem,
  }
}

export const primaryBlankSource = (selected) => {
  const taskBlank = asObjectArray(selected?.fillTasks)
    .map((task) => task?.blankSource)
    .find((blank) => blank && blank.id)
  if (taskBlank) return taskBlank

  const appendix = asObjectArray(selected?.appendixTasks).find((item) => item?.id)
  if (!appendix) return null
  return {
    id: appendix.id,
    title: appendix.title,
    sourceFile: appendix.sourceFile,
    workspacePath: appendix.workspacePath,
  }
}

export const previewChoicesForItem = (selected, allItems = []) => {
  if (!selected) return []

  const choices = []
  const artifacts = asObjectArray(selected?.resolvedArtifacts).slice().reverse()
  artifacts
    .filter((item) => item?.onlyoffice?.fileUrl || item?.onlyoffice?.documentServerFileUrl)
    .forEach((artifact) => {
      choices.push({
      key: `artifact:${artifact.id}`,
      kind: 'artifact',
      label: artifact.source === 'ai_fill' ? 'AI已填写' : '最终产物',
      title: artifact.fileName || artifact.title || artifact.id || '处理产物',
      subtitle: artifact.source === 'ai_fill' ? 'AI 填写后结果' : '补充后结果',
      artifact,
      })
    })

  const blank = asObjectArray(selected?.fillTasks)
    .map((task) => task?.blankSource)
    .filter((blank) => blank?.id)
    .find(Boolean)
  if (blank) {
    const isMaterialBlank = blank.sourceType === 'material_fill_template' || String(blank.materialId || blank.id || '').startsWith('RAW-')
    choices.push({
      key: `${blank.sourceType === 'material_fill_template' || String(blank.materialId || blank.id || '').startsWith('RAW-') ? 'blank-material' : 'appendix'}:${blank.id}`,
      kind: isMaterialBlank ? 'blankMaterial' : 'appendix',
      label: isMaterialBlank ? '待填写素材' : '空副表',
      title: blank.title || blank.id || '空副表',
      subtitle: blank.folderPath || blank.sourceFile || blank.workspacePath || '招标文件解析产物',
      blankSource: blank,
      material: isMaterialBlank
        ? {
            id: blank.materialId || blank.id,
            name: blank.title || blank.cleanedFileName || blank.id,
            folderPath: blank.folderPath,
            path: blank.path,
            cleanedFileName: blank.cleanedFileName,
          }
        : null,
    })
  }

  const materialMatch = matchedMaterialForItem(selected, allItems)
  if (materialMatch?.material?.id) {
    choices.push({
        key: `material:${materialMatch.material.id}:${materialMatch.inherited ? 'parent' : 'direct'}`,
        kind: 'material',
        label: materialMatch.inherited ? '父章素材' : '匹配素材',
        title: materialMatch.material.name || materialMatch.material.cleanedFileName || materialMatch.material.id,
        subtitle: materialMatch.inherited
          ? `由 ${materialMatch.sourceItem?.number || materialMatch.sourceItem?.title || '父章节'} 覆盖`
          : (materialMatch.material.folderPath || materialMatch.material.path || ''),
        material: materialMatch.material,
        sourceItem: materialMatch.sourceItem,
        inherited: materialMatch.inherited,
    })
  }

  return choices
}

export const resultSummaryForItem = (selected, allItems = []) => {
  const artifact = latestResolvedArtifact(selected)
  if (artifact) {
    if (artifact.source === 'ai_fill') {
      const qualityStatus = artifact?.qualityReport?.status || selected?.qualityReport?.status
      if (qualityStatus === 'passed') {
        return {
          label: 'AI已填写 · 验收通过',
          tone: 'resolved',
        }
      }
      if (qualityStatus && qualityStatus !== 'passed') {
        return {
          label: 'AI已填写 · 待复核',
          tone: 'fill',
        }
      }
      return {
        label: 'AI已填写',
        tone: 'resolved',
      }
    }

    return {
      label: artifact.fileName || artifact.title || artifact.id || '已生成处理产物',
      tone: 'resolved',
    }
  }

  if (
    String(selected?.decision || '') === 'fill_required'
    && asObjectArray(selected?.fillTasks).some((task) => task?.status === 'completed')
  ) {
    return { label: '填写完毕', tone: 'resolved' }
  }

  const materialMatch = matchedMaterialForItem(selected, allItems)
  if (materialMatch?.material) {
    return {
      label: materialMatch.inherited
        ? `父章素材：${materialMatch.material.name || materialMatch.material.id}`
        : (materialMatch.material.name || materialMatch.material.id || '已匹配素材'),
      tone: 'material',
    }
  }

  if (asObjectArray(selected?.fillTasks).length || String(selected?.decision || '') === 'fill_required') {
    return { label: '等待 AI 填写', tone: 'fill' }
  }

  if (String(selected?.decision || '') === 'material_required') {
    return { label: '等待上传或选择素材', tone: 'missing' }
  }

  return { label: selected?.coverageRole === 'structural' || selected?.usage === 'structural' ? '结构目录' : '暂无预览产物', tone: 'none' }
}
