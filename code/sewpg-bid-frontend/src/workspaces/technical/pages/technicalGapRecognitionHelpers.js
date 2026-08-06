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

// —— 目录标签（v4）：标签 = 「匹配置信度 × 素材形态 × 处理进度」的派生视图 ——
// 产品裁决（2026-08-04，S3 树状改造，替代 2026-07-16/21 的旧裁决）：
// - 八标签两轨，名词管形态、动词管状态：素材轨（直接可用）已就绪素材/待确认素材，
//   模板轨（需 AI 填写）待确认模板/已就绪模板/待复核模板；缺口为待人工补充。
// - 选定即定案：人工亲手选/传素材即人工决策（后端 register 落 humanConfirmed），
//   不再要求二次点「确认」；「确认」动作只服务系统自动匹配的 30~98 档。
// - AI 填写改变标签（推翻 2026-07-16「AI 填写不改目录状态」）：填写完成 → 待复核模板；
//   复核通过（qualityStatus=human_confirmed）→ 已就绪素材；复核不通过原地重新 AI 填写。
// - 0.99 仍专用于「文件名精确命中」，自动定案；人工撤销（humanConfirmed=false）后回落分数档。
// - 解析生成的附表空表来源天生确定 → 已就绪模板，不参与 30 分线；
//   甲方已填附表（sourceRouting.status=client_provided 全覆盖）→ 已就绪素材。
// - 冻结/释放按目录树派生：任一「未忽略且自身有工作标签」的祖先冻结整棵子树（由父章覆盖）；
//   「忽略」（titleOnly，父级仅保留标题）后子级释放、各自按候选派生标签，逐级递归。
//   planner 的 coveredByParent 降级为素材继承提示，不再参与标签判定。
export const TECHNICAL_GAP_READY_SCORE = 0.99
export const TECHNICAL_GAP_WEAK_SCORE = 0.3

// 标签命名 v6（产品裁决 2026-08-04）：工作态统一三字「待/已 + 二字动作」，
// 流水线 待补充 → 待确认 → 待填写 → 待审核 → 已就绪；旁路态四字一对。
// 标签管状态、按钮管动作（AI填写/复核通过在右侧面板按钮上），tip 供 hover 提示。
export const TECHNICAL_GAP_TAG_CONFIG = {
  manual_supplement: { label: '待补充', tip: '系统没找到素材，请上传或从素材库挑选', variant: 'error' },
  needs_choice: { label: '待确认', tip: '请从备选中确认用哪份素材', variant: 'amber' },
  template_ready: { label: '待填写', tip: '模板已定，点击发起 AI 填写', variant: 'info' },
  template_review: { label: '待审核', tip: 'AI 已填写完成，请检查结果', variant: 'cyan' },
  material_ready: { label: '已就绪', tip: '素材已定案，无需处理', variant: 'done' },
  parent_covered: { label: '父章覆盖', tip: '跟父章素材走，无需单独处理', variant: 'muted' },
  title_only: { label: '仅留标题', tip: '本级已忽略，内容由下级承接', variant: 'muted' },
}

// 待填写素材：严格按命名纪律，文件名（或清洗稿名）前缀「待填写-」。
export const isFillTemplateMaterial = (material) => (
  [material?.name, material?.cleanedFileName, material?.title]
    .some((value) => String(value || '').trim().startsWith('待填写-'))
)

// 目录节点级人工确认：三态——unset（从未点过）/ confirmed（人工确认）/ revoked（人工撤销）。
// humanConfirmed 由「确认」接口或「选定即定案」的 register 写入，不存在即 unset。
export const technicalGapHumanConfirmState = (item) => {
  if (!item || !Object.prototype.hasOwnProperty.call(item, 'humanConfirmed')) return 'unset'
  return item.humanConfirmed ? 'confirmed' : 'revoked'
}

export const isTechnicalGapHumanConfirmed = (item) => technicalGapHumanConfirmState(item) === 'confirmed'

const candidatePool = (item) => [
  ...asObjectArray(item?.matchedMaterials),
  ...asObjectArray(item?.candidateMaterials),
]

// 甲方已填附表：附表任务全部命中甲方提供的填好文件（sourceRouting.status=client_provided）。
const appendixAllClientProvided = (item) => {
  const tasks = asObjectArray(item?.appendixTasks)
  return tasks.length > 0 && tasks.every(
    (task) => String(task?.sourceRouting?.status || '') === 'client_provided'
  )
}

const bestPoolScore = (item) => candidatePool(item)
  .reduce((max, material) => Math.max(max, technicalMatchScore(material)), 0)

const bestPoolMaterial = (item) => {
  let best = null
  let bestScore = -1
  candidatePool(item).forEach((material) => {
    const score = technicalMatchScore(material)
    if (score > bestScore) {
      best = material
      bestScore = score
    }
  })
  return best
}

