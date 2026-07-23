export const getOutlineDisplayNumber = (node = {}, treeSequence = '') =>
  String(treeSequence || (node.tocNumber ?? node.number ?? node.toc_number ?? '')).trim()
