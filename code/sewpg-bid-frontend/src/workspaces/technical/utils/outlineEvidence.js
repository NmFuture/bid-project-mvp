export const pickTenderBasis = (node) => {
  const basis = node?.tenderBasis || node?.tender_basis
  return basis && typeof basis === 'object' ? basis : null
}

export const tenderBasisSearchText = (basis) =>
  String(basis?.searchText || basis?.search_text || '')
    .replace(/\s+/g, ' ')
    .trim()

export const shouldPreserveOutlineNumber = (node) =>
  /^(?:技术)?附表|^副表|^附件/i.test(String(node?.tocNumber || node?.number || '').trim())

export const markOutlineNodeEdited = (node, title) => ({
  ...node,
  title,
  suggestionAction: '待确认',
  suggestionReason: '目录标题已人工修改，请确认现有招标依据仍然适用。',
})
