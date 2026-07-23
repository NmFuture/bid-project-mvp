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

export const technicalGenerationPresentation = (status) => {
  const assembly = status?.assembly && typeof status.assembly === 'object' ? status.assembly : {}
  const warnings = asObjectArray(assembly.warnings)
  const rawWarningCount = assembly.summary?.warningCount
  const summaryWarningCount = Number(rawWarningCount)
  const hasSummaryWarningCount = rawWarningCount !== null
    && rawWarningCount !== undefined
    && rawWarningCount !== ''
    && Number.isFinite(summaryWarningCount)
    && summaryWarningCount >= 0
  const warningCounts = warnings
    .map((warning) => Number(warning.count))
    .filter((count) => Number.isInteger(count) && count > 0)
  const derivedWarningCount = warningCounts.length
    ? warningCounts.reduce((total, count) => total + count, 0)
    : warnings.length
  const warningCount = hasSummaryWarningCount
    ? Math.max(summaryWarningCount, derivedWarningCount)
    : derivedWarningCount
  const formatClean = assembly.formatClean && typeof assembly.formatClean === 'object'
    ? assembly.formatClean
    : (status?.formatClean && typeof status.formatClean === 'object' ? status.formatClean : {})
  const formatCleanFailed = formatClean.status === 'failed'

  return {
    warningCount,
    formatCleanFailed,
    formatCleanMessage: formatCleanFailed ? '格式清洗失败，当前使用组装稿' : '',
  }
}

export const technicalFormatStateFromDocument = (documentPayload, defaultStyleOverrides) => {
  const storedOverrides = documentPayload?.technicalFormatStyleOverrides
  const styleOverrides = storedOverrides && typeof storedOverrides === 'object' && !Array.isArray(storedOverrides)
    ? storedOverrides
    : {}
  return {
    preset: documentPayload?.technicalFormatPreset === 'custom' ? 'custom' : 'standard',
    styleOverrides: { ...defaultStyleOverrides, ...styleOverrides },
  }
}

export const technicalFormatRequest = (preset, styleOverrides) => (
  preset === 'custom'
    ? { preset: 'custom', styleOverrides: { ...styleOverrides } }
    : { preset: 'standard' }
)

export const technicalFormatDocumentAfterApply = (
  currentDocument,
  preset,
  styleOverrides,
  responseDocument,
) => {
  if (responseDocument && typeof responseDocument === 'object' && !Array.isArray(responseDocument)) {
    return responseDocument
  }
  return {
    ...(currentDocument && typeof currentDocument === 'object' ? currentDocument : {}),
    technicalFormatPreset: preset === 'custom' ? 'custom' : 'standard',
    technicalFormatStyleOverrides: preset === 'custom' ? { ...styleOverrides } : {},
  }
}

// 候选素材匹配度（0~1），口径与商务标 numericMatchScore 一致：
// 优先 score/matchScore/similarity/confidence，兜底 topicRelevance。
// 后端输出 0~1 归一化分；99 分（0.99）专用于「文件名精确命中」，启发式分永远落在 98 及以下。
// 值 >1 是旧版无界原始分（已入库的存量 plan），按百分制换算兼容。
export const technicalMatchScore = (material) => {
  const raw = material?.score
    ?? material?.matchScore
    ?? material?.similarity
    ?? material?.confidence
    ?? material?.topicRelevance
    ?? 0
  const value = Number(raw)
  if (!Number.isFinite(value)) return 0
  return value > 1 ? value / 100 : value
}

export const isStructuralItem = (item) => (
  String(item?.status || '') === 'structural'
    || String(item?.usage || '') === 'structural'
    || asArray(item?.usages).includes('structural')
)

