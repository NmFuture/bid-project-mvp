import { useEffect, useMemo, useState } from 'react'
import { materialsAPI, projectsAPI } from '../../api'
import Button from '../ui/Button'

const MANUAL_TURBINE_VALUE = '__manual_turbine_model__'
const PROJECT_WIZARD_DRAFT_VERSION = 1
const PROJECT_WIZARD_DRAFT_PREFIX = 'sewpg.projectWizardDraft'
const FORM_REQUIRED_STEP = 0

const normalizeCustomers = (list = []) =>
  (Array.isArray(list) ? list : [])
    .map((item) => ({
      id: String(item?.customerId || item?.id || item?.name || '').trim(),
      customerId: String(item?.customerId || item?.id || '').trim(),
      name: String(item?.customerCanonicalName || item?.name || item?.label || item?.id || '').trim(),
      aliases: Array.isArray(item?.aliases) ? item.aliases : [],
    }))
    .filter((item) => item.id && item.name)

const normalizeMaterialProjects = (list = []) =>
  (Array.isArray(list) ? list : [])
    .map((item) => ({
      id: String(item?.projectId || item?.id || '').trim(),
      projectId: String(item?.projectId || item?.id || '').trim(),
      projectCode: String(item?.projectCode || item?.projectId || item?.id || '').trim(),
      name: String(item?.projectName || item?.name || item?.projectCode || item?.projectId || item?.id || '').trim(),
      customerId: String(item?.customerId || '').trim(),
      customerName: String(item?.customerCanonicalName || item?.customerName || '').trim(),
      bidType: String(item?.bidType || '').trim(),
    }))
    .filter((item) => item.id && item.name)

const normalizeTurbineModel = (value = null) => {
  if (!value) return { model: '', platform: '', layout: '', ratedPowerKw: '', rotorDiameterM: '', status: '', statusLabel: '', source: '', aliases: [] }
  const item = typeof value === 'string' ? { model: value } : value
  return {
    id: String(item?.id || item?.model || '').trim(),
    model: String(item?.model || item?.turbineModel || item?.name || '').trim(),
    platform: String(item?.platform || item?.turbinePlatform || '').trim(),
    layout: String(item?.layout || '').trim(),
    ratedPowerKw: item?.ratedPowerKw || '',
    rotorDiameterM: item?.rotorDiameterM || '',
    status: String(item?.status || '').trim(),
    statusLabel: String(item?.statusLabel || '').trim(),
    source: String(item?.source || '').trim(),
    sourceFileId: String(item?.sourceFileId || '').trim(),
    sourceFileName: String(item?.sourceFileName || '').trim(),
    aliases: Array.isArray(item?.aliases) ? item.aliases : [],
  }
}

const turbineModelLabel = (item = {}) => {
  const parts = [
    item.platform,
    item.ratedPowerKw ? `${item.ratedPowerKw}kW` : '',
    item.rotorDiameterM ? `叶轮${item.rotorDiameterM}m` : '',
    item.layout,
    item.statusLabel,
  ].filter(Boolean)
  return `${item.model}${parts.length ? `（${parts.join(' / ')}）` : ''}`
}

const buildInitialForm = (project = null, defaultBidType = '') => ({
  projectCode: String(project?.projectCode || ''),
  name: String(project?.name || ''),
  customerName: String(project?.customerName || ''),
  customerId: String(project?.materialCustomerId || project?.customerId || ''),
  customerCanonicalName: String(project?.materialCustomerName || project?.customerCanonicalName || project?.customerName || ''),
  materialProjectName: String(project?.materialProjectName || ''),
  manager: String(project?.manager || ''),
  bidType: String(project?.bidType || defaultBidType || '技术标'),
  turbineModel: normalizeTurbineModel(project?.turbineModel || project?.selectedTurbineModel),
  startDate: String(project?.startDate || ''),
  endDate: String(project?.endDate || project?.deadline || ''),
})