// 模板轨判定：有附表/填写任务，或最佳候选本身是待填写模板。形态跟着最佳/选定素材走。
const isTemplateTrackItem = (item) => {
  if (asObjectArray(item?.appendixTasks).length > 0) return true
  if (asObjectArray(item?.fillTasks).length > 0) return true
  const best = bestPoolMaterial(item)
  return best ? isFillTemplateMaterial(best) : false
}

const hasAiFillArtifact = (item) => asObjectArray(item?.resolvedArtifacts)
  .some((artifact) => String(artifact?.source || '') === 'ai_fill')

// 人工产物算「成稿」必须与后端 S7 闸口同口径（s7Ready）：人工选中的「待填写-」空模板
// s7Ready=false（R10-B07-01），只是定下要填的模板，不算成稿，不进「已就绪」。
const hasManualArtifact = (item) => asObjectArray(item?.resolvedArtifacts)
  .some((artifact) => ['manual_upload', 'material_library', 'manual'].includes(String(artifact?.source || ''))
    && artifact?.s7Ready !== false)

export const technicalGapOwnTag = (item) => {
  if (!item || isStructuralItem(item) || String(item?.status || '') === 'ignored') return ''
  if (item?.titleOnly) return 'title_only'
  const confirmState = technicalGapHumanConfirmState(item)
  const confirmed = confirmState === 'confirmed'
  const revoked = confirmState === 'revoked'
  const best = bestPoolScore(item)
  const exact = !revoked && best >= TECHNICAL_GAP_READY_SCORE

  // 甲方已填附表：与 0.99 精确命中同级的定案豁免，人工撤销后回落。
  if (!revoked && appendixAllClientProvided(item)) return 'material_ready'

  // AI 填写产物存在：待审核；复核通过（human_confirmed）收口为绿色终态。
  if (hasAiFillArtifact(item)) {
    return String(item?.qualityStatus || '') === 'human_confirmed' ? 'material_ready' : 'template_review'
  }

  // 人工上传/选材（选定即定案）：拿到的是成稿，直接绿色终态。
  if (confirmed && hasManualArtifact(item)) return 'material_ready'

  if (isTemplateTrackItem(item)) {
    // 解析空表来源天生确定；模板被人工定案或文件名精确命中同样算已定。
    // 填写轨的实体证据由任务（blankSource/空表）或最佳候选模板天然保证。
    if (asObjectArray(item?.appendixTasks).length > 0 || confirmed || exact) return 'template_ready'
    if (best >= TECHNICAL_GAP_WEAK_SCORE) return 'needs_choice'
    return 'manual_supplement'
  }

  // 空确认防御（产品反馈 2026-08-04）：变绿必须有素材实体证据——人工确认只对
  // 系统预选素材（matchedMaterials）生效，空项确认不产生任何定案。
  const hasSelectedMaterial = asObjectArray(item?.matchedMaterials).length > 0
  if ((confirmed && hasSelectedMaterial) || exact) return 'material_ready'
  // 初判 ready 且无候选无产物的空骨架不算任务（decision 可能被终审改写，仅用于识别空骨架）。
  if (
    String(item?.decision || '') === 'ready'
    && !candidatePool(item).length
    && !asObjectArray(item?.resolvedArtifacts).length
  ) return ''
  if (best >= TECHNICAL_GAP_WEAK_SCORE) return 'needs_choice'
  return 'manual_supplement'
}

// 祖先链：3.2.1 → [3.2, 第3章]、附表A.1 → [技术附表根]，最近的祖先在前（level 栈回溯）。
export const technicalGapAncestorItems = (item, allItems = []) => {
  const list = asObjectArray(allItems)
  const index = technicalGapItemIndex(item, list)
  if (index < 0) return []
  const ancestors = []
  let level = technicalGapItemLevel(list[index])
  for (let cursor = index - 1; cursor >= 0 && level > 1; cursor -= 1) {
    const entryLevel = technicalGapItemLevel(list[cursor])
    if (entryLevel < level) {
      ancestors.push(list[cursor])
      level = entryLevel
    }
  }
  return ancestors
}

// 冻结源：任一「未忽略且自身有工作标签」的祖先都会冻结整棵子树；返回最近的一个供展示。
export const technicalGapFreezerItem = (item, allItems = []) => (
  technicalGapAncestorItems(item, allItems).find((ancestor) => {
    const tag = technicalGapOwnTag(ancestor)
    return tag && tag !== 'title_only'
  }) || null
)

export const technicalGapTagOf = (item, allItems = []) => {
  if (!item) return ''
  const own = technicalGapOwnTag(item)
  if (own === 'title_only') return 'title_only'
  // 结构项/人工忽略状态自身无标签，也不参与冻结展示。
  if (isStructuralItem(item) || String(item?.status || '') === 'ignored') return own
  // 冻结判定不依赖子级自身标签：空骨架子级同样显示「由父章覆盖」（否则会漏出可操作入口）。
  if (technicalGapFreezerItem(item, allItems)) return 'parent_covered'
  return own
}