// —— 目录标签（v3）：标签是「候选池 × 素材形态 × 人工确认」的派生视图 ——
// 产品裁决（2026-07-16 / 2026-07-21）：
// - AI 填写是素材的二次编辑，不是目录项的状态；目录只看匹配到的素材。
// - 待填写素材靠命名纪律识别：文件名前缀「待填写-」；解析生成的附表空表天然待填写。
// - 99 分专用于「文件名精确命中」（自动定案并默认选中），30~98 为同档启发式匹配。
// - 变「已就绪」的唯一途径是人工点目录节点的「确认」（humanConfirmed）；仅文件名精确
//   命中豁免确认自动就绪。选材/上传/AI填写只改内容，点确认之前标签不变。
// - 确认可撤销（产品反馈 2026-07-21）：humanConfirmed 是三态——未操作过/人工确认 true/
//   人工撤销 false。撤销对文件名精确命中的自动就绪同样生效：撤销后跳过自动就绪判定，
//   按候选分数回落到对应档位标签，需要再次点「确认」才能变回已就绪。
// - 后端 recompute 会在选材/上传后把 decision 翻成 ready，因此这里不再信任 decision=ready。
export const TECHNICAL_GAP_READY_SCORE = 0.99
export const TECHNICAL_GAP_WEAK_SCORE = 0.3

// 标签命名规范（产品意见 2026-07-17）：组合状态用短横线连接，不用逗号；「待完善」统一改叫「待确认」。
export const TECHNICAL_GAP_TAG_CONFIG = {
  needs_material: { label: '人工补充', variant: 'error' },
  needs_refine: { label: '已匹配-待确认', variant: 'warn' },
  needs_fill: { label: '已匹配-待填写', variant: 'info' },
  ready: { label: '已就绪', variant: 'done' },
}

// 待填写素材：严格按命名纪律，文件名（或清洗稿名）前缀「待填写-」。
export const isFillTemplateMaterial = (material) => (
  [material?.name, material?.cleanedFileName, material?.title]
    .some((value) => String(value || '').trim().startsWith('待填写-'))
)

// 目录节点级人工确认：三态——unset（从未点过）/ confirmed（人工确认）/ revoked（人工撤销）。
// humanConfirmed 字段本身由后端在「确认」接口调用后才写入，不存在即 unset。
export const technicalGapHumanConfirmState = (item) => {
  if (!item || !Object.prototype.hasOwnProperty.call(item, 'humanConfirmed')) return 'unset'
  return item.humanConfirmed ? 'confirmed' : 'revoked'
}

export const isTechnicalGapHumanConfirmed = (item) => technicalGapHumanConfirmState(item) === 'confirmed'

const candidatePool = (item) => [
  ...asObjectArray(item?.matchedMaterials),
  ...asObjectArray(item?.candidateMaterials),
]

// 匹配到待填写素材：附表空表/填写任务，或候选池里带「待填写-」前缀的素材。
const hasFillMaterial = (item) => (
  asObjectArray(item?.appendixTasks).length > 0
    || asObjectArray(item?.fillTasks).length > 0
    || candidatePool(item).some(isFillTemplateMaterial)
)

const ownTechnicalGapTag = (item) => {
  if (!item || isStructuralItem(item) || String(item?.status || '') === 'ignored') return ''
  const confirmState = technicalGapHumanConfirmState(item)
  if (confirmState === 'confirmed') return 'ready'
  if (hasFillMaterial(item)) return 'needs_fill'
  const pool = candidatePool(item)
  const best = pool.reduce((max, material) => Math.max(max, technicalMatchScore(material)), 0)
  // 文件名精确命中（0.99）豁免人工确认，自动已就绪——除非人工已显式撤销过。
  if (confirmState !== 'revoked' && best >= TECHNICAL_GAP_READY_SCORE) return 'ready'
  // 初判 ready 且无候选无产物的空骨架不算任务（decision 可能被终审改写，仅用于识别空骨架）。
  if (
    String(item?.decision || '') === 'ready'
    && !pool.length
    && !asObjectArray(item?.resolvedArtifacts).length
  ) return ''
  if (best >= TECHNICAL_GAP_WEAK_SCORE) return 'needs_refine'
  return 'needs_material'
}

