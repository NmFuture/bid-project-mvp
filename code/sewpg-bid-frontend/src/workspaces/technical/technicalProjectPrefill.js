import { normalizeTurbineModelRows } from '../shared/projectInfoForm.js'

export const TECHNICAL_BID_TYPE = '技术标'

export const technicalProjectToday = (now = new Date()) => {
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

const PARSE_PREFILL_FORM_FIELDS = ['name', 'projectCode', 'endDate']

export const mergeTechnicalProjectDraftForm = ({ initialForm, draftForm } = {}) => {
  const initial = initialForm && typeof initialForm === 'object' ? initialForm : {}
  const draft = draftForm && typeof draftForm === 'object' ? draftForm : null
  if (!draft) return initial

  const merged = { ...initial, ...draft }
  for (const field of PARSE_PREFILL_FORM_FIELDS) {
    if (!String(draft[field] || '').trim()) merged[field] = initial[field]
  }
  return merged
}

export const buildTechnicalProjectInitialForm = ({
  project = null,
  prefill = null,
  today = technicalProjectToday(),
  allowPrefill = Boolean(project?.isParseDraft),
} = {}) => {
  const parsed = allowPrefill && prefill && typeof prefill === 'object' ? prefill : {}
  return {
    projectCode: String(parsed.projectCode || project?.projectCode || ''),
    name: String(parsed.name || project?.name || ''),
    customerName: String(project?.customerName || ''),
    customerId: String(project?.materialCustomerId || project?.customerId || ''),
    customerCanonicalName: String(project?.materialCustomerName || project?.customerCanonicalName || project?.customerName || ''),
    materialProjectName: String(project?.materialProjectName || ''),
    manager: String(project?.manager || ''),
    bidType: TECHNICAL_BID_TYPE,
    turbineModels: normalizeTurbineModelRows(project),
    startDate: String(project?.startDate || today),
    endDate: String(parsed.endDate || parsed.deadline || project?.endDate || project?.deadline || '').slice(0, 10),
  }
}
