export const getOutlineDisplayNumber = (node = {}) =>
  String(node.tocNumber ?? node.number ?? node.toc_number ?? '').trim()
