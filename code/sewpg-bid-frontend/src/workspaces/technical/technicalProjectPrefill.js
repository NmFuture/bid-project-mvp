import { normalizeTurbineModelRows } from '../shared/projectInfoForm.js'

export const TECHNICAL_BID_TYPE = '技术标'

export const technicalProjectToday = (now = new Date()) => {
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
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