const buildDraftKey = ({ mode = 'create', project = null, defaultBidType = '' }) => [
  PROJECT_WIZARD_DRAFT_PREFIX,
  mode,
  project?.id || 'new',
  project?.bidType || defaultBidType || 'unknown',
].join(':')

const readDraft = (key) => {
  if (typeof window === 'undefined' || !key) return null
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || 'null')
    if (!parsed || parsed.version !== PROJECT_WIZARD_DRAFT_VERSION || !parsed.form) return null
    return {
      ...parsed,
      step: FORM_REQUIRED_STEP,
      form: {
        ...parsed.form,
        turbineModel: normalizeTurbineModel(parsed.form.turbineModel),
      },
      turbineEntryMode: parsed.turbineEntryMode === 'manual' ? 'manual' : 'library',
      customerMode: parsed.customerMode === 'library' ? 'library' : 'ordinary',
      materialProjectMode: parsed.materialProjectMode === 'library' ? 'library' : 'ordinary',
      selectedMaterialCustomerId: String(parsed.selectedMaterialCustomerId || ''),
      selectedMaterialProjectId: String(parsed.selectedMaterialProjectId || ''),
    }
  } catch {
    return null
  }
}

const writeDraft = (key, data) => {
  if (typeof window === 'undefined' || !key) return
  window.localStorage.setItem(key, JSON.stringify({
    version: PROJECT_WIZARD_DRAFT_VERSION,
    ...data,
    updatedAt: new Date().toISOString(),
  }))
}

const clearDraft = (key) => {
  if (typeof window === 'undefined' || !key) return
  window.localStorage.removeItem(key)
}

const customerLabel = (item) => `${item.name}${item.customerId ? ` / ${item.customerId}` : ''}`

const materialProjectLabel = (item) => {
  const parts = [
    item.projectId,
    item.projectCode && item.projectCode !== item.projectId ? item.projectCode : '',
    item.customerName,
  ].filter(Boolean)
  return `${item.name}${parts.length ? `（${parts.join(' / ')}）` : ''}`
}

