import { useEffect, useMemo, useState } from 'react'
import { materialsAPI, projectsAPI } from '../../api'

const STEPS = ['基本信息', '确认创建']

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

const buildInitialForm = (project = null, defaultBidType = '') => ({
  projectCode: String(project?.projectCode || ''),
  name: String(project?.name || ''),
  customerName: String(project?.customerName || ''),
  customerId: String(project?.materialCustomerId || project?.customerId || ''),
  customerCanonicalName: String(project?.materialCustomerName || project?.customerCanonicalName || project?.customerName || ''),
  materialProjectName: String(project?.materialProjectName || ''),
  manager: String(project?.manager || ''),
  bidType: String(project?.bidType || defaultBidType || '技术标'),
  startDate: String(project?.startDate || ''),
  endDate: String(project?.endDate || project?.deadline || ''),
})

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
  const [step, setStep] = useState(0)
  const [form, setForm] = useState(() => buildInitialForm(project, defaultBidType))
  const [customerMode, setCustomerMode] = useState(
    project?.materialCustomerId || project?.customerId || project?.isKeyAccount ? 'library' : 'ordinary',
  )
  const [materialProjectMode, setMaterialProjectMode] = useState(
    project?.materialProjectMode || (project?.materialProjectId ? 'library' : 'ordinary'),
  )
  const [materialCustomers, setMaterialCustomers] = useState([])
  const [materialProjects, setMaterialProjects] = useState([])
  const [selectedMaterialCustomerId, setSelectedMaterialCustomerId] = useState(
    String(project?.materialCustomerId || project?.customerId || project?.keyAccountId || ''),
  )
  const [selectedMaterialProjectId, setSelectedMaterialProjectId] = useState(
    String(project?.materialProjectId || ''),
  )
  const [loadingIdentities, setLoadingIdentities] = useState(false)
  const [identityError, setIdentityError] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const updateForm = (key, val) => setForm((prev) => ({ ...prev, [key]: val }))
  const selectedMaterialCustomer = materialCustomers.find((item) => item.id === selectedMaterialCustomerId)
  const selectedMaterialProject = materialProjects.find((item) => item.id === selectedMaterialProjectId)
  const effectiveCustomerId = customerMode === 'library' ? selectedMaterialCustomer?.customerId || selectedMaterialCustomerId : form.customerId
  const filteredMaterialProjects = materialProjects.filter((item) => {
    if (!effectiveCustomerId) return true
    return !item.customerId || item.customerId === effectiveCustomerId
  })

  useEffect(() => {
    if (isUpdateMode || !defaultBidType) return
    const timer = setTimeout(() => {
      setForm((prev) => ({ ...prev, bidType: defaultBidType }))
    }, 0)
    return () => clearTimeout(timer)
  }, [defaultBidType, isUpdateMode])

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
        if (customers.length > 0) {
          const defaultCustomer = customers[0]
          setCustomerMode('library')
          setSelectedMaterialCustomerId(defaultCustomer.id)
          setForm((prev) => ({
            ...prev,
            customerId: defaultCustomer.customerId,
            customerCanonicalName: defaultCustomer.name,
            customerName: defaultCustomer.name,
          }))
          const defaultProject = projects.find((item) => !item.customerId || item.customerId === defaultCustomer.customerId)
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
        setIdentityError(e?.message || '素材库客户/项目加载失败，可选择普通客户或普通项目。')
      } finally {
        if (mounted) setLoadingIdentities(false)
      }
    }
    loadMaterialIdentities()
    return () => {
      mounted = false
    }
  }, [form.bidType, isUpdateMode, project?.customerId, project?.customerName, project?.keyAccountId, project?.materialCustomerId, project?.materialProjectId, project?.materialProjectMode])

  const canNextStep = useMemo(() => {
    if (step !== 0) return true
    if (!form.name.trim()) return false
    if (!form.customerName.trim()) return false
    if (customerMode === 'library' && !selectedMaterialCustomerId) return false
    if (materialProjectMode === 'library' && !selectedMaterialProjectId) return false
    if (!form.manager.trim()) return false
    if (!form.startDate) return false
    if (!form.endDate) return false
    return true
  }, [customerMode, form, materialProjectMode, selectedMaterialCustomerId, selectedMaterialProjectId, step])

  const archivePathPreview = useMemo(() => {
    const customer = form.customerName.trim() || '客户名'
    const projectIdentity = materialProjectMode === 'library'
      ? selectedMaterialProject?.projectId || selectedMaterialProjectId || '素材库项目ID'
      : project?.materialProjectId || '系统生成素材项目ID'
    return `技术标/客户素材/${customer}；技术标/项目素材/${projectIdentity}`
  }, [form.customerName, materialProjectMode, project?.materialProjectId, selectedMaterialProject?.projectId, selectedMaterialProjectId])

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
      }
      if (forceReviewDecision) payload.reviewDecision = forceReviewDecision

      if (isUpdateMode) {
        const updatedProject = await projectsAPI.update(project.id, payload)
        onCreated(updatedProject)
      } else {
        const createdProject = await projectsAPI.create(payload)
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

        {/* Step Indicator */}
        <div className="flex items-center gap-3 px-5 py-3 bg-white border-b border-[#d7e0ea]">
          {STEPS.map((label, i) => (
            <div key={i} className="flex items-center gap-2 flex-1">
              <div
                className={`step-circle w-8 h-8 flex items-center justify-center text-sm font-semibold ${
                  i < step
                    ? 'bg-[#0068b7] text-white'
                    : i === step
                      ? 'bg-[#0068b7] text-white'
                      : 'bg-[#dbe4ee] text-[#8193a8]'
                }`}
              >
                {i < step ? <span className="material-symbols-outlined text-[16px]">check</span> : i + 1}
              </div>
              <span className={`text-sm font-medium ${i === step || i < step ? 'text-[#0068b7]' : 'text-[#8193a8]'}`}>{label}</span>
              {i < STEPS.length - 1 && (
                <div className={`flex-1 h-[1px] ${i < step ? 'bg-[#0068b7]' : 'bg-[#d0dbe7]'}`}></div>
              )}
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div className="px-5 py-5 min-h-[410px] bg-white">
          {step === 0 && (
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
              <div>
                <label className="block text-sm font-semibold text-on-surface mb-2">业务项目编号</label>
                <input
                  className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                  placeholder="例如：招标编号、项目编号"
                  value={form.projectCode}
                  onChange={(e) => updateForm('projectCode', e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
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
                    <option value="library" disabled={!materialCustomers.length}>素材库客户</option>
                    <option value="ordinary">普通客户</option>
                  </select>
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
              <div>
                <label className="block text-sm font-semibold text-on-surface mb-2">业主单位（客户） *</label>
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
                        const currentProject = materialProjects.find((item) => item.id === selectedMaterialProjectId)
                        if (currentProject?.customerId && currentProject.customerId !== selected.customerId) {
                          setSelectedMaterialProjectId('')
                        }
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
                    {identityError || '正在加载素材库客户/项目...'}
                  </p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">素材项目来源</label>
                  <select
                    className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:ring-0 transition-all cursor-pointer"
                    value={materialProjectMode}
                    onChange={(e) => {
                      const nextMode = e.target.value
                      setMaterialProjectMode(nextMode)
                      if (nextMode === 'library') {
                        const selected = filteredMaterialProjects.find((item) => item.id === selectedMaterialProjectId) || filteredMaterialProjects[0]
                        if (selected) {
                          setSelectedMaterialProjectId(selected.id)
                          setForm((prev) => ({
                            ...prev,
                            materialProjectName: selected.name,
                            projectCode: prev.projectCode || selected.projectCode,
                          }))
                          if (selected.customerId) {
                            const customer = materialCustomers.find((item) => item.customerId === selected.customerId)
                            if (customer) {
                              setCustomerMode('library')
                              setSelectedMaterialCustomerId(customer.id)
                              setForm((prev) => ({
                                ...prev,
                                customerId: customer.customerId,
                                customerCanonicalName: customer.name,
                                customerName: customer.name,
                              }))
                            }
                          }
                        }
                      }
                    }}
                    disabled={loadingIdentities}
                  >
                    <option value="library" disabled={!filteredMaterialProjects.length}>素材库项目</option>
                    <option value="ordinary">普通项目</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-semibold text-on-surface mb-2">素材库项目 *</label>
                  {materialProjectMode === 'library' && filteredMaterialProjects.length > 0 ? (
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
	                          if (selected.customerId) {
	                            const customer = materialCustomers.find((item) => item.customerId === selected.customerId)
	                            if (customer) {
	                              setCustomerMode('library')
	                              setSelectedMaterialCustomerId(customer.id)
	                              setForm((prev) => ({
	                                ...prev,
	                                customerId: customer.customerId,
	                                customerCanonicalName: customer.name,
	                                customerName: customer.name,
	                              }))
	                            }
	                          }
	                        }
                      }}
                    >
                      <option value="">选择素材库项目</option>
                      {filteredMaterialProjects.map((item) => (
                        <option key={item.id} value={item.id}>{materialProjectLabel(item)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                      placeholder="普通项目名称，不填则使用投标项目名称"
                      value={form.materialProjectName}
                      onChange={(e) => updateForm('materialProjectName', e.target.value)}
                    />
                  )}
                </div>
              </div>
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
            </div>
          )}

          {step === 1 && (
            <div className="flex flex-col gap-4 animate-fade-in">
              <div className="bg-[#ffffff] border border-[#d2dce8] rounded-[4px] p-5">
                <h3 className="text-[16px] font-semibold text-on-surface mb-4">
                  {isUpdateMode ? '项目信息确认' : '项目概览'}
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  {[
	                    ['项目名称', form.name || '—'],
	                    ['业务项目编号', form.projectCode || (project?.id || '创建后生成')],
	                    ['业主单位', form.customerName || '—'],
	                    ['客户来源', customerMode === 'library' ? '素材库客户' : '普通客户'],
	                    ['素材库项目', materialProjectMode === 'library' ? selectedMaterialProject?.name || '—' : form.materialProjectName || form.name || '普通项目'],
	                    ['素材项目ID', materialProjectMode === 'library' ? selectedMaterialProjectId || '—' : project?.materialProjectId || '创建后生成'],
	                    ['负责人', form.manager || '—'],
	                    ['标书类型', form.bidType],
	                    ['起始日期', form.startDate || '—'],
	                    ['截止日期', form.endDate || '—'],
                  ].map(([label, value], i) => (
                    <div key={i} className="flex flex-col gap-1">
                      <span className="text-xs text-outline">{label}</span>
                      <span className="text-sm font-medium text-on-surface">{value}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-4 border-t border-[#cfdae7]">
                  <p className="text-xs text-outline">材料归档路径预览</p>
                  <p className="text-sm font-medium text-on-surface mt-1">{archivePathPreview}</p>
                </div>
              </div>
              {createError && (
                <div className="bg-error-container/30 border border-error/30 rounded-[4px] p-3 text-sm text-error">
                  {createError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center px-5 py-4 border-t border-[#d7e0ea] bg-white">
          <button
            onClick={() => (step === 0 ? onClose() : setStep(step - 1))}
            className="h-8 px-6 text-sm font-medium text-white border border-[#a8acaf] bg-[#b6babd] hover:bg-[#a9adb0] transition-colors"
          >
            {step === 0 ? '取消' : '上一步'}
          </button>
          {step < 1 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={!canNextStep}
              className="h-8 px-6 bg-[#0bafff] text-on-primary text-sm font-medium border border-[#0aa3ea] hover:bg-[#07a3ef] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              下一步
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={creating}
              className="h-8 px-7 bg-[#0bafff] text-on-primary text-sm font-semibold border border-[#0aa3ea] hover:bg-[#07a3ef] transition-colors disabled:opacity-50"
            >
              {creating ? (isUpdateMode ? '保存中...' : '创建中...') : (isUpdateMode ? '确认提交' : '确认创建')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