// —— 人工「父章节覆盖」（产品需求 2026-07-27）——
// 一、二级目录选定素材后，下级小节常常就是跟着这份素材一起写。这里判断某个目录项
// 能不能一键把下级设为父章节覆盖：口径与后端 technical_gap_number_key 保持一致。
const CHINESE_DIGITS = { 零: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 }

export const technicalGapNumberKey = (number) => {
  const text = String(number || '').trim()
  const match = /^第\s*([一二三四五六七八九十百千万0-9]+)\s*章$/.exec(text)
  if (!match) return text
  const raw = match[1]
  if (/^\d+$/.test(raw)) return raw
  if (raw in CHINESE_DIGITS) return String(CHINESE_DIGITS[raw])
  if (raw === '十') return '10'
  if (raw.includes('十')) {
    const [left, right] = raw.split('十')
    const tens = left ? (CHINESE_DIGITS[left] ?? 1) : 1
    const ones = right ? (CHINESE_DIGITS[right] ?? 0) : 0
    return String(tens * 10 + ones)
  }
  return text
}

// —— 目录树父子关系（2026-08-04 v6.1）：按计划顺序 + level 栈推导 ——
// TOC 的顺序与层级本来就定义了树；目录号前缀链（3.1→第3章）只是它的特例。
// 附表（附表A.1 等编号不成链）同样归入最近的上级（附录/技术附表根）。
const technicalGapItemIndex = (item, allItems) => {
  const list = asObjectArray(allItems)
  const id = String(item?.id || '')
  return list.findIndex((entry) => entry === item || (id && String(entry?.id || '') === id))
}

const technicalGapItemLevel = (item) => {
  const level = Number(item?.level)
  return Number.isFinite(level) && level > 0 ? level : 1
}

export const technicalGapDescendants = (item, allItems = []) => {
  const list = asObjectArray(allItems)
  const index = technicalGapItemIndex(item, list)
  if (index < 0) return []
  const level = technicalGapItemLevel(list[index])
  const descendants = []
  for (let cursor = index + 1; cursor < list.length; cursor += 1) {
    if (technicalGapItemLevel(list[cursor]) <= level) break
    descendants.push(list[cursor])
  }
  return descendants
}

export const technicalGapParentCoverageState = (item, allItems = []) => {
  const descendants = technicalGapDescendants(item, allItems)
  const gapId = String(item?.id || '')
  // 已按本节点人工设置覆盖的下级；planner 自动判定的覆盖不计入（不由这个按钮撤销）。
  const manualCovered = descendants.filter(
    (entry) => String(entry?.coveredByParent || '') === gapId
      && String(entry?.parentCoverageSource || '') === 'manual',
  )
  const hasMaterial = asObjectArray(item?.matchedMaterials).length > 0
    || asObjectArray(item?.resolvedArtifacts).length > 0
  return {
    descendantCount: descendants.length,
    coveredCount: manualCovered.length,
    applied: manualCovered.length > 0,
    hasMaterial,
    // 有下级 + 本节点自己有素材，才谈得上让下级跟着它写。
    canApply: descendants.length > 0 && hasMaterial,
  }
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

  // 被冻结的子级继承冻结源的素材：树派生优先，回退 planner 的 coveredByParent 提示。
  const freezer = technicalGapFreezerItem(selected, allItems)
  const freezerMaterial = asObjectArray(freezer?.matchedMaterials)[0]
  if (freezerMaterial) {
    return {
      inherited: true,
      material: freezerMaterial,
      sourceItem: freezer,
    }
  }

  const parentId = String(selected?.coveredByParent || '').trim()
  if (!parentId) return null

  const parentItem = asObjectArray(allItems).find((item) => String(item?.id || '') === parentId)
  // 覆盖源已被「忽略」（仅保留标题）：旧 coveredByParent 提示失效，子级不再继承其素材。
  if (parentItem?.titleOnly) return null
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

// AI 结果预览固定配成「填写前参考稿 + AI 填写结果」。填写前优先使用空表/待填写模板，
// 没有模板时才退回匹配素材；普通素材或人工上传产物仍使用单文档预览。
export const aiFillComparisonPair = (choices, selectedChoice) => {
  if (
    selectedChoice?.kind !== 'artifact'
    || String(selectedChoice?.artifact?.source || '') !== 'ai_fill'
  ) return null

  const candidates = asObjectArray(choices).filter((choice) => choice?.key !== selectedChoice.key)
  const reference = candidates.find((choice) => choice.kind === 'blankMaterial' || choice.kind === 'appendix')
    || candidates.find((choice) => choice.kind === 'material')
  return reference ? { reference, result: selectedChoice } : null
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
