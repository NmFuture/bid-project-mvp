// 解析证据校验横幅的数据推导：从 parse 结果的 structured.workflow 里取出 finalize 校验状态。
// 后端的分片链路与单会话链路都会把未通过项写进 workflow，这里只负责整理成可展示的形状。
// 刻意不产出任何"能否继续"的判断——校验未通过不阻断后续流程，是否采用由人决定。
// 抽成纯函数模块是为了可用 node:test 直接覆盖（组件本体是 JSX）。

const textOf = (value) => (typeof value === 'string' ? value.trim() : '')

const stringList = (values) => (
  Array.isArray(values) ? values.map(textOf).filter(Boolean) : []
)

// 后端 validationErrors 的元素可能是结构化对象，也可能是纯字符串（早期链路）
export const validationErrorText = (item) => {
  if (typeof item === 'string') return item.trim()
  if (!item || typeof item !== 'object') return ''
  const rowNo = item.rowNo === 0 || item.rowNo ? String(item.rowNo).trim() : ''
  const fieldKey = textOf(item.fieldKey)
  const locator = rowNo ? `清单第 ${rowNo} 行` : fieldKey
  const message = textOf(item.message) || textOf(item.code)
  if (locator && message) return `${locator}：${message}`
  return message || locator
}

export function parseValidationSummary(structured) {
  const workflow = structured && typeof structured === 'object' ? structured.workflow : null
  if (!workflow || typeof workflow !== 'object') return null
  const stage = textOf(workflow.stage)
  // 没跑过 agentic 校验的结果（本地兜底、历史数据）没有 stage，此时无从判断，不展示
  if (!stage) return null

  const errors = Array.isArray(workflow.validationErrors)
    ? workflow.validationErrors.map(validationErrorText).filter(Boolean)
    : []
  const missingTargets = stringList(workflow.missingTargets)
  const repairedShards = stringList(workflow.repairedShards)
  const failedShards = stringList(workflow.failedShards)
  const passed = stage === 'finalized' && !errors.length && !missingTargets.length

  return { passed, stage, errors, missingTargets, repairedShards, failedShards }
}
