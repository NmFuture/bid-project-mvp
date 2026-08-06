// 素材库与 Wiki 的展示排序（产品需求 2026-08-05）：后端按 sort_order/id 返回，
// sort_order 目前恒为 0，实际等于创建顺序，页面上看着是乱的。这里统一按名称排序：
// - 中文按拼音首字母，英文按字母序（zh-CN collator）；
// - 数字按数值大小，且小数整体参与比较——机型编码 EW6.25 要排在 EW6.7 前面，
//   而 Intl 的 numeric 选项会被小数点打断成 6 和 25 两段，得出 6.7 < 6.25 的错序；
// - 目录在前、文件在后，沿用文件浏览器的通用惯例。
// 只影响展示，不改后端存储的 sort_order——将来若要支持人工拖拽排序，这里再让位。
const collator = new Intl.Collator('zh-CN', { sensitivity: 'base' })
const NUMBER_SEGMENT = /(\d+(?:\.\d+)?)/
const NUMBER_ONLY = /^\d+(?:\.\d+)?$/

// 「EW6.25-202」→ ['EW', '6.25', '-', '202']：文本段比拼音，数字段比数值。
const splitSegments = (value) => String(value ?? '').split(NUMBER_SEGMENT).filter(Boolean)

export const compareByName = (left, right) => {
  const leftParts = splitSegments(left)
  const rightParts = splitSegments(right)
  const shared = Math.min(leftParts.length, rightParts.length)
  for (let index = 0; index < shared; index += 1) {
    const leftPart = leftParts[index]
    const rightPart = rightParts[index]
    if (NUMBER_ONLY.test(leftPart) && NUMBER_ONLY.test(rightPart)) {
      const gap = Number(leftPart) - Number(rightPart)
      if (gap !== 0) return gap < 0 ? -1 : 1
      continue
    }
    const gap = collator.compare(leftPart, rightPart)
    if (gap !== 0) return gap
  }
  return leftParts.length - rightParts.length
}

const nodeName = (node) => String(node?.name ?? node?.title ?? '')

// 后端对所有节点都返回 children 数组（叶子为 []），据此区分目录与文件。
const isFolder = (node) => Array.isArray(node?.children) && node.children.length > 0

export const sortNodesByName = (nodes = []) => {
  if (!Array.isArray(nodes)) return []
  return [...nodes]
    .sort((left, right) => {
      const folderGap = Number(isFolder(right)) - Number(isFolder(left))
      if (folderGap !== 0) return folderGap
      return compareByName(nodeName(left), nodeName(right))
    })
    .map((node) => (
      Array.isArray(node?.children) && node.children.length
        ? { ...node, children: sortNodesByName(node.children) }
        : node
    ))
}

export const sortFilesByName = (files = []) => (
  Array.isArray(files)
    ? [...files].sort((left, right) => compareByName(nodeName(left), nodeName(right)))
    : []
)
