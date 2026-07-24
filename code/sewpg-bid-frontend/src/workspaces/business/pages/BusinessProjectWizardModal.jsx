import { useEffect, useMemo, useState } from 'react'
import { businessMaterialsAPI, businessProjectsAPI } from '../../../api'
import Button from '../../../components/ui/Button'

const normalizeCustomers = (list = []) =>
  (Array.isArray(list) ? list : [])
    .map((item) => ({
      id: String(item?.customerId || item?.id || item?.name || '').trim(),
      customerId: String(item?.customerId || item?.id || '').trim(),
      name: String(item?.customerCanonicalName || item?.name || item?.label || item?.id || '').trim(),
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
    }))
    .filter((item) => item.id && item.name)

const today = () => new Date().toISOString().slice(0, 10)
const BUSINESS_BID_TYPE = '商务标'

const buildInitialForm = (project = null) => ({
  bidType: BUSINESS_BID_TYPE,
  projectCode: String(project?.projectCode || ''),
  name: String(project?.name || ''),
  customerName: String(project?.customerName || ''),
  customerId: String(project?.materialCustomerId || project?.customerId || ''),
  customerCanonicalName: String(project?.materialCustomerName || project?.customerCanonicalName || project?.customerName || ''),
  materialProjectName: String(project?.materialProjectName || ''),
  manager: String(project?.manager || ''),
  startDate: String(project?.startDate || today()),
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

export default function BusinessProjectWizardModal({
  onClose,
  onCreated,
  mode = 'create',
  project = null,
  forceReviewDecision = '',
}) {
  const isUpdateMode = mode === 'update' && Boolean(project?.id)
  const [form, setForm] = useState(() => buildInitialForm(project))
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

  useEffect(() => {
    let mounted = true
    const loadMaterialIdentities = async () => {
      setLoadingIdentities(true)
      setIdentityError('')
      try {
        const payload = await businessMaterialsAPI.identityOptions()
        if (!mounted) return
        const customers = normalizeCustomers(payload?.customers || [])
        const projects = normalizeMaterialProjects(payload?.projects || [])
        setMaterialCustomers(customers)
        setMaterialProjects(projects)
        if (customers.length) {
          const expectedCustomerId = String(project?.materialCustomerId || project?.customerId || project?.keyAccountId || '')
          const selectedCustomer = isUpdateMode
            ? customers.find((item) => item.id === expectedCustomerId || item.customerId === expectedCustomerId)
              || customers.find((item) => item.name === String(project?.customerName || ''))
            : customers[0]
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
        }
        if (projects.length) {
          const expectedProjectId = String(project?.materialProjectId || '')
          const selectedProject = isUpdateMode
            ? projects.find((item) => item.id === expectedProjectId || item.projectId === expectedProjectId)
            : projects[0]
          if (selectedProject) {
            setMaterialProjectMode(project?.materialProjectMode || 'library')
            setSelectedMaterialProjectId(selectedProject.id)
            setForm((prev) => ({
              ...prev,
              materialProjectName: selectedProject.name,
              projectCode: prev.projectCode || selectedProject.projectCode,
            }))
          }
        }
      } catch (e) {
        if (!mounted) return
        setMaterialCustomers([])
        setMaterialProjects([])
        setCustomerMode('ordinary')
        setMaterialProjectMode('ordinary')
        setIdentityError(e?.message || '商务标客户/项目候选加载失败，可手工填写。')
      } finally {
        if (mounted) setLoadingIdentities(false)
      }
    }
    loadMaterialIdentities()
    return () => {
      mounted = false
    }
  }, [isUpdateMode, project?.customerId, project?.customerName, project?.keyAccountId, project?.materialCustomerId, project?.materialProjectId, project?.materialProjectMode])

  const missingRequiredItems = useMemo(() => {
    const items = []
    if (!form.name.trim()) items.push('项目名称')
    if (customerMode === 'library') {
      if (!selectedMaterialCustomerId || !form.customerName.trim()) items.push('重点客户')
    } else if (!form.customerName.trim()) {
      items.push('普通客户')
    }
    if (materialProjectMode === 'library' && !selectedMaterialProjectId) items.push('重点项目')
    if (!form.manager.trim()) items.push('负责人')
    if (!form.startDate) items.push('起始日期')
    if (!form.endDate) items.push('截止日期')
    return items
  }, [customerMode, form, materialProjectMode, selectedMaterialCustomerId, selectedMaterialProjectId])

  const canSubmit = missingRequiredItems.length === 0
  const disabledReason = missingRequiredItems.length ? `请先补全：${missingRequiredItems.join('、')}` : ''

  const archivePathPreview = useMemo(() => {
    const customer = form.customerName.trim() || '客户名'
    const projectIdentity = materialProjectMode === 'library'
      ? selectedMaterialProject?.projectId || selectedMaterialProjectId || '项目ID'
      : '系统生成项目ID'
    return `商务标/客户素材/${customer}；商务标/项目素材/${projectIdentity}`
  }, [form.customerName, materialProjectMode, selectedMaterialProject?.projectId, selectedMaterialProjectId])

  const handleCreate = async () => {
    setCreating(true)
    setCreateError('')
    try {
      const payload = {
        ...form,
        bidType: BUSINESS_BID_TYPE,
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
        turbineModel: {},
      }
      if (forceReviewDecision) payload.reviewDecision = forceReviewDecision
      const savedProject = isUpdateMode
        ? await businessProjectsAPI.update(project.id, payload)
        : await businessProjectsAPI.create(payload)
      onCreated(savedProject)
    } catch (e) {
      setCreateError(e?.message || `商务标项目${isUpdateMode ? '保存' : '创建'}失败，请稍后重试。`)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="dialog-overlay bg-[rgba(23,33,43,0.28)] backdrop-blur-0" onClick={onClose}>
      <div
        className="dialog-content wizard-modal-surface w-full max-w-[720px] animate-fade-in border border-[#d1d9e4]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#d8e0ea] bg-white">
          <div>
            <h2 className="text-[18px] font-headline font-semibold text-on-surface">
              {isUpdateMode ? '完善商务标项目信息' : '新建商务标项目'}
            </h2>
            <p className="text-xs text-on-surface-variant mt-1">
              {isUpdateMode ? '确认参与投标前补齐商务资料字段。' : '该入口只创建商务标项目，并按商务资料字段维护。'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="close-plain text-on-surface-variant hover:text-primary transition-colors"
            aria-label="关闭"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="px-5 py-5 bg-white">
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-semibold text-on-surface mb-2">标书类型</label>
                <input
                  className="w-full min-h-0 h-9 px-4 bg-[#eef3f7] border border-[#c2d0df] text-sm text-on-surface"
                  value={BUSINESS_BID_TYPE}
                  disabled
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm font-semibold text-on-surface mb-2">项目名称 *</label>
                <input
                  className="w-full min-h-0 h-9 px-4 bg-[#e8eef2] border border-[#c2d0df] text-sm text-on-surface focus:border-primary/70 focus:ring-0 transition-all"
                  placeholder="输入商务标项目名称"
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
                  placeholder="负责人姓名"
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
                    placeholder="输入客户名称"
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
                    {identityError || '正在加载商务标客户/项目...'}
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
                id="business-project-required-hint"
                className="border border-[#f2c169] bg-[#fff8e6] px-3 py-2 text-xs text-[#7a4d00]"
              >
                {disabledReason}
              </div>
            )}

            <div className="rounded-md border border-[#d2dce8] bg-[#f8fbfd] px-3 py-2">
              <p className="text-xs text-outline">商务标材料归档路径预览</p>
              <p className="mt-1 text-sm font-medium text-on-surface">{archivePathPreview}</p>
            </div>

            {createError && (
              <div className="bg-error-container/30 border border-error/30 rounded-[4px] p-3 text-sm text-error">
                {createError}
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-between items-center px-5 py-4 border-t border-[#d7e0ea] bg-white">
          <Button onClick={onClose} size="sm" variant="quiet">
            取消
          </Button>
          <Button
            onClick={handleCreate}
            disabled={creating || !canSubmit}
            title={!canSubmit ? disabledReason : undefined}
            aria-describedby={!canSubmit ? 'business-project-required-hint' : undefined}
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