export const technicalGapTagOf = (item, allItems = []) => {
  if (!item) return ''
  const parentId = String(item?.coveredByParent || '').trim()
  if (parentId && !isTechnicalGapHumanConfirmed(item)) {
    const parent = asObjectArray(allItems).find((entry) => String(entry?.id || '') === parentId)
    if (parent) return ownTechnicalGapTag(parent)
  }
  return ownTechnicalGapTag(item)
}

export const appendixTaskForFillTask = (selected, task) => {
  const appendixTasks = asObjectArray(selected?.appendixTasks)
  const blankId = String(task?.blankSource?.id || '').trim()
  if (blankId) {
    return appendixTasks.find((appendixTask) => String(appendixTask?.id || '').trim() === blankId) || null
  }
  return appendixTasks[0] || null
}

export const defaultAiFillReferenceMaterialIds = (selected, selectedMaterialIds = [], task = null) => {
  const manualIds = uniqueStrings(selectedMaterialIds)
  if (manualIds.length) return manualIds

  const appendixTask = appendixTaskForFillTask(selected, task)
  const scopedAppendixTasks = appendixTask ? [appendixTask] : asObjectArray(selected?.appendixTasks)
  const hasSourceRouting = scopedAppendixTasks.some((item) => item?.sourceRouting?.source === 'appendix_source_matrix')
    || selected?.sourceRouting?.source === 'appendix_source_matrix'
  const routedIds = uniqueStrings([
    ...scopedAppendixTasks
      .flatMap((item) => asObjectArray(item?.recommendedMaterials))
      .map((item) => item.id || item.materialId),
    ...asObjectArray(selected?.sourceRoutedMaterials).map((item) => item.id || item.materialId),
  ])
  if (hasSourceRouting && routedIds.length) return routedIds
  const recommendedIds = uniqueStrings(
    scopedAppendixTasks
      .flatMap((item) => asObjectArray(item?.recommendedMaterials))
      .map((item) => item.id),
  )
  if (hasSourceRouting) return recommendedIds
  if (recommendedIds.length) return recommendedIds

  const matchedIds = uniqueStrings(
    asObjectArray(selected?.matchedMaterials).map((item) => item.id),
  )
  if (matchedIds.length) return matchedIds
  return []
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

// 取素材上的证据片段：优先 planner 召回的 recalledSegments（带 matchScore，已按相关度排序），
// 否则回退到该素材切分出的全部 evidenceSegments。返回归一化的片段数组（最多 limit 条）。
export const evidenceSegmentsForMaterial = (material, limit = 3) => {
  const recalled = asObjectArray(material?.recalledSegments)
  const source = recalled.length ? recalled : asObjectArray(material?.evidenceSegments)
  return source.slice(0, limit).map((segment) => ({
    id: String(segment?.segmentId || segment?.id || '').trim(),
    title: String(segment?.title || '').trim(),
    summary: String(segment?.summary || '').trim(),
    sourcePages: String(segment?.sourcePages || '').trim(),
    matchScore: typeof segment?.matchScore === 'number' ? segment.matchScore : null,
  })).filter((segment) => segment.title || segment.summary)
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

  if (asObjectArray(selected?.fillTasks).length || (
    String(selected?.decision || '') === 'fill_required'
    && asObjectArray(selected?.appendixTasks).length > 0
  )) {
    return { label: '等待 AI 填写', tone: 'fill' }
  }

  if (String(selected?.decision || '') === 'fill_required') {
    return { label: '等待选择匹配素材', tone: 'missing' }
  }

  if (String(selected?.decision || '') === 'material_required') {
    return { label: '等待上传或选择素材', tone: 'missing' }
  }

  return { label: selected?.coverageRole === 'structural' || selected?.usage === 'structural' ? '结构目录' : '暂无预览产物', tone: 'none' }
}