export default function ProjectWizardModal({
  onClose,
  onCreated,
  mode = 'create',
  project = null,
  forceReviewDecision = '',
  defaultBidType = '',
  lockBidType = false,
}) {
  const isUpdateMode = mode === 'update' && Boolean(project?.id)
  const draftKey = useMemo(() => buildDraftKey({ mode, project, defaultBidType }), [defaultBidType, mode, project])
  const draft = useMemo(() => readDraft(draftKey), [draftKey])
  const hasDraft = Boolean(draft)
  const [form, setForm] = useState(() => draft?.form || buildInitialForm(project, defaultBidType))
  const [turbineEntryMode, setTurbineEntryMode] = useState(() => {
    if (draft?.turbineEntryMode) return draft.turbineEntryMode
    const initial = normalizeTurbineModel(project?.turbineModel || project?.selectedTurbineModel)
    return initial.model && initial.source === 'manual' ? 'manual' : 'library'
  })
  const [customerMode, setCustomerMode] = useState(
    draft?.customerMode || (project?.materialCustomerId || project?.customerId || project?.isKeyAccount ? 'library' : 'ordinary'),
  )
  const [materialProjectMode, setMaterialProjectMode] = useState(
    draft?.materialProjectMode || project?.materialProjectMode || (project?.materialProjectId ? 'library' : 'ordinary'),
  )
  const [materialCustomers, setMaterialCustomers] = useState([])
  const [materialProjects, setMaterialProjects] = useState([])
  const [turbineOptions, setTurbineOptions] = useState([])
  const [loadingTurbines, setLoadingTurbines] = useState(false)
  const [turbineError, setTurbineError] = useState('')
  const [selectedMaterialCustomerId, setSelectedMaterialCustomerId] = useState(
    draft?.selectedMaterialCustomerId || String(project?.materialCustomerId || project?.customerId || project?.keyAccountId || ''),
  )
  const [selectedMaterialProjectId, setSelectedMaterialProjectId] = useState(
    draft?.selectedMaterialProjectId || String(project?.materialProjectId || ''),
  )
  const [loadingIdentities, setLoadingIdentities] = useState(false)
  const [identityError, setIdentityError] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const updateForm = (key, val) => setForm((prev) => ({ ...prev, [key]: val }))
  const selectedMaterialCustomer = materialCustomers.find((item) => item.id === selectedMaterialCustomerId)
  const selectedMaterialProject = materialProjects.find((item) => item.id === selectedMaterialProjectId)
  const selectedTurbineId = form.turbineModel?.id || form.turbineModel?.model || ''
  const selectedTurbineOption = turbineOptions.find((item) => {
    const optionId = item.id || item.model
    return optionId === selectedTurbineId || item.model === form.turbineModel?.model
  })
  const turbineSelectValue = form.turbineModel?.model
    ? turbineEntryMode === 'manual'
      ? MANUAL_TURBINE_VALUE
      : selectedTurbineOption?.id || selectedTurbineOption?.model || MANUAL_TURBINE_VALUE
    : turbineEntryMode === 'manual'
      ? MANUAL_TURBINE_VALUE
      : ''

  useEffect(() => {
    if (hasDraft || isUpdateMode || !defaultBidType) return
    const timer = setTimeout(() => {
      setForm((prev) => ({ ...prev, bidType: defaultBidType }))
    }, 0)
    return () => clearTimeout(timer)
  }, [defaultBidType, hasDraft, isUpdateMode])

  useEffect(() => {
    if (creating) return undefined
    const timer = setTimeout(() => {
      writeDraft(draftKey, {
        step: FORM_REQUIRED_STEP,
        form,
        turbineEntryMode,
        customerMode,
        materialProjectMode,
        selectedMaterialCustomerId,
        selectedMaterialProjectId,
      })
    }, 250)
    return () => clearTimeout(timer)
  }, [
    creating,
    customerMode,
    draftKey,
    form,
    materialProjectMode,
    selectedMaterialCustomerId,
    selectedMaterialProjectId,
    turbineEntryMode,
  ])

  useEffect(() => {
    let mounted = true
    const loadMaterialIdentities = async () => {
      setLoadingIdentities(true)
      setIdentityError('')
      try {
        const payload = await materialsAPI.identityOptions({ bidType: form.bidType })
        if (!mounted) return
        const customers = normalizeCustomers(payload?.customers || [])
        const projects = normalizeMaterialProjects(payload?.projects || [])
        setMaterialCustomers(customers)
        setMaterialProjects(projects)
        if (isUpdateMode) {
          if (hasDraft) return
          const selectedCustomer = customers.find((item) => item.id === String(project?.materialCustomerId || project?.customerId || project?.keyAccountId || ''))
            || customers.find((item) => item.name === String(project?.customerName || ''))
          if (selectedCustomer) {
            setCustomerMode('library')
            setSelectedMaterialCustomerId(selectedCustomer.id)
            setForm((prev) => ({
              ...prev,
              customerId: selectedCustomer.customerId,
              customerCanonicalName: selectedCustomer.name,
              customerName: selectedCustomer.name,
            }))
          }
          const selectedProject = projects.find((item) => item.id === String(project?.materialProjectId || ''))
          if (selectedProject) {
            setMaterialProjectMode(project?.materialProjectMode || 'library')
            setSelectedMaterialProjectId(selectedProject.id)
            setForm((prev) => ({
              ...prev,
              materialProjectName: selectedProject.name,
              projectCode: prev.projectCode || selectedProject.projectCode,
            }))
          }
          return
        }
        if (customers.length > 0 && !hasDraft) {
          const defaultCustomer = customers[0]
          setCustomerMode('library')
          setSelectedMaterialCustomerId(defaultCustomer.id)
          setForm((prev) => ({
            ...prev,
            customerId: defaultCustomer.customerId,
            customerCanonicalName: defaultCustomer.name,
            customerName: defaultCustomer.name,
          }))
          const defaultProject = projects[0]
          if (defaultProject) {
            setMaterialProjectMode('library')
            setSelectedMaterialProjectId(defaultProject.id)
            setForm((prev) => ({
              ...prev,
              materialProjectName: defaultProject.name,
              projectCode: prev.projectCode || defaultProject.projectCode,
            }))
          }
        }
      } catch (e) {
        if (!mounted) return
        setMaterialCustomers([])
        setMaterialProjects([])
        if (!isUpdateMode) setCustomerMode('ordinary')
        setIdentityError(e?.message || '客户/项目候选加载失败，可选择普通客户或普通项目。')
      } finally {
        if (mounted) setLoadingIdentities(false)
      }
    }
    loadMaterialIdentities()
    return () => {
      mounted = false
    }
  }, [form.bidType, hasDraft, isUpdateMode, project?.customerId, project?.customerName, project?.keyAccountId, project?.materialCustomerId, project?.materialProjectId, project?.materialProjectMode])

  useEffect(() => {
    let mounted = true
    const loadTurbineOptions = async () => {
      if (form.bidType !== '技术标') {
        setTurbineOptions([])
        setTurbineError('')
        return
      }
      setLoadingTurbines(true)
      setTurbineError('')
      try {
        const payload = await materialsAPI.turbineModelOptions({ bidType: form.bidType })
        if (!mounted) return
        const options = (Array.isArray(payload?.items) ? payload.items : []).map(normalizeTurbineModel).filter((item) => item.model)
        setTurbineOptions(options)
        setForm((prev) => {
          if (prev.turbineModel?.model) return prev
          const first = options.find((item) => item.status !== 'deprecated') || options[0]
          return first ? { ...prev, turbineModel: first } : prev
        })
      } catch (e) {
        if (!mounted) return
        setTurbineOptions([])
        setTurbineError(e?.message || '投标机型候选加载失败，可手工录入。')
      } finally {
        if (mounted) setLoadingTurbines(false)
      }
    }
    loadTurbineOptions()
    return () => {
      mounted = false
    }
  }, [form.bidType])

  const missingRequiredItems = useMemo(() => {
    const items = []
    if (!form.name.trim()) items.push('项目名称')
    if (customerMode === 'library') {
      if (!selectedMaterialCustomerId || !form.customerName.trim()) items.push('重点客户')
    } else if (!form.customerName.trim()) {
      items.push('普通客户')
    }
    if (materialProjectMode === 'library' && !selectedMaterialProjectId) items.push('重点项目')
    if (form.bidType === '技术标' && !String(form.turbineModel?.model || '').trim()) items.push('投标机型')
    if (!form.manager.trim()) items.push('负责人')
    if (!form.startDate) items.push('起始日期')
    if (!form.endDate) items.push('截止日期')
    return items
  }, [customerMode, form, materialProjectMode, selectedMaterialCustomerId, selectedMaterialProjectId])
  const canSubmit = missingRequiredItems.length === 0
  const nextDisabledReason = missingRequiredItems.length ? `请先补全：${missingRequiredItems.join('、')}` : ''

  const archivePathPreview = useMemo(() => {
    const bidType = form.bidType || '技术标'
    const customer = form.customerName.trim() || '客户名'
    const projectIdentity = materialProjectMode === 'library'
      ? selectedMaterialProject?.projectId || selectedMaterialProjectId || '项目ID'
      : project?.materialProjectId || '系统生成项目ID'
    return `${bidType}/客户素材/${customer}；${bidType}/项目素材/${projectIdentity}`
  }, [form.bidType, form.customerName, materialProjectMode, project?.materialProjectId, selectedMaterialProject?.projectId, selectedMaterialProjectId])

  const handleCreate = async () => {
    setCreating(true)
    setCreateError('')
    try {
      const payload = {
        ...form,
        deadline: form.endDate,
        owner: form.customerName,
        isKeyAccount: customerMode === 'library' && Boolean(selectedMaterialCustomerId),
        keyAccountId: customerMode === 'library' ? selectedMaterialCustomerId : '',
        customerId: customerMode === 'library' ? selectedMaterialCustomer?.customerId || selectedMaterialCustomerId : '',
        customerCanonicalName: customerMode === 'library' ? selectedMaterialCustomer?.name || form.customerName : '',
        materialCustomerId: customerMode === 'library' ? selectedMaterialCustomer?.customerId || selectedMaterialCustomerId : '',
        materialCustomerName: customerMode === 'library' ? selectedMaterialCustomer?.name || form.customerName : form.customerName,
        materialProjectMode,
        materialProjectId: materialProjectMode === 'library' ? selectedMaterialProject?.projectId || selectedMaterialProjectId : '',
        materialProjectCode: materialProjectMode === 'library' ? selectedMaterialProject?.projectCode || selectedMaterialProjectId : form.projectCode,
        materialProjectName: materialProjectMode === 'library' ? selectedMaterialProject?.name || selectedMaterialProjectId : (form.materialProjectName || form.name),
        turbineModel: form.bidType === '技术标'
          ? {
              ...form.turbineModel,
              model: String(form.turbineModel?.model || '').trim(),
              source: form.turbineModel?.source || 'manual',
            }
          : {},
      }
      if (forceReviewDecision) payload.reviewDecision = forceReviewDecision

      if (isUpdateMode) {
        const updatedProject = await projectsAPI.update(project.id, payload)
        clearDraft(draftKey)
        onCreated(updatedProject)
      } else {
        const createdProject = await projectsAPI.create(payload)
        clearDraft(draftKey)
        onCreated(createdProject)
      }
    } catch (e) {
      console.error(e)
      setCreateError(e?.message || `${isUpdateMode ? '保存' : '创建'}失败，请稍后重试。`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="dialog-overlay bg-[rgba(23,33,43,0.28)] backdrop-blur-0" onClick={onClose}>
      <div
        className="dialog-content wizard-modal-surface w-full max-w-[760px] animate-fade-in border border-[#d1d9e4]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#d8e0ea] bg-white">
          <div className="flex items-center gap-3">
            <h2 className="text-[18px] font-headline font-semibold text-on-surface">
              {isUpdateMode ? '完善项目信息' : '新建投标项目'}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="close-plain text-on-surface-variant hover:text-primary transition-colors"
            aria-label="关闭"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {/* Step Content */}
        <div className="px-5 py-5 min-h-[410px] bg-white">
            <div className="flex flex-col gap-4 animate-fade-in">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">标书类型</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={form.bidType}
                    onChange={(e) => updateForm('bidType', e.target.value)}
                    disabled={lockBidType}
                  >
                    {lockBidType ? (
                      <option>{form.bidType}</option>
                    ) : (
                      <>
                        <option>技术标</option>
                        <option>商务标</option>
                      </>
                    )}
                  </select>
                </div>
                <div className="md:col-span-2">
                  <label className="block text-sm font-semibold text-on-surface mb-2">项目名称 *</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="输入项目名称，例如：甘肃华能100MW风电项目"
                    value={form.name}
                    onChange={(e) => updateForm('name', e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">业务项目编号</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="例如：招标编号、项目编号"
                    value={form.projectCode}
                    onChange={(e) => updateForm('projectCode', e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">负责人 *</label>
                  <input
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    placeholder="张建国"
                    value={form.manager}
                    onChange={(e) => updateForm('manager', e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">客户来源</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={customerMode}
                    onChange={(e) => {
                      const nextMode = e.target.value
                      setCustomerMode(nextMode)
                      if (nextMode === 'library') {
                        const selected = materialCustomers.find((item) => item.id === selectedMaterialCustomerId) || materialCustomers[0]
                        if (selected) {
                          setSelectedMaterialCustomerId(selected.id)
                          setForm((prev) => ({
                            ...prev,
                            customerId: selected.customerId,
                            customerCanonicalName: selected.name,
                            customerName: selected.name,
                          }))
                        }
                      }
                    }}
                    disabled={loadingIdentities}
                  >
                    <option value="library" disabled={!materialCustomers.length}>重点客户</option>
                    <option value="ordinary">普通客户</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">
                    {customerMode === 'library' ? '重点客户 *' : '普通客户 *'}
                  </label>
                  {customerMode === 'library' && materialCustomers.length > 0 ? (
                    <select
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                      value={selectedMaterialCustomerId}
                      onChange={(e) => {
                        const nextId = e.target.value
                        setSelectedMaterialCustomerId(nextId)
                        const selected = materialCustomers.find((item) => item.id === nextId)
                        if (selected) {
                          setForm((prev) => ({
                            ...prev,
                            customerId: selected.customerId,
                            customerCanonicalName: selected.name,
                            customerName: selected.name,
                          }))
                        }
                      }}
                    >
                      {materialCustomers.map((item) => (
                        <option key={item.id} value={item.id}>{customerLabel(item)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                      placeholder="输入客户名称，例如：华能集团"
                      value={form.customerName}
                      onChange={(e) => {
                        updateForm('customerName', e.target.value)
                        updateForm('customerId', '')
                        updateForm('customerCanonicalName', e.target.value)
                      }}
                    />
                  )}
                  {(identityError || loadingIdentities) && (
                    <p className={`text-xs mt-2 ${identityError ? 'text-error' : 'text-outline'}`}>
                      {identityError || '正在加载客户/项目...'}
                    </p>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">项目来源</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={materialProjectMode}
                    onChange={(e) => {
                      const nextMode = e.target.value
                      setMaterialProjectMode(nextMode)
                      if (nextMode === 'library') {
                        const selected = materialProjects.find((item) => item.id === selectedMaterialProjectId) || materialProjects[0]
                        if (selected) {
                          setSelectedMaterialProjectId(selected.id)
                          setForm((prev) => ({
                            ...prev,
                            materialProjectName: selected.name,
                            projectCode: prev.projectCode || selected.projectCode,
                          }))
                        }
                      }
                    }}
                    disabled={loadingIdentities}
                  >
                    <option value="library" disabled={!materialProjects.length}>重点项目</option>
                    <option value="ordinary">普通项目</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">
                    {materialProjectMode === 'library' ? '重点项目 *' : '普通项目'}
                  </label>
                  {materialProjectMode === 'library' && materialProjects.length > 0 ? (
                    <select
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                      value={selectedMaterialProjectId}
                      onChange={(e) => {
                        const nextId = e.target.value
                        setSelectedMaterialProjectId(nextId)
                        const selected = materialProjects.find((item) => item.id === nextId)
                        if (selected) {
                          setForm((prev) => ({
                            ...prev,
                            materialProjectName: selected.name,
                            projectCode: prev.projectCode || selected.projectCode,
                          }))
                        }
                      }}
                    >
                      <option value="">选择项目</option>
                      {materialProjects.map((item) => (
                        <option key={item.id} value={item.id}>{materialProjectLabel(item)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                      placeholder="项目名称，不填则使用投标项目名称"
                      value={form.materialProjectName}
                      onChange={(e) => updateForm('materialProjectName', e.target.value)}
                    />
                  )}
                </div>
              </div>
              {form.bidType === '技术标' && (
                <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                  <div className="lg:col-span-3">
                    <label className="block text-sm font-semibold text-on-surface mb-2">投标机型 *</label>
                    <select
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                      value={turbineSelectValue}
                      onChange={(e) => {
                        const value = e.target.value
                        if (!value) {
                          setTurbineEntryMode('library')
                          updateForm('turbineModel', normalizeTurbineModel())
                          return
                        }
                        if (value === MANUAL_TURBINE_VALUE) {
                          setTurbineEntryMode('manual')
                          updateForm('turbineModel', normalizeTurbineModel({
                            model: form.turbineModel?.model || '',
                            source: 'manual',
                            status: 'manual',
                            statusLabel: '人工指定',
                          }))
                          return
                        }
                        const selected = turbineOptions.find((item) => (item.id || item.model) === value)
                        setTurbineEntryMode('library')
                        updateForm('turbineModel', selected || normalizeTurbineModel())
                      }}
                      disabled={loadingTurbines && turbineOptions.length === 0}
                    >
                      <option value="">{loadingTurbines ? '正在加载机型...' : '选择投标机型'}</option>
                      {turbineOptions.map((item) => (
                        <option key={`${item.id || item.model}-${item.platform}-${item.layout}`} value={item.id || item.model}>
                          {turbineModelLabel(item)}
                        </option>
                      ))}
                      <option value={MANUAL_TURBINE_VALUE}>人工指定机型</option>
                    </select>
                    {turbineSelectValue === MANUAL_TURBINE_VALUE && (
                      <input
                        className="mt-2 w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                        placeholder="输入投标机型，例如 EW10.0-220下置"
                        value={form.turbineModel?.model || ''}
                        onChange={(e) => updateForm('turbineModel', normalizeTurbineModel({
                          ...form.turbineModel,
                          model: e.target.value,
                          source: 'manual',
                          status: 'manual',
                          statusLabel: '人工指定',
                        }))}
                      />
                    )}
                    {(turbineError || loadingTurbines) && (
                      <p className={`text-xs mt-2 ${turbineError ? 'text-error' : 'text-outline'}`}>
                        {turbineError || '正在加载机型候选...'}
                      </p>
                    )}
                  </div>
                  <div className="lg:col-span-2">
                    <label className="block text-sm font-semibold text-on-surface mb-2">机型参数</label>
                    <div className="min-h-[104px] border border-[#d2dce8] bg-[#f8fbfd] px-3 py-2 text-xs text-on-surface">
                      {form.turbineModel?.model ? (
                        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                          <span className="text-outline">机型</span><span className="font-semibold text-primary">{form.turbineModel.model || '—'}</span>
                          <span className="text-outline">平台</span><span>{form.turbineModel.platform || '—'}</span>
                          <span className="text-outline">功率</span><span>{form.turbineModel.ratedPowerKw ? `${form.turbineModel.ratedPowerKw} kW` : '—'}</span>
                          <span className="text-outline">叶轮</span><span>{form.turbineModel.rotorDiameterM ? `${form.turbineModel.rotorDiameterM} m` : '—'}</span>
                          <span className="text-outline">状态</span><span>{form.turbineModel.statusLabel || form.turbineModel.status || '—'}</span>
                        </div>
                      ) : (
                        <span className="text-outline">选择或录入投标机型后，后续素材匹配和 Word 填写会自动带入。</span>
                      )}
                    </div>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">起始日期 *</label>
                  <input
                    type="date"
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    value={form.startDate}
                    onChange={(e) => updateForm('startDate', e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">截止日期 *</label>
                  <input
                    type="date"
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                    value={form.endDate}
                    onChange={(e) => updateForm('endDate', e.target.value)}
                  />
                </div>
              </div>
              {missingRequiredItems.length > 0 && (
                <div
                  id="project-wizard-required-hint"
                  className="border border-[#f2c169] bg-[#fff8e6] px-3 py-2 text-xs text-[#7a4d00]"
                >
                  {nextDisabledReason}
                </div>
              )}
              <div className="rounded-md border border-[#d2dce8] bg-[#f8fbfd] px-3 py-2">
                <p className="text-xs text-outline">材料归档路径预览</p>
                <p className="mt-1 text-sm font-medium text-on-surface">{archivePathPreview}</p>
              </div>
              {createError && (
                <div className="bg-error-container/30 border border-error/30 rounded-[4px] p-3 text-sm text-error">
                  {createError}
                </div>
              )}
            </div>
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-5 py-4 border-t border-[#d7e0ea] bg-white">
          <Button
            onClick={onClose}
            size="sm"
            variant="quiet"
          >
            取消
          </Button>
          <Button
            onClick={handleCreate}
            disabled={creating || !canSubmit}
            title={!canSubmit ? nextDisabledReason : undefined}
            aria-describedby={!canSubmit ? 'project-wizard-required-hint' : undefined}
            size="stage"
            variant="primary"
          >
            {creating ? (isUpdateMode ? '保存中...' : '创建中...') : '确认提交'}
          </Button>
        </div>
      </div>
    </div>
  )
}
